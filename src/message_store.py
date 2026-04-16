"""In-memory message and conversation state for the UI layer."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class MessageRole(str, Enum):
    CUSTOMER = "customer"
    BOT = "bot"
    OWNER = "owner"


class ConversationMode(str, Enum):
    BOT = "bot"
    ESCALATED = "escalated"
    OWNER = "owner"


@dataclass
class Message:
    id: str
    role: MessageRole
    text: str
    timestamp: str
    images: list[str] = field(default_factory=list)
    is_escalation: bool = False
    escalation_reason: str = ""


@dataclass
class Conversation:
    customer_id: str
    customer_name: str = "Customer"
    messages: list[Message] = field(default_factory=list)
    mode: ConversationMode = ConversationMode.BOT
    created_at: str = ""
    last_activity: str = ""
    escalation_reason: str = ""


# Global store
_conversations: dict[str, Conversation] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_or_create_conversation(customer_id: str, name: str | None = None) -> Conversation:
    if customer_id not in _conversations:
        _conversations[customer_id] = Conversation(
            customer_id=customer_id,
            customer_name=name or f"Customer {len(_conversations) + 1}",
            created_at=_now(),
            last_activity=_now(),
        )
    elif name:
        _conversations[customer_id].customer_name = name
    return _conversations[customer_id]


def add_message(
    customer_id: str,
    role: MessageRole,
    text: str,
    images: list[str] | None = None,
    is_escalation: bool = False,
    escalation_reason: str = "",
) -> Message:
    convo = get_or_create_conversation(customer_id)
    msg = Message(
        id=str(uuid4()),
        role=role,
        text=text,
        timestamp=_now(),
        images=images or [],
        is_escalation=is_escalation,
        escalation_reason=escalation_reason,
    )
    convo.messages.append(msg)
    convo.last_activity = msg.timestamp
    return msg


def get_messages(customer_id: str, since_id: str | None = None) -> list[Message]:
    convo = _conversations.get(customer_id)
    if not convo:
        return []
    if not since_id:
        return convo.messages
    # Return messages after the given ID
    found = False
    result = []
    for msg in convo.messages:
        if found:
            result.append(msg)
        if msg.id == since_id:
            found = True
    return result


def list_conversations() -> list[dict]:
    result = []
    for cid, convo in _conversations.items():
        last_msg = convo.messages[-1] if convo.messages else None
        has_escalation = convo.mode == ConversationMode.ESCALATED
        result.append({
            "customer_id": cid,
            "customer_name": convo.customer_name,
            "last_message": last_msg.text[:80] if last_msg else "",
            "last_message_role": last_msg.role.value if last_msg else "",
            "last_activity": convo.last_activity,
            "mode": convo.mode.value,
            "message_count": len(convo.messages),
            "has_escalation": has_escalation,
            "escalation_reason": convo.escalation_reason,
        })
    # Most recent first
    result.sort(key=lambda x: x["last_activity"], reverse=True)
    return result


def set_mode(customer_id: str, mode: ConversationMode, reason: str = "") -> None:
    convo = _conversations.get(customer_id)
    if convo:
        convo.mode = mode
        if reason:
            convo.escalation_reason = reason


def get_mode(customer_id: str) -> ConversationMode:
    convo = _conversations.get(customer_id)
    return convo.mode if convo else ConversationMode.BOT
