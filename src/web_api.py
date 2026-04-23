"""REST API endpoints for the web frontend."""

from __future__ import annotations

import base64
import hmac
import logging
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from catalogue import search_cars
import config
import state
from channels.base import get_channel
from channels.web_clone.adapter import WebCloneAdapter, get_pending_messages, reset_outbox
from models import ConversationState, IncomingMessage, MessageType
from router import dispatch
from services.message_log import (
    delete_messages_for_wa_id,
    fetch_messages_for_wa_id,
    list_conversations_from_logs,
    log_incoming_message,
)
from services.relay import open_relay

log = logging.getLogger("vyapari.web_api")

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=2000)
    customer_name: str | None = Field(default=None, max_length=120)


class OwnerChatRequest(BaseModel):
    staff_id: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=2000)


class OwnerSendRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=2000)


class OwnerReleaseRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)


class OracleRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class OwnerSendRequest(BaseModel):
    customer_id: str
    message: str


class OwnerReleaseRequest(BaseModel):
    customer_id: str


class OracleRequest(BaseModel):
    query: str


class ResetRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)


def _require_web_clone() -> WebCloneAdapter:
    channel = get_channel()
    if not isinstance(channel, WebCloneAdapter):
        raise HTTPException(
            status_code=400,
            detail="Web API requires CHANNEL_MODE=web_clone.",
        )
    return channel


def _resolve_business_id(request: Request) -> str:
    """Resolve the tenant for a REST API request.

    Priority (Phase 3.7):
    1. If `request.state.business_id` was set by `_require_api_auth` from
       an API key lookup, use that — the key binds to a specific tenant.
    2. Explicit `X-Business-Id` header (dev / ops override).
    3. Single-tenant bootstrap default (web demo, tests).
    """
    auth_bid = getattr(request.state, "business_id", None)
    if auth_bid:
        return auth_bid
    header_bid = request.headers.get("X-Business-Id")
    if header_bid:
        return header_bid.strip()
    from services.business_config import default_business_id
    return default_business_id()


def _new_msg_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


async def _require_api_auth(request: Request) -> None:
    """Authenticate a REST request.

    Tries (in order):
    1. Per-business API key (X-API-Key or Bearer token) against the
       `api_keys` table. Success sets `request.state.business_id`.
    2. Legacy shared `config.API_AUTH_TOKEN` — single-tenant demo path.
       No business_id is bound; _resolve_business_id falls back to the
       bootstrap default.

    Auth is skipped entirely when neither enforcement path is enabled
    (APP_ENV != production AND API_AUTH_TOKEN unset).
    """
    requires_auth = config.APP_ENV.lower() == "production" or bool(config.API_AUTH_TOKEN)
    if not requires_auth:
        return

    auth_header = request.headers.get("Authorization", "")
    bearer = auth_header.removeprefix("Bearer ").strip() if auth_header else ""
    provided = request.headers.get("X-API-Key") or bearer
    if not provided:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Phase 3.7: per-business API key lookup first.
    try:
        from services.api_keys import verify_api_key
        biz = await verify_api_key(provided)
    except Exception:
        biz = None

    if biz:
        request.state.business_id = biz
        return

    # Legacy fallback: shared single-tenant token.
    if config.API_AUTH_TOKEN and hmac.compare_digest(provided, config.API_AUTH_TOKEN):
        return

    raise HTTPException(status_code=401, detail="Unauthorized")


def _to_ui_mode(state_value: ConversationState) -> str:
    if state_value == ConversationState.ESCALATED:
        return "escalated"
    if state_value == ConversationState.RELAY_ACTIVE:
        return "owner"
    return "bot"


def _to_catalogue_card(car: dict[str, object]) -> dict[str, object]:
    images = car.get("images")
    image_url = car.get("image_url")
    if not image_url and isinstance(images, list) and images:
        image_url = images[0]

    return {
        "id": car.get("id"),
        "title": (
            f"{car.get('year')} {car.get('make')} {car.get('model')} {car.get('variant')}"
        ).replace("  ", " ").strip(),
        "make": car.get("make"),
        "model": car.get("model"),
        "variant": car.get("variant"),
        "year": car.get("year"),
        "fuel_type": car.get("fuel_type"),
        "transmission": car.get("transmission"),
        "km_driven": car.get("km_driven"),
        "num_owners": car.get("num_owners"),
        "price_lakhs": car.get("price_lakhs"),
        "condition": car.get("condition"),
        "color": car.get("color"),
        "highlights": car.get("highlights") or [],
        "image_url": image_url,
    }


# ---------------------------------------------------------------------------
# Customer endpoints
# ---------------------------------------------------------------------------

@router.post("/chat")
async def customer_chat(req: ChatRequest, request: Request):
    """Customer sends a message through the web clone."""
    await _require_api_auth(request)
    channel = _require_web_clone()
    msg = IncomingMessage(
        wa_id=req.customer_id,
        text=req.message,
        msg_id=_new_msg_id("web-in"),
        msg_type=MessageType.TEXT,
        sender_name=req.customer_name,
        business_id=_resolve_business_id(request),
    )

    await log_incoming_message(msg, "web_clone")
    reply = await dispatch(msg)
    if reply:
        await channel.send_text(req.customer_id, reply)

    pending = get_pending_messages(req.customer_id)
    mode = await state.get_conversation_state(req.customer_id)

    return {
        "reply": reply,
        "messages": pending,
        "customer_id": req.customer_id,
        "mode": _to_ui_mode(mode),
        "is_escalation": mode == ConversationState.ESCALATED,
    }


@router.get("/messages/{wa_id}")
async def get_messages(
    wa_id: str,
    request: Request,
    since_id: str | None = None,
):
    """Return persisted message history for a single customer.

    Tenant-scoped (P3.5a #4): the wa_id is resolved within the caller's
    business only. A valid API key for tenant A looking up tenant B's
    customer_id receives an empty list, not B's transcripts.
    """
    await _require_api_auth(request)
    _require_web_clone()
    business_id = _resolve_business_id(request)
    mode = await state.get_conversation_state(wa_id)
    messages = await fetch_messages_for_wa_id(
        wa_id, since_id=since_id, business_id=business_id,
    )
    return {
        "customer_id": wa_id,
        "mode": _to_ui_mode(mode),
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# Owner/Staff endpoints
# ---------------------------------------------------------------------------

@router.post("/owner/chat")
async def owner_chat(req: OwnerChatRequest, request: Request):
    """Owner or SDR sends a message to the agent or relay path."""
    await _require_api_auth(request)
    _require_web_clone()
    msg = IncomingMessage(
        wa_id=req.staff_id,
        text=req.message,
        msg_id=_new_msg_id("web-owner-chat"),
        msg_type=MessageType.TEXT,
        sender_name=None,
        business_id=_resolve_business_id(request),
    )

    await log_incoming_message(msg, "web_clone")
    reply = await dispatch(msg)
    pending = get_pending_messages(req.staff_id)

    return {
        "reply": reply,
        "messages": pending,
        "staff_id": req.staff_id,
    }


@router.get("/conversations")
async def list_conversations(request: Request):
    """List conversations for the owner panel (tenant-scoped, P3.5a #4)."""
    await _require_api_auth(request)
    _require_web_clone()
    business_id = _resolve_business_id(request)
    conversations = await list_conversations_from_logs(business_id=business_id)
    for conversation in conversations:
        conv_state = await state.get_conversation_state(conversation["customer_id"])
        conversation["mode"] = _to_ui_mode(conv_state)
        conversation["has_escalation"] = conv_state == ConversationState.ESCALATED
    return {"conversations": conversations}


@router.get("/conversation/{wa_id}")
async def get_conversation_detail(wa_id: str, request: Request):
    """Get a customer's full message history (tenant-scoped, P3.5a #4).

    Returns a 'Customer not found' payload if the wa_id does not exist
    within the caller's business — avoiding cross-tenant enumeration
    via the existence of an error message.
    """
    await _require_api_auth(request)
    _require_web_clone()
    business_id = _resolve_business_id(request)
    customer = await state.get_customer(wa_id)
    if not customer or customer.business_id != business_id:
        return {"error": "Customer not found", "messages": []}
    mode = await state.get_conversation_state(wa_id)
    messages = await fetch_messages_for_wa_id(wa_id, business_id=business_id)

    return {
        "customer_id": wa_id,
        "customer_name": customer.name,
        "lead_status": customer.lead_status.value,
        "conversation_state": _to_ui_mode(mode),
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# Staff management
# ---------------------------------------------------------------------------

@router.get("/staff")
async def list_staff(request: Request):
    """List all staff members."""
    await _require_api_auth(request)
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

@router.post("/owner/send")
async def owner_send(req: OwnerSendRequest, request: Request):
    """Send a message from the default owner into a customer relay."""
    await _require_api_auth(request)
    _require_web_clone()
    from services.business_config import default_owner_phone
    owner_wa_id = default_owner_phone()

    await state.get_or_create_customer(req.customer_id)
    await state.get_or_create_conversation(req.customer_id)
    relay = await state.get_active_relay_for_staff(owner_wa_id)
    if relay is None or relay.customer_wa_id != req.customer_id:
        session, error = await open_relay(owner_wa_id, req.customer_id)
        if not session:
            raise HTTPException(status_code=400, detail=error)

    incoming = IncomingMessage(
        wa_id=owner_wa_id,
        text=req.message,
        msg_id=_new_msg_id("web-owner"),
        msg_type=MessageType.TEXT,
        sender_name=config.DEFAULT_OWNER_NAME,
        business_id=_resolve_business_id(request),
    )
    await log_incoming_message(incoming, "web_clone")
    reply = await dispatch(incoming)

    mode = await state.get_conversation_state(req.customer_id)
    return {"status": "ok", "mode": _to_ui_mode(mode), "reply": reply}


@router.post("/owner/release")
async def owner_release(req: OwnerReleaseRequest, request: Request):
    """Release a relay session for the default owner."""
    await _require_api_auth(request)
    _require_web_clone()
    from services.business_config import default_owner_phone
    owner_wa_id = default_owner_phone()
    incoming = IncomingMessage(
        wa_id=owner_wa_id,
        text=f"{config.COMMAND_PREFIX}done",
        msg_id=_new_msg_id("web-owner-cmd"),
        msg_type=MessageType.TEXT,
        sender_name=config.DEFAULT_OWNER_NAME,
        business_id=_resolve_business_id(request),
    )
    await log_incoming_message(incoming, "web_clone")
    await dispatch(incoming)
    mode = await state.get_conversation_state(req.customer_id)
    return {"status": "ok", "mode": _to_ui_mode(mode)}


@router.post("/owner/query")
async def oracle_query(req: OracleRequest, request: Request):
    """Send an owner oracle query via the standard owner dispatch path."""
    await _require_api_auth(request)
    _require_web_clone()
    from services.business_config import default_owner_phone
    owner_wa_id = default_owner_phone()
    incoming = IncomingMessage(
        wa_id=owner_wa_id,
        text=req.query,
        msg_id=_new_msg_id("web-owner-oracle"),
        msg_type=MessageType.TEXT,
        sender_name=config.DEFAULT_OWNER_NAME,
        business_id=_resolve_business_id(request),
    )
    await log_incoming_message(incoming, "web_clone")
    reply = await dispatch(incoming)
    return {"text": reply or "No response.", "action": None}


@router.post("/reset")
async def reset_conversation(req: ResetRequest, request: Request):
    """Reset a customer's conversation within the caller's business.

    Tenant-scoped (P3.5a #4): a valid API key for tenant A cannot wipe
    tenant B's messages or customer state. Scoping the message-log
    delete is the primary defense; the customer-state reset also
    checks tenant ownership before touching the row.
    """
    await _require_api_auth(request)
    _require_web_clone()
    business_id = _resolve_business_id(request)
    # Scoped delete: rows for req.customer_id owned by OTHER tenants
    # are left untouched.
    await delete_messages_for_wa_id(req.customer_id, business_id=business_id)
    # Only reset the customer row if it actually belongs to this tenant.
    customer = await state.get_customer(req.customer_id)
    if customer and customer.business_id == business_id:
        await state.reset_customer_state(req.customer_id)
    reset_outbox()
    return {"status": "ok", "customer_id": req.customer_id}


@router.get("/catalogue")
async def get_catalogue(
    request: Request,
    limit: int = Query(default=8, ge=1, le=20),
    max_price: float | None = Query(default=None, ge=0),
    min_price: float | None = Query(default=None, ge=0),
    fuel_type: str | None = Query(default=None, max_length=32),
    make: str | None = Query(default=None, max_length=64),
    transmission: str | None = Query(default=None, max_length=32),
):
    """Get filtered catalogue cards for frontend browsing."""
    await _require_api_auth(request)
    _require_web_clone()
    results = search_cars(
        max_price=max_price,
        min_price=min_price,
        fuel_type=fuel_type,
        make=make,
        transmission=transmission,
    )
    available = [car for car in results if not car.get("sold")]
    available.sort(key=lambda car: float(car.get("price_lakhs", 0)))
    cards = [_to_catalogue_card(car) for car in available[:limit]]
    return {
        "cars": cards,
        "count": len(cards),
        "total_matches": len(available),
    }


# ---------------------------------------------------------------------------
# Voice upload (for voice note demo)
# ---------------------------------------------------------------------------

@router.post("/voice")
async def voice_chat(
    request: Request,
    wa_id: str = Form(...),
    customer_name: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload a voice note, transcribe it, process through the agent.

    Returns both the text reply and an audio reply (base64-encoded Opus).
    """
    await _require_api_auth(request)
    channel = _require_web_clone()
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
        business_id=_resolve_business_id(request),
    )

    await log_incoming_message(msg, "web_clone")
    reply = await dispatch(msg)
    if reply:
        await channel.send_text(wa_id, reply)
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
    request: Request,
    wa_id: str = Form(...),
    message: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload an image, store it persistently, and process through the agent.

    Image is stored to Supabase Storage (public URL) and passed to the
    agent for vision analysis. The URL is also saved in message history
    so conversation replay can show the image.
    """
    await _require_api_auth(request)
    channel = _require_web_clone()
    from services.image_store import upload_image as store_image

    contents = await file.read()
    mime = file.content_type or "image/jpeg"

    # Determine folder based on context
    staff = await state.get_staff(wa_id)
    if staff:
        folder = (
            "token_proofs"
            if "token" in (message or "").lower() or "payment" in (message or "").lower()
            else "inventory"
        )
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
        business_id=_resolve_business_id(request),
    )

    await log_incoming_message(msg, "web_clone")
    reply = await dispatch(msg)
    if reply:
        await channel.send_text(wa_id, reply)
    pending = get_pending_messages(wa_id)

    return {
        "reply": reply,
        "messages": pending,
        "image_url": image_url,
        "wa_id": wa_id,
    }
