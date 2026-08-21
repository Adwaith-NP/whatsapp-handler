from django.utils import timezone
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import gemini, services
from .models import (
    DEFAULT_MODEL,
    MAX_INSTRUCTION_CHARS,
    ApiKey,
    AutomationSettings,
    GeminiSettings,
)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_view(request):
    """Who the current token belongs to. Also doubles as a token check."""
    user = request.user
    return Response(
        {
            "username": user.get_username(),
            "display_name": user.get_full_name() or user.get_username(),
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def queue_view(request):
    """Live reply queue, straight from the worker (never persisted)."""
    try:
        return Response(services.get_queue())
    except Exception as exc:  # noqa: BLE001
        return Response({"error": str(exc)}, status=502)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def status_view(request):
    try:
        return Response(services.get_status())
    except Exception as exc:  # noqa: BLE001
        return Response({"error": f"worker unreachable: {exc}"}, status=502)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_view(request):
    phone = (request.data.get("phone") or "").strip()
    message = request.data.get("message") or ""
    if not phone or not message:
        return Response({"error": "phone and message are required"}, status=400)
    try:
        return Response(services.send_message(phone, message))
    except Exception as exc:  # noqa: BLE001
        return Response({"error": str(exc)}, status=502)


def _serialize_gemini(s):
    """The API key itself is never returned -- only whether one is stored."""
    return {
        "model": s.model,
        "instruction": s.instruction,
        "has_api_key": bool(s.api_key),
        "api_key_hint": s.api_key_hint,
        "default_model": DEFAULT_MODEL,
        "updated_at": s.updated_at,
    }


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def gemini_settings_view(request):
    settings_row = GeminiSettings.load()

    if request.method == "PUT":
        model = (request.data.get("model") or "").strip()
        settings_row.model = model or DEFAULT_MODEL

        instruction = request.data.get("instruction")
        if instruction is not None:
            settings_row.instruction = str(instruction).strip()[:MAX_INSTRUCTION_CHARS]

        if request.data.get("clear_api_key"):
            settings_row.api_key = ""
        else:
            # A blank key means "leave the stored one alone" -- the browser is
            # never given the current key to send back.
            key = (request.data.get("api_key") or "").strip()
            if key:
                settings_row.api_key = key

        settings_row.save()

    return Response(_serialize_gemini(settings_row))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def gemini_test_view(request):
    """Send one probe message to Gemini and return its reply.

    Falls back to the saved values, so the form can be tested before saving.
    """
    saved = GeminiSettings.load()
    api_key = (request.data.get("api_key") or "").strip() or saved.api_key
    model = (request.data.get("model") or "").strip() or saved.model

    instruction = request.data.get("instruction")
    instruction = saved.instruction if instruction is None else str(instruction)

    message = (request.data.get("message") or "").strip() or "Hi, what can you help me with?"

    try:
        reply = gemini.generate(message, api_key=api_key, model=model, instruction=instruction)
    except gemini.GeminiError as exc:
        return Response({"ok": False, "error": str(exc)}, status=400)
    return Response({"ok": True, "model": model, "reply": reply})


def _serialize_key(row):
    return {
        "id": row.id,
        "name": row.name,
        "type": row.key_type,
        "type_label": row.get_key_type_display(),
        "prefix": row.prefix,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def api_keys_view(request):
    if request.method == "POST":
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "A name is required"}, status=400)
        if len(name) > 100:
            return Response({"error": "Name is too long (100 characters max)"}, status=400)

        key_type = (request.data.get("type") or ApiKey.TYPE_SEND_MESSAGE).strip()
        valid_types = [choice[0] for choice in ApiKey.TYPE_CHOICES]
        if key_type not in valid_types:
            return Response(
                {"error": f"Unknown type '{key_type}'. Valid: {', '.join(valid_types)}"},
                status=400,
            )

        row, raw_key = ApiKey.issue(name, key_type)
        # The only time the key is ever returned.
        return Response({**_serialize_key(row), "key": raw_key}, status=201)

    return Response([_serialize_key(row) for row in ApiKey.objects.all()])


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def api_key_detail_view(request, pk):
    try:
        row = ApiKey.objects.get(pk=pk)
    except ApiKey.DoesNotExist:
        return Response({"error": "No such API key"}, status=404)
    row.delete()
    return Response(status=204)


def _key_from_request(request):
    """The ApiKey behind this request, or None.

    Accepts `X-API-Key: <key>` or `Authorization: Bearer <key>`.
    """
    raw = (request.headers.get("X-API-Key") or "").strip()
    if not raw:
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            raw = auth[7:].strip()
    if not raw:
        return None
    return ApiKey.objects.filter(key_hash=ApiKey.hash_key(raw)).first()


@api_view(["POST"])
@authentication_classes([])  # API-key auth, not the portal's login token
@permission_classes([AllowAny])
def public_send_message_view(request):
    """POST /api/v1/messages/ -- send a WhatsApp message from another app."""
    key = _key_from_request(request)
    if key is None:
        return Response(
            {"ok": False, "error": "Missing or invalid API key (send it as X-API-Key)"},
            status=401,
        )
    if key.key_type != ApiKey.TYPE_SEND_MESSAGE:
        return Response(
            {"ok": False, "error": "This key is not allowed to send messages"}, status=403
        )

    phone = str(request.data.get("phone") or "").strip().lstrip("+").replace(" ", "")
    message = request.data.get("message") or ""

    if not phone or not message:
        return Response({"ok": False, "error": "phone and message are required"}, status=400)
    if not phone.isdigit():
        return Response(
            {"ok": False, "error": "phone must be digits only, including the country code"},
            status=400,
        )
    if not 8 <= len(phone) <= 15:
        return Response({"ok": False, "error": "phone is not a valid length"}, status=400)

    try:
        services.send_message(phone, message)
    except services.WorkerError as exc:
        # 409 from the worker means WhatsApp itself is not connected.
        status = 503 if exc.status_code == 409 else 502
        return Response({"ok": False, "error": str(exc)}, status=status)
    except Exception as exc:  # noqa: BLE001
        return Response({"ok": False, "error": str(exc)}, status=502)

    ApiKey.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
    return Response({"ok": True, "phone": phone}, status=200)


def _as_bool(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _as_delay(value, default):
    """Seconds, clamped to the allowed window. Junk falls back to the default."""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return default
    return max(AutomationSettings.DELAY_MIN, min(AutomationSettings.DELAY_MAX, seconds))


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def automation_settings_view(request):
    auto = AutomationSettings.load()

    if request.method == "PUT":
        auto.reply_to_all = _as_bool(request.data.get("reply_to_all"), auto.reply_to_all)
        auto.skip_direct = _as_bool(request.data.get("skip_direct"), auto.skip_direct)
        auto.skip_groups = _as_bool(request.data.get("skip_groups"), auto.skip_groups)
        auto.read_receipt_enabled = _as_bool(
            request.data.get("read_receipt_enabled"), auto.read_receipt_enabled
        )
        if "read_receipt_delay" in request.data:
            auto.read_receipt_delay = _as_delay(
                request.data["read_receipt_delay"], auto.read_receipt_delay
            )
        if "typing_delay" in request.data:
            auto.typing_delay = _as_delay(request.data["typing_delay"], auto.typing_delay)
        if "batch_window" in request.data:
            auto.batch_window = _as_delay(request.data["batch_window"], auto.batch_window)
        auto.save()

    # The automation is inert without a key, so the page needs to know.
    ai = GeminiSettings.load()
    return Response(
        {
            "reply_to_all": auto.reply_to_all,
            "skip_direct": auto.skip_direct,
            "skip_groups": auto.skip_groups,
            "read_receipt_enabled": auto.read_receipt_enabled,
            "read_receipt_delay": auto.read_receipt_delay,
            "typing_delay": auto.typing_delay,
            "batch_window": auto.batch_window,
            "delay_min": AutomationSettings.DELAY_MIN,
            "delay_max": AutomationSettings.DELAY_MAX,
            "updated_at": auto.updated_at,
            "ai_configured": bool(ai.api_key),
            "ai_model": ai.model,
            "ai_has_instruction": bool(ai.instruction.strip()),
        }
    )
