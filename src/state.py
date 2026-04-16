"""In-memory state store with async interface.

Every function is async so the interface stays stable when swapped to
PostgreSQL. Uses asyncio.Lock per wa_id to prevent race conditions
in concurrent webhook handling.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import config
from models import (
    ConversationRecord,
    ConversationState,
    CustomerRecord,
    EscalationRecord,
    LeadStatus,
    MessageRecord,
    MessageRole,
    MessageType,
    PendingOwnerActionRecord,
    RelaySessionRecord,
    RelaySessionStatus,
    StaffEscalationNotificationRecord,
    StaffRecord,
    StaffRole,
    StaffStatus,
)

# ---------------------------------------------------------------------------
# Storage (will be replaced by DB queries)
# ---------------------------------------------------------------------------
_staff: dict[str, StaffRecord] = {}
_customers: dict[str, CustomerRecord] = {}
_conversations: dict[str, ConversationRecord] = {}  # keyed by customer_wa_id
_messages: dict[str, list[MessageRecord]] = {}  # keyed by conversation_id
_relay_sessions: dict[str, RelaySessionRecord] = {}  # keyed by staff_wa_id
_escalations: dict[str, list[EscalationRecord]] = {}  # keyed by conversation_id
_staff_escalation_notifications: dict[str, list[StaffEscalationNotificationRecord]] = {}
_pending_owner_actions: dict[str, PendingOwnerActionRecord] = {}  # keyed by staff_wa_id
_processed_msg_ids: set[str] = set()  # for webhook idempotency

# Per-conversation locks to prevent race conditions
_locks: dict[str, asyncio.Lock] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

async def is_message_processed(msg_id: str) -> bool:
    """Check if we've already processed this webhook message ID."""
    return msg_id in _processed_msg_ids


async def mark_message_processed(msg_id: str) -> None:
    """Mark a webhook message ID as processed."""
    _processed_msg_ids.add(msg_id)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

async def get_staff(wa_id: str) -> StaffRecord | None:
    """Look up a staff member by phone number."""
    staff = _staff.get(wa_id)
    if staff and staff.status == StaffStatus.REMOVED:
        return None
    return staff


async def add_staff(
    wa_id: str,
    name: str,
    role: StaffRole,
    status: StaffStatus = StaffStatus.ACTIVE,
    otp_hash: str | None = None,
    otp_expires_at: datetime | None = None,
    added_by: str | None = None,
) -> StaffRecord:
    """Add a new staff member."""
    record = StaffRecord(
        wa_id=wa_id,
        name=name,
        role=role,
        status=status,
        otp_hash=otp_hash,
        otp_expires_at=otp_expires_at,
        added_by=added_by,
        last_active=_now(),
    )
    _staff[wa_id] = record
    return record


async def remove_staff(wa_id: str) -> bool:
    """Revoke staff access. Returns True if found."""
    if wa_id in _staff:
        _staff[wa_id].status = StaffStatus.REMOVED
        # Close any active relay sessions
        if wa_id in _relay_sessions:
            await close_relay_session(wa_id)
        return True
    return False


async def update_staff(wa_id: str, **fields) -> StaffRecord | None:
    """Update staff record fields."""
    staff = _staff.get(wa_id)
    if not staff:
        return None
    for key, value in fields.items():
        if hasattr(staff, key):
            setattr(staff, key, value)
    return staff


async def list_staff() -> list[StaffRecord]:
    """List all active and invited staff."""
    return [s for s in _staff.values() if s.status != StaffStatus.REMOVED]


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

async def get_customer(wa_id: str) -> CustomerRecord | None:
    return _customers.get(wa_id)


async def get_or_create_customer(
    wa_id: str, name: str | None = None, source: str | None = None
) -> CustomerRecord:
    """Get existing customer or create a new one."""
    if wa_id not in _customers:
        _customers[wa_id] = CustomerRecord(
            wa_id=wa_id,
            name=name or "Customer",
            source=source,
            created_at=_now(),
            last_message_at=_now(),
        )
    else:
        _customers[wa_id].last_message_at = _now()
        if name:
            _customers[wa_id].name = name
    return _customers[wa_id]


async def update_lead_status(wa_id: str, status: LeadStatus) -> None:
    if wa_id in _customers:
        _customers[wa_id].lead_status = status


async def list_customers(
    status_filter: list[LeadStatus] | None = None,
    search_query: str | None = None,
    limit: int = 20,
) -> list[CustomerRecord]:
    """List customers with optional filters."""
    results = list(_customers.values())
    if status_filter:
        results = [c for c in results if c.lead_status in status_filter]
    if search_query:
        q = search_query.lower()
        results = [
            c for c in results
            if q in c.name.lower()
            or q in c.wa_id
            or any(q in car.lower() for car in c.interested_cars)
        ]
    results.sort(key=lambda c: c.last_message_at, reverse=True)
    return results[:limit]


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

async def get_conversation(customer_wa_id: str) -> ConversationRecord | None:
    return _conversations.get(customer_wa_id)


async def get_or_create_conversation(customer_wa_id: str) -> ConversationRecord:
    if customer_wa_id not in _conversations:
        conv_id = str(uuid4())
        _conversations[customer_wa_id] = ConversationRecord(
            id=conv_id,
            customer_wa_id=customer_wa_id,
            created_at=_now(),
            last_activity=_now(),
        )
        _messages[conv_id] = []
    else:
        _conversations[customer_wa_id].last_activity = _now()
    return _conversations[customer_wa_id]


async def get_conversation_state(customer_wa_id: str) -> ConversationState:
    conv = _conversations.get(customer_wa_id)
    return conv.state if conv else ConversationState.ACTIVE


async def set_conversation_state(
    customer_wa_id: str, state: ConversationState, reason: str = ""
) -> None:
    conv = _conversations.get(customer_wa_id)
    if conv:
        conv.state = state
        conv.last_activity = _now()
        if reason:
            conv.escalation_reason = reason


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

async def add_message(
    conversation_id: str,
    role: MessageRole,
    content: str,
    msg_type: MessageType = MessageType.TEXT,
    wa_msg_id: str | None = None,
    images: list[str] | None = None,
    is_escalation: bool = False,
    escalation_reason: str = "",
) -> MessageRecord:
    """Append a message to a conversation."""
    msg = MessageRecord(
        id=str(uuid4()),
        conversation_id=conversation_id,
        role=role,
        content=content,
        msg_type=msg_type,
        wa_msg_id=wa_msg_id,
        images=images or [],
        is_escalation=is_escalation,
        escalation_reason=escalation_reason,
        timestamp=_now(),
    )
    if conversation_id not in _messages:
        _messages[conversation_id] = []
    _messages[conversation_id].append(msg)
    return msg


async def get_messages(
    conversation_id: str, limit: int | None = None
) -> list[MessageRecord]:
    """Get messages for a conversation, optionally limited to last N."""
    msgs = _messages.get(conversation_id, [])
    if limit:
        return msgs[-limit:]
    return msgs


async def get_last_customer_message_time(customer_wa_id: str) -> datetime | None:
    """Get timestamp of last customer message (for 24hr window check)."""
    conv = _conversations.get(customer_wa_id)
    if not conv:
        return None
    msgs = _messages.get(conv.id, [])
    for msg in reversed(msgs):
        if msg.role == MessageRole.CUSTOMER:
            return msg.timestamp
    return None


# ---------------------------------------------------------------------------
# Relay Sessions
# ---------------------------------------------------------------------------

async def create_relay_session(
    staff_wa_id: str, customer_wa_id: str
) -> RelaySessionRecord | None:
    """Create a relay session. Returns None if customer is already in a relay."""
    # Check if customer is already in a relay
    for session in _relay_sessions.values():
        if (
            session.customer_wa_id == customer_wa_id
            and session.status == RelaySessionStatus.ACTIVE
        ):
            return None  # lock — another staff member holds this customer

    conv = _conversations.get(customer_wa_id)
    if not conv:
        return None

    session = RelaySessionRecord(
        id=str(uuid4()),
        staff_wa_id=staff_wa_id,
        customer_wa_id=customer_wa_id,
        conversation_id=conv.id,
        started_at=_now(),
        last_active=_now(),
    )
    _relay_sessions[staff_wa_id] = session
    await set_conversation_state(customer_wa_id, ConversationState.RELAY_ACTIVE)
    return session


async def get_active_relay_for_staff(staff_wa_id: str) -> RelaySessionRecord | None:
    session = _relay_sessions.get(staff_wa_id)
    if session and session.status == RelaySessionStatus.ACTIVE:
        return session
    return None


async def get_active_relay_for_customer(
    customer_wa_id: str,
) -> RelaySessionRecord | None:
    for session in _relay_sessions.values():
        if (
            session.customer_wa_id == customer_wa_id
            and session.status == RelaySessionStatus.ACTIVE
        ):
            return session
    return None


async def close_relay_session(
    staff_wa_id: str, reason: str = "manual"
) -> RelaySessionRecord | None:
    """Close a relay session. Returns the closed session or None."""
    session = _relay_sessions.get(staff_wa_id)
    if not session or session.status != RelaySessionStatus.ACTIVE:
        return None

    session.status = (
        RelaySessionStatus.EXPIRED
        if reason == "timeout"
        else RelaySessionStatus.CLOSED
    )
    await set_conversation_state(
        session.customer_wa_id, ConversationState.ACTIVE
    )
    return session


async def update_relay_last_active(staff_wa_id: str) -> None:
    session = _relay_sessions.get(staff_wa_id)
    if session and session.status == RelaySessionStatus.ACTIVE:
        session.last_active = _now()


async def check_expired_relay_sessions() -> list[RelaySessionRecord]:
    """Check and close expired relay sessions. Returns list of expired."""
    timeout = timedelta(minutes=config.RELAY_SESSION_TIMEOUT_MINUTES)
    expired = []
    for staff_wa_id, session in list(_relay_sessions.items()):
        if session.status != RelaySessionStatus.ACTIVE:
            continue
        if _now() - session.last_active > timeout:
            await close_relay_session(staff_wa_id, reason="timeout")
            expired.append(session)
    return expired


async def is_customer_in_relay(customer_wa_id: str) -> bool:
    relay = await get_active_relay_for_customer(customer_wa_id)
    return relay is not None


# ---------------------------------------------------------------------------
# Escalations
# ---------------------------------------------------------------------------

async def add_escalation(
    conversation_id: str, trigger: str, summary: str
) -> EscalationRecord:
    esc = EscalationRecord(
        id=str(uuid4()),
        conversation_id=conversation_id,
        trigger=trigger,
        summary=summary,
        created_at=_now(),
    )
    if conversation_id not in _escalations:
        _escalations[conversation_id] = []
    _escalations[conversation_id].append(esc)
    return esc


async def get_escalations(conversation_id: str) -> list[EscalationRecord]:
    return list(_escalations.get(conversation_id, []))


async def queue_staff_escalation_notification(
    staff_wa_id: str,
    escalation_id: str,
    conversation_id: str,
    customer_wa_id: str,
    customer_name: str,
    lead_status: str,
    trigger: str,
    summary: str,
) -> StaffEscalationNotificationRecord:
    notification = StaffEscalationNotificationRecord(
        id=str(uuid4()),
        staff_wa_id=staff_wa_id,
        escalation_id=escalation_id,
        conversation_id=conversation_id,
        customer_wa_id=customer_wa_id,
        customer_name=customer_name,
        lead_status=lead_status,
        trigger=trigger,
        summary=summary,
        created_at=_now(),
    )
    _staff_escalation_notifications.setdefault(staff_wa_id, []).append(notification)
    return notification


async def get_staff_escalation_notifications(
    staff_wa_id: str,
) -> list[StaffEscalationNotificationRecord]:
    return list(_staff_escalation_notifications.get(staff_wa_id, []))


async def pop_staff_escalation_notifications(
    staff_wa_id: str,
) -> list[StaffEscalationNotificationRecord]:
    return _staff_escalation_notifications.pop(staff_wa_id, [])


# ---------------------------------------------------------------------------
# Pending owner actions
# ---------------------------------------------------------------------------

async def get_pending_owner_action(staff_wa_id: str) -> PendingOwnerActionRecord | None:
    return _pending_owner_actions.get(staff_wa_id)


async def set_pending_owner_action(
    staff_wa_id: str,
    action_name: str,
    payload: dict,
    summary: str,
    confirmation_prompt: str,
) -> PendingOwnerActionRecord:
    record = PendingOwnerActionRecord(
        staff_wa_id=staff_wa_id,
        action_name=action_name,
        payload=payload,
        summary=summary,
        confirmation_prompt=confirmation_prompt,
    )
    _pending_owner_actions[staff_wa_id] = record
    return record


async def clear_pending_owner_action(staff_wa_id: str) -> None:
    _pending_owner_actions.pop(staff_wa_id, None)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

async def init_state() -> None:
    """Seed initial state — owner from config."""
    if config.DEFAULT_OWNER_PHONE not in _staff:
        await add_staff(
            wa_id=config.DEFAULT_OWNER_PHONE,
            name=config.DEFAULT_OWNER_NAME,
            role=StaffRole.OWNER,
            status=StaffStatus.ACTIVE,
        )


async def reset_state() -> None:
    """Clear all state. Used in tests."""
    _staff.clear()
    _customers.clear()
    _conversations.clear()
    _messages.clear()
    _relay_sessions.clear()
    _escalations.clear()
    _staff_escalation_notifications.clear()
    _pending_owner_actions.clear()
    _processed_msg_ids.clear()
    _locks.clear()
