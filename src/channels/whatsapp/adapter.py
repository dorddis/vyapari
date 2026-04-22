"""WhatsApp channel adapter implementation."""

from __future__ import annotations

import logging
from uuid import uuid4

from channels.base import ChannelAdapter
from models import IncomingMessage, MessageType
from services.message_log import log_message
from whatsapp import (
    mark_read as legacy_mark_read,
    send_audio as legacy_send_audio,
    send_image as legacy_send_image,
    send_text as legacy_send_text,
    upload_media as legacy_upload_media,
)

log = logging.getLogger("vyapari.channels.whatsapp")


def _extract_response_msg_id(response: dict) -> str:
    """Extract message id from Cloud API response."""
    try:
        return str(response["messages"][0]["id"])
    except (KeyError, IndexError, TypeError):
        return f"wa-{uuid4()}"


class WhatsAppAdapter(ChannelAdapter):
    """Adapter that talks to WhatsApp Cloud API."""

    async def _resolve_outbound_role(self, to: str) -> str:
        """Return the logical sender role for a message we're about to send.

        Default is 'bot'. If the customer has an active relay session, the
        role reflects the staff on the other end (owner/sdr) so message
        logs distinguish agent replies from human hijacks.

        DB lookups are best-effort. A DB outage or schema mismatch falls
        back to 'bot' with a warning (previously masked as silent success).
        """
        try:
            import state
            from models import StaffRole

            relay = await state.get_active_relay_for_customer(to)
            if not relay:
                return "bot"
            staff = await state.get_staff(relay.staff_wa_id)
            if staff and staff.role == StaffRole.OWNER:
                return "owner"
            if staff and staff.role == StaffRole.SDR:
                return "sdr"
            return "bot"
        except Exception:
            log.warning("Role resolution failed for %s; defaulting to 'bot'", to, exc_info=True)
            return "bot"

    async def send_text(self, to: str, text: str) -> str:
        response = await legacy_send_text(to, text)
        external_msg_id = _extract_response_msg_id(response)
        role = await self._resolve_outbound_role(to)

        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="whatsapp",
            text=text,
            msg_type="text",
            external_msg_id=external_msg_id,
        )
        return external_msg_id

    async def send_image(self, to: str, image_url: str, caption: str = "") -> str:
        response = await legacy_send_image(to, image_url, caption)
        external_msg_id = _extract_response_msg_id(response)
        role = await self._resolve_outbound_role(to)

        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="whatsapp",
            text=caption or "Image",
            msg_type="image",
            external_msg_id=external_msg_id,
            images=[image_url],
        )
        return external_msg_id

    async def send_audio(
        self, to: str, audio_bytes: bytes, mime_type: str = "audio/ogg; codecs=opus"
    ) -> str:
        """Upload the audio bytes to Meta's media endpoint, then send by media_id.

        Two Graph API calls: upload -> /media, send -> /messages. Returns the
        Cloud API message id so the caller can correlate status callbacks.
        """
        # Trim any codec parameters for the filename hint; the mime_type stays full.
        base_mime = mime_type.split(";")[0].strip()
        ext = base_mime.split("/")[-1] if "/" in base_mime else "bin"
        upload_result = await legacy_upload_media(
            file_bytes=audio_bytes,
            mime_type=mime_type,
            filename=f"voice.{ext}",
        )
        media_id = upload_result.get("id")
        if not media_id:
            raise RuntimeError(f"upload_media returned no id: {upload_result}")

        response = await legacy_send_audio(to, media_id=media_id)
        external_msg_id = _extract_response_msg_id(response)
        await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="whatsapp",
            text="Audio",
            msg_type="audio",
            external_msg_id=external_msg_id,
        )
        return external_msg_id

    async def send_buttons(
        self,
        to: str,
        body: str,
        buttons: list[dict],
        header: str | None = None,
        footer: str | None = None,
        image_url: str | None = None,
    ) -> str:
        # Fallback text rendering until interactive payload sender is added.
        titles = ", ".join(button.get("title", "Option") for button in buttons)
        text = body if titles == "" else f"{body}\n\nOptions: {titles}"
        return await self.send_text(to, text)

    async def send_list(
        self,
        to: str,
        body: str,
        button_text: str,
        sections: list[dict],
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        rows: list[str] = []
        for section in sections:
            for row in section.get("rows", []):
                rows.append(row.get("title", "Item"))
        text = body if not rows else f"{body}\n\n{button_text}: {', '.join(rows[:10])}"
        return await self.send_text(to, text)

    async def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
    ) -> str:
        label = name or "Location"
        text = f"{label}: {latitude}, {longitude}"
        if address:
            text = f"{text}\n{address}"
        return await self.send_text(to, text)

    async def send_contact(self, to: str, name: str, phone: str) -> str:
        return await self.send_text(to, f"Contact: {name} ({phone})")

    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en",
        params: list[str] | None = None,
        image_url: str | None = None,
    ) -> str:
        params_text = ", ".join(params or [])
        text = f"Template[{template_name}/{language}]"
        if params_text:
            text = f"{text}: {params_text}"
        return await self.send_text(to, text)

    async def send_typing(self, to: str, replying_to_msg_id: str | None = None) -> None:
        # Cloud API v21 typing indicators POST to the messages endpoint
        # with {"status":"read", "message_id": <wamid>, "typing_indicator":
        # {"type":"text"}}. Wiring that up is a Phase 1 task (needs
        # main.py to thread msg.msg_id through). For now, no-op.
        return None

    async def mark_read(self, msg_id: str) -> None:
        await legacy_mark_read(msg_id)

    def extract_message(self, payload: dict) -> IncomingMessage | None:
        """Parse a WhatsApp Cloud API webhook payload into an IncomingMessage.

        Returns None for:
        - Non-message payloads (status updates, system events, malformed)
        - Message types we don't yet parse in Phase 0: interactive, location,
          contacts, sticker, reaction, unsupported. These are handled in Phase 1.
        """
        try:
            value = payload["entry"][0]["changes"][0]["value"]
        except (KeyError, IndexError, TypeError):
            return None

        # Status updates (delivered/read/failed/sent) have `statuses`, not `messages`.
        # These get logged in Phase 1; for now they're safely dropped.
        if "statuses" in value:
            return None

        messages = value.get("messages")
        if not messages:
            return None

        msg = messages[0]
        wa_id = msg.get("from")
        msg_id = msg.get("id")
        msg_type_raw = msg.get("type", "text")

        if not wa_id or not msg_id:
            return None

        # Sender display name (from WhatsApp profile) if present.
        sender_name: str | None = None
        contacts = value.get("contacts") or []
        if contacts:
            profile = contacts[0].get("profile") or {}
            sender_name = profile.get("name")

        # Branch on message type. Phase 0 covers text + the four media kinds
        # that main.py:200-275 already flows. Everything else is deferred.
        if msg_type_raw == "text":
            text_body = (msg.get("text") or {}).get("body")
            return IncomingMessage(
                wa_id=wa_id,
                text=text_body,
                msg_id=msg_id,
                msg_type=MessageType.TEXT,
                sender_name=sender_name,
            )

        if msg_type_raw == "image":
            image = msg.get("image") or {}
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.IMAGE,
                media_id=image.get("id"),
                caption=image.get("caption"),
                sender_name=sender_name,
            )

        if msg_type_raw == "document":
            doc = msg.get("document") or {}
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.DOCUMENT,
                media_id=doc.get("id"),
                caption=doc.get("caption"),
                sender_name=sender_name,
            )

        if msg_type_raw == "audio":
            audio = msg.get("audio") or {}
            # Voice notes carry `voice: true`; plain audio uploads don't.
            # Use `is True` (not bool()) so a stringly-typed "false" from
            # a future Meta schema change doesn't misroute to the voice path.
            is_voice = audio.get("voice") is True
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.VOICE if is_voice else MessageType.AUDIO,
                media_id=audio.get("id"),
                sender_name=sender_name,
            )

        if msg_type_raw == "video":
            # main.py:270-275 rejects videos with a friendly message.
            # Surface the type so that reject path fires.
            video = msg.get("video") or {}
            return IncomingMessage(
                wa_id=wa_id,
                text=None,
                msg_id=msg_id,
                msg_type=MessageType.VIDEO,
                media_id=video.get("id"),
                caption=video.get("caption"),
                sender_name=sender_name,
            )

        # Interactive replies, location, contacts, sticker, reaction, unsupported,
        # etc. — Phase 1 will parse these into IncomingMessage. For Phase 0 we
        # drop them safely so dispatch doesn't crash.
        log.info(
            "Dropping unsupported inbound type '%s' from %s (handled in Phase 1)",
            msg_type_raw, wa_id,
        )
        return None
