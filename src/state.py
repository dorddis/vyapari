"""Persistent state store backed by SQLAlchemy async sessions.

Every function is async and returns the same Pydantic record types as the
original in-memory implementation so **no callers need to change**.

DB tables live in db_models.py.  On startup, init_state() seeds the demo
owner.  For tests, reset_state() truncates all tables.

Idempotency and relay locks stay in-memory (they are ephemeral by nature).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, select, update

import config
import db_models as M
from database import get_session_factory
from models import (
    ConversationRecord,
    ConversationState,
    CustomerRecord,
    EscalationRecord,
    LeadStatus,
    MessageRecord,
    MessageRole,
    MessageType,
    OwnerSetupRecord,
    RelaySessionRecord,
    RelaySessionStatus,
    StaffRecord,
    StaffRole,
    StaffStatus,
)

log = logging.getLogger("vyapari.state")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_biz_for_seed() -> str:
    """Resolve the single-tenant bootstrap business id for seed paths.

    The ONLY legitimate caller is init_state() below — it seeds the demo
    Business row + the first owner so an empty DB is usable locally.
    Production / multi-tenant deployments do not rely on this; every
    inbound request carries its own resolved business_id which gets
    threaded through state.* functions as a required parameter.
    """
    from services.business_config import default_business_id
    return default_business_id()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session():
    """Shortcut to get an async session context manager."""
    return get_session_factory()()


# Ephemeral in-memory stores (not worth persisting)
_processed_msg_ids: dict[str, float] = {}
_MAX_PROCESSED_IDS = 10000
_locks: dict[str, asyncio.Lock] = {}


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


# ---------------------------------------------------------------------------
# ORM row <-> Pydantic record converters
# ---------------------------------------------------------------------------

def _tz_aware(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware (SQLite returns naive)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _staff_to_record(row: M.Staff) -> StaffRecord:
    return StaffRecord(
        wa_id=row.wa_id,
        name=row.name,
        role=StaffRole(row.role),
        status=StaffStatus(row.status),
        otp_hash=row.otp_hash,
        otp_expires_at=_tz_aware(row.otp_expires_at),
        added_by=row.added_by,
        last_active=_tz_aware(row.last_active_at),
    )


def _customer_to_record(row: M.Customer) -> CustomerRecord:
    return CustomerRecord(
        wa_id=row.wa_id,
        name=row.name,
        channel=row.channel,
        source=row.source,
        lead_status=LeadStatus(row.lead_status),
        created_at=row.first_seen,
        last_message_at=row.last_active,
        interested_cars=row.interested_cars or [],
    )


def _conv_to_record(row: M.Conversation) -> ConversationRecord:
    return ConversationRecord(
        id=row.id,
        customer_wa_id=row.customer_wa_id,
        state=ConversationState(row.status),
        assigned_to=row.assigned_to,
        escalation_reason=row.escalation_reason or "",
        created_at=row.started_at,
        last_activity=row.last_updated_at,
    )


def _msg_to_record(row: M.Message) -> MessageRecord:
    return MessageRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        role=MessageRole(row.role),
        content=row.content,
        msg_type=MessageType(row.message_type) if row.message_type in {e.value for e in MessageType} else MessageType.TEXT,
        wa_msg_id=row.wa_msg_id,
        images=row.images or [],
        is_escalation=row.is_escalation,
        escalation_reason=row.escalation_reason or "",
        timestamp=row.timestamp,
    )


def _relay_to_record(row: M.RelaySession) -> RelaySessionRecord:
    return RelaySessionRecord(
        id=row.id,
        staff_wa_id=row.staff_wa_id,
        customer_wa_id=row.customer_wa_id,
        conversation_id=row.conversation_id,
        started_at=row.started_at,
        last_active=row.last_active_at,
        status=RelaySessionStatus(row.status),
    )


def _esc_to_record(row: M.Escalation) -> EscalationRecord:
    return EscalationRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        trigger=row.trigger,
        summary=row.summary,
        status=row.status,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
    )


def _setup_to_record(row: M.OwnerSetup) -> OwnerSetupRecord:
    return OwnerSetupRecord(
        wa_id=row.wa_id,
        current_step=row.current_step,
        collected=row.collected or {},
        active=row.active,
        started_at=row.started_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


# ---------------------------------------------------------------------------
# Idempotency (stays in-memory — ephemeral by design)
# ---------------------------------------------------------------------------

async def is_message_processed(msg_id: str) -> bool:
    return msg_id in _processed_msg_ids


async def mark_message_processed(msg_id: str) -> None:
    import time
    _processed_msg_ids[msg_id] = time.time()
    if len(_processed_msg_ids) > _MAX_PROCESSED_IDS:
        sorted_ids = sorted(_processed_msg_ids.items(), key=lambda x: x[1])
        for old_id, _ in sorted_ids[: len(sorted_ids) - _MAX_PROCESSED_IDS]:
            del _processed_msg_ids[old_id]


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------

async def get_staff(wa_id: str) -> StaffRecord | None:
    async with _session() as s:
        row = await s.get(M.Staff, wa_id)
        if not row or row.status == "removed":
            return None
        return _staff_to_record(row)


async def get_staff_raw(wa_id: str) -> StaffRecord | None:
    """Like get_staff but returns ANY status (including invited/removed).

    Used by auth.py to check invite state.
    """
    async with _session() as s:
        row = await s.get(M.Staff, wa_id)
        return _staff_to_record(row) if row else None


async def add_staff(
    wa_id: str,
    name: str,
    role: StaffRole,
    status: StaffStatus = StaffStatus.ACTIVE,
    otp_hash: str | None = None,
    otp_expires_at: datetime | None = None,
    added_by: str | None = None,
    *,
    business_id: str | None = None,
) -> StaffRecord:
    """Add or upsert a staff member. `business_id` is required for new
    rows; updates are keyed by wa_id so existing rows keep their tenant.

    `business_id` defaults to the single-tenant bootstrap id for back-
    compat with Phase 0-2 callers + test fixtures. Phase 3 multi-tenant
    callers always pass it explicitly.
    """
    async with _session() as s:
        existing = await s.get(M.Staff, wa_id)
        if existing:
            existing.name = name
            existing.role = role.value
            existing.status = status.value
            existing.otp_hash = otp_hash
            existing.otp_expires_at = otp_expires_at
            existing.added_by = added_by
            existing.last_active_at = _now()
            await s.commit()
            return _staff_to_record(existing)
        row = M.Staff(
            wa_id=wa_id,
            business_id=business_id or _default_biz_for_seed(),
            name=name,
            role=role.value,
            status=status.value,
            otp_hash=otp_hash,
            otp_expires_at=otp_expires_at,
            added_by=added_by,
            last_active_at=_now(),
        )
        s.add(row)
        await s.commit()
        return _staff_to_record(row)


async def remove_staff(wa_id: str) -> bool:
    async with _session() as s:
        row = await s.get(M.Staff, wa_id)
        if not row:
            return False
        row.status = "removed"
        await s.commit()
    # Close any active relay sessions
    await close_relay_session(wa_id)
    return True


async def update_staff(wa_id: str, **fields) -> StaffRecord | None:
    async with _session() as s:
        row = await s.get(M.Staff, wa_id)
        if not row:
            return None
        field_map = {
            "status": "status",
            "otp_hash": "otp_hash",
            "otp_expires_at": "otp_expires_at",
            "name": "name",
            "last_active": "last_active_at",
            "attempts": "attempts",
        }
        for key, value in fields.items():
            col = field_map.get(key, key)
            if hasattr(row, col):
                # Convert enum values to strings for DB storage
                if hasattr(value, "value"):
                    value = value.value
                setattr(row, col, value)
        await s.commit()
        return _staff_to_record(row)


async def list_staff() -> list[StaffRecord]:
    async with _session() as s:
        result = await s.execute(
            select(M.Staff).where(M.Staff.status != "removed")
        )
        return [_staff_to_record(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

async def get_customer(wa_id: str) -> CustomerRecord | None:
    async with _session() as s:
        row = await s.get(M.Customer, wa_id)
        return _customer_to_record(row) if row else None


async def get_or_create_customer(
    wa_id: str,
    name: str | None = None,
    source: str | None = None,
    *,
    business_id: str | None = None,
) -> CustomerRecord:
    """Find or create a Customer row.

    `business_id` is used when creating a new row; existing rows keep
    their original tenant. Defaults to the bootstrap id for back-compat;
    new code paths should always pass it explicitly.
    """
    async with _session() as s:
        row = await s.get(M.Customer, wa_id)
        if row:
            row.last_active = _now()
            if name:
                row.name = name
            await s.commit()
            return _customer_to_record(row)
        row = M.Customer(
            wa_id=wa_id,
            business_id=business_id or _default_biz_for_seed(),
            name=name or "Customer",
            source=source,
            first_seen=_now(),
            last_active=_now(),
        )
        s.add(row)
        await s.commit()
        return _customer_to_record(row)


async def update_lead_status(wa_id: str, status: LeadStatus) -> None:
    async with _session() as s:
        row = await s.get(M.Customer, wa_id)
        if row:
            row.lead_status = status.value
            await s.commit()


async def update_customer_interested_cars(wa_id: str, cars: list[str]) -> None:
    async with _session() as s:
        row = await s.get(M.Customer, wa_id)
        if row:
            row.interested_cars = cars
            await s.commit()


async def list_customers(
    status_filter: list[LeadStatus] | None = None,
    search_query: str | None = None,
    limit: int = 20,
    *,
    business_id: str | None = None,
) -> list[CustomerRecord]:
    """List customers scoped to a business.

    `business_id` defaults to the bootstrap id for back-compat. Agent
    tools that have a CustomerContext must pass ctx.business_id.
    """
    scope_biz = business_id or _default_biz_for_seed()
    async with _session() as s:
        stmt = select(M.Customer).where(M.Customer.business_id == scope_biz)
        if status_filter:
            stmt = stmt.where(M.Customer.lead_status.in_([st.value for st in status_filter]))
        if search_query:
            q = f"%{search_query.lower()}%"
            stmt = stmt.where(
                M.Customer.name.ilike(q) | M.Customer.wa_id.contains(search_query)
            )
        stmt = stmt.order_by(M.Customer.last_active.desc()).limit(limit)
        result = await s.execute(stmt)
        return [_customer_to_record(r) for r in result.scalars().all()]


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

async def get_conversation(customer_wa_id: str) -> ConversationRecord | None:
    async with _session() as s:
        result = await s.execute(
            select(M.Conversation)
            .where(M.Conversation.customer_wa_id == customer_wa_id)
            .order_by(M.Conversation.started_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return _conv_to_record(row) if row else None


async def get_or_create_conversation(
    customer_wa_id: str, *, business_id: str | None = None
) -> ConversationRecord:
    """Find or create a Conversation row for a customer.

    `business_id` is stamped on new rows only; existing ones keep their
    tenant. Back-compat default preserves Phase 0-2 behavior; Phase 3
    callers should always pass it explicitly.
    """
    async with _session() as s:
        result = await s.execute(
            select(M.Conversation)
            .where(M.Conversation.customer_wa_id == customer_wa_id)
            .order_by(M.Conversation.started_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            row.last_updated_at = _now()
            await s.commit()
            return _conv_to_record(row)
        conv_id = str(uuid4())
        row = M.Conversation(
            id=conv_id,
            business_id=business_id or _default_biz_for_seed(),
            customer_wa_id=customer_wa_id,
            started_at=_now(),
            last_updated_at=_now(),
        )
        s.add(row)
        await s.commit()
        return _conv_to_record(row)


async def get_conversation_state(customer_wa_id: str) -> ConversationState:
    async with _session() as s:
        result = await s.execute(
            select(M.Conversation.status)
            .where(M.Conversation.customer_wa_id == customer_wa_id)
            .order_by(M.Conversation.started_at.desc())
            .limit(1)
        )
        status = result.scalar_one_or_none()
        return ConversationState(status) if status else ConversationState.ACTIVE


async def set_conversation_state(
    customer_wa_id: str, state: ConversationState, reason: str = ""
) -> None:
    async with _session() as s:
        result = await s.execute(
            select(M.Conversation)
            .where(M.Conversation.customer_wa_id == customer_wa_id)
            .order_by(M.Conversation.started_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row:
            row.status = state.value
            row.last_updated_at = _now()
            if reason:
                row.escalation_reason = reason
            await s.commit()


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
    msg_id = str(uuid4())
    async with _session() as s:
        row = M.Message(
            id=msg_id,
            conversation_id=conversation_id,
            role=role.value,
            content=content,
            message_type=msg_type.value,
            wa_msg_id=wa_msg_id,
            images=images or [],
            is_escalation=is_escalation,
            escalation_reason=escalation_reason,
            timestamp=_now(),
        )
        s.add(row)
        await s.commit()
    return MessageRecord(
        id=msg_id,
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


async def get_messages(
    conversation_id: str, limit: int | None = None
) -> list[MessageRecord]:
    async with _session() as s:
        stmt = (
            select(M.Message)
            .where(M.Message.conversation_id == conversation_id)
            .order_by(M.Message.timestamp.asc())
        )
        if limit:
            # Get the last N messages by subquery
            count_result = await s.execute(
                select(M.Message.id)
                .where(M.Message.conversation_id == conversation_id)
            )
            all_ids = count_result.scalars().all()
            if len(all_ids) > limit:
                stmt = (
                    select(M.Message)
                    .where(M.Message.conversation_id == conversation_id)
                    .order_by(M.Message.timestamp.desc())
                    .limit(limit)
                )
                result = await s.execute(stmt)
                rows = list(result.scalars().all())
                rows.reverse()
                return [_msg_to_record(r) for r in rows]
        result = await s.execute(stmt)
        return [_msg_to_record(r) for r in result.scalars().all()]


async def get_last_customer_message_time(customer_wa_id: str) -> datetime | None:
    conv = await get_conversation(customer_wa_id)
    if not conv:
        return None
    async with _session() as s:
        result = await s.execute(
            select(M.Message.timestamp)
            .where(
                M.Message.conversation_id == conv.id,
                M.Message.role == "customer",
            )
            .order_by(M.Message.timestamp.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Relay Sessions
# ---------------------------------------------------------------------------

async def create_relay_session(
    staff_wa_id: str, customer_wa_id: str
) -> RelaySessionRecord | None:
    async with _get_lock(f"relay_{customer_wa_id}"):
        async with _session() as s:
            # Check if customer is already in active relay with ANOTHER staff
            result = await s.execute(
                select(M.RelaySession).where(
                    M.RelaySession.customer_wa_id == customer_wa_id,
                    M.RelaySession.status == "active",
                    M.RelaySession.staff_wa_id != staff_wa_id,
                )
            )
            if result.scalar_one_or_none():
                return None

            # Close any existing session for this staff member
            result = await s.execute(
                select(M.RelaySession).where(
                    M.RelaySession.staff_wa_id == staff_wa_id,
                    M.RelaySession.status == "active",
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.status = "closed"
                await s.commit()
                await set_conversation_state(existing.customer_wa_id, ConversationState.ACTIVE)

        # Get conversation (need fresh session after possible commit)
        conv = await get_conversation(customer_wa_id)
        if not conv:
            return None

        async with _session() as s:
            row = M.RelaySession(
                id=str(uuid4()),
                staff_wa_id=staff_wa_id,
                customer_wa_id=customer_wa_id,
                conversation_id=conv.id,
                started_at=_now(),
                last_active_at=_now(),
            )
            s.add(row)
            await s.commit()

        await set_conversation_state(customer_wa_id, ConversationState.RELAY_ACTIVE)
        return _relay_to_record(row)


async def get_active_relay_for_staff(staff_wa_id: str) -> RelaySessionRecord | None:
    async with _session() as s:
        result = await s.execute(
            select(M.RelaySession).where(
                M.RelaySession.staff_wa_id == staff_wa_id,
                M.RelaySession.status == "active",
            )
        )
        row = result.scalar_one_or_none()
        return _relay_to_record(row) if row else None


async def get_active_relay_for_customer(
    customer_wa_id: str,
) -> RelaySessionRecord | None:
    async with _session() as s:
        result = await s.execute(
            select(M.RelaySession).where(
                M.RelaySession.customer_wa_id == customer_wa_id,
                M.RelaySession.status == "active",
            )
        )
        row = result.scalar_one_or_none()
        return _relay_to_record(row) if row else None


async def close_relay_session(
    staff_wa_id: str, reason: str = "manual"
) -> RelaySessionRecord | None:
    async with _session() as s:
        result = await s.execute(
            select(M.RelaySession).where(
                M.RelaySession.staff_wa_id == staff_wa_id,
                M.RelaySession.status == "active",
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        row.status = "expired" if reason == "timeout" else "closed"
        customer_wa_id = row.customer_wa_id
        record = _relay_to_record(row)
        await s.commit()

    await set_conversation_state(customer_wa_id, ConversationState.ACTIVE)
    return record


async def update_relay_last_active(staff_wa_id: str) -> None:
    async with _session() as s:
        result = await s.execute(
            select(M.RelaySession).where(
                M.RelaySession.staff_wa_id == staff_wa_id,
                M.RelaySession.status == "active",
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.last_active_at = _now()
            await s.commit()


async def check_expired_relay_sessions() -> list[RelaySessionRecord]:
    timeout = timedelta(minutes=config.RELAY_SESSION_TIMEOUT_MINUTES)
    cutoff = _now() - timeout
    expired = []
    async with _session() as s:
        result = await s.execute(
            select(M.RelaySession).where(
                M.RelaySession.status == "active",
                M.RelaySession.last_active_at < cutoff,
            )
        )
        rows = result.scalars().all()
        for row in rows:
            row.status = "expired"
            expired.append(_relay_to_record(row))
        await s.commit()

    # Restore conversation states
    for rec in expired:
        await set_conversation_state(rec.customer_wa_id, ConversationState.ACTIVE)
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
    esc_id = str(uuid4())
    async with _session() as s:
        row = M.Escalation(
            id=esc_id,
            conversation_id=conversation_id,
            trigger=trigger,
            summary=summary,
            created_at=_now(),
        )
        s.add(row)
        await s.commit()
    return EscalationRecord(
        id=esc_id,
        conversation_id=conversation_id,
        trigger=trigger,
        summary=summary,
        created_at=_now(),
    )


# ---------------------------------------------------------------------------
# Owner setup / onboarding
# ---------------------------------------------------------------------------

async def get_owner_setup(wa_id: str) -> OwnerSetupRecord | None:
    async with _session() as s:
        row = await s.get(M.OwnerSetup, wa_id)
        return _setup_to_record(row) if row else None


async def start_owner_setup(
    wa_id: str,
    current_step: str = "business_name",
    collected: dict | None = None,
) -> OwnerSetupRecord:
    async with _session() as s:
        existing = await s.get(M.OwnerSetup, wa_id)
        if existing:
            existing.current_step = current_step
            existing.collected = collected or {}
            existing.active = True
            existing.updated_at = _now()
            await s.commit()
            return _setup_to_record(existing)
        row = M.OwnerSetup(
            wa_id=wa_id,
            current_step=current_step,
            collected=collected or {},
            active=True,
            started_at=_now(),
            updated_at=_now(),
        )
        s.add(row)
        await s.commit()
        return _setup_to_record(row)


async def update_owner_setup(
    wa_id: str,
    *,
    current_step: str | None = None,
    collected: dict | None = None,
    active: bool | None = None,
) -> OwnerSetupRecord | None:
    async with _session() as s:
        row = await s.get(M.OwnerSetup, wa_id)
        if not row:
            return None
        if current_step is not None:
            row.current_step = current_step
        if collected is not None:
            row.collected = collected
        if active is not None:
            row.active = active
        row.updated_at = _now()
        await s.commit()
        return _setup_to_record(row)


async def complete_owner_setup(wa_id: str) -> OwnerSetupRecord | None:
    async with _session() as s:
        row = await s.get(M.OwnerSetup, wa_id)
        if not row:
            return None
        row.active = False
        row.completed_at = _now()
        row.updated_at = _now()
        await s.commit()
        return _setup_to_record(row)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

async def init_state() -> None:
    """Seed initial state — demo business + owner from config.

    The SQL migration already seeds these for Postgres, but this handles
    the SQLite fallback case where create_all doesn't run seeds. This
    is the ONE legitimate caller of _default_biz_for_seed() — single-
    tenant bootstrap for local dev. Production / multi-tenant deploys
    skip this path entirely (businesses are created via onboarding).
    """
    from services.business_config import default_owner_phone
    bootstrap_biz = _default_biz_for_seed()
    bootstrap_owner = default_owner_phone()
    # Ensure the demo business exists
    async with _session() as s:
        biz = await s.get(M.Business, bootstrap_biz)
        if not biz:
            s.add(M.Business(
                id=bootstrap_biz,
                name=config.DEFAULT_BUSINESS_NAME,
                type="dealership",
                vertical=config.DEFAULT_BUSINESS_VERTICAL,
                owner_phone=bootstrap_owner,
                greeting="Welcome to Sharma Motors! How can I help you today?",
            ))
            await s.commit()

    # Ensure the owner staff record exists
    existing = await get_staff(bootstrap_owner)
    if not existing:
        await add_staff(
            wa_id=bootstrap_owner,
            name=config.DEFAULT_OWNER_NAME,
            role=StaffRole.OWNER,
            status=StaffStatus.ACTIVE,
            business_id=bootstrap_biz,
        )


async def reset_state() -> None:
    """Clear all state. Used in tests."""
    async with _session() as s:
        # Delete in FK-safe order
        await s.execute(delete(M.Message))
        await s.execute(delete(M.Escalation))
        await s.execute(delete(M.RelaySession))
        await s.execute(delete(M.OwnerSetup))
        await s.execute(delete(M.Conversation))
        await s.execute(delete(M.Customer))
        await s.execute(delete(M.Staff))
        await s.commit()
    _processed_msg_ids.clear()
    _locks.clear()


async def reset_customer_state(customer_wa_id: str) -> None:
    """Clear one customer's runtime state without affecting global staff state."""
    async with _session() as s:
        # Get conversation IDs for this customer
        result = await s.execute(
            select(M.Conversation.id).where(
                M.Conversation.customer_wa_id == customer_wa_id
            )
        )
        conv_ids = [r for r in result.scalars().all()]

        if conv_ids:
            await s.execute(
                delete(M.Message).where(M.Message.conversation_id.in_(conv_ids))
            )
            await s.execute(
                delete(M.Escalation).where(M.Escalation.conversation_id.in_(conv_ids))
            )
            await s.execute(
                delete(M.RelaySession).where(M.RelaySession.conversation_id.in_(conv_ids))
            )
            await s.execute(
                delete(M.Conversation).where(M.Conversation.customer_wa_id == customer_wa_id)
            )
        await s.execute(
            delete(M.Customer).where(M.Customer.wa_id == customer_wa_id)
        )
        await s.commit()
    _locks.pop(customer_wa_id, None)
