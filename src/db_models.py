"""SQLAlchemy ORM models for all persisted app data.

Maps directly to the design doc schema (DESIGN_DOC.md Section 4) and the
Pydantic record schemas in models/schemas.py.  When we swap state.py from
in-memory dicts to real DB queries, these are the tables it will hit.

Table overview:
    businesses        - Multi-tenant business profiles
    catalogue_items   - Inventory (cars, products)
    faqs              - Business FAQ entries
    staff             - Owner / SDR records with OTP auth
    customers         - Lead / customer records
    conversations     - Customer conversation sessions
    messages          - Individual messages within conversations
    escalations       - Escalation events
    relay_sessions    - Staff takeover sessions
    daily_wraps       - End-of-day summary snapshots
    owner_setup       - Owner onboarding wizard state
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid4())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Business (multi-tenant root)
# ---------------------------------------------------------------------------

class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    type: Mapped[str] = mapped_column(String(64), default="")
    vertical: Mapped[str] = mapped_column(String(64), default="")
    owner_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    wa_catalog_id: Mapped[str | None] = mapped_column(String(128))
    greeting: Mapped[str] = mapped_column(Text, default="")
    hours: Mapped[dict] = mapped_column(JSON, default=dict)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )

    # Relationships
    catalogue_items: Mapped[list[CatalogueItem]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    faqs: Mapped[list[FAQ]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    staff_members: Mapped[list[Staff]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )
    customers: Mapped[list[Customer]] = relationship(
        back_populates="business", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Catalogue Item (inventory)
# ---------------------------------------------------------------------------

class CatalogueItem(Base):
    __tablename__ = "catalogue_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    business_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    wa_product_id: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="")
    price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    images: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sold: Mapped[bool] = mapped_column(Boolean, default=False)
    reserved_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, onupdate=_now_utc
    )

    business: Mapped[Business] = relationship(back_populates="catalogue_items")

    __table_args__ = (
        Index("ix_catalogue_items_business_active", "business_id", "active"),
        Index("ix_catalogue_items_category", "category"),
    )


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------

class FAQ(Base):
    __tablename__ = "faqs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    business_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="general")

    business: Mapped[Business] = relationship(back_populates="faqs")

    __table_args__ = (
        Index("ix_faqs_business_category", "business_id", "category"),
    )


# ---------------------------------------------------------------------------
# Staff (owner / SDR)
# ---------------------------------------------------------------------------

class Staff(Base):
    __tablename__ = "staff"

    wa_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    business_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # owner / sdr
    status: Mapped[str] = mapped_column(String(16), default="active")  # active / invited / removed
    otp_hash: Mapped[str | None] = mapped_column(String(256))
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    added_by: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    business: Mapped[Business] = relationship(back_populates="staff_members")

    __table_args__ = (
        Index("ix_staff_business_role", "business_id", "role"),
    )


# ---------------------------------------------------------------------------
# Customer (lead)
# ---------------------------------------------------------------------------

class Customer(Base):
    __tablename__ = "customers"

    wa_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    business_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), default="Customer")
    channel: Mapped[str] = mapped_column(String(32), default="whatsapp")
    source: Mapped[str | None] = mapped_column(String(256))
    lead_status: Mapped[str] = mapped_column(String(16), default="new")
    interested_cars: Mapped[list] = mapped_column(JSON, default=list)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    notes: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business] = relationship(back_populates="customers")
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_customers_business_lead", "business_id", "lead_status"),
        Index("ix_customers_last_active", "last_active"),
    )


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    business_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    customer_wa_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.wa_id", ondelete="CASCADE"), nullable=False
    )
    assigned_to: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("staff.wa_id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(24), default="active")
    escalation_reason: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, onupdate=_now_utc
    )

    customer: Mapped[Customer] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    escalations: Mapped[list[Escalation]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    relay_sessions: Mapped[list[RelaySession]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_conversations_customer", "customer_wa_id"),
        Index("ix_conversations_status", "status"),
        Index("ix_conversations_business_status", "business_id", "status"),
    )


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # customer / agent / owner / sdr
    content: Mapped[str] = mapped_column(Text, default="")
    message_type: Mapped[str] = mapped_column(String(24), default="text")
    wa_msg_id: Mapped[str | None] = mapped_column(String(128), index=True)
    images: Mapped[list] = mapped_column(JSON, default=list)
    is_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conversation_ts", "conversation_id", "timestamp"),
    )


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------

class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped[Conversation] = relationship(back_populates="escalations")

    __table_args__ = (
        Index("ix_escalations_conversation", "conversation_id"),
        Index("ix_escalations_status", "status"),
    )


# ---------------------------------------------------------------------------
# Relay Session
# ---------------------------------------------------------------------------

class RelaySession(Base):
    __tablename__ = "relay_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    staff_wa_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("staff.wa_id", ondelete="CASCADE"), nullable=False
    )
    customer_wa_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("customers.wa_id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    status: Mapped[str] = mapped_column(String(16), default="active")
    inactivity_timeout_minutes: Mapped[int] = mapped_column(Integer, default=15)
    total_timeout_minutes: Mapped[int] = mapped_column(Integer, default=20)

    conversation: Mapped[Conversation] = relationship(back_populates="relay_sessions")

    __table_args__ = (
        Index("ix_relay_sessions_staff", "staff_wa_id", "status"),
        Index("ix_relay_sessions_customer", "customer_wa_id", "status"),
        UniqueConstraint(
            "customer_wa_id",
            name="uq_relay_one_active_per_customer",
            # Enforced in app logic: only one ACTIVE session per customer
        ),
    )


# ---------------------------------------------------------------------------
# Daily Wrap
# ---------------------------------------------------------------------------

class DailyWrap(Base):
    __tablename__ = "daily_wraps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    business_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )

    __table_args__ = (
        UniqueConstraint("business_id", "date", name="uq_daily_wrap_business_date"),
    )


# ---------------------------------------------------------------------------
# Owner Setup (onboarding wizard)
# ---------------------------------------------------------------------------

class OwnerSetup(Base):
    __tablename__ = "owner_setup"

    wa_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("staff.wa_id", ondelete="CASCADE"), primary_key=True
    )
    current_step: Mapped[str] = mapped_column(String(64), default="business_name")
    collected: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, onupdate=_now_utc
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------------------
# Message Log (Rahul's existing table - kept for web clone compat)
# ---------------------------------------------------------------------------

class MessageLog(Base):
    """Flat message log used by web_clone channel and owner panel.

    This is the table Rahul created on dev-rowl.  Kept here for backwards
    compatibility with the web UI polling endpoints.  New code should prefer
    the normalized messages table above.
    """

    __tablename__ = "message_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    wa_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(24), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    msg_type: Mapped[str] = mapped_column(String(32), default="text")
    external_msg_id: Mapped[str | None] = mapped_column(String(128), index=True)
    images: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, index=True
    )
