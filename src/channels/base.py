"""Abstract channel adapter interface.

All messaging (WhatsApp, web clone, future channels) goes through this
interface. Router and agents call these methods — never WhatsApp directly.
Swapping channels = changing CHANNEL_MODE in config, not rewriting code.
"""

from abc import ABC, abstractmethod

from models import IncomingMessage


class ChannelAdapter(ABC):
    """Base interface for all messaging channels."""

    # --- Sending ---

    @abstractmethod
    async def send_text(self, to: str, text: str) -> str:
        """Send a plain text message. Returns message ID."""
        ...

    @abstractmethod
    async def send_image(
        self, to: str, image_url: str, caption: str = ""
    ) -> str:
        """Send an image with optional caption. Returns message ID."""
        ...

    @abstractmethod
    async def send_buttons(
        self,
        to: str,
        body: str,
        buttons: list[dict],
        header: str | None = None,
        footer: str | None = None,
        image_url: str | None = None,
    ) -> str:
        """Send a message with reply buttons (max 3 on WhatsApp).

        Each button: {"id": "btn_id", "title": "Button Title"}
        Returns message ID.
        """
        ...

    @abstractmethod
    async def send_list(
        self,
        to: str,
        body: str,
        button_text: str,
        sections: list[dict],
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        """Send a list/section picker (max 10 rows on WhatsApp).

        Each section: {"title": "Section", "rows": [{"id": "row_id", "title": "...", "description": "..."}]}
        Returns message ID.
        """
        ...

    @abstractmethod
    async def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
    ) -> str:
        """Send a location pin. Returns message ID."""
        ...

    @abstractmethod
    async def send_contact(
        self, to: str, name: str, phone: str
    ) -> str:
        """Send a tappable contact card. Returns message ID."""
        ...

    @abstractmethod
    async def send_audio(
        self, to: str, audio_bytes: bytes, mime_type: str = "audio/ogg; codecs=opus"
    ) -> str:
        """Send an audio/voice note. Returns message ID."""
        ...

    @abstractmethod
    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en",
        params: list[str] | None = None,
        image_url: str | None = None,
    ) -> str:
        """Send a pre-approved template message (for 24hr window fallback).
        Returns message ID.
        """
        ...

    # --- Indicators ---

    @abstractmethod
    async def send_typing(self, to: str, replying_to_msg_id: str | None = None) -> None:
        """Show typing indicator (up to 25s on WhatsApp).

        `replying_to_msg_id` is required by the WhatsApp Cloud API v21+
        typing_indicator endpoint (it keys off the inbound message_id).
        Channels that don't use it (web_clone) can ignore the argument.
        """
        ...

    @abstractmethod
    async def mark_read(self, msg_id: str) -> None:
        """Mark a message as read (blue ticks on WhatsApp)."""
        ...

    # --- Receiving ---

    @abstractmethod
    def extract_message(self, payload: dict) -> IncomingMessage | None:
        """Parse a webhook/API payload into an IncomingMessage.

        Returns None if the payload isn't a user message (e.g. status update).
        """
        ...

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download inbound media by provider-side id. Returns (bytes, mime)."""
        raise NotImplementedError(
            f"{type(self).__name__} does not implement download_media"
        )

    def extract_status_updates(self, payload: dict) -> list[dict]:
        """Parse outbound-message delivery status events from a webhook payload.

        Return shape (per event):
            {"external_msg_id": str, "status": str,
             "timestamp": str | None, "recipient_id": str | None,
             "error": dict | None}

        Default is empty — channels without delivery callbacks (web_clone)
        inherit this. WhatsAppAdapter overrides to parse the `statuses[]`
        array Meta delivers alongside (or instead of) inbound messages.
        """
        return []


# ---------------------------------------------------------------------------
# Channel factory
# ---------------------------------------------------------------------------

_active_adapter: ChannelAdapter | None = None
# Per-business adapter cache for whatsapp mode: {business_id: adapter}.
# Each entry is bound to that tenant's access_token + phone_number_id
# via WhatsAppAdapter.__init__ so outbound sends hit the right WABA.
_per_business_adapters: dict[str, ChannelAdapter] = {}


def get_channel() -> ChannelAdapter:
    """Return the active channel adapter (singleton).

    For web_clone mode: one WebCloneAdapter shared across tenants (the
    web demo is inherently single-tenant).

    For whatsapp mode: the UNBOUND WhatsAppAdapter that falls back to
    the module-level env `WHATSAPP_ACCESS_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID`.
    This is the legacy single-tenant path — any multi-tenant caller MUST
    use `await get_tenant_channel(business_id)` instead to pick up that
    tenant's credentials.

    Note: the earlier sync signature of this function accepted a
    `business_id` arg that would warn-and-fallback to the unbound
    adapter. That was a silent tenant-crossover footgun — a caller who
    forgot to await `get_tenant_channel` would get a warning and the
    wrong tenant's creds. It's now removed; use `get_tenant_channel`.
    """
    global _active_adapter
    from config import CHANNEL_MODE

    if _active_adapter is not None:
        return _active_adapter

    if CHANNEL_MODE == "web_clone":
        from channels.web_clone.adapter import WebCloneAdapter
        _active_adapter = WebCloneAdapter()
    else:
        from channels.whatsapp.adapter import WhatsAppAdapter
        _active_adapter = WhatsAppAdapter()
    return _active_adapter


async def get_tenant_channel(business_id: str) -> ChannelAdapter:
    """Async variant that resolves tenant creds + returns a bound adapter.

    Use this from request-scoped code (webhook handler, agent tool runs)
    that knows the tenant. Caches per business_id.

    Empty / None business_id falls back to the unbound adapter — this
    is the legacy single-tenant path (web_clone demo, pre-P3 callers).
    """
    from config import CHANNEL_MODE
    if CHANNEL_MODE != "whatsapp":
        return get_channel()

    if not business_id:
        return get_channel()

    cached = _per_business_adapters.get(business_id)
    if cached is not None:
        return cached

    from channels.whatsapp.adapter import WhatsAppAdapter
    from services.business_config import (
        load_business_context,
        BusinessNotFoundError,
        NoActiveChannelError,
    )
    try:
        ctx = await load_business_context(business_id)
        adapter: ChannelAdapter = WhatsAppAdapter(
            access_token=ctx.access_token,
            phone_number_id=ctx.phone_number_id,
        )
    except (BusinessNotFoundError, NoActiveChannelError):
        # Tenant not fully provisioned yet — fall back to unbound.
        adapter = WhatsAppAdapter()
    _per_business_adapters[business_id] = adapter
    return adapter


def invalidate_channel(business_id: str | None = None) -> None:
    """Drop cached per-business adapters.

    Call after mutating a tenant's provider_config (token rotation,
    reauthorization, channel config edit) so the next send uses fresh
    credentials.
    """
    global _per_business_adapters
    if business_id is None:
        _per_business_adapters.clear()
        return
    _per_business_adapters.pop(business_id, None)


def reset_channel() -> None:
    """Reset the active adapter (for tests)."""
    global _active_adapter
    _per_business_adapters.clear()
    _active_adapter = None
