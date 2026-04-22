"""Shared enums used across the entire codebase."""

from enum import Enum


class ConversationState(str, Enum):
    """State machine for customer conversations."""
    ACTIVE = "active"
    ESCALATED = "escalated"
    RELAY_ACTIVE = "relay_active"
    RESOLVED = "resolved"


class StaffRole(str, Enum):
    """Role of an authenticated staff member."""
    OWNER = "owner"
    SDR = "sdr"


class StaffStatus(str, Enum):
    """Lifecycle status of a staff record."""
    ACTIVE = "active"
    INVITED = "invited"      # OTP generated, not yet verified
    REMOVED = "removed"


class LeadStatus(str, Enum):
    """Sales pipeline status for a customer."""
    NEW = "new"
    WARM = "warm"
    HOT = "hot"
    QUIET = "quiet"
    CONVERTED = "converted"


class MessageRole(str, Enum):
    """Who sent a message."""
    CUSTOMER = "customer"
    AGENT = "agent"
    OWNER = "owner"
    SDR = "sdr"


class MessageType(str, Enum):
    """Type of incoming message content."""
    TEXT = "text"
    IMAGE = "image"
    VOICE = "voice"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    LOCATION = "location"
    CONTACTS = "contacts"
    STICKER = "sticker"
    REACTION = "reaction"
    BUTTON_REPLY = "button_reply"
    LIST_REPLY = "list_reply"


class RoutingAction(str, Enum):
    """What the router decides to do with a message."""
    CUSTOMER_AGENT = "customer_agent"
    OWNER_AGENT = "owner_agent"
    SDR_AGENT = "sdr_agent"
    RELAY_FORWARD = "relay_forward"
    RELAY_COMMAND = "relay_command"
    AUTH_FLOW = "auth_flow"
    IGNORE = "ignore"


class RelaySessionStatus(str, Enum):
    """Status of a relay session."""
    ACTIVE = "active"
    CLOSED = "closed"
    EXPIRED = "expired"


class MessageTemplateStatus(str, Enum):
    """Lifecycle status of a Meta-approved message template."""
    PENDING = "pending"        # submitted, awaiting Meta review
    APPROVED = "approved"      # safe to send (inside + outside 24h window)
    REJECTED = "rejected"      # Meta rejected; cannot send
    PAUSED = "paused"          # auto-paused by Meta for quality issues
    DISABLED = "disabled"      # we turned it off (do-not-use)
