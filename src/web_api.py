"""REST API endpoints for the web frontend.

All chat messages go through router.dispatch() — same agents,
same tools, same state whether it's web or WhatsApp.
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

import state
from channels.web_clone.adapter import get_pending_messages, reset_outbox
from models import IncomingMessage, MessageRole, MessageType
from router import dispatch
from services.customer_experience import build_source_aware_greeting

log = logging.getLogger("vyapari.web_api")

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    customer_id: str
    message: str
    customer_name: str | None = None
    source: str | None = None


class ChatStartRequest(BaseModel):
    customer_id: str
    customer_name: str | None = None
    source: str | None = None
    source_car: str | None = None
    source_video: str | None = None


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
    await state.get_or_create_customer(
        req.customer_id,
        name=req.customer_name,
        source=req.source,
    )

    msg = IncomingMessage(
        wa_id=req.customer_id,
        text=req.message,
        msg_id=f"web_{req.customer_id}_{id(req)}",
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


@router.post("/chat/start")
async def customer_chat_start(req: ChatStartRequest):
    """Start a web demo customer chat with a source-aware greeting."""
    customer = await state.get_or_create_customer(
        req.customer_id,
        name=req.customer_name,
        source=req.source,
    )
    conversation = await state.get_or_create_conversation(req.customer_id)
    existing_messages = await state.get_messages(conversation.id)
    if existing_messages:
        return {
            "reply": None,
            "images": [],
            "messages": get_pending_messages(req.customer_id),
            "customer_id": req.customer_id,
        }

    reply, images = build_source_aware_greeting(
        source_car=req.source_car,
        source_video=req.source_video,
    )
    await state.add_message(
        conversation.id,
        MessageRole.AGENT,
        reply,
        images=images,
    )

    return {
        "reply": reply,
        "images": images,
        "messages": [],
        "customer_id": customer.wa_id,
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
    from models import ConversationState

    conv = await state.get_conversation(req.customer_id)
    if conv:
        if conv.id in state._messages:
            state._messages[conv.id].clear()
        conv.state = ConversationState.ACTIVE
        conv.escalation_reason = ""

    reset_outbox()
    return {"status": "ok", "customer_id": req.customer_id}


@router.get("/catalogue")
async def get_catalogue():
    """Get available cars (for frontend browsing)."""
    from catalogue import CATALOGUE

    available = [c for c in CATALOGUE["cars"] if not c.get("sold")]
    return {"cars": available, "total": len(available)}
