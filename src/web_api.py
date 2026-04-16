"""REST API endpoints for the web frontend.

All chat messages go through router.dispatch() — same agents,
same tools, same state whether it's web or WhatsApp.
"""

import base64
import logging
import os
import tempfile

from uuid import uuid4

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

import config
import state
from channels.web_clone.adapter import get_pending_messages, reset_outbox
from models import IncomingMessage, MessageType
from router import dispatch

log = logging.getLogger("vyapari.web_api")

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    customer_id: str
    message: str
    customer_name: str | None = None


class OwnerChatRequest(BaseModel):
    staff_id: str
    message: str


class ResetRequest(BaseModel):
    customer_id: str


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------

@router.post("/chat")
async def customer_chat(req: ChatRequest):
    """Customer sends a message. Returns agent reply + any queued messages."""
    msg = IncomingMessage(
        wa_id=req.customer_id,
        text=req.message,
        msg_id=f"web_{uuid4().hex[:16]}",
        msg_type=MessageType.TEXT,
        sender_name=req.customer_name,
    )

    reply = await dispatch(msg)

    # Collect any messages the agent queued (images, buttons, lists, etc.)
    pending = get_pending_messages(req.customer_id)

    return {
        "reply": reply,
        "messages": pending,
        "customer_id": req.customer_id,
    }


@router.get("/messages/{wa_id}")
async def get_messages(wa_id: str, since_id: str | None = None):
    """Poll for new messages (frontend calls this periodically).

    Returns pending outbox messages + conversation state.
    """
    pending = get_pending_messages(wa_id, since_id=since_id)
    conv = await state.get_conversation(wa_id)
    conv_state = conv.state.value if conv else "active"

    return {
        "wa_id": wa_id,
        "state": conv_state,
        "messages": pending,
    }


# ---------------------------------------------------------------------------
# Owner/Staff endpoints
# ---------------------------------------------------------------------------

@router.post("/owner/chat")
async def owner_chat(req: OwnerChatRequest):
    """Owner/SDR sends a message to the agent (or relay)."""
    msg = IncomingMessage(
        wa_id=req.staff_id,
        text=req.message,
        msg_id=f"web_{req.staff_id}_{id(req)}",
        msg_type=MessageType.TEXT,
    )

    reply = await dispatch(msg)
    pending = get_pending_messages(req.staff_id)

    return {
        "reply": reply,
        "messages": pending,
        "staff_id": req.staff_id,
    }


@router.get("/conversations")
async def list_conversations():
    """List all customer conversations for the owner panel."""
    customers = await state.list_customers(limit=50)
    convos = []
    for c in customers:
        conv = await state.get_conversation(c.wa_id)
        msgs = await state.get_messages(conv.id) if conv else []
        last_msg = msgs[-1] if msgs else None

        convos.append({
            "customer_id": c.wa_id,
            "customer_name": c.name,
            "lead_status": c.lead_status.value,
            "conversation_state": conv.state.value if conv else "active",
            "last_message": last_msg.content[:80] if last_msg else "",
            "last_message_role": last_msg.role.value if last_msg else "",
            "message_count": len(msgs),
            "last_active": c.last_message_at.isoformat() if c.last_message_at else "",
        })

    convos.sort(key=lambda x: x["last_active"], reverse=True)
    return {"conversations": convos}


@router.get("/conversation/{wa_id}")
async def get_conversation_detail(wa_id: str):
    """Get full conversation history for a specific customer."""
    customer = await state.get_customer(wa_id)
    conv = await state.get_conversation(wa_id)

    if not customer or not conv:
        return {"error": "Customer not found", "messages": []}

    msgs = await state.get_messages(conv.id)

    return {
        "customer_id": wa_id,
        "customer_name": customer.name,
        "lead_status": customer.lead_status.value,
        "conversation_state": conv.state.value,
        "messages": [
            {
                "id": m.id,
                "role": m.role.value,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
                "images": m.images,
                "is_escalation": m.is_escalation,
            }
            for m in msgs
        ],
    }


# ---------------------------------------------------------------------------
# Staff management
# ---------------------------------------------------------------------------

@router.get("/staff")
async def list_staff():
    """List all staff members."""
    staff_list = await state.list_staff()
    return {
        "staff": [
            {
                "wa_id": s.wa_id,
                "name": s.name,
                "role": s.role.value,
                "status": s.status.value,
            }
            for s in staff_list
        ]
    }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

@router.post("/reset")
async def reset_conversation(req: ResetRequest):
    """Reset a customer's conversation (for demo purposes)."""
    await state.reset_customer_state(req.customer_id)
    reset_outbox()
    return {"status": "ok", "customer_id": req.customer_id}


@router.get("/catalogue")
async def get_catalogue():
    """Get available cars (for frontend browsing)."""
    from catalogue import CATALOGUE

    available = [c for c in CATALOGUE["cars"] if not c.get("sold")]
    return {"cars": available, "total": len(available)}


# ---------------------------------------------------------------------------
# Voice upload (for voice note demo)
# ---------------------------------------------------------------------------

@router.post("/voice")
async def voice_chat(
    wa_id: str = Form(...),
    customer_name: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload a voice note, transcribe it, process through the agent.

    Returns both the text reply and an audio reply (base64-encoded Opus).
    """
    from services.voice import generate_voice_reply, transcribe_voice_note

    contents = await file.read()
    mime = file.content_type or "audio/ogg"

    # Transcribe voice to text
    transcribed_text = await transcribe_voice_note(contents, mime)

    # Create an IncomingMessage with the transcribed text
    msg = IncomingMessage(
        wa_id=wa_id,
        text=transcribed_text,
        msg_id=f"web_{uuid4().hex[:16]}",
        msg_type=MessageType.VOICE,
        sender_name=customer_name or None,
    )

    reply = await dispatch(msg)
    pending = get_pending_messages(wa_id)

    # Generate voice reply
    voice_reply_b64 = None
    if reply and config.VOICE_REPLY_ENABLED:
        try:
            voice_bytes = await generate_voice_reply(reply)
            voice_reply_b64 = base64.b64encode(voice_bytes).decode("utf-8")
        except Exception as e:
            log.warning(f"Voice reply generation failed: {e}")

    return {
        "reply": reply,
        "transcribed_text": transcribed_text,
        "voice_reply": voice_reply_b64,
        "voice_mime": "audio/ogg; codecs=opus",
        "messages": pending,
        "wa_id": wa_id,
    }


# ---------------------------------------------------------------------------
# Image upload (for vision tools)
# ---------------------------------------------------------------------------

@router.post("/upload-image")
async def upload_image_endpoint(
    wa_id: str = Form(...),
    message: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload an image, store it persistently, and process through the agent.

    Image is stored to Supabase Storage (public URL) and passed to the
    agent for vision analysis. The URL is also saved in message history
    so conversation replay can show the image.
    """
    from services.image_store import upload_image as store_image

    contents = await file.read()
    mime = file.content_type or "image/jpeg"

    # Determine folder based on context
    staff = await state.get_staff(wa_id)
    if staff:
        folder = "token_proofs" if "token" in (message or "").lower() or "payment" in (message or "").lower() else "inventory"
    else:
        folder = "customer_uploads"

    # Store persistently and get public URL
    image_url = await store_image(
        image_bytes=contents,
        filename=f"{uuid4().hex[:12]}_{file.filename or 'upload.jpg'}",
        folder=folder,
        content_type=mime,
    )

    # Create an IncomingMessage with the stored image URL
    msg = IncomingMessage(
        wa_id=wa_id,
        text=message or f"[Image: {file.filename or 'uploaded'}]",
        msg_id=f"web_{uuid4().hex[:16]}",
        msg_type=MessageType.IMAGE,
        media_url=image_url,
        sender_name=None,
    )

    reply = await dispatch(msg)
    pending = get_pending_messages(wa_id)

    return {
        "reply": reply,
        "messages": pending,
        "image_url": image_url,
        "wa_id": wa_id,
    }
