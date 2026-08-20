import hashlib
import secrets

from django.db import models

# Sensible current default; any Gemini model id the API key has access to works.
DEFAULT_MODEL = "gemini-3.6-flash"

# Guard rail so a runaway paste can't fill the column.
MAX_INSTRUCTION_CHARS = 8000


class GeminiSettings(models.Model):
    """Single-row table holding the Gemini integration config.

    The API key is write-only as far as the portal API is concerned: it is
    stored here and used server-side, but never sent back to the browser (only
    a "last 4 characters" hint is).
    """

    SINGLETON_PK = 1

    api_key = models.CharField(max_length=255, blank=True, default="")
    model = models.CharField(max_length=100, default=DEFAULT_MODEL)
    instruction = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Gemini settings"
        verbose_name_plural = "Gemini settings"

    def __str__(self):
        return f"Gemini settings ({self.model})"

    def save(self, *args, **kwargs):
        # There is only ever one row.
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj

    @property
    def api_key_hint(self):
        return f"…{self.api_key[-4:]}" if self.api_key else ""


class ChatMemory(models.Model):
    """One line of conversation with one chat.

    Gives the AI continuity: on each incoming message the worker replays the
    recent turns for *that* chat, so every contact has its own separate thread.
    Written and read by the worker; Django owns the schema.
    """

    ROLE_USER = "user"
    ROLE_MODEL = "model"
    ROLE_CHOICES = [(ROLE_USER, "Them"), (ROLE_MODEL, "AI")]

    chat_jid = models.CharField(max_length=64, db_index=True)
    role = models.CharField(max_length=8, choices=ROLE_CHOICES)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "chat memory"
        verbose_name_plural = "chat memory"
        indexes = [models.Index(fields=["chat_jid", "id"])]

    def __str__(self):
        return f"{self.chat_jid} {self.role}: {self.text[:40]}"


class ApiKey(models.Model):
    """A key another application uses to call this portal's public API.

    Only a SHA-256 hash is stored -- the key itself is shown once, at creation,
    and cannot be recovered afterwards. `prefix` is the readable head of the key
    kept purely so a row can be told apart in the UI.
    """

    TYPE_SEND_MESSAGE = "send_message"
    TYPE_CHOICES = [(TYPE_SEND_MESSAGE, "Send a WhatsApp message")]

    KEY_PREFIX = "wap"
    PREFIX_LENGTH = 12  # "wap_" + 8 characters

    name = models.CharField(max_length=100)
    key_type = models.CharField(max_length=32, choices=TYPE_CHOICES, default=TYPE_SEND_MESSAGE)
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    prefix = models.CharField(max_length=16)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "API key"

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def hash_key(raw):
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, name, key_type=TYPE_SEND_MESSAGE):
        """Create a key. Returns (row, raw_key) -- raw_key is never stored."""
        raw = f"{cls.KEY_PREFIX}_{secrets.token_urlsafe(32)}"
        row = cls.objects.create(
            name=name,
            key_type=key_type,
            key_hash=cls.hash_key(raw),
            prefix=raw[: cls.PREFIX_LENGTH],
        )
        return row, raw


class AutomationSettings(models.Model):
    """Single-row table controlling automatic replies.

    Read by the worker (straight from Postgres) every time a message arrives,
    so a change here takes effect within seconds without a restart.
    """

    SINGLETON_PK = 1

    # Master switch: answer incoming messages with the AI.
    reply_to_all = models.BooleanField(default=False)

    # Chat kinds to leave alone while the switch is on.
    skip_direct = models.BooleanField(default=False)
    skip_groups = models.BooleanField(default=True)

    # Timing, in seconds. Both are clamped to DELAY_MIN..DELAY_MAX.
    # When read receipts are on, the message is marked read after
    # read_receipt_delay, and typing_delay is counted from that point.
    read_receipt_enabled = models.BooleanField(default=False)
    read_receipt_delay = models.PositiveSmallIntegerField(default=5)
    typing_delay = models.PositiveSmallIntegerField(default=3)

    updated_at = models.DateTimeField(auto_now=True)

    DELAY_MIN = 1
    DELAY_MAX = 60

    class Meta:
        verbose_name = "Automation settings"
        verbose_name_plural = "Automation settings"

    def __str__(self):
        return f"Automation (reply_to_all={self.reply_to_all})"

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj
