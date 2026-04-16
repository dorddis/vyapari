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
        return _enqueue(to, "text", {"body": text})

    async def send_image(self, to: str, image_url: str, caption: str = "") -> str:
        return _enqueue(to, "image", {"url": image_url, "caption": caption})

    async def send_buttons(
        self,
        to: str,
        body: str,
        buttons: list[dict],
        header: str | None = None,
        footer: str | None = None,
        image_url: str | None = None,
    ) -> str:
        return _enqueue(to, "buttons", {
            "body": body,
            "buttons": buttons,
            "header": header,
            "footer": footer,
            "image_url": image_url,
        })

    async def send_list(
        self,
        to: str,
        body: str,
        button_text: str,
        sections: list[dict],
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        return _enqueue(to, "list", {
            "body": body,
            "button_text": button_text,
            "sections": sections,
            "header": header,
            "footer": footer,
        })

    async def send_location(
        self,
        to: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
    ) -> str:
        return _enqueue(to, "location", {
            "latitude": latitude,
            "longitude": longitude,
            "name": name,
            "address": address,
        })

    async def send_contact(self, to: str, name: str, phone: str) -> str:
        return _enqueue(to, "contact", {"name": name, "phone": phone})

    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "en",
        params: list[str] | None = None,
        image_url: str | None = None,
    ) -> str:
        # Web clone doesn't have templates — just send as text
        param_str = ", ".join(params) if params else ""
        return _enqueue(to, "text", {
            "body": f"[Template: {template_name}] {param_str}",
        })

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
