"""Thin client for the Gemini Interactions API.

Docs: https://ai.google.dev/gemini-api/docs/interactions/quickstart

Request shape:
    POST https://generativelanguage.googleapis.com/v1beta/interactions
    {"model": ..., "input": ..., "system_instruction": ..., "generation_config": {...}}

Response shape (the `steps` schema, pinned via the Api-Revision header):
    {"status": "completed",
     "steps": [{"type": "model_output", "content": [{"type": "text", "text": "..."}]}]}
"""
import requests

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

# Pins the response schema. Google replaced the older `outputs` array with
# `steps` in this revision; without the header we're at the mercy of whatever
# the default becomes next.
API_REVISION = "2026-05-20"

# Gemini 3 models think before answering; vague or meta questions can take a
# while. Kept in step with the worker so the Test button behaves like a real
# incoming message.
TIMEOUT_S = 60
THINKING_LEVEL = "low"

DEFAULT_MAX_OUTPUT_TOKENS = 1024


class GeminiError(RuntimeError):
    """Anything that stopped us getting a reply, phrased for the portal UI."""


def generate(prompt, api_key, model, instruction="", max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS):
    """Ask Gemini for a single reply. Returns the text, or raises GeminiError."""
    if not (api_key or "").strip():
        raise GeminiError("No Gemini API key configured")
    if not (model or "").strip():
        raise GeminiError("No Gemini model configured")
    if not (prompt or "").strip():
        raise GeminiError("Nothing to send")

    body = {
        "model": model.strip(),
        "input": prompt,
        "generation_config": {
            "max_output_tokens": max_output_tokens,
            "thinking_level": THINKING_LEVEL,
        },
    }
    if (instruction or "").strip():
        body["system_instruction"] = instruction.strip()

    try:
        r = requests.post(
            ENDPOINT,
            json=body,
            timeout=TIMEOUT_S,
            headers={
                "x-goog-api-key": api_key.strip(),
                "Api-Revision": API_REVISION,
                "Content-Type": "application/json",
            },
        )
    except requests.Timeout as exc:
        raise GeminiError(f"Gemini did not respond within {TIMEOUT_S}s") from exc
    except requests.RequestException as exc:
        raise GeminiError(f"Could not reach Gemini: {exc}") from exc

    try:
        data = r.json()
    except ValueError:
        data = {}

    # Errors from this endpoint arrive as a JSON array wrapping the error
    # object, while successful replies are a plain object. Normalise both.
    if isinstance(data, list):
        data = next((item for item in data if isinstance(item, dict)), {})
    if not isinstance(data, dict):
        data = {}

    if not r.ok:
        raise GeminiError(_error_message(r.status_code, data))

    text = _extract_text(data)
    if not text:
        status = data.get("status") or "unknown"
        raise GeminiError(f"Gemini returned no text (interaction status: {status})")
    return text


def _extract_text(data):
    """Pull the model's text out of the `steps` array."""
    chunks = []
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if item.get("type") == "text" and item.get("text"):
                chunks.append(item["text"])
    return "\n".join(chunks).strip()


def _error_message(status_code, data):
    """Google's error body, flattened. Never echoes the API key back."""
    error = data.get("error")
    message = ""
    if isinstance(error, dict):
        message = error.get("message") or ""
    elif isinstance(error, str):
        message = error
    message = message or data.get("message") or ""

    if status_code in (401, 403):
        return message or "Gemini rejected the API key (check it is valid and enabled)"
    if status_code == 404:
        return message or "Model not found — check the model id"
    if status_code == 429:
        return message or "Gemini rate limit or quota exceeded"
    return message or f"Gemini returned HTTP {status_code}"
