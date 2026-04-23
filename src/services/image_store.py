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

# Characters allowed inside a stored filename segment. Anything else
# (including `/`, `\`, `..`, NUL, shell meta, path separators of every
# OS) is replaced with `_`. 64-char cap prevents filesystem limits on
# deeply-nested user-supplied prefixes.
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")

# Windows reserved filename stems. Even with an extension (e.g.
# `CON.jpg`) the Win32 API rejects the name — `write_bytes` raises
# PermissionError. Linux-first hosting makes this reliability-only,
# but dev environments on Windows hit the same code path in tests.
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _sanitize_path_segment(segment: str, *, max_len: int = 64) -> str:
    """Return a filesystem-safe version of a user-supplied path segment.

    Used before composing `{folder}/{filename}` that hits
    `pathlib.Path(local_upload_dir) / segment` — unsanitized input
    containing `../` lets the composed path escape `_LOCAL_UPLOAD_DIR`
    and overwrite arbitrary files on disk (P3.5b #6).

    Collapses consecutive separators and strips leading dots so names
    like `..`, `.hidden`, or `///passwd` can't resolve upwards or hide.

    Preserves the final extension when truncating at `max_len` so an
    iPhone/Android gallery filename like
    `IMG_20241015_really_long_device_export_filename.jpg` (easily
    60+ chars) doesn't silently lose `.jpg` and serve as
    application/octet-stream to the UI.
    """
    if not segment:
        return "upload"
    # Strip leading/trailing dots and spaces BEFORE the regex — otherwise
    # a trailing space becomes `_` and survives rstrip. Leading dots
    # prevent hidden-file / dot-traversal attacks (`.ssh`, `..`); trailing
    # dots and spaces prevent Win32 silent-trim collisions (`report.` vs
    # `report`).
    segment = segment.strip(". ")
    if not segment:
        return "upload"
    cleaned = _SAFE_NAME_RE.sub("_", segment)
    # Windows reserved-name guard. Compare stem (pre-extension) case-
    # insensitively. If it matches, prefix an underscore so the name
    # survives as a real file on Windows.
    dot_idx = cleaned.rfind(".")
    stem = cleaned[:dot_idx] if dot_idx > 0 else cleaned
    if stem.upper() in _WIN_RESERVED:
        cleaned = "_" + cleaned
    if len(cleaned) <= max_len:
        return cleaned
    # Extension-preserving truncation. `.` is in the allow-list, so a
    # dot in `cleaned` is a genuine separator, not a sanitized byte.
    # Only treat the LAST dot as the extension boundary and only if the
    # suffix is short enough to leave room for the stem (reject things
    # like `foo.abcdefghij...50chars` being "preserved" — that's not a
    # real extension, strip it).
    dot = cleaned.rfind(".")
    if 0 < dot < len(cleaned) - 1:
        suffix = cleaned[dot:]
        if len(suffix) <= 16:
            stem = cleaned[:dot]
            return (stem[: max_len - len(suffix)] + suffix)
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
    """Upload image bytes and return a public URL.

    Uses Supabase Storage if configured, otherwise saves to local disk.

    Both `filename` and `folder` are sanitized with `_sanitize_path_segment`
    before being concatenated into the storage path. Callers MAY pass raw
    user input — a `filename='../../src/router.py'` attack is neutralized
    here rather than relying on every caller to remember to sanitize.
    (P3.5b #6 regression guard.)

    Args:
        image_bytes: Raw image data
        filename: Optional filename (auto-generated if None)
        folder: Subfolder in the bucket (e.g., "token_proofs", "inventory", "cars")
        content_type: MIME type of the image

    Returns: Public URL to the stored image
    """
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
    """Save to local disk as fallback.

    Containment check (P3.5b #6): after resolving `full_path`, verify it
    sits inside `_LOCAL_UPLOAD_DIR`. The sanitization in `upload_image`
    should already have stripped traversal sequences, but this is the
    final backstop — any future caller that bypasses `upload_image` and
    calls `_upload_local` directly with an attacker-controlled path
    must not be able to write outside the upload dir.
    """
    _ensure_local_dir()
    base = _LOCAL_UPLOAD_DIR.resolve()
    full_path = (_LOCAL_UPLOAD_DIR / path).resolve()
    # `relative_to` raises ValueError if `full_path` escapes base.
    # Both sides go through `.resolve()` so any `..` or symlink in the
    # composed path is evaluated before the comparison.
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
