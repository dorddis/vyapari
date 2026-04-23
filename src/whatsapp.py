"""WhatsApp Cloud API client - send and receive messages.

Multi-tenant note (Phase 3.4+): per-request credentials are resolved
through a `ContextVar` rather than always reading the module-level
`WHATSAPP_ACCESS_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` env values.

- `WhatsAppAdapter.__init__` can be given per-tenant credentials. The
  adapter calls `use_tenant(access_token, phone_number_id)` as a
  context manager around each outbound send so this module's helpers
  see the tenant-scoped values.
- When the contextvar is unset (legacy single-tenant mode, test
  harnesses that bypass the adapter, scripts that call the helpers
  directly), the functions fall back to the module-level env values.

The contextvar is task-local — two concurrent asyncio tasks serving
different tenants never see each other's creds.
"""

import asyncio
import contextlib
import logging
import random
import re
from contextvars import ContextVar
from urllib.parse import urlparse
from typing import NamedTuple

import httpx
from config import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_API_URL,
    WHATSAPP_API_VERSION,
    WHATSAPP_PHONE_NUMBER_ID,
)

log = logging.getLogger("vyapari.whatsapp")


class _TenantCreds(NamedTuple):
    """Per-request WhatsApp Cloud API credentials."""
    access_token: str
    phone_number_id: str


# ContextVar carrying per-request (access_token, phone_number_id). None
# means "no tenant resolved — fall back to module-level env values".
_current_tenant: ContextVar[_TenantCreds | None] = ContextVar(
    "vyapari.whatsapp.tenant", default=None,
)


def _access_token() -> str:
    t = _current_tenant.get()
    return t.access_token if t else WHATSAPP_ACCESS_TOKEN


def _phone_number_id() -> str:
    t = _current_tenant.get()
    return t.phone_number_id if t else WHATSAPP_PHONE_NUMBER_ID


def _messages_url() -> str:
    """Return the /{phone_number_id}/messages endpoint for the current tenant."""
    pnid = _phone_number_id()
    return (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
        f"/{pnid}/messages"
    )


@contextlib.contextmanager
def use_tenant(access_token: str, phone_number_id: str):
    """Context manager that binds per-request Cloud API credentials.

    Caller pattern (inside the WhatsApp adapter):
        with use_tenant(tok, pnid):
            await whatsapp.send_text(to, text)

    Nested `use_tenant` calls are safe — ContextVar is task-local and
    restored on exit.
    """
    token = _current_tenant.set(_TenantCreds(access_token, phone_number_id))
    try:
        yield
    finally:
        _current_tenant.reset(token)

# Hosts we'll attach the Graph bearer token to when downloading media.
# Meta's pre-signed media URLs today live on lookaside.fbsbx.com; we
# also accept subdomains of facebook.com / fbcdn.net / whatsapp.net for
# forward-compat. Any host outside this set is refused rather than
# handing our access token to an unknown origin.
_MEDIA_HOST_ALLOWLIST_SUFFIXES = (
    ".facebook.com",
    ".fbcdn.net",
    ".whatsapp.net",
    ".fbsbx.com",
)


def _is_trusted_media_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    # Match as a suffix — `lookaside.fbsbx.com` ends with `.fbsbx.com`, etc.
    return any(host == s.lstrip(".") or host.endswith(s) for s in _MEDIA_HOST_ALLOWLIST_SUFFIXES)


def _media_endpoint() -> str:
    """URL for /{phone_number_id}/media upload.

    Resolved at call-time from the current tenant context (Phase 3.4+).
    Falls back to the module-level env value for legacy / unscoped
    callers. A missing id surfaces as a clean 404 rather than silent
    URL corruption.
    """
    return (
        f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
        f"/{_phone_number_id()}/media"
    )


class GraphAPIError(Exception):
    """Raised when the Graph API response indicates a send failure.

    Triggered by: HTTP status >= 400, OR a 2xx response carrying an
    `error` object (Meta sometimes sneaks errors into 200 responses
    for deprecated edge cases — we treat either as failure).

    Attributes:
        status_code: HTTP status Meta returned (0 if network/parse error).
        code: Meta's numeric error code (e.g. 131047 for 24h-window).
        body: The full response body dict (may be empty on parse failure).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        code: int | None = None,
        body: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.body = body or {}


# Graph statuses worth retrying: 429 (rate limit), 502/503/504 (transient
# upstream). Client errors 4xx (except 429) are the caller's fault and
# never succeed on retry.
_RETRY_STATUSES = {429, 502, 503, 504}
_MAX_ATTEMPTS = 3


async def _post_message(payload: dict, timeout: int = 30) -> dict:
    """POST a pre-built Graph API payload to /messages and return the JSON.

    Shared by every outbound message type. Raises GraphAPIError on
    non-2xx OR on any 2xx response that carries an `error` object.

    Retries on 429/502/503/504 up to 3 attempts with jittered exponential
    backoff (base 1s, max ~8s between attempts). Other 4xx errors raise
    immediately — they're caller bugs and retrying wouldn't help.
    """
    last_resp: httpx.Response | None = None
    last_body: dict = {}

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _messages_url(),
                json=payload,
                headers={
                    "Authorization": f"Bearer {_access_token()}",
                    "Content-Type": "application/json",
                },
                timeout=timeout,
            )

        try:
            body = resp.json() if resp.content else {}
        except Exception:
            body = {"raw_text": resp.text}

        last_resp = resp
        last_body = body if isinstance(body, dict) else {}

        if resp.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS:
            delay = min(2 ** (attempt - 1), 8) + random.random() * 0.5
            log.warning(
                "Graph API %s on attempt %d/%d; backing off %.2fs",
                resp.status_code, attempt, _MAX_ATTEMPTS, delay,
            )
            await asyncio.sleep(delay)
            continue

        break

    resp = last_resp
    body = last_body

    if resp.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        code = (err or {}).get("code") if isinstance(err, dict) else None
        raise GraphAPIError(
            f"Graph API {resp.status_code}: {err or body}",
            status_code=resp.status_code,
            code=code,
            body=body,
        )

    if isinstance(body, dict) and "error" in body:
        err = body["error"]
        code = err.get("code") if isinstance(err, dict) else None
        raise GraphAPIError(
            f"Graph API error in {resp.status_code} response: {err}",
            status_code=resp.status_code,
            code=code,
            body=body,
        )

    return body


def _build_media_obj(*, media_id: str | None, link: str | None) -> dict:
    """Build the inner {id|link: ...} object for image/audio/video/document/sticker."""
    if not media_id and not link:
        raise ValueError("media send requires either media_id or link")
    return {"id": media_id} if media_id else {"link": link}


async def send_text(to: str, text: str) -> dict:
    """Send a text message to a WhatsApp number."""
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
    )


async def send_image(to: str, image_url: str, caption: str = "") -> dict:
    """Send an image message by public URL."""
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"link": image_url, "caption": caption},
        }
    )


async def send_audio(to: str, media_id: str | None = None, link: str | None = None) -> dict:
    """Send an audio/voice message.

    Pass either `media_id` (after uploading bytes via `upload_media`) or
    `link` (publicly reachable URL). WhatsApp voice notes must be OGG/Opus.
    """
    audio_obj = _build_media_obj(media_id=media_id, link=link)
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": audio_obj,
        }
    )


_MIME_FORMAT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9!#$&.+\-^_]*/[A-Za-z0-9!#$&.+\-^_]+(\s*;\s*[A-Za-z0-9!#$&.+\-^_]+=[A-Za-z0-9!#$&.+\-^_]+)*$")


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
    if not _MIME_FORMAT_RE.match(mime_type):
        # Reject anything that looks injected (e.g. "../etc/passwd") before
        # we embed it in multipart form fields and the filename header.
        raise ValueError(f"upload_media: invalid mime_type format: {mime_type!r}")

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
            headers={"Authorization": f"Bearer {_access_token()}"},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        log.info(
            "Uploaded media (%s, %d bytes) -> %s",
            mime_type, len(file_bytes), result.get("id"),
        )
        return result


async def send_video(
    to: str,
    *,
    media_id: str | None = None,
    link: str | None = None,
    caption: str | None = None,
) -> dict:
    """Send a video message by media_id (after upload_media) or public URL."""
    video_obj = _build_media_obj(media_id=media_id, link=link)
    if caption:
        video_obj["caption"] = caption
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "video",
            "video": video_obj,
        }
    )


async def send_document(
    to: str,
    *,
    media_id: str | None = None,
    link: str | None = None,
    filename: str | None = None,
    caption: str | None = None,
) -> dict:
    """Send a document (PDF, docx, etc.). `filename` is what the recipient sees."""
    doc_obj = _build_media_obj(media_id=media_id, link=link)
    if filename:
        doc_obj["filename"] = filename
    if caption:
        doc_obj["caption"] = caption
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "document",
            "document": doc_obj,
        }
    )


async def send_sticker(to: str, media_id: str) -> dict:
    """Send a WebP sticker by media_id (must be uploaded first)."""
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "sticker",
            "sticker": {"id": media_id},
        }
    )


async def send_reaction(to: str, message_id: str, emoji: str) -> dict:
    """React to an inbound message. Pass emoji="" to remove a reaction."""
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "reaction",
            "reaction": {"message_id": message_id, "emoji": emoji},
        }
    )


async def send_location(
    to: str,
    latitude: float,
    longitude: float,
    name: str | None = None,
    address: str | None = None,
) -> dict:
    """Send a location pin."""
    loc: dict = {"latitude": latitude, "longitude": longitude}
    if name:
        loc["name"] = name
    if address:
        loc["address"] = address
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "location",
            "location": loc,
        }
    )


async def send_contacts(to: str, contacts: list[dict]) -> dict:
    """Send one or more contact cards. Each contact follows the
    Meta `contacts` schema ({"name": {...}, "phones": [...], ...}).
    """
    if not contacts:
        raise ValueError("send_contacts requires at least one contact dict")
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "contacts",
            "contacts": contacts,
        }
    )


def _build_interactive_header(
    header_text: str | None = None,
    header_media: dict | None = None,
) -> dict | None:
    """Build the `interactive.header` object from either a text string
    or a pre-shaped media dict (e.g. {"type": "image", "image": {"link": "..."}}).
    Returns None if both args are None (header is optional).
    """
    if header_media:
        return header_media
    if header_text:
        return {"type": "text", "text": header_text}
    return None


async def send_interactive_buttons(
    to: str,
    body: str,
    buttons: list[dict],
    *,
    header_text: str | None = None,
    header_media: dict | None = None,
    footer: str | None = None,
) -> dict:
    """Send interactive reply-buttons (max 3 per Meta spec).

    `buttons` entries must have `id` (<= 256 chars) and `title` (<= 20 chars).
    """
    if not buttons:
        raise ValueError("send_interactive_buttons requires at least one button")
    if len(buttons) > 3:
        raise ValueError(f"WhatsApp allows max 3 reply buttons, got {len(buttons)}")
    interactive: dict = {
        "type": "button",
        "body": {"text": body},
        "action": {
            "buttons": [
                {"type": "reply", "reply": {"id": b["id"], "title": b["title"]}}
                for b in buttons
            ]
        },
    }
    header = _build_interactive_header(header_text, header_media)
    if header:
        interactive["header"] = header
    if footer:
        interactive["footer"] = {"text": footer}
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
    )


async def send_interactive_list(
    to: str,
    body: str,
    button_text: str,
    sections: list[dict],
    *,
    header_text: str | None = None,
    footer: str | None = None,
) -> dict:
    """Send interactive list.

    Meta's limits: max 10 sections, max 10 rows total across all sections,
    row titles <= 24 chars, descriptions <= 72 chars.

    Sections are rebuilt explicitly to strip any extra keys a caller may
    have attached — the Graph API rejects unknown fields.
    """
    if not sections:
        raise ValueError("send_interactive_list requires at least one section")
    if len(sections) > 10:
        raise ValueError(f"WhatsApp allows max 10 list sections, got {len(sections)}")
    total_rows = sum(len(s.get("rows", [])) for s in sections)
    if total_rows == 0:
        raise ValueError("send_interactive_list requires at least one row across sections")
    if total_rows > 10:
        raise ValueError(f"WhatsApp allows max 10 list rows total, got {total_rows}")

    rebuilt_sections: list[dict] = []
    for sec in sections:
        rebuilt_rows: list[dict] = []
        for row in sec.get("rows", []):
            row_out = {"id": row["id"], "title": row["title"]}
            if row.get("description"):
                row_out["description"] = row["description"]
            rebuilt_rows.append(row_out)
        sec_out: dict = {"rows": rebuilt_rows}
        if sec.get("title"):
            sec_out["title"] = sec["title"]
        rebuilt_sections.append(sec_out)

    interactive: dict = {
        "type": "list",
        "body": {"text": body},
        "action": {
            "button": button_text,
            "sections": rebuilt_sections,
        },
    }
    header = _build_interactive_header(header_text=header_text)
    if header:
        interactive["header"] = header
    if footer:
        interactive["footer"] = {"text": footer}
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
    )


async def send_interactive_cta_url(
    to: str,
    body: str,
    display_text: str,
    url: str,
    *,
    header_text: str | None = None,
    footer: str | None = None,
) -> dict:
    """Send a single call-to-action button that opens a URL in the user's browser."""
    interactive: dict = {
        "type": "cta_url",
        "body": {"text": body},
        "action": {
            "name": "cta_url",
            "parameters": {
                "display_text": display_text,
                "url": url,
            },
        },
    }
    header = _build_interactive_header(header_text=header_text)
    if header:
        interactive["header"] = header
    if footer:
        interactive["footer"] = {"text": footer}
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
    )


async def send_template(
    to: str,
    name: str,
    language: str = "en",
    components: list[dict] | None = None,
) -> dict:
    """Send a pre-approved template message (required outside the 24h window).

    `components` is a list of dicts shaped per Meta's template spec, e.g.:
        [
            {"type": "header", "parameters": [{"type": "image", "image": {"id": "..."}}]},
            {"type": "body",   "parameters": [{"type": "text",  "text": "Rahul"}]},
            {"type": "button", "sub_type": "url", "index": "0",
             "parameters": [{"type": "text", "text": "VAR_ID"}]},
        ]
    Phase 2 will wrap this in a higher-level dispatcher that picks templates
    by name + validates params against the approved shape.
    """
    tmpl: dict = {"name": name, "language": {"code": language}}
    if components:
        tmpl["components"] = components
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": tmpl,
        }
    )


async def send_typing_on(replying_to_msg_id: str) -> dict:
    """Turn on the typing indicator for the inbound message `replying_to_msg_id`.

    Cloud API v21+ overloaded the read-receipt endpoint: POSTing with
    `status=read` + `message_id` marks it read, and optionally setting
    `typing_indicator.type=text` additionally shows the typing dots.
    The indicator auto-clears when we send our reply or after ~25 seconds.
    """
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": replying_to_msg_id,
        "typing_indicator": {"type": "text"},
    }
    return await _post_message(payload, timeout=10)


async def mark_read(message_id: str) -> dict:
    """Mark a message as read (blue ticks, no typing indicator)."""
    return await _post_message(
        {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        },
        timeout=10,
    )


async def download_media(media_id: str) -> tuple[bytes, str]:
    """Download media from WhatsApp Cloud API.

    Two-step process:
    1. GET graph.facebook.com/{media_id} -> JSON with a `url` field
    2. GET that url -> actual file bytes

    Returns (file_bytes, mime_type).
    Raises httpx.HTTPStatusError on failure.
    """
    # Meta media ids are ASCII digits. `\d` without re.ASCII also matches
    # Arabic-Indic and other unicode digits — Meta would reject those
    # but we shouldn't interpolate them into a Graph URL either.
    if not re.fullmatch(r"[0-9]+", media_id or ""):
        raise ValueError(f"Invalid media_id format: {media_id!r}")
    graph_base = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"
    headers = {"Authorization": f"Bearer {_access_token()}"}

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

        # We re-send the Graph bearer token on the second-hop GET, so we
        # only follow URLs whose host is in our allow-list. Without this
        # check, a misconfigured or malicious Meta response pointing at
        # an arbitrary host would leak the access token to that host.
        if not _is_trusted_media_host(download_url):
            parsed_host = urlparse(download_url).hostname or "<unparseable>"
            raise ValueError(
                f"Refusing to download media {media_id}: untrusted host "
                f"{parsed_host!r}. Update _MEDIA_HOST_ALLOWLIST_SUFFIXES "
                "if Meta has rolled out a new CDN."
            )

        # Step 2: download the actual file bytes. follow_redirects=False
        # because any redirect would slip past the host check above.
        file_resp = await client.get(
            download_url,
            headers=headers,
            timeout=60,
            follow_redirects=False,
        )
        file_resp.raise_for_status()

        log.info(
            "Downloaded media %s (%s, %d bytes)",
            media_id, mime_type, len(file_resp.content),
        )
        return file_resp.content, mime_type
