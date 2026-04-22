"""FastAPI server — webhook + web frontend + REST API.

Entry point for the Vyapari Agent. Integrates:
- WhatsApp Cloud API webhook (POST /webhook)
- Web demo REST API (mounted from web_api.py)
- Static frontend serving
- Background task for relay session expiry
- Startup/shutdown lifecycle (DB init, state seeding)
"""

import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
import state
from channels.base import get_channel
from database import close_db, init_db
from models import IncomingMessage
from router import dispatch
from web_api import router as api_router

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
log = logging.getLogger("vyapari")


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def relay_expiry_loop():
    """Periodically check for expired relay sessions."""
    while True:
        try:
            expired = await state.check_expired_relay_sessions()
            for session in expired:
                customer = await state.get_customer(session.customer_wa_id)
                name = customer.name if customer else "Customer"
                log.info(f"Relay session expired: {name} ({session.customer_wa_id})")

                channel = get_channel()
                await channel.send_text(
                    session.staff_wa_id,
                    f"Session with {name} auto-closed (idle timeout). Agent resumed.",
                )
                await channel.send_text(
                    session.customer_wa_id,
                    "Thanks for your patience! I'm here if you need anything else.",
                )
        except Exception as e:
            log.error(f"Relay expiry check error: {e}")
        await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Lifespan (startup + shutdown)
# ---------------------------------------------------------------------------

_WHATSAPP_REQUIRED_ENV = (
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "META_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
)


def _validate_whatsapp_config() -> None:
    """Fail fast if CHANNEL_MODE=whatsapp but core creds are unset.

    Without these we'd either build a malformed Graph URL (when
    WHATSAPP_PHONE_NUMBER_ID is empty, see config.py:76-79), silently
    fail signature verification on every inbound webhook (META_APP_SECRET),
    or 503 every subscribe handshake Meta sends (WHATSAPP_VERIFY_TOKEN).

    Whitespace-only values count as unset — they are a common .env footgun
    (trailing space after `=`) that used to slip past the old `not x` check.
    """
    if config.CHANNEL_MODE != "whatsapp":
        return
    missing = [
        name
        for name in _WHATSAPP_REQUIRED_ENV
        if not (getattr(config, name, "") or "").strip()
    ]
    if missing:
        raise RuntimeError(
            "CHANNEL_MODE=whatsapp requires these env vars: "
            f"{', '.join(missing)}. Set them in .env or switch to "
            "CHANNEL_MODE=web_clone for the demo path."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Vyapari Agent...")
    _validate_whatsapp_config()
    await init_db()
    await state.init_state()
    from services.business_config import default_owner_phone
    log.info(f"Owner seeded: {config.DEFAULT_OWNER_NAME} ({default_owner_phone()})")
    log.info(f"Channel mode: {config.CHANNEL_MODE}")
    log.info(f"LLM: OpenAI {config.OPENAI_MAIN_MODEL}")

    expiry_task = asyncio.create_task(relay_expiry_loop())
    yield
    expiry_task.cancel()
    await close_db()
    log.info("Vyapari Agent stopped.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Vyapari Agent",
    description="AI sales agent for high-ticket businesses",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


# ---------------------------------------------------------------------------
# Web frontend
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_frontend():
    return FileResponse(config.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

# Serve locally uploaded images (fallback when Supabase unavailable)
_uploads_dir = config.BASE_DIR / "uploads"
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")


# ---------------------------------------------------------------------------
# WhatsApp webhook
# ---------------------------------------------------------------------------

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification (GET request during setup)."""
    if not config.WHATSAPP_VERIFY_TOKEN:
        log.error("Webhook verify token not configured (WHATSAPP_VERIFY_TOKEN).")
        return Response(content="Webhook verify token is not configured", status_code=503)

    if hub_mode == "subscribe" and hub_verify_token == config.WHATSAPP_VERIFY_TOKEN:
        log.info("Webhook verified")
        return Response(content=hub_challenge, media_type="text/plain")
    log.warning("Webhook verification failed")
    return Response(content="Forbidden", status_code=403)


def _safe_log_field(value: str | None) -> str:
    """Strip CR/LF from strings we interpolate into log lines.

    Prevents a log-injection edge case if a bad actor (or a corrupt Meta
    response) smuggles `\\r\\n` into a value we format with `%s`.
    """
    if not value:
        return ""
    return str(value).replace("\r", "").replace("\n", "")


async def _record_status_event(
    external_msg_id: str,
    status: str,
    timestamp: str | None,
    error: dict | None,
) -> None:
    """Record a delivery-status event on the outbound row's meta JSON.

    Runs as a background task from the webhook handler so Meta still
    gets its ack quickly. Failures are logged but not raised — losing
    one status update is better than 5xx'ing the webhook.
    """
    try:
        from services.message_log import update_status
        await update_status(
            external_msg_id=external_msg_id,
            status=status,
            timestamp=timestamp,
            error=error,
        )
    except Exception:
        log.exception(
            "Failed to record status %s for %s",
            _safe_log_field(status),
            _safe_log_field(external_msg_id),
        )


def _is_valid_whatsapp_signature(
    raw_body: bytes,
    signature_header: str | None,
    *,
    app_secret: str | None = None,
) -> bool:
    """Verify X-Hub-Signature-256.

    `app_secret` defaults to the global `config.META_APP_SECRET` so the
    legacy single-tenant call sites stay working. Phase 3 multi-tenant
    callers pass the per-tenant secret resolved from `whatsapp_channels`.
    """
    if not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    secret = app_secret if app_secret is not None else config.META_APP_SECRET
    if not secret:
        return False
    provided = signature_header.split("=", 1)[1].strip()
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided, digest)


def _extract_phone_number_id(raw_body: bytes) -> str | None:
    """Peek at a webhook body to find the phone_number_id without full parse.

    Returns None if the body isn't JSON or doesn't carry the field.
    Used for tenant resolution BEFORE signature verification — we don't
    need a signed body to decide which tenant's app_secret to verify
    against. (The signature check still happens; we just need to know
    which key to use.)
    """
    import json as _json
    try:
        payload = _json.loads(raw_body)
    except Exception:
        return None
    try:
        return payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
    except (KeyError, IndexError, TypeError):
        return None


@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming WhatsApp messages.

    Always returns 200 on well-formed POSTs (WhatsApp requirement — if we
    5xx, Meta retries and eventually disables the subscription). Signature
    verification failures return 403 before we touch the payload.
    """
    raw_body = await request.body()

    # Tenant resolution: if the payload carries a phone_number_id we serve,
    # look up the per-tenant app_secret from whatsapp_channels and verify
    # the signature against THAT. Falls back to the global META_APP_SECRET
    # for the single-tenant demo deployments that haven't created a
    # whatsapp_channels row yet (Phase 0-2 compatibility).
    phone_number_id = _extract_phone_number_id(raw_body)
    tenant_app_secret: str | None = None
    tenant_business_id: str | None = None
    if phone_number_id:
        try:
            from services.business_config import (
                resolve_business_id_from_phone_number_id,
                load_business_context,
                NoActiveChannelError,
                BusinessNotFoundError,
            )
            tenant_business_id = await resolve_business_id_from_phone_number_id(
                phone_number_id
            )
            if tenant_business_id:
                try:
                    ctx = await load_business_context(tenant_business_id)
                    tenant_app_secret = ctx.app_secret
                except (NoActiveChannelError, BusinessNotFoundError):
                    # Resolver found the phone_number_id but the channel
                    # row is stale / orphaned. Fall through to global key.
                    tenant_app_secret = None
        except Exception:
            log.exception("Tenant resolution failed; falling back to global secret")

    # Signature verification fires for any whatsapp-mode deployment, not just
    # when WHATSAPP_ENABLED=true — the two flags used to be independent and
    # a reviewer flagged that CHANNEL_MODE=whatsapp + WHATSAPP_ENABLED=false
    # silently skipped signature checks, letting the internet spoof inbound
    # messages from arbitrary phone numbers.
    verify_signature = config.WHATSAPP_ENABLED or config.CHANNEL_MODE == "whatsapp"
    if verify_signature:
        effective_secret = tenant_app_secret or config.META_APP_SECRET
        if not effective_secret:
            log.error(
                "No signing secret for webhook (phone_number_id=%s, "
                "tenant=%s): set META_APP_SECRET or provision a "
                "whatsapp_channels row.",
                _safe_log_field(phone_number_id),
                _safe_log_field(tenant_business_id),
            )
            return Response(content="Webhook signature not configured", status_code=503)
        signature = request.headers.get("X-Hub-Signature-256")
        if not _is_valid_whatsapp_signature(raw_body, signature, app_secret=effective_secret):
            log.warning(
                "Webhook signature verification failed "
                "(phone_number_id=%s, tenant=%s)",
                _safe_log_field(phone_number_id),
                _safe_log_field(tenant_business_id),
            )
            return Response(content="Forbidden", status_code=403)

    # Parse + extract is the only place user-controlled JSON meets our
    # typed models. Any exception here (bad JSON, unexpected Meta shape,
    # parser regression) must be logged and acked — never propagated to
    # 500, because that triggers Meta's retry + eventual disable cascade.
    try:
        payload = await request.json()
        channel = get_channel()
        msg = channel.extract_message(payload)
    except Exception:
        log.exception("Webhook payload parse failed; ack'ing anyway")
        return {"status": "ok"}

    # Tag the message with the resolved tenant so downstream handlers
    # (router -> agent -> tools) can scope state lookups correctly. The
    # tenant was resolved above via phone_number_id; fall back to the
    # single-tenant bootstrap default if this is a legacy deployment.
    if msg is not None and not msg.business_id:
        from services.business_config import default_business_id
        msg.business_id = tenant_business_id or default_business_id()

    # Status callbacks (delivered / read / failed) arrive on the same
    # endpoint as inbound user messages. Fan them out to message_log in
    # the background so the ack doesn't wait on DB.
    try:
        status_events = channel.extract_status_updates(payload)
    except Exception:
        log.exception("Status-update parsing failed; continuing")
        status_events = []
    for ev in status_events:
        if ev.get("external_msg_id"):
            background_tasks.add_task(
                _record_status_event,
                ev["external_msg_id"],
                ev.get("status") or "unknown",
                ev.get("timestamp"),
                ev.get("error"),
            )

    if msg is None:
        return {"status": "ok"}

    log.info(f"Incoming from {msg.wa_id}: {msg.text or msg.msg_type}")

    # Process in background so we return 200 fast
    background_tasks.add_task(_process_and_reply, msg)
    return {"status": "ok"}


async def _process_and_reply(msg: IncomingMessage):
    """Process a message through the router and send the reply."""
    try:
        channel = get_channel()
        await channel.send_typing(msg.wa_id, msg.msg_id)
        await channel.mark_read(msg.msg_id)

        # Voice note: download from WhatsApp if needed, then transcribe
        if msg.msg_type.value in ("voice", "audio") and (msg.media_url or msg.media_id):
            try:
                from services.voice import transcribe_voice_note

                if msg.media_id and not msg.media_url:
                    # WhatsApp: download via Graph API
                    from whatsapp import download_media
                    log.info(f"Downloading voice note {msg.media_id} for {msg.wa_id}...")
                    audio_bytes, mime_type = await download_media(msg.media_id)
                else:
                    # media_url already set (e.g. web upload)
                    import httpx
                    log.info(f"Downloading voice note from {msg.media_url[:60]}...")
                    async with httpx.AsyncClient() as http:
                        headers = {}
                        if config.WHATSAPP_ACCESS_TOKEN:
                            headers["Authorization"] = f"Bearer {config.WHATSAPP_ACCESS_TOKEN}"
                        resp = await http.get(msg.media_url, headers=headers, timeout=30)
                        resp.raise_for_status()
                        audio_bytes = resp.content
                        mime_type = resp.headers.get("content-type", "audio/ogg")

                msg.text = await transcribe_voice_note(audio_bytes, mime_type)
                log.info(f"Voice transcribed for {msg.wa_id}: {msg.text[:80]}...")
            except Exception as e:
                log.error(f"Voice transcription failed for {msg.wa_id}: {e}", exc_info=True)
                await channel.send_text(
                    msg.wa_id,
                    "Sorry, I couldn't understand that voice note. Could you type your message instead?",
                )
                return

        # Image / Document: download from WhatsApp, store, set media_url
        if msg.msg_type.value in ("image", "document") and msg.media_id and not msg.media_url:
            try:
                from whatsapp import download_media
                from services.image_store import upload_image as store_image
                from services.image_store import _ext_from_mime

                log.info(f"Downloading media {msg.media_id} for {msg.wa_id}...")
                file_bytes, mime_type = await download_media(msg.media_id)

                if not file_bytes:
                    raise ValueError(f"Downloaded 0 bytes for media {msg.media_id}")

                # Pick storage folder based on sender role
                staff = await state.get_staff(msg.wa_id)
                folder = "inventory" if staff else "customer_uploads"

                from uuid import uuid4
                ext = _ext_from_mime(mime_type)
                fname = f"{uuid4().hex[:12]}_{msg.msg_id[-8:]}{ext}"

                media_url = await store_image(
                    image_bytes=file_bytes,
                    filename=fname,
                    folder=folder,
                    content_type=mime_type,
                )
                msg.media_url = media_url
                log.info(f"Media stored for {msg.wa_id}: {media_url}")
            except Exception as e:
                log.error(f"Media download/store failed for {msg.wa_id}: {e}", exc_info=True)
                await channel.send_text(
                    msg.wa_id,
                    "Sorry, I couldn't process that file. Could you try sending it again?",
                )
                return

        # Video: not supported yet
        if msg.msg_type.value == "video":
            await channel.send_text(
                msg.wa_id,
                "Sorry, I can't process videos yet. Please send a photo or PDF instead!",
            )
            return

        reply = await dispatch(msg)

        if reply:
            await channel.send_text(msg.wa_id, reply)

            # Send voice reply if the incoming message was a voice note
            if msg.msg_type.value in ("voice", "audio") and config.VOICE_REPLY_ENABLED:
                try:
                    from services.voice import generate_voice_reply
                    voice_bytes = await generate_voice_reply(reply)
                    await channel.send_audio(msg.wa_id, voice_bytes)
                except Exception as e:
                    log.warning(f"Voice reply generation failed (text already sent): {e}")

    except Exception as e:
        log.error(f"Error processing {msg.wa_id}: {e}", exc_info=True)
        try:
            channel = get_channel()
            await channel.send_text(
                msg.wa_id,
                "Sorry, I'm having trouble right now. Please try again in a moment!",
            )
        except Exception:
            log.error("Failed to send error message", exc_info=True)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
