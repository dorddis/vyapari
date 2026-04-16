"""SQLAlchemy ORM models for persisted app data."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class MessageLog(Base):
    """Durable message log for both web clone and WhatsApp channels."""

    __tablename__ = "message_logs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    wa_id: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(24), index=True)
    direction: Mapped[str] = mapped_column(String(16), index=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(Text, default="")
    msg_type: Mapped[str] = mapped_column(String(32), default="text")
    external_msg_id: Mapped[str | None] = mapped_column(String(128), index=True)
    images: Mapped[list[str]] = mapped_column(JSON, default=list)
    meta: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_now_utc,
        index=True,
    )
