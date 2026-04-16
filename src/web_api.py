"""REST API endpoints for web clone frontend.

This API uses router.dispatch with normalized IncomingMessage payloads.
Messages are persisted in DB and fetched via polling.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import config
import state
from channels.base import get_channel
from channels.web_clone.adapter import WebCloneAdapter
from models import ConversationState, IncomingMessage, MessageType
from router import dispatch
from services.message_log import (
    fetch_messages_for_wa_id,
    list_conversations_from_logs,
)
from services.relay import open_relay

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=2000)
    customer_name: str | None = Field(default=None, max_length=120)


class OwnerSendRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=2000)


class OwnerReleaseRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=32)


class OracleRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


def _require_web_clone() -> WebCloneAdapter:
    """Get the active channel adapter and ensure it supports web polling."""
    channel = get_channel()
    if not isinstance(channel, WebCloneAdapter):
        raise HTTPException(
            status_code=400,
            detail=(
                "Web API polling requires CHANNEL_MODE=web_clone "
                "(current mode is not web_clone)."
            ),
        )
    return channel


def _new_msg_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _to_ui_mode(state_value: ConversationState) -> str:
    """Map backend conversation state to legacy web demo labels."""
    if state_value == ConversationState.ESCALATED:
        return "escalated"
    if state_value == ConversationState.RELAY_ACTIVE:
        return "owner"
    return "bot"


@router.post("/chat")
async def customer_chat(req: ChatRequest) -> dict[str, object]:
    """Customer sends a message through web clone."""
    channel = _require_web_clone()

    incoming = IncomingMessage(
        wa_id=req.customer_id,
        text=req.message,
        msg_id=_new_msg_id("web-in"),
        msg_type=MessageType.TEXT,
        sender_name=req.customer_name,
    )

    reply = await dispatch(incoming)
    if reply:
        await channel.send_text(req.customer_id, reply)

    mode = await state.get_conversation_state(req.customer_id)
    return {
        "reply": reply,
        "mode": _to_ui_mode(mode),
        "is_escalation": mode == ConversationState.ESCALATED,
    }


@router.get("/messages/{wa_id}")
async def get_conversation_messages(
    wa_id: str,
    since_id: str | None = None,
) -> dict[str, object]:
    """Poll buffered web messages for one wa_id."""
    _require_web_clone()
    mode = await state.get_conversation_state(wa_id)
    messages = await fetch_messages_for_wa_id(wa_id, since_id=since_id)
    return {
        "customer_id": wa_id,
        "mode": _to_ui_mode(mode),
        "messages": messages,
    }


@router.get("/conversations")
async def get_conversations() -> dict[str, object]:
    """Conversation list for owner panel."""
    _require_web_clone()
    conversations = await list_conversations_from_logs()
    for conversation in conversations:
        conv_state = await state.get_conversation_state(conversation["customer_id"])
        conversation["mode"] = _to_ui_mode(conv_state)
        conversation["has_escalation"] = conv_state == ConversationState.ESCALATED
    return {"conversations": conversations}


@router.post("/owner/send")
async def owner_send(req: OwnerSendRequest) -> dict[str, object]:
    """Owner sends a message to current customer via relay path."""
    _require_web_clone()
    owner_wa_id = config.DEFAULT_OWNER_PHONE

    # Ensure customer/session exists; if no relay open, open it.
    await state.get_or_create_customer(req.customer_id)
    await state.get_or_create_conversation(req.customer_id)
    relay = await state.get_active_relay_for_staff(owner_wa_id)
    if relay is None or relay.customer_wa_id != req.customer_id:
        await open_relay(owner_wa_id, req.customer_id)

    incoming = IncomingMessage(
        wa_id=owner_wa_id,
        text=req.message,
        msg_id=_new_msg_id("web-owner"),
        msg_type=MessageType.TEXT,
        sender_name=config.DEFAULT_OWNER_NAME,
    )
    reply = await dispatch(incoming)

    mode = await state.get_conversation_state(req.customer_id)
    return {"status": "ok", "mode": _to_ui_mode(mode), "reply": reply}


@router.post("/owner/release")
async def owner_release(req: OwnerReleaseRequest) -> dict[str, str]:
    """Owner releases relay using router command path."""
    _require_web_clone()
    owner_wa_id = config.DEFAULT_OWNER_PHONE
    incoming = IncomingMessage(
        wa_id=owner_wa_id,
        text=f"{config.COMMAND_PREFIX}done",
        msg_id=_new_msg_id("web-owner-cmd"),
        msg_type=MessageType.TEXT,
        sender_name=config.DEFAULT_OWNER_NAME,
    )
    await dispatch(incoming)
    mode = await state.get_conversation_state(req.customer_id)
    return {"status": "ok", "mode": _to_ui_mode(mode)}


@router.post("/owner/query")
async def oracle_query(req: OracleRequest) -> dict[str, object]:
    """Owner oracle query via normal owner dispatch path."""
    _require_web_clone()
    owner_wa_id = config.DEFAULT_OWNER_PHONE
    incoming = IncomingMessage(
        wa_id=owner_wa_id,
        text=req.query,
        msg_id=_new_msg_id("web-owner-oracle"),
        msg_type=MessageType.TEXT,
        sender_name=config.DEFAULT_OWNER_NAME,
    )
    reply = await dispatch(incoming)
    return {"text": reply or "No response.", "action": None}
