"""Web clone adapter.

Stores outbound/inbound messages in memory so the web frontend can poll
`GET /api/messages/{wa_id}` instead of calling WhatsApp Cloud API.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from channels.base import ChannelAdapter
from models import IncomingMessage, MessageType


class WebCloneAdapter(ChannelAdapter):
    """In-memory channel adapter for local web demo/testing."""

    def __init__(self) -> None:
        self._messages_by_wa_id: dict[str, list[dict]] = {}

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _append_message(
        self,
        wa_id: str,
        role: str,
        text: str,
        images: list[str] | None = None,
        msg_type: str = "text",
    ) -> str:
        msg_id = f"web-{uuid4()}"
        payload = {
            "id": msg_id,
            "role": role,
            "text": text,
            "timestamp": self._now_iso(),
            "images": images or [],
            "is_escalation": False,
            "escalation_reason": "",
            "msg_type": msg_type,
        }
        self._messages_by_wa_id.setdefault(wa_id, []).append(payload)
        return msg_id

    # --- Extra helpers used by web_api.py ---

    def record_incoming(self, msg: IncomingMessage) -> str:
        """Store a user message from the web UI."""
        return self._append_message(
            wa_id=msg.wa_id,
            role="customer",
            text=msg.text or "",
            msg_type=msg.msg_type.value,
        )

    def get_messages(self, wa_id: str, since_id: str | None = None) -> list[dict]:
        """Get buffered messages for one wa_id."""
        messages = self._messages_by_wa_id.get(wa_id, [])
        if not since_id:
            return list(messages)

        found = False
        result: list[dict] = []
        for message in messages:
            if found:
                result.append(message)
            if message["id"] == since_id:
                found = True
        return result

    def list_conversations(self) -> list[dict]:
        """List per-customer summaries for owner web panel."""
        conversations: list[dict] = []
        for wa_id, messages in self._messages_by_wa_id.items():
            if not messages:
                continue
            last = messages[-1]
            customer_name = f"Customer {wa_id[-4:]}" if len(wa_id) >= 4 else "Customer"
            conversations.append(
                {
                    "customer_id": wa_id,
                    "customer_name": customer_name,
                    "last_message": last.get("text", ""),
                    "last_activity": last.get("timestamp", ""),
                    "mode": "bot",
                    "has_escalation": False,
                }
            )
        conversations.sort(key=lambda item: item["last_activity"], reverse=True)
        return conversations

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

        return self._append_message(wa_id=to, role=role, text=text)

    async def send_image(self, to: str, image_url: str, caption: str = "") -> str:
        return self._append_message(
            wa_id=to,
            role="bot",
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
        return self._append_message(wa_id=to, role="bot", text=text, images=images)

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
        return self._append_message(wa_id=to, role="bot", text=text)

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
        return self._append_message(wa_id=to, role="bot", text=text, msg_type="location")

    async def send_contact(self, to: str, name: str, phone: str) -> str:
        return self._append_message(
            wa_id=to,
            role="bot",
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
        return self._append_message(wa_id=to, role="bot", text=text, images=images)

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
