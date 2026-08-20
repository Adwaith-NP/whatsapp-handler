"""Per-chat conversation memory.

Each WhatsApp chat gets its own thread of recent turns, so the AI can follow a
conversation instead of meeting every message cold -- and so two different
contacts never see each other's context.

Kept deliberately short: only the last few turns go to the model, each one
truncated. That bounds both the token cost per reply and how far back a stale
thread can reach.
"""
import logging
import os

import psycopg2

log = logging.getLogger("worker.memory")

DATABASE_URL = os.environ["NEONIZE_DATABASE_URL"]
TABLE = "whatsapp_chatmemory"

# Turns replayed to the model (a turn is one message from either side).
MAX_TURNS = 10
# Each remembered line is cut to this length before it is stored.
MAX_CHARS = 600
# Rows kept per chat; older ones are pruned as new ones arrive.
KEEP_PER_CHAT = 40
# Nothing older than this is replayed -- a conversation from last week should
# not silently continue today.
MAX_AGE_HOURS = 24

ROLE_USER = "user"
ROLE_MODEL = "model"


def history(chat_jid, limit=MAX_TURNS):
    """Recent turns for one chat, oldest first: [{"role": ..., "text": ...}].

    Never raises -- no memory is better than no reply.
    """
    try:
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT role, text FROM {TABLE} "
                "WHERE chat_jid = %s AND created_at > NOW() - make_interval(hours => %s) "
                "ORDER BY id DESC LIMIT %s",
                (chat_jid, MAX_AGE_HOURS, limit),
            )
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not read chat memory for %s: %s", chat_jid, exc)
        return []

    rows.reverse()  # oldest first, the order the model expects
    return [{"role": role, "text": text} for role, text in rows]


def remember(chat_jid, role, text):
    """Append one line to a chat's memory and prune that chat's old rows."""
    text = (text or "").strip()[:MAX_CHARS]
    if not text:
        return
    try:
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {TABLE} (chat_jid, role, text, created_at) "
                "VALUES (%s, %s, %s, NOW())",
                (chat_jid, role, text),
            )
            cur.execute(
                f"DELETE FROM {TABLE} WHERE chat_jid = %s AND id NOT IN "
                f"(SELECT id FROM {TABLE} WHERE chat_jid = %s ORDER BY id DESC LIMIT %s)",
                (chat_jid, chat_jid, KEEP_PER_CHAT),
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not save chat memory for %s: %s", chat_jid, exc)
