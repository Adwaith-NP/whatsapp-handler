"""Thin client for the Gemini Interactions API.

Mirrors backend/whatsapp/gemini.py. The two services are separate containers
with no shared package, so this small client is deliberately duplicated rather
than reached for over HTTP -- keep them in step if the API shape changes.

Docs: https://ai.google.dev/gemini-api/docs/interactions/quickstart
"""
import requests

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"

# Pins the response schema (the `steps` array).
API_REVISION = "2026-05-20"

# Gemini 3 models think before answering, and vague or meta questions ("oii",
# "are you an AI") send them off on much longer deliberations than a plain
# "hello". At 30s those were timing out and the chat got no reply at all.
TIMEOUT_S = 60

# Keeps the reasoning short so a WhatsApp reply arrives in seconds. "minimal",
# "low", "medium" and "high" are the documented levels.
THINKING_LEVEL = "low"

DEFAULT_MAX_OUTPUT_TOKENS = 1024


class GeminiError(RuntimeError):
    pass


def _steps(history, prompt):
    """Conversation history plus the new message, as Interactions API steps.

    Roles map to step types: what they said is `user_input`, what the AI said
    last time is `model_output`.
    """
    steps = []
    for turn in history:
        step_type = "model_output" if turn.get("role") == "model" else "user_input"
        text = (turn.get("text") or "").strip()
        if text:
            steps.append({"type": step_type, "content": [{"type": "text", "text": text}]})
    steps.append({"type": "user_input", "content": [{"type": "text", "text": prompt}]})
    return steps


def generate(
    prompt,
    api_key,
    model,
    instruction="",
    history=None,
    max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
):
    """Ask Gemini for a single reply. Returns the text, or raises GeminiError.

    `history` is an optional list of {"role": "user"|"model", "text": ...},
    oldest first, giving the model the thread so far.
    """
    if not (api_key or "").strip():
        raise GeminiError("No Gemini API key configured")
    if not (model or "").strip():
        raise GeminiError("No Gemini model configured")
    if not (prompt or "").strip():
        raise GeminiError("Nothing to send")

    body = {
        "model": model.strip(),
        # We keep the conversation ourselves rather than letting Google hold it
        # server-side: the thread stays on this server, and each request carries
        # only the few recent turns instead of an ever-growing history.
        "store": False,
        "input": _steps(history, prompt) if history else prompt,
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

    # Errors come back as a JSON array wrapping the error object; successful
    # replies are a plain object.
    if isinstance(data, list):
        data = next((item for item in data if isinstance(item, dict)), {})
    if not isinstance(data, dict):
        data = {}

    if not r.ok:
        error = data.get("error")
        message = error.get("message") if isinstance(error, dict) else (error or "")
        raise GeminiError(message or f"Gemini returned HTTP {r.status_code}")

    chunks = []
    for step in data.get("steps") or []:
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if item.get("type") == "text" and item.get("text"):
                chunks.append(item["text"])
    text = "\n".join(chunks).strip()

    if not text:
        raise GeminiError(f"Gemini returned no text (status: {data.get('status')})")
    return text
