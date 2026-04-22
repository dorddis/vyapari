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
    # 24-hour customer-service window source of truth. Updated ONLY on
    # inbound messages (not our own outbound), so the dispatcher can
    # decide whether to send a free-form reply or a template.
    last_inbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text)

    business: Mapped[Business] = relationship(back_populates="customers")
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_customers_business_lead", "business_id", "lead_status"),
        Index("ix_customers_last_active", "last_active"),
        Index("ix_customers_last_inbound", "last_inbound_at"),
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
    # Nullable for Phase 3.5 rollout + back-compat with pre-P3.5 rows.
    # Phase 3.7+ rewrites ALL insert paths to populate + will eventually
    # flip to NOT NULL after a backfill job.
    business_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
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
    business_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
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
    business_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
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
# WhatsApp Channel (per-business WABA credentials + config)
# ---------------------------------------------------------------------------

class WhatsAppChannel(Base):
    """Per-business WhatsApp Cloud API configuration.

    Phase 3 multi-tenant root for WhatsApp: the webhook handler resolves
    inbound `phone_number_id` against this table to identify the tenant,
    then threads the decrypted access_token / app_secret through the
    adapter. Phase 5 onboards new tenants via Embedded Signup, which
    populates this row via services.business_config.

    provider_config shape (encrypted via services/secrets.py):
        {
            "key_id": "primary",
            "ct": "<Fernet token>"  # decrypts to:
            #   {"access_token": "...", "app_secret": "...",
            #    "webhook_verify_token": "...", "verification_pin": "..."}
        }

    Non-secret fields (source, health, etc.) live as top-level columns
    so queries don't require decryption.
    """

    __tablename__ = "whatsapp_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    business_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    # Human-readable phone ("919876543210" or "+919876543210").
    phone_number: Mapped[str] = mapped_column(String(32), nullable=False)
    # Meta's identifier (the thing that arrives in every webhook's
    # metadata.phone_number_id). This is the tenancy resolution key.
    phone_number_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # WABA (WhatsApp Business Account) id. Templates + embedded-signup
    # operations are WABA-scoped.
    waba_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Encrypted credentials. See services/secrets.encrypt_secrets.
    provider_config: Mapped[dict] = mapped_column(JSON, default=dict)
    # Onboarding source: "manual" (ops wrote the row directly) or
    # "embedded_signup" (owner went through Meta's OAuth flow).
    source: Mapped[str] = mapped_column(String(32), default="manual")
    # Channel-level health — "healthy" | "pending" | "token_expired" | "error".
    health_status: Mapped[str] = mapped_column(String(32), default="pending")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, onupdate=_now_utc
    )

    __table_args__ = (
        UniqueConstraint(
            "business_id", "phone_number", name="uq_channel_business_phone"
        ),
        Index("ix_whatsapp_channels_business", "business_id"),
    )


# ---------------------------------------------------------------------------
# Message Template (Meta-approved outbound templates)
# ---------------------------------------------------------------------------

class MessageTemplate(Base):
    """A business-scoped record of a WhatsApp message template.

    Templates are authored by us (or the business owner), submitted to
    Meta for approval, and cached here with their latest status. The
    outbound dispatcher checks this table before sending anything
    outside the 24-hour customer-service window.

    Unique on (business_id, name, language) — a business can have
    `followup_24h` in both en and hi_IN, but not two "en" copies.
    """

    __tablename__ = "message_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    business_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    # Meta's template categories: "UTILITY", "MARKETING", "AUTHENTICATION".
    category: Mapped[str] = mapped_column(String(32), default="UTILITY")
    # The header/body/footer/buttons shape we'll send to Meta. Matches
    # the `components` field on the send_template payload exactly.
    components: Mapped[list] = mapped_column(JSON, default=list)
    # See MessageTemplateStatus enum. Stored as string so Alembic
    # migrations don't have to know about the enum class.
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    # Meta's own identifier after approval. Nullable until Meta acks.
    meta_template_id: Mapped[str | None] = mapped_column(String(128))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, onupdate=_now_utc
    )

    __table_args__ = (
        UniqueConstraint(
            "business_id", "name", "language", name="uq_template_business_name_lang"
        ),
        Index("ix_templates_business_status", "business_id", "status"),
    )


# ---------------------------------------------------------------------------
# Processed Messages (DB-backed idempotency)
# ---------------------------------------------------------------------------

class ProcessedMessage(Base):
    """Idempotency key store for inbound webhooks.

    Replaces the in-memory _processed_msg_ids dict on state.py with a
    cross-replica safe table. Meta retries webhooks with the same wamid
    for ~24 hours; we dedup on (business_id, wa_msg_id) so two replicas
    cannot both dispatch the same message.

    Rows older than 48h are cleaned up by the relay-expiry worker (or
    a separate cron if ops wants to decouple).
    """

    __tablename__ = "processed_messages"

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wa_msg_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now_utc, index=True,
    )


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
    business_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
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
