"""Web clone adapter."""

from __future__ import annotations

from uuid import uuid4

from channels.base import ChannelAdapter
from models import IncomingMessage, MessageType
from services.message_log import log_message


class WebCloneAdapter(ChannelAdapter):
    """Web adapter that writes outbound messages to DB message log."""

    # --- ChannelAdapter implementation ---

    async def send_text(self, to: str, text: str) -> str:
        role = "bot"

        # If this customer is in relay mode, outbound messages to them come
        # from an active staff member (owner/sdr), not the bot.
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
            # Keep demo adapter resilient; fallback role is bot.
            role = "bot"

        return await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="web_clone",
            text=text,
            msg_type="text",
        )

    async def send_image(self, to: str, image_url: str, caption: str = "") -> str:
        return await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=caption or "Image",
            images=[image_url],
            msg_type="image",
        )

    async def send_buttons(
        self,
        to: str,
        body: str,
        buttons: list[dict],
        header: str | None = None,
        footer: str | None = None,
        image_url: str | None = None,
    ) -> str:
        titles = ", ".join(button.get("title", "Option") for button in buttons)
        text = body if titles == "" else f"{body}\n\nOptions: {titles}"
        images = [image_url] if image_url else []
        return await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=text,
            images=images,
            msg_type="interactive_buttons",
        )

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
        items_text = ", ".join(rows[:10])
        text = body if items_text == "" else f"{body}\n\n{button_text}: {items_text}"
        return await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=text,
            msg_type="interactive_list",
        )

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
        return await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=text,
            msg_type="location",
        )

    async def send_contact(self, to: str, name: str, phone: str) -> str:
        return await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=f"Contact: {name} ({phone})",
            msg_type="contact",
        )

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
        images = [image_url] if image_url else []
        return await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=text,
            images=images,
            msg_type="template",
        )

    async def send_typing(self, to: str) -> None:
        return None

    async def mark_read(self, msg_id: str) -> None:
        return None

    def extract_message(self, payload: dict) -> IncomingMessage | None:
        """Parse optional web payloads into IncomingMessage."""
        try:
            wa_id = str(payload["wa_id"])
            text = payload.get("text")
            msg_id = str(payload.get("msg_id") or f"web-{uuid4()}")
            sender_name = payload.get("sender_name")
            msg_type_raw = payload.get("msg_type", "text")
            msg_type = (
                MessageType(msg_type_raw)
                if msg_type_raw in {item.value for item in MessageType}
                else MessageType.TEXT
            )
            return IncomingMessage(
                wa_id=wa_id,
                text=text,
                msg_id=msg_id,
                msg_type=msg_type,
                sender_name=sender_name,
            )
        except (KeyError, TypeError, ValueError):
            return None
