"""Image storage service — Supabase Storage for persistent image hosting.

Uploads images to a public Supabase Storage bucket. Returns public URLs
that work from any device (phones, browsers, WhatsApp).

Falls back to local disk if Supabase is not configured.
"""

import logging
import os
from pathlib import Path
from uuid import uuid4

import httpx

import config

log = logging.getLogger("vyapari.services.image_store")

# Supabase Storage config
_SUPABASE_URL = os.getenv(
    "SUPABASE_URL",
    "https://mhxpcsylxicnzujgtepa.supabase.co",
)
_SUPABASE_SERVICE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1oeHBjc3lseGljbnp1amd0ZXBhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NjMyMzQ1NywiZXhwIjoyMDkxODk5NDU3fQ.euQeE2FGiIxP3BnICFCOnmQ_3M1ky-LPRnOuxOA3YHk",
)
_BUCKET = "images"
_USE_SUPABASE = bool(_SUPABASE_URL and _SUPABASE_SERVICE_KEY)

# Local fallback
_LOCAL_UPLOAD_DIR = config.BASE_DIR / "uploads"


def _ensure_local_dir():
    _LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def upload_image(
    image_bytes: bytes,
    filename: str | None = None,
    folder: str = "general",
    content_type: str = "image/jpeg",
) -> str:
    """Upload image bytes and return a public URL.

    Uses Supabase Storage if configured, otherwise saves to local disk.

    Args:
        image_bytes: Raw image data
        filename: Optional filename (auto-generated if None)
        folder: Subfolder in the bucket (e.g., "token_proofs", "inventory", "cars")
        content_type: MIME type of the image

    Returns: Public URL to the stored image
    """
    ext = _ext_from_mime(content_type)
    fname = filename or f"{uuid4().hex[:16]}{ext}"
    path = f"{folder}/{fname}"

    if _USE_SUPABASE:
        return await _upload_supabase(image_bytes, path, content_type)
    else:
        return _upload_local(image_bytes, path)


async def _upload_supabase(image_bytes: bytes, path: str, content_type: str) -> str:
    """Upload to Supabase Storage bucket."""
    url = f"{_SUPABASE_URL}/storage/v1/object/{_BUCKET}/{path}"
    headers = {
        "apikey": _SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {_SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type,
    }

    async with httpx.AsyncClient() as client:
        # Try upload (upsert if exists)
        resp = await client.post(url, headers=headers, content=image_bytes, timeout=30)

        if resp.status_code == 400 and "already exists" in resp.text:
            # File exists, update instead
            resp = await client.put(url, headers=headers, content=image_bytes, timeout=30)

        if resp.status_code not in (200, 201):
            log.error(f"Supabase upload failed: {resp.status_code} {resp.text[:200]}")
            # Fallback to local
            return _upload_local(image_bytes, path)

    public_url = f"{_SUPABASE_URL}/storage/v1/object/public/{_BUCKET}/{path}"
    log.info(f"Image uploaded to Supabase: {public_url}")
    return public_url


def _upload_local(image_bytes: bytes, path: str) -> str:
    """Save to local disk as fallback."""
    _ensure_local_dir()
    full_path = _LOCAL_UPLOAD_DIR / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_bytes(image_bytes)
    log.info(f"Image saved locally: {full_path}")
    return f"{config.PUBLIC_BASE_URL}/uploads/{path}"


def _ext_from_mime(content_type: str) -> str:
    """Get file extension from MIME type."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/heic": ".heic",
        "image/heif": ".heif",
        "application/pdf": ".pdf",
    }
    return mapping.get(content_type, ".jpg")
