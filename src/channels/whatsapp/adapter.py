"""WhatsApp channel adapter implementation."""

from __future__ import annotations

from uuid import uuid4

from channels.base import ChannelAdapter
from models import IncomingMessage, MessageType
from services.message_log import log_message
from whatsapp import (
    extract_message as legacy_extract_message,
    mark_read as legacy_mark_read,
    send_image as legacy_send_image,
    send_text as legacy_send_text,
)


def _extract_response_msg_id(response: dict) -> str:
    """Extract message id from Cloud API response."""
    try:
        return str(response["messages"][0]["id"])
    except (KeyError, IndexError, TypeError):
        return f"wa-{uuid4()}"


class WhatsAppAdapter(ChannelAdapter):
    """Adapter that talks to WhatsApp Cloud API."""

    async def send_text(self, to: str, text: str) -> str:
        response = await legacy_send_text(to, text)
        external_msg_id = _extract_response_msg_id(response)
        role = "bot"
        try:
            import state
            from models import StaffRole

            relay = await state.get_active_relay_for_customer(to)
            if relay:
                staff = await state.get_staff(relay.staff_wa_id)
                if staff and staff.role == StaffRole.OWNER:
                    role = "owner"
                elif staff and staff.role == StaffRole.SDR:
                    role = "sdr"
        except Exception:
            role = "bot"

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
        role = "bot"
        try:
            import state
            from models import StaffRole

            relay = await state.get_active_relay_for_customer(to)
            if relay:
                staff = await state.get_staff(relay.staff_wa_id)
                if staff and staff.role == StaffRole.OWNER:
                    role = "owner"
                elif staff and staff.role == StaffRole.SDR:
                    role = "sdr"
        except Exception:
            role = "bot"

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

    async def send_typing(self, to: str) -> None:
        # Typing indicator via Graph API can be added later.
        return None

    async def mark_read(self, msg_id: str) -> None:
        await legacy_mark_read(msg_id)

    def extract_message(self, payload: dict) -> IncomingMessage | None:
        parsed = legacy_extract_message(payload)
        if parsed is None:
            return None

        wa_id, text, msg_id = parsed
        return IncomingMessage(
            wa_id=wa_id,
            text=text,
            msg_id=msg_id,
            msg_type=MessageType.TEXT,
        )
