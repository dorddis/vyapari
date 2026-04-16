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
    async def send_typing(self, to: str) -> None:
        """Show typing indicator (up to 25s on WhatsApp)."""
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


# ---------------------------------------------------------------------------
# Channel factory
# ---------------------------------------------------------------------------

_active_adapter: ChannelAdapter | None = None


def get_channel() -> ChannelAdapter:
    """Get the active channel adapter (singleton)."""
    global _active_adapter
    if _active_adapter is None:
        from config import CHANNEL_MODE
        if CHANNEL_MODE == "web_clone":
            from channels.web_clone.adapter import WebCloneAdapter
            _active_adapter = WebCloneAdapter()
        else:
            from channels.whatsapp.adapter import WhatsAppAdapter
            _active_adapter = WhatsAppAdapter()
    return _active_adapter


def reset_channel() -> None:
    """Reset the active adapter (for tests)."""
    global _active_adapter
    _active_adapter = None
