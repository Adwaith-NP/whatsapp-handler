"""Reads the portal's AI + automation settings out of Postgres.

The worker and the Django backend share one database. Rather than exposing an
internal HTTP endpoint (a new public surface that would need its own secret),
the worker reads the two single-row settings tables directly. Django owns the
schema; these are its table names.

Values are cached briefly so a burst of incoming messages doesn't mean a query
each -- but short enough that toggling automation in the portal takes effect
within a few seconds, with no restart.
"""
import logging
import os
import threading
import time

import psycopg2

log = logging.getLogger("worker.config")

DATABASE_URL = os.environ["NEONIZE_DATABASE_URL"]
CACHE_TTL_S = 5

GEMINI_TABLE = "whatsapp_geminisettings"
AUTOMATION_TABLE = "whatsapp_automationsettings"

DEFAULTS = {
    "reply_to_all": False,
    "skip_direct": False,
    "skip_groups": True,
    "read_receipt_enabled": False,
    "read_receipt_delay": 5,
    "typing_delay": 3,
    "api_key": "",
    "model": "",
    "instruction": "",
}

_cache = {"at": 0.0, "value": dict(DEFAULTS)}
_lock = threading.Lock()


def load(force=False):
    """Current settings as a plain dict. Never raises -- falls back to the last
    known good values (or the defaults), so a database hiccup can't take the
    WhatsApp connection down with it."""
    now = time.monotonic()
    with _lock:
        if not force and now - _cache["at"] < CACHE_TTL_S:
            return dict(_cache["value"])

    value = dict(DEFAULTS)
    try:
        # Django's migrations create the row on first read from the portal, so
        # an empty table simply means "never configured" -> defaults.
        with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT reply_to_all, skip_direct, skip_groups, read_receipt_enabled, "
                f"read_receipt_delay, typing_delay FROM {AUTOMATION_TABLE} ORDER BY id LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                (
                    value["reply_to_all"],
                    value["skip_direct"],
                    value["skip_groups"],
                    value["read_receipt_enabled"],
                    value["read_receipt_delay"],
                    value["typing_delay"],
                ) = row

            cur.execute(
                f"SELECT api_key, model, instruction FROM {GEMINI_TABLE} ORDER BY id LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                value["api_key"], value["model"], value["instruction"] = row
    except Exception as exc:  # noqa: BLE001 - stale config beats a crash loop
        log.warning("Could not read settings from the database: %s", exc)
        with _lock:
            _cache["at"] = time.monotonic()
            return dict(_cache["value"])

    with _lock:
        _cache["at"] = time.monotonic()
        _cache["value"] = value
    return dict(value)
