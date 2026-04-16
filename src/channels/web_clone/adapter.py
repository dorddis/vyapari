"""Web Clone channel adapter.

Instead of sending messages via WhatsApp API, stores them in an
in-memory queue that the frontend polls via REST API. This is the
primary demo path — no WhatsApp integration needed.

Messages flow:
  Frontend POST /api/chat → router.dispatch() → agent reply
  → adapter.send_text() stores reply in outbox
  → Frontend GET /api/messages/{wa_id} polls and receives it
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from channels.base import ChannelAdapter
from models import IncomingMessage, MessageType
from services.message_log import log_message

log = logging.getLogger("vyapari.channels.web_clone")


# ---------------------------------------------------------------------------
# Outgoing message queue (frontend polls this)
# ---------------------------------------------------------------------------

# {wa_id: [{"id": str, "type": str, "content": dict, "timestamp": str}, ...]}
_outbox: dict[str, list[dict]] = {}


def get_pending_messages(wa_id: str, since_id: str | None = None) -> list[dict]:
    """Get pending outgoing messages for a wa_id.

    Called by the REST API when the frontend polls.
    If since_id is provided, returns only messages after that ID.
    """
    messages = _outbox.get(wa_id, [])
    if not since_id:
        return messages

    found = False
    result = []
    for msg in messages:
        if found:
            result.append(msg)
        if msg["id"] == since_id:
            found = True
    return result


def clear_outbox(wa_id: str) -> None:
    """Clear all pending messages for a wa_id."""
    _outbox.pop(wa_id, None)


def reset_outbox() -> None:
    """Clear all outboxes. For tests."""
    _outbox.clear()


def _enqueue(wa_id: str, msg_type: str, content: dict) -> str:
    """Add a message to the outbox. Returns message ID."""
    msg_id = f"web_{uuid4().hex[:12]}"
    if wa_id not in _outbox:
        _outbox[wa_id] = []
    _outbox[wa_id].append({
        "id": msg_id,
        "type": msg_type,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return msg_id


# ---------------------------------------------------------------------------
# WebCloneAdapter
# ---------------------------------------------------------------------------

class WebCloneAdapter(ChannelAdapter):
    """Channel adapter for the web demo frontend."""

    async def send_text(self, to: str, text: str) -> str:
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

        msg_id = _enqueue(to, "text", {"body": text})
        await log_message(
            wa_id=to,
            role=role,
            direction="outbound",
            channel="web_clone",
            text=text,
            msg_type="text",
            external_msg_id=msg_id,
        )
        return msg_id

    async def send_image(self, to: str, image_url: str, caption: str = "") -> str:
        msg_id = _enqueue(to, "image", {"url": image_url, "caption": caption})
        await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=caption or "Image",
            msg_type="image",
            images=[image_url],
            external_msg_id=msg_id,
        )
        return msg_id

    async def send_audio(
        self, to: str, audio_bytes: bytes, mime_type: str = "audio/ogg; codecs=opus"
    ) -> str:
        import base64
        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        msg_id = _enqueue(to, "audio", {
            "data": b64,
            "mime_type": mime_type,
        })
        await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text="Audio",
            msg_type="audio",
            external_msg_id=msg_id,
        )
        return msg_id

    async def send_buttons(
        self,
        to: str,
        body: str,
        buttons: list[dict],
        header: str | None = None,
        footer: str | None = None,
        image_url: str | None = None,
    ) -> str:
        msg_id = _enqueue(to, "buttons", {
            "body": body,
            "buttons": buttons,
            "header": header,
            "footer": footer,
            "image_url": image_url,
        })
        titles = ", ".join(button.get("title", "Option") for button in buttons)
        text = body if titles == "" else f"{body}\n\nOptions: {titles}"
        await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=text,
            msg_type="interactive_buttons",
            images=[image_url] if image_url else [],
            external_msg_id=msg_id,
        )
        return msg_id

    async def send_list(
        self,
        to: str,
        body: str,
        button_text: str,
        sections: list[dict],
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        msg_id = _enqueue(to, "list", {
            "body": body,
            "button_text": button_text,
            "sections": sections,
            "header": header,
            "footer": footer,
        })
        rows: list[str] = []
        for section in sections:
            for row in section.get("rows", []):
                rows.append(row.get("title", "Item"))
        text = body if not rows else f"{body}\n\n{button_text}: {', '.join(rows[:10])}"
        await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=text,
            msg_type="interactive_list",
            external_msg_id=msg_id,
        )
        return msg_id

    async def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
    ) -> str:
        msg_id = _enqueue(to, "location", {
            "latitude": latitude,
            "longitude": longitude,
            "name": name,
            "address": address,
        })
        label = name or "Location"
        text = f"{label}: {latitude}, {longitude}"
        if address:
            text = f"{text}\n{address}"
        await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=text,
            msg_type="location",
            external_msg_id=msg_id,
        )
        return msg_id

    async def send_contact(self, to: str, name: str, phone: str) -> str:
        msg_id = _enqueue(to, "contact", {"name": name, "phone": phone})
        await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=f"Contact: {name} ({phone})",
            msg_type="contact",
            external_msg_id=msg_id,
        )
        return msg_id

    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en",
        params: list[str] | None = None,
        image_url: str | None = None,
    ) -> str:
        param_str = ", ".join(params) if params else ""
        msg_id = _enqueue(to, "text", {
            "body": f"[Template: {template_name}] {param_str}",
        })
        await log_message(
            wa_id=to,
            role="bot",
            direction="outbound",
            channel="web_clone",
            text=f"Template[{template_name}/{language}] {param_str}".strip(),
            msg_type="template",
            images=[image_url] if image_url else [],
            external_msg_id=msg_id,
        )
        return msg_id

    async def send_typing(self, to: str) -> None:
        # Enqueue a typing indicator the frontend can render
        _enqueue(to, "typing", {})

    async def mark_read(self, msg_id: str) -> None:
        # No-op for web clone
        pass

    def extract_message(self, payload: dict) -> IncomingMessage | None:
        """Parse a REST API payload into an IncomingMessage.

        Expected payload from frontend:
        {"wa_id": "...", "text": "...", "sender_name": "...", "msg_type": "text"}
        """
        try:
            wa_id = payload.get("wa_id") or payload.get("customer_id")
            text = payload.get("text") or payload.get("message")
            if not wa_id or not text:
                return None

            return IncomingMessage(
                wa_id=str(wa_id),
                text=str(text),
                msg_id=f"web_{uuid4().hex[:12]}",
                msg_type=MessageType(payload.get("msg_type", "text")),
                sender_name=payload.get("sender_name") or payload.get("customer_name"),
            )
        except Exception as e:
            log.error(f"Failed to parse web clone payload: {e}")
            return None
