"""Image storage service — Supabase Storage for persistent image hosting.

Uploads images to a public Supabase Storage bucket. Returns public URLs
that work from any device (phones, browsers, WhatsApp).

Falls back to local disk if Supabase is not configured.
"""

import logging
import os
import re
from pathlib import Path
from uuid import uuid4

import httpx

import config

log = logging.getLogger("vyapari.services.image_store")

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")

# Win32 rejects these even with an extension (CON.jpg still fails).
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _sanitize_path_segment(segment: str, *, max_len: int = 64) -> str:
    """Return a filesystem-safe version of a user-supplied path segment."""
    if not segment:
        return "upload"
    # Strip leading/trailing dots+spaces before the regex; otherwise a
    # trailing space becomes `_` and survives rstrip.
    segment = segment.strip(". ")
    if not segment:
        return "upload"
    cleaned = _SAFE_NAME_RE.sub("_", segment)
    dot_idx = cleaned.rfind(".")
    stem = cleaned[:dot_idx] if dot_idx > 0 else cleaned
    if stem.upper() in _WIN_RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) <= max_len:
        return cleaned
    # Preserve a short final extension (<=16 chars) through truncation.
    dot = cleaned.rfind(".")
    if 0 < dot < len(cleaned) - 1:
        suffix = cleaned[dot:]
        if len(suffix) <= 16:
            return cleaned[:dot][: max_len - len(suffix)] + suffix
    return cleaned[:max_len]

# Supabase Storage config
_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
_BUCKET = "images"
# In development, always use local storage to avoid polluting shared bucket
_IS_DEV = os.getenv("APP_ENV", "development") == "development"
_USE_SUPABASE = bool(_SUPABASE_URL and _SUPABASE_SERVICE_KEY) and not _IS_DEV

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
    """Upload image bytes and return a public URL. Sanitizes filename+folder."""
    ext = _ext_from_mime(content_type)
    safe_folder = _sanitize_path_segment(folder) or "general"
    if filename:
        safe_fname = _sanitize_path_segment(filename)
    else:
        safe_fname = f"{uuid4().hex[:16]}{ext}"
    path = f"{safe_folder}/{safe_fname}"

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
    base = _LOCAL_UPLOAD_DIR.resolve()
    full_path = (_LOCAL_UPLOAD_DIR / path).resolve()
    try:
        full_path.relative_to(base)
    except ValueError:
        raise ValueError(
            f"Refusing to write {path!r}: resolves outside upload dir"
        )
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
