"""
WhatsApp worker.

Runs the long-lived neonize (whatsmeow) client that holds the WhatsApp
connection, and exposes a tiny internal HTTP API that the Django backend calls.
This service is NOT exposed to the internet -- only the backend talks to it.

Session data is stored in PostgreSQL (neonize uses the connection string as its
first argument; if it starts with "postgres" it uses Postgres instead of SQLite).
Because the session lives in Postgres, rebuilding/redeploying this container does
NOT require re-scanning the QR code.

Losing the link (e.g. the user removes this device under WhatsApp -> Linked
devices) is handled too: whatsmeow raises LoggedOut and wipes the stored session,
and we then restart the process so a fresh pairing QR is produced. The container
restart policy (`restart: unless-stopped`) is what brings us back up.
"""
import os
import logging
import threading
import time

from flask import Flask, request, jsonify
from waitress import serve

from neonize.client import NewClient
from neonize.proto.waCompanionReg.WAWebProtobufsCompanionReg_pb2 import DeviceProps
from neonize.events import (
    ConnectedEv,
    DisconnectedEv,
    KeepAliveRestoredEv,
    KeepAliveTimeoutEv,
    LoggedOutEv,
    MessageEv,
    PairStatusEv,
    StreamReplacedEv,
)
from neonize.utils import build_jid
from neonize.utils.enum import ChatPresence, ChatPresenceMedia, Presence, ReceiptType

import config_store
import gemini
import memory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

# e.g. postgres://user:pass@db:5432/whatsapp?sslmode=disable
DATABASE_URL = os.environ["NEONIZE_DATABASE_URL"]

# How often the watchdog re-checks the real client state, and how many
# consecutive "not logged in" checks we tolerate before assuming the session is
# gone for good (a short network blip must not trigger a restart).
WATCHDOG_INTERVAL_S = 10
WATCHDOG_MISSES_BEFORE_RESTART = 6

# Shared connection state, guarded by a lock (read by the API thread, written by
# neonize's event callbacks).
#
# "state" is the single value the portal renders from:
#   starting      -- process just came up, nothing decided yet
#   awaiting_scan -- no session; a QR code is waiting to be scanned
#   connected     -- linked and online
#   reconnecting  -- linked but the socket dropped; whatsmeow is retrying
#   logged_out    -- the device was unlinked; restarting to get a new QR
_state = {
    "state": "starting",
    "connected": False,
    "logged_in": False,
    "jid": None,   # phone/user part we are logged in as, once paired
    "qr": None,    # latest QR string, only while waiting to be scanned
}
_lock = threading.Lock()
_restarting = False

# Chats with an auto-reply in flight (guards against overlapping answers).
_replying = set()

# WhatsApp clears the "typing…" bubble by itself after a few seconds, so it has
# to be refreshed while the AI is still thinking.
TYPING_REFRESH_S = 5


def _device_props():
    """How this linked device introduces itself to WhatsApp.

    Sent when the QR code is scanned, so a change only takes effect on the next
    pairing -- it does not rename an already-linked device.

    neonize's default is ``os="Neonize", platformType=SAFARI``, which is what
    shows up under WhatsApp -> Linked devices and is the only thing in the whole
    flow announcing an unofficial client. We instead describe an ordinary
    browser session: DEVICE_OS is the operating system ("Windows", "Mac OS",
    "Ubuntu"...) and DEVICE_PLATFORM the browser (CHROME, FIREFOX, SAFARI,
    EDGE...), matching how WhatsApp Web itself fills these in.
    """
    os_name = os.environ.get("DEVICE_OS", "Windows")
    platform_name = os.environ.get("DEVICE_PLATFORM", "CHROME").upper()
    try:
        platform = DeviceProps.PlatformType.Value(platform_name)
    except ValueError:
        valid = ", ".join(v.name for v in DeviceProps.PlatformType.DESCRIPTOR.values)
        log.warning("Unknown DEVICE_PLATFORM %r, falling back to CHROME. Valid: %s",
                    platform_name, valid)
        platform_name = "CHROME"
        platform = DeviceProps.CHROME
    log.info("Registering as device: os=%s platform=%s", os_name, platform_name)
    return DeviceProps(os=os_name, platformType=platform)


client = NewClient(DATABASE_URL, props=_device_props())


def _set(**changes):
    with _lock:
        _state.update(changes)


def _restart(reason):
    """Tear the process down so it comes back with a clean slate.

    Once WhatsApp has invalidated the session there is no way to re-pair the
    running Go client -- it has to be built again from an empty store. Exiting
    lets the container restart policy do that for us; on the way back up neonize
    finds no device and immediately emits a fresh QR code.
    """
    global _restarting
    with _lock:
        if _restarting:
            return
        _restarting = True
        _state.update(
            state="logged_out", connected=False, logged_in=False, jid=None, qr=None
        )

    def run():
        log.warning("Restarting worker to re-pair: %s", reason)
        try:
            client.stop()  # cancel the Go context so it shuts down cleanly
        except Exception:  # noqa: BLE001 - best effort, we are exiting anyway
            log.exception("client.stop() failed during restart")
        # Brief grace period so the portal can poll /status once more and show
        # "unlinked" before the API goes away for a second.
        time.sleep(2)
        os._exit(0)

    threading.Thread(target=run, daemon=True).start()


def _on_qr(_client, data_qr):
    """Called repeatedly while a QR code is waiting to be scanned."""
    qr_str = data_qr.decode() if isinstance(data_qr, (bytes, bytearray)) else str(data_qr)
    _set(state="awaiting_scan", qr=qr_str, connected=False, logged_in=False, jid=None)
    log.info("New QR code emitted (waiting for scan)")


# Override neonize's default behaviour (which prints the QR to the terminal) so
# we can hand the QR string to the web frontend instead.
client.qr(_on_qr)


@client.event(ConnectedEv)
def _on_connected(_client, _ev):
    _set(state="connected", connected=True, logged_in=True, qr=None)
    log.info("WhatsApp connected")


@client.event(PairStatusEv)
def _on_pair(_client, ev):
    _set(state="connected", connected=True, logged_in=True, jid=ev.ID.User, qr=None)
    log.info("Logged in as %s", ev.ID.User)


@client.event(LoggedOutEv)
def _on_logged_out(_client, ev):
    """The device was unlinked (or the session was invalidated server-side)."""
    _restart(f"logged out by WhatsApp (reason={getattr(ev, 'Reason', 'unknown')})")


@client.event(DisconnectedEv)
def _on_disconnected(_client, _ev):
    _mark_offline("socket disconnected")


@client.event(StreamReplacedEv)
def _on_stream_replaced(_client, _ev):
    _mark_offline("stream replaced by another session")


@client.event(KeepAliveTimeoutEv)
def _on_keepalive_timeout(_client, _ev):
    _mark_offline("keepalive timeout")


@client.event(KeepAliveRestoredEv)
def _on_keepalive_restored(_client, _ev):
    with _lock:
        if _state["logged_in"] and not _restarting:
            _state.update(state="connected", connected=True)
    log.info("Keepalive restored")


def _mark_offline(reason):
    """Socket went down. Keep the session -- whatsmeow reconnects on its own."""
    with _lock:
        if _restarting or _state["state"] == "logged_out":
            return  # a logout is already in flight; don't downgrade it
        _state["connected"] = False
        if _state["logged_in"]:
            _state["state"] = "reconnecting"
        elif _state["qr"] is None:
            _state["state"] = "starting"
    log.warning("WhatsApp offline: %s", reason)


def _message_text(message):
    """The plain text of a message, if it has any.

    Media, reactions, polls and the like return "" -- we only auto-reply to text.
    """
    msg = message.Message
    if msg.conversation:
        return msg.conversation
    if msg.extendedTextMessage.text:
        return msg.extendedTextMessage.text
    return ""


def _set_presence(state):
    """Mark the account online/offline.

    WhatsApp only shows a typing indicator from a client the server considers
    online, so this has to be AVAILABLE while we type. We switch back to
    UNAVAILABLE once the reply is sent: staying online permanently would show
    the account as online to every contact around the clock, and would make the
    worker send read receipts (blue ticks) for everything that arrives.
    """
    try:
        client.send_presence(state)
    except Exception as exc:  # noqa: BLE001 - cosmetic, replies still work
        log.warning("Could not set presence %s: %s", state.name, exc)


def _hold_typing(chat, stop):
    """Keep the "typing…" bubble alive until `stop` is set."""
    while True:
        try:
            client.send_chat_presence(
                chat,
                ChatPresence.CHAT_PRESENCE_COMPOSING,
                ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
            )
        except Exception as exc:  # noqa: BLE001 - cosmetic, never break the reply
            log.debug("Could not send typing state: %s", exc)
            return
        if stop.wait(TYPING_REFRESH_S):
            return


def _stop_typing(chat):
    try:
        client.send_chat_presence(
            chat,
            ChatPresence.CHAT_PRESENCE_PAUSED,
            ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT,
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not clear typing state: %s", exc)


def _mark_read(message, chat):
    """Turn the sender's ticks blue."""
    try:
        client.mark_read(
            message.Info.ID,
            chat=chat,
            sender=message.Info.MessageSource.Sender,
            receipt=ReceiptType.READ,
        )
    except Exception as exc:  # noqa: BLE001 - cosmetic, never break the reply
        log.warning("Could not mark message read: %s", exc)


def _auto_reply(message, text, chat, is_group):
    """Ask Gemini for a reply and send it. Runs on its own thread.

    The pacing mirrors a person picking up their phone: the message is read
    (blue ticks) after one delay, then "typing…" starts after a second delay,
    then the answer lands whenever the model is done.
    """
    chat_key = f"{chat.User}@{chat.Server}"
    cfg = config_store.load()

    if cfg["read_receipt_enabled"]:
        time.sleep(cfg["read_receipt_delay"])
        _set_presence(Presence.AVAILABLE)  # ticks only turn blue for an online client
        _mark_read(message, chat)

    # Counted from the blue ticks when those are on, otherwise from arrival.
    time.sleep(cfg["typing_delay"])

    # Show "typing…" for as long as the model takes, so the other person sees
    # something is happening instead of silence.
    _set_presence(Presence.AVAILABLE)
    stop_typing = threading.Event()
    typist = threading.Thread(target=_hold_typing, args=(chat, stop_typing), daemon=True)
    typist.start()

    try:
        # The thread so far with this chat only -- every contact has its own.
        past = memory.history(chat_key)
        try:
            reply = gemini.generate(
                text,
                api_key=cfg["api_key"],
                model=cfg["model"],
                instruction=cfg["instruction"],
                history=past,
            )
        finally:
            # Clear the indicator whether the model answered or failed --
            # otherwise the bubble hangs until WhatsApp times it out.
            stop_typing.set()
            typist.join(timeout=2)
            _stop_typing(chat)

        client.send_message(chat, reply)
        # Only remember exchanges that actually happened: if the model failed,
        # neither side is recorded, so the thread has no phantom turns.
        memory.remember(chat_key, memory.ROLE_USER, text)
        memory.remember(chat_key, memory.ROLE_MODEL, reply)
        log.info(
            "Auto-replied in %s (%d chars, %d turns of context)",
            chat_key,
            len(reply),
            len(past),
        )
    except gemini.GeminiError as exc:
        # A bad key or a quota wall shouldn't spam the chat with error text.
        log.error("Auto-reply skipped for %s: %s", chat_key, exc)
    except Exception:  # noqa: BLE001
        log.exception("Auto-reply failed for %s", chat_key)
    finally:
        # Back offline, so the account isn't shown as online between replies.
        _set_presence(Presence.UNAVAILABLE)
        with _lock:
            _replying.discard(chat_key)


@client.event(MessageEv)
def _on_message(_client, message):
    try:
        source = message.Info.MessageSource
        chat = source.Chat
        text = _message_text(message)
        is_group = bool(source.IsGroup)

        if text:
            log.info("Incoming message from %s: %s", chat.User, text)

        # Never answer ourselves -- that is how reply loops start.
        if source.IsFromMe:
            return
        # Status updates are not a conversation.
        if chat.Server == "broadcast" or chat.User == "status":
            return
        if not text.strip():
            return

        cfg = config_store.load()
        if not cfg["reply_to_all"]:
            return
        if not cfg["api_key"]:
            log.warning("Auto-reply is on but no Gemini API key is configured")
            return
        if is_group and cfg["skip_groups"]:
            return
        if not is_group and cfg["skip_direct"]:
            return

        # One reply at a time per chat, so a rapid burst can't fan out into
        # several overlapping answers.
        chat_key = f"{chat.User}@{chat.Server}"
        with _lock:
            if chat_key in _replying:
                log.info("Already replying in %s, skipping this one", chat_key)
                return
            _replying.add(chat_key)

        threading.Thread(
            target=_auto_reply, args=(message, text, chat, is_group), daemon=True
        ).start()
    except Exception:  # noqa: BLE001 - a bad message must not kill the handler
        log.exception("Failed to handle incoming message")


def _watchdog():
    """Safety net in case a LoggedOut event is ever missed.

    Asks the client itself whether it still has a valid session. Only acts once
    we've actually had one in this process, so a fresh install sitting on the QR
    screen is never restarted.
    """
    had_session = False
    misses = 0
    while True:
        time.sleep(WATCHDOG_INTERVAL_S)
        with _lock:
            if _restarting:
                return
            had_session = had_session or _state["logged_in"]
        try:
            logged_in = client.is_logged_in()
        except Exception:  # noqa: BLE001 - client not ready yet, try again later
            continue

        if logged_in:
            had_session = True
            misses = 0
            continue

        if not had_session:
            continue  # never paired in this process: nothing to lose

        misses += 1
        if misses >= WATCHDOG_MISSES_BEFORE_RESTART:
            _restart(
                "session no longer valid after "
                f"{misses * WATCHDOG_INTERVAL_S}s (device unlinked?)"
            )
            return


# ---------------------------------------------------------------------------
# Internal HTTP API (backend-only)
# ---------------------------------------------------------------------------
app = Flask(__name__)


@app.get("/status")
def status():
    with _lock:
        return jsonify(dict(_state))


@app.post("/send")
def send():
    data = request.get_json(force=True, silent=True) or {}
    phone = str(data.get("phone", "")).strip().lstrip("+")
    message = data.get("message", "")

    if not phone or not message:
        return jsonify({"ok": False, "error": "phone and message are required"}), 400

    with _lock:
        connected = _state["connected"] and not _restarting
        current = _state["state"]
    if not connected:
        errors = {
            "logged_out": "This device was unlinked from WhatsApp -- scan the QR code again",
            "reconnecting": "WhatsApp connection dropped, reconnecting -- try again shortly",
            "awaiting_scan": "WhatsApp is not connected yet -- scan the QR code",
        }
        return jsonify({"ok": False, "error": errors.get(current, "WhatsApp is not connected yet")}), 409

    try:
        client.send_message(build_jid(phone), message)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        log.exception("send failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


def _serve_api():
    serve(app, host="0.0.0.0", port=8100)


if __name__ == "__main__":
    # Serve the internal API in a background thread; run the WhatsApp connection
    # loop on the main thread (this blocks and keeps the process alive).
    threading.Thread(target=_serve_api, daemon=True).start()
    threading.Thread(target=_watchdog, daemon=True).start()
    log.info("Worker API listening on :8100 -- starting WhatsApp client")
    client.connect()
    # connect() returns when the Go context is cancelled (i.e. we asked for a
    # restart). Give the restart thread its moment; if it never arrives, exit
    # anyway so the container restarts us rather than idling with no connection.
    time.sleep(5)
    log.warning("WhatsApp client loop ended -- exiting so the container restarts")
    os._exit(0)
