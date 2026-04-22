"""WhatsApp Cloud API client - send and receive messages."""

import logging

import httpx
from config import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_API_URL,
    WHATSAPP_API_VERSION,
    WHATSAPP_PHONE_NUMBER_ID,
)

log = logging.getLogger("vyapari.whatsapp")


def _media_endpoint() -> str:
    """URL for /{phone_number_id}/media upload.

    Derived at call-time so a missing WHATSAPP_PHONE_NUMBER_ID env var
    surfaces as a clean 404 rather than a silent URL corruption.
    """
    return (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
        f"/{WHATSAPP_PHONE_NUMBER_ID}/media"
    )


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


async def send_audio(to: str, media_id: str | None = None, link: str | None = None) -> dict:
    """Send an audio/voice message.

    Pass either `media_id` (after uploading bytes via `upload_media`) or
    `link` (publicly reachable URL). WhatsApp voice notes must be OGG/Opus.
    """
    if not media_id and not link:
        raise ValueError("send_audio requires either media_id or link")

    audio_obj: dict = {"id": media_id} if media_id else {"link": link}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": audio_obj,
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


async def upload_media(
    file_bytes: bytes,
    mime_type: str,
    filename: str = "upload.bin",
) -> dict:
    """Upload media to WhatsApp and return {"id": <media_id>, ...}.

    Required before sending audio/video/document by media_id. Uses the
    /{phone_number_id}/media endpoint (multipart/form-data).
    """
    if not file_bytes:
        raise ValueError("upload_media called with empty bytes")

    files = {"file": (filename, file_bytes, mime_type)}
    data = {
        "messaging_product": "whatsapp",
        "type": mime_type,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _media_endpoint(),
            files=files,
            data=data,
            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        log.info(
            "Uploaded media (%s, %d bytes) -> %s",
            mime_type, len(file_bytes), result.get("id"),
        )
        return result


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


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Download media from WhatsApp Cloud API.

    Two-step process:
    1. GET graph.facebook.com/{media_id} -> JSON with a `url` field
    2. GET that url -> actual file bytes

    Returns (file_bytes, mime_type).
    Raises httpx.HTTPStatusError on failure.
    """
    graph_base = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}

    async with httpx.AsyncClient() as client:
        # Step 1: get the download URL
        meta_resp = await client.get(
            f"{graph_base}/{media_id}",
            headers=headers,
            timeout=15,
        )
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        download_url = meta.get("url")
        if not download_url:
            raise ValueError(f"WhatsApp media metadata missing 'url': {meta}")
        mime_type = meta.get("mime_type", "application/octet-stream")

        # Step 2: download the actual file bytes
        file_resp = await client.get(
            download_url,
            headers=headers,
            timeout=60,
        )
        file_resp.raise_for_status()

        log.info(
            "Downloaded media %s (%s, %d bytes)",
            media_id, mime_type, len(file_resp.content),
        )
        return file_resp.content, mime_type
