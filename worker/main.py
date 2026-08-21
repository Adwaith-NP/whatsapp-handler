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
    ChatPresenceEv,
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

# ---------------------------------------------------------------------------
# Reply queue
#
# Two problems this solves:
#  1. A reply takes seconds (model latency + the configured delays). Anything
#     arriving in that window used to be dropped on the floor. Now it queues.
#  2. People split one thought over several quick messages ("wait", "actually",
#     "can you also"). Answering each line separately is wrong and wastes quota,
#     so a chat is held briefly after its last message and the whole burst is
#     answered once. The hold is extended while they are still typing.
#
# One chat is answered at a time, in arrival order, which is also what makes the
# Queue page in the portal meaningful.
# ---------------------------------------------------------------------------

# How often the dispatcher looks for work.
QUEUE_TICK_S = 0.5
# Never hold a chat longer than this, however much they keep typing.
MAX_HOLD_S = 90
# Seconds added past the moment we see a "typing" signal from them.
TYPING_GRACE_S = 4
# Completed replies kept for the portal's Queue page.
RECENT_KEEP = 12

_queue_lock = threading.Lock()
_pending = {}    # chat_key -> entry being collected / waiting its turn
_order = []      # chat_keys, arrival order
_current = None  # the entry being answered right now
_recent = []     # newest first, for the Queue page

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


def _stage(entry, stage):
    """Record what is happening to the chat being answered, for the Queue page."""
    with _queue_lock:
        entry["stage"] = stage
        entry["stage_at"] = time.time()


def _answer(entry):
    """Answer one queued chat: its whole burst of messages, as a single reply."""
    chat = entry["chat"]
    chat_key = entry["chat_key"]
    # The burst, joined into one message so the model sees the complete thought.
    text = "\n".join(entry["texts"]).strip()
    cfg = config_store.load()

    try:
        if cfg["read_receipt_enabled"]:
            _stage(entry, "reading")
            time.sleep(cfg["read_receipt_delay"])
            _set_presence(Presence.AVAILABLE)  # ticks only turn blue when online
            _mark_read(entry["last_message"], chat)

        # Counted from the blue ticks when those are on, otherwise from arrival.
        _stage(entry, "waiting")
        time.sleep(cfg["typing_delay"])

        # Show "typing…" for as long as the model takes, so the other person
        # sees something is happening instead of silence.
        _stage(entry, "thinking")
        _set_presence(Presence.AVAILABLE)
        stop_typing = threading.Event()
        typist = threading.Thread(target=_hold_typing, args=(chat, stop_typing), daemon=True)
        typist.start()

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

        _stage(entry, "sending")
        client.send_message(chat, reply)
        # Only remember exchanges that actually happened: if the model failed,
        # neither side is recorded, so the thread has no phantom turns.
        memory.remember(chat_key, memory.ROLE_USER, text)
        memory.remember(chat_key, memory.ROLE_MODEL, reply)
        entry["outcome"] = "replied"
        log.info(
            "Auto-replied in %s (%d messages merged, %d chars, %d turns of context)",
            chat_key,
            len(entry["texts"]),
            len(reply),
            len(past),
        )
    except gemini.GeminiError as exc:
        # A bad key or a quota wall shouldn't spam the chat with error text.
        entry["outcome"] = "failed"
        entry["error"] = str(exc)
        log.error("Auto-reply skipped for %s: %s", chat_key, exc)
    except Exception as exc:  # noqa: BLE001
        entry["outcome"] = "failed"
        entry["error"] = str(exc)
        log.exception("Auto-reply failed for %s", chat_key)
    finally:
        # Back offline, so the account isn't shown as online between replies.
        _set_presence(Presence.UNAVAILABLE)


def _enqueue(message, text, chat, is_group, name):
    """Add a message to its chat's pending burst, queueing the chat if new."""
    chat_key = f"{chat.User}@{chat.Server}"
    now = time.time()
    window = config_store.load()["batch_window"]

    with _queue_lock:
        entry = _pending.get(chat_key)
        if entry is None:
            entry = {
                "chat_key": chat_key,
                "chat": chat,
                "name": name or chat.User,
                "is_group": is_group,
                "texts": [],
                "queued_at": now,
                "stage": "collecting",
                "stage_at": now,
            }
            _pending[chat_key] = entry
            _order.append(chat_key)

        entry["texts"].append(text)
        entry["last_message"] = message
        entry["last_at"] = now
        # Hold for the batch window after this message, but never past MAX_HOLD_S
        # from the first one -- someone typing forever can't stall the queue.
        entry["ready_at"] = min(entry["queued_at"] + MAX_HOLD_S, now + window)
        position = _order.index(chat_key) + 1
        count = len(entry["texts"])

    log.info(
        "Queued message from %s (#%d in this burst, position %d)",
        chat_key, count, position,
    )


def _extend_hold(chat_key):
    """They are typing -- wait a little longer before answering."""
    now = time.time()
    with _queue_lock:
        entry = _pending.get(chat_key)
        if not entry:
            return
        entry["ready_at"] = min(
            entry["queued_at"] + MAX_HOLD_S, max(entry["ready_at"], now + TYPING_GRACE_S)
        )
        entry["stage"] = "collecting"


def _take_next():
    """Pop the first queued chat whose collecting window has closed."""
    global _current
    now = time.time()
    with _queue_lock:
        if _current is not None:
            return None
        for chat_key in _order:
            entry = _pending[chat_key]
            if entry["ready_at"] <= now:
                _order.remove(chat_key)
                del _pending[chat_key]
                entry["stage"] = "starting"
                entry["stage_at"] = now
                entry["started_at"] = now
                _current = entry
                return entry
    return None


def _finish(entry):
    global _current
    with _queue_lock:
        entry["finished_at"] = time.time()
        _recent.insert(0, entry)
        del _recent[RECENT_KEEP:]
        _current = None


def _dispatcher():
    """One chat answered at a time, in arrival order."""
    while True:
        time.sleep(QUEUE_TICK_S)
        if _restarting:
            return
        try:
            entry = _take_next()
            if entry is None:
                continue
            _answer(entry)
            _finish(entry)
        except Exception:  # noqa: BLE001 - the queue must never die
            log.exception("Dispatcher error")
            with _queue_lock:
                globals()["_current"] = None


@client.event(ChatPresenceEv)
def _on_chat_presence(_client, ev):
    """Someone is typing at us -- if they are mid-burst, wait for the rest."""
    try:
        source = ev.MessageSource
        if source.IsFromMe:
            return
        if ev.State != ChatPresence.CHAT_PRESENCE_COMPOSING:
            return
        chat = source.Chat
        _extend_hold(f"{chat.User}@{chat.Server}")
    except Exception:  # noqa: BLE001
        log.debug("Could not handle chat presence", exc_info=True)


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

        # Nothing is dropped any more: it joins the queue, merging with anything
        # else this chat has sent in the last few seconds.
        _enqueue(message, text, chat, is_group, message.Info.Pushname)
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


def _view(entry, now, position=None):
    """One queue entry, shaped for the portal (no full message bodies)."""
    joined = " / ".join(entry["texts"])
    return {
        "chat": entry["chat_key"],
        "name": entry["name"],
        "is_group": entry["is_group"],
        "messages": len(entry["texts"]),
        "preview": joined[:90] + ("…" if len(joined) > 90 else ""),
        "stage": entry["stage"],
        "position": position,
        "waiting_for": round(now - entry["queued_at"], 1),
        "ready_in": round(max(0.0, entry.get("ready_at", now) - now), 1),
        "outcome": entry.get("outcome"),
        "error": entry.get("error"),
        "took": (
            round(entry["finished_at"] - entry["started_at"], 1)
            if entry.get("finished_at") and entry.get("started_at")
            else None
        ),
    }


@app.get("/queue")
def queue():
    """Live view of who is being answered and who is next."""
    now = time.time()
    with _queue_lock:
        current = _view(_current, now) if _current else None
        waiting = [
            _view(_pending[key], now, position=i + 1) for i, key in enumerate(_order)
        ]
        recent = [_view(e, now) for e in _recent]
    return jsonify(
        {
            "current": current,
            "waiting": waiting,
            "recent": recent,
            "waiting_count": len(waiting),
        }
    )


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
    threading.Thread(target=_dispatcher, daemon=True).start()
    log.info("Worker API listening on :8100 -- starting WhatsApp client")
    client.connect()
    # connect() returns when the Go context is cancelled (i.e. we asked for a
    # restart). Give the restart thread its moment; if it never arrives, exit
    # anyway so the container restarts us rather than idling with no connection.
    time.sleep(5)
    log.warning("WhatsApp client loop ended -- exiting so the container restarts")
    os._exit(0)
