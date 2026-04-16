"""REST API for the standalone demo, backed by the real src backend."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import state
from channels.base import get_channel
from channels.web_clone.adapter import WebCloneAdapter
from catalogue import search_cars
from models import ConversationState, IncomingMessage, MessageType
from router import dispatch
from services.message_log import (
    delete_messages_for_wa_id,
    fetch_messages_for_wa_id,
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


def _new_msg_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _to_ui_mode(state_value: ConversationState) -> str:
    if state_value == ConversationState.ESCALATED:
        return "escalated"
    if state_value == ConversationState.RELAY_ACTIVE:
        return "owner"
    return "bot"


def _require_web_clone() -> WebCloneAdapter:
    channel = get_channel()
    if not isinstance(channel, WebCloneAdapter):
        raise RuntimeError("whatsapp-demo requires CHANNEL_MODE=web_clone")
    return channel


def _to_catalogue_card(car: dict[str, object]) -> dict[str, object]:
    image_url = car.get("image_url")
    images = car.get("images")
    if not image_url and isinstance(images, list) and images:
        image_url = images[0]

    return {
        "id": car.get("id"),
        "title": (
            f"{car.get('year')} {car.get('make')} {car.get('model')} {car.get('variant')}"
        ).replace("  ", " ").strip(),
        "fuel_type": car.get("fuel_type"),
        "transmission": car.get("transmission"),
        "km_driven": car.get("km_driven"),
        "price_lakhs": car.get("price_lakhs"),
        "image_url": image_url,
    }


@router.post("/chat")
async def customer_chat(req: ChatRequest) -> dict[str, object]:
    """Dispatch a demo message through the real backend and log to DB."""
    channel = _require_web_clone()
    incoming = IncomingMessage(
        wa_id=req.customer_id,
        text=req.message,
        msg_id=_new_msg_id("web-demo-in"),
        msg_type=MessageType.TEXT,
        sender_name=req.customer_name,
    )

    reply = await dispatch(incoming)
    if reply:
        await channel.send_text(req.customer_id, reply)

    mode = await state.get_conversation_state(req.customer_id)
    return {"reply": reply, "mode": _to_ui_mode(mode)}


@router.get("/messages/{customer_id}")
async def conversation_messages(customer_id: str) -> dict[str, object]:
    """Return conversation history from the shared DB-backed message log."""
    _require_web_clone()
    mode = await state.get_conversation_state(customer_id)
    messages = await fetch_messages_for_wa_id(customer_id)
    return {
        "customer_id": customer_id,
        "mode": _to_ui_mode(mode),
        "messages": messages,
    }


@router.get("/catalogue")
async def catalogue(limit: int = 8, max_price: float | None = None) -> dict[str, object]:
    """Return compact catalogue cards for the demo frontend."""
    _require_web_clone()
    clamped_limit = max(1, min(limit, 20))
    cars = search_cars(max_price=max_price)
    available = [car for car in cars if not car.get("sold")]
    available.sort(key=lambda car: float(car.get("price_lakhs", 0)))
    return {
        "cars": [_to_catalogue_card(car) for car in available[:clamped_limit]],
        "total_matches": len(available),
    }


@router.post("/reset")
async def reset_chat(req: ResetRequest) -> dict[str, object]:
    """Reset one demo conversation from DB logs and in-memory runtime state."""
    deleted = await delete_messages_for_wa_id(req.customer_id)
    await state.reset_customer_state(req.customer_id)
    return {"reset": deleted}
