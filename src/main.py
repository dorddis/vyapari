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

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting Vyapari Agent...")
    await init_db()
    await state.init_state()
    log.info(f"Owner seeded: {config.DEFAULT_OWNER_NAME} ({config.DEFAULT_OWNER_PHONE})")
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


def _is_valid_whatsapp_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 against META_APP_SECRET."""
    if not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    provided = signature_header.split("=", 1)[1].strip()
    digest = hmac.new(
        key=config.META_APP_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided, digest)


@app.post("/webhook")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receive incoming WhatsApp messages.

    Returns 200 immediately (WhatsApp requirement), processes async.
    """
    raw_body = await request.body()
    if config.WHATSAPP_ENABLED:
        if not config.META_APP_SECRET:
            log.error("META_APP_SECRET is required when WHATSAPP_ENABLED=true")
            return Response(content="Webhook signature not configured", status_code=503)
        signature = request.headers.get("X-Hub-Signature-256")
        if not _is_valid_whatsapp_signature(raw_body, signature):
            log.warning("Webhook signature verification failed")
            return Response(content="Forbidden", status_code=403)

    payload = await request.json()

    channel = get_channel()
    msg = channel.extract_message(payload)

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
        await channel.send_typing(msg.wa_id)
        await channel.mark_read(msg.msg_id)

        # Voice note: transcribe audio to text before dispatching
        if msg.msg_type.value in ("voice", "audio") and msg.media_url:
            try:
                from services.voice import transcribe_voice_note
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
