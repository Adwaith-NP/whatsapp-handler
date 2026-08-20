"""Thin client for the internal WhatsApp worker API."""
import requests
from django.conf import settings


class WorkerError(RuntimeError):
    """A failure reported by the worker, carrying its HTTP status.

    Subclasses RuntimeError so existing `except Exception` callers are unaffected;
    the status lets the public API tell "not connected" (worker 409) apart from a
    genuine fault.
    """

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def get_status():
    r = requests.get(f"{settings.WORKER_URL}/status", timeout=5)
    r.raise_for_status()
    return r.json()


def send_message(phone, message):
    r = requests.post(
        f"{settings.WORKER_URL}/send",
        json={"phone": phone, "message": message},
        timeout=20,
    )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not r.ok:
        raise WorkerError(data.get("error", f"worker returned {r.status_code}"), r.status_code)
    return data
