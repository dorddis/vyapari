"""WhatsApp Cloud API client - send and receive messages."""

import httpx
from config import WHATSAPP_ACCESS_TOKEN, WHATSAPP_API_URL


async def send_text(to: str, text: str) -> dict:
    """Send a text message to a WhatsApp number."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            WHATSAPP_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        return resp.json()


async def send_image(to: str, image_url: str, caption: str = "") -> dict:
    """Send an image message."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {"link": image_url, "caption": caption},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            WHATSAPP_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        return resp.json()


async def mark_read(message_id: str) -> dict:
    """Mark a message as read (blue ticks)."""
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            WHATSAPP_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        return resp.json()


def extract_message(payload: dict) -> tuple[str, str, str] | None:
    """Extract (sender_number, message_text, message_id) from webhook payload.

    Returns None if this isn't a user text message (could be status update, etc).
    """
    try:
        entry = payload["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        # Skip status updates
        if "messages" not in value:
            return None

        msg = value["messages"][0]

        # Only handle text messages for now
        if msg["type"] != "text":
            return None

        sender = msg["from"]  # phone number like "919876543210"
        text = msg["text"]["body"]
        msg_id = msg["id"]

        return sender, text, msg_id
    except (KeyError, IndexError):
        return None
