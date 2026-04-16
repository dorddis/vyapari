"""Minimal REST API endpoints for the local chat-only demo."""

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel, Field

from message_store import (
    MessageRole,
    add_message,
    get_messages,
    get_or_create_conversation,
    reset_conversation,
)

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    """Incoming customer message."""

    customer_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1000)
    customer_name: str | None = Field(default=None, max_length=80)


class ResetRequest(BaseModel):
    """Conversation reset payload."""

    customer_id: str = Field(min_length=1, max_length=128)


def _build_demo_reply(message: str) -> str:
    """Return a deterministic placeholder reply until the real agent is wired in."""
    text = message.lower()

    if any(word in text for word in ["price", "budget", "cost", "rate", "kitna"]):
        return (
            "Got it. Pricing logic will come from the agent soon. "
            "For now, this demo only validates the WhatsApp-style chat flow."
        )

    if any(word in text for word in ["test drive", "visit", "showroom", "book"]):
        return (
            "Great intent signal captured. Once the agent is connected, this will trigger "
            "test-drive and visit handling."
        )

    if any(word in text for word in ["compare", "vs", "difference"]):
        return (
            "Comparison request noted. Agent tools for catalogue comparison will be added next."
        )

    return (
        "Message received. This is the chat interface shell; we can now plug the real agent "
        "into this endpoint."
    )


@router.post("/chat")
async def customer_chat(req: ChatRequest) -> dict[str, str]:
    """Store customer message and return a demo reply."""
    get_or_create_conversation(req.customer_id, req.customer_name or "Demo Customer")
    add_message(req.customer_id, MessageRole.CUSTOMER, req.message)

    reply_text = _build_demo_reply(req.message)
    reply_message = add_message(req.customer_id, MessageRole.BOT, reply_text)

    return {
        "reply": reply_text,
        "message_id": reply_message.id,
        "timestamp": reply_message.timestamp,
    }


@router.get("/messages/{customer_id}")
async def conversation_messages(customer_id: str) -> dict[str, object]:
    """Return full conversation history for a customer."""
    messages = get_messages(customer_id)
    return {
        "customer_id": customer_id,
        "messages": [asdict(message) for message in messages],
    }


@router.post("/reset")
async def reset_chat(req: ResetRequest) -> dict[str, object]:
    """Reset one customer conversation."""
    deleted = reset_conversation(req.customer_id)
    return {"reset": deleted}
