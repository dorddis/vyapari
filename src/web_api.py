"""REST API endpoints for the web frontend."""

import logging
from dataclasses import asdict
from fastapi import APIRouter
from pydantic import BaseModel

from message_store import (
    MessageRole, ConversationMode,
    get_or_create_conversation, add_message, get_messages,
    list_conversations, set_mode, get_mode,
)
from conversation import get_reply_rich, inject_owner_message
from owner_agent import owner_query
from catalogue import mark_car_sold, CATALOGUE

log = logging.getLogger("vibecon")

router = APIRouter(prefix="/api")


# --- Request/Response models ---

class ChatRequest(BaseModel):
    customer_id: str
    message: str
    customer_name: str | None = None


class OwnerSendRequest(BaseModel):
    customer_id: str
    message: str


class OwnerReleaseRequest(BaseModel):
    customer_id: str


class OracleRequest(BaseModel):
    query: str


# --- Customer endpoints ---

@router.post("/chat")
async def customer_chat(req: ChatRequest):
    """Customer sends a message. Returns bot reply (or null if owner is active)."""
    get_or_create_conversation(req.customer_id, req.customer_name)

    # Store customer message
    add_message(req.customer_id, MessageRole.CUSTOMER, req.message)

    mode = get_mode(req.customer_id)

    # If owner is actively chatting, don't call Gemini
    if mode == ConversationMode.OWNER:
        return {
            "reply": None,
            "images": [],
            "is_escalation": False,
            "escalation_reason": "",
            "mode": mode.value,
        }

    # Get AI reply
    try:
        result = get_reply_rich(req.customer_id, req.message)
    except Exception as e:
        log.error(f"Gemini error: {e}")
        result = {
            "text": "Sorry, I'm having trouble right now. Please try again!",
            "images": [],
            "is_escalation": False,
            "escalation_reason": "",
        }

    # Store bot reply
    add_message(
        req.customer_id,
        MessageRole.BOT,
        result["text"],
        images=result["images"],
        is_escalation=result["is_escalation"],
        escalation_reason=result.get("escalation_reason", ""),
    )

    # Update mode if escalation detected
    if result["is_escalation"] and mode != ConversationMode.OWNER:
        set_mode(req.customer_id, ConversationMode.ESCALATED, result.get("escalation_reason", ""))

    return {
        "reply": result["text"],
        "images": result["images"],
        "is_escalation": result["is_escalation"],
        "escalation_reason": result.get("escalation_reason", ""),
        "mode": get_mode(req.customer_id).value,
    }


@router.get("/messages/{customer_id}")
async def get_conversation_messages(customer_id: str, since_id: str | None = None):
    """Get conversation history. Supports polling with since_id."""
    messages = get_messages(customer_id, since_id)
    mode = get_mode(customer_id)
    return {
        "customer_id": customer_id,
        "mode": mode.value,
        "messages": [asdict(m) for m in messages],
    }


# --- Owner endpoints ---

@router.get("/conversations")
async def get_conversations():
    """List all conversations for owner panel."""
    return {"conversations": list_conversations()}


@router.post("/owner/send")
async def owner_send(req: OwnerSendRequest):
    """Owner sends a message to a customer (hijack)."""
    get_or_create_conversation(req.customer_id)

    # Switch to owner mode
    set_mode(req.customer_id, ConversationMode.OWNER)

    # Store owner message
    msg = add_message(req.customer_id, MessageRole.OWNER, req.message)

    # Inject into Gemini history for context continuity
    inject_owner_message(req.customer_id, req.message)

    return {"status": "ok", "message_id": msg.id, "mode": "owner"}


@router.post("/owner/release")
async def owner_release(req: OwnerReleaseRequest):
    """Owner releases conversation back to bot."""
    set_mode(req.customer_id, ConversationMode.BOT)
    return {"status": "ok", "mode": "bot"}


@router.post("/owner/query")
async def oracle_query(req: OracleRequest):
    """Owner asks the data oracle."""
    try:
        result = owner_query(req.query)
    except Exception as e:
        log.error(f"Oracle error: {e}")
        return {"text": "Sorry, something went wrong.", "action": None}

    # Execute catalogue actions if detected
    if result.get("action"):
        action = result["action"]
        if action["action"] == "mark_sold":
            sold_car = mark_car_sold(action["car_id"])
            if sold_car:
                action["success"] = True
            else:
                action["success"] = False

    return result


@router.get("/catalogue")
async def get_catalogue():
    """Get full catalogue (available cars only)."""
    available = [c for c in CATALOGUE["cars"] if not c.get("sold")]
    return {"cars": available, "total": len(available)}
