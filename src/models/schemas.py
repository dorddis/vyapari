"""Pydantic schemas — the shared contracts everyone codes against."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from models.enums import (
    ConversationState,
    LeadStatus,
    MessageRole,
    MessageType,
    RelaySessionStatus,
    RoutingAction,
    StaffRole,
    StaffStatus,
)


# ---------------------------------------------------------------------------
# Incoming message (from webhook or web API)
# ---------------------------------------------------------------------------

class IncomingMessage(BaseModel):
    """Normalized incoming message from any channel."""
    wa_id: str = Field(..., description="Sender phone number with country code, e.g. 919876543210")
    text: str | None = Field(None, description="Message text body (None for media-only)")
    msg_id: str = Field(..., description="Channel-specific message ID for dedup and read receipts")
    msg_type: MessageType = Field(default=MessageType.TEXT)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    # Optional media fields
    media_id: str | None = None
    media_url: str | None = None
    caption: str | None = None
    # Optional interactive reply fields
    button_reply_id: str | None = None
    button_reply_title: str | None = None
    list_reply_id: str | None = None
    list_reply_title: str | None = None
    # Sender profile
    sender_name: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "wa_id": "919876543210",
                "text": "Koi SUV hai 8 lakh ke under?",
                "msg_id": "wamid.abc123",
                "msg_type": "text",
                "sender_name": "Ramesh Patil",
            }
        }


# ---------------------------------------------------------------------------
# Routing decision (output of router.route_message)
# ---------------------------------------------------------------------------

class RoutingDecision(BaseModel):
    """What the router decides to do with a message."""
    role: StaffRole | str = Field(..., description="Resolved role: 'customer', 'unknown', or StaffRole")
    action: RoutingAction
    target_wa_id: str | None = Field(None, description="For relay_forward: who to send to")
    conversation_state: ConversationState | None = None
    staff_name: str | None = None


# ---------------------------------------------------------------------------
# Tool response (universal return contract from design doc Section 7)
# ---------------------------------------------------------------------------

class ToolResponse(BaseModel):
    """Every agent tool returns this shape."""
    success: bool
    data: dict | list | None = None
    message: str

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "data": [{"id": 1, "name": "2022 Tata Nexon XZ"}],
                "message": "Found 1 car matching your criteria.",
            }
        }


# ---------------------------------------------------------------------------
# Record schemas (used in state.py and API responses)
# ---------------------------------------------------------------------------

class StaffRecord(BaseModel):
    wa_id: str
    name: str
    role: StaffRole
    status: StaffStatus = StaffStatus.ACTIVE
    otp_hash: str | None = None
    otp_expires_at: datetime | None = None
    added_by: str | None = None
    last_active: datetime | None = None


class CustomerRecord(BaseModel):
    wa_id: str
    name: str = "Customer"
    channel: str = "whatsapp"
    source: str | None = None
    lead_status: LeadStatus = LeadStatus.NEW
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_message_at: datetime = Field(default_factory=datetime.utcnow)
    interested_cars: list[str] = Field(default_factory=list)


class ConversationRecord(BaseModel):
    id: str
    customer_wa_id: str
    state: ConversationState = ConversationState.ACTIVE
    assigned_to: str | None = None  # staff wa_id
    escalation_reason: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)


class MessageRecord(BaseModel):
    id: str
    conversation_id: str
    role: MessageRole
    content: str
    msg_type: MessageType = MessageType.TEXT
    wa_msg_id: str | None = None
    images: list[str] = Field(default_factory=list)
    is_escalation: bool = False
    escalation_reason: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RelaySessionRecord(BaseModel):
    id: str
    staff_wa_id: str
    customer_wa_id: str
    conversation_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    status: RelaySessionStatus = RelaySessionStatus.ACTIVE


class EscalationRecord(BaseModel):
    id: str
    conversation_id: str
    trigger: str
    summary: str
    status: str = "pending"  # pending / acknowledged / resolved
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None


class StaffEscalationNotificationRecord(BaseModel):
    id: str
    staff_wa_id: str
    escalation_id: str
    conversation_id: str
    customer_wa_id: str
    customer_name: str
    lead_status: str
    trigger: str
    summary: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PendingOwnerActionRecord(BaseModel):
    staff_wa_id: str
    action_name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    summary: str
    confirmation_prompt: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DailyWrapRecord(BaseModel):
    id: str
    date: str  # YYYY-MM-DD
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
