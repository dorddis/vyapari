"""FastAPI server - WhatsApp webhook + Web frontend + REST API."""

import logging
from fastapi import FastAPI, Request, Query, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from config import WHATSAPP_VERIFY_TOKEN, HOST, PORT, STATIC_DIR
from whatsapp import extract_message, send_text, mark_read
from conversation import get_reply
from web_api import router as api_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vibecon")

app = FastAPI(title="VibeCon AI Sales Agent")

# CORS for dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router)


# --- Web Frontend ---

@app.get("/")
async def serve_frontend():
    return FileResponse(STATIC_DIR / "index.html")


# Mount static AFTER the root route so / serves index.html
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- WhatsApp Webhook ---

@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification (GET request on setup)."""
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        log.info("Webhook verified successfully")
        return Response(content=hub_challenge, media_type="text/plain")
    log.warning("Webhook verification failed: token mismatch")
    return Response(content="Forbidden", status_code=403)


@app.post("/webhook")
async def handle_webhook(request: Request):
    """Receive incoming WhatsApp messages."""
    payload = await request.json()
    log.info(f"Webhook received: {payload}")

    parsed = extract_message(payload)
    if parsed is None:
        return {"status": "ok"}

    sender, text, msg_id = parsed
    log.info(f"Message from {sender}: {text}")

    await mark_read(msg_id)

    try:
        reply = get_reply(customer_id=sender, message=text)
        log.info(f"Reply to {sender}: {reply}")
    except Exception as e:
        log.error(f"Gemini error: {e}")
        reply = "Sorry, I'm having trouble right now. Please try again in a moment!"

    await send_text(to=sender, text=reply)

    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=int(PORT), reload=True)
