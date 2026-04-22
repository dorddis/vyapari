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
    send_contacts as legacy_send_contacts,
    send_image as legacy_send_image,
    send_interactive_buttons as legacy_send_interactive_buttons,
    send_interactive_list as legacy_send_interactive_list,
    send_location as legacy_send_location,
    send_template as legacy_send_template,
    send_text as legacy_send_text,
    send_typing_on as legacy_send_typing_on,
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
        """Send interactive reply buttons. Max 3 per Meta spec (enforced in helper)."""
        header_media: dict | None = None
        if image_url:
            header_media = {"type": "image", "image": {"link": image_url}}
        response = await legacy_send_interactive_buttons(
            to=to,
            body=body,
            buttons=buttons,
            header_text=header if not header_media else None,
            header_media=header_media,
            footer=footer,
        )
        external_msg_id = _extract_response_msg_id(response)
        role = await self._resolve_outbound_role(to)
        titles = ", ".join(button.get("title", "Option") for button in buttons)
        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="whatsapp",
            text=f"{body}\n[buttons: {titles}]" if titles else body,
            msg_type="interactive_buttons",
            external_msg_id=external_msg_id,
            images=[image_url] if image_url else [],
        )
        return external_msg_id

    async def send_list(
        self,
        to: str,
        body: str,
        button_text: str,
        sections: list[dict],
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        """Send interactive list picker. Max 10 rows across sections."""
        response = await legacy_send_interactive_list(
            to=to,
            body=body,
            button_text=button_text,
            sections=sections,
            header_text=header,
            footer=footer,
        )
        external_msg_id = _extract_response_msg_id(response)
        role = await self._resolve_outbound_role(to)
        rows: list[str] = []
        for section in sections:
            for row in section.get("rows", []):
                rows.append(row.get("title", "Item"))
        preview = f"{body}\n[{button_text}: {', '.join(rows[:10])}]" if rows else body
        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="whatsapp",
            text=preview,
            msg_type="interactive_list",
            external_msg_id=external_msg_id,
        )
        return external_msg_id

    async def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
    ) -> str:
        response = await legacy_send_location(
            to=to,
            latitude=latitude,
            longitude=longitude,
            name=name or None,
            address=address or None,
        )
        external_msg_id = _extract_response_msg_id(response)
        role = await self._resolve_outbound_role(to)
        label = name or "Location"
        text = f"{label}: {latitude}, {longitude}"
        if address:
            text = f"{text}\n{address}"
        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="whatsapp",
            text=text,
            msg_type="location",
            external_msg_id=external_msg_id,
        )
        return external_msg_id

    async def send_contact(self, to: str, name: str, phone: str) -> str:
        """Send a single contact card. Minimal shape: name + WORK phone."""
        parts = (name or "").strip().split(None, 1)
        first_name = parts[0] if parts else name
        last_name = parts[1] if len(parts) > 1 else ""
        contact: dict = {
            "name": {
                "formatted_name": name,
                "first_name": first_name,
                **({"last_name": last_name} if last_name else {}),
            },
            "phones": [{"phone": phone, "type": "WORK"}],
        }
        response = await legacy_send_contacts(to, [contact])
        external_msg_id = _extract_response_msg_id(response)
        role = await self._resolve_outbound_role(to)
        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="whatsapp",
            text=f"Contact: {name} ({phone})",
            msg_type="contact",
            external_msg_id=external_msg_id,
        )
        return external_msg_id

    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en",
        params: list[str] | None = None,
        image_url: str | None = None,
    ) -> str:
        """Send an approved template.

        `params` are positional body parameters that Meta substitutes into
        {{1}}, {{2}}, ... in the approved template body. `image_url` adds
        an image header component. For richer templates (video/document
        headers, button-param substitution) use the whatsapp.send_template
        helper directly with the full `components` list — Phase 2's
        dispatcher will replace this adapter method with a catalog-aware
        one that reads the approved schema from the DB.
        """
        components: list[dict] = []
        if image_url:
            components.append(
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"link": image_url}}],
                }
            )
        if params:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(p)} for p in params],
                }
            )
        response = await legacy_send_template(
            to=to,
            name=template_name,
            language=language,
            components=components or None,
        )
        external_msg_id = _extract_response_msg_id(response)
        role = await self._resolve_outbound_role(to)
        params_str = ", ".join(params) if params else ""
        preview = f"Template[{template_name}/{language}]"
        if params_str:
            preview = f"{preview}: {params_str}"
        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="whatsapp",
            text=preview,
            msg_type="template",
            external_msg_id=external_msg_id,
            images=[image_url] if image_url else [],
        )
        return external_msg_id

    async def send_typing(self, to: str, replying_to_msg_id: str | None = None) -> None:
        """Show typing dots for the given inbound message.

        Cloud API v21+ keys typing indicators off the inbound message_id.
        If the caller didn't pass one (legacy callers / web-clone-only
        code paths), we no-op rather than send a malformed request.
        """
        if not replying_to_msg_id:
            return None
        try:
            await legacy_send_typing_on(replying_to_msg_id)
        except Exception:
            # Typing indicator is a UX nicety; a failure must never block
            # the actual reply. Log and move on.
            log.warning("Typing indicator failed for %s", to, exc_info=True)
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
