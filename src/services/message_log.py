"""DB-backed message logging and retrieval helpers."""

from __future__ import annotations

from collections import OrderedDict

from sqlalchemy import delete, select

import state
from database import get_session_factory
from db_models import MessageLog
from models import IncomingMessage


async def log_message(
    *,
    wa_id: str,
    role: str,
    direction: str,
    channel: str,
    text: str = "",
    msg_type: str = "text",
    external_msg_id: str | None = None,
    images: list[str] | None = None,
    meta: dict | None = None,
    business_id: str | None = None,
) -> str:
    """Persist one message row and return generated DB id.

    `business_id` is optional for Phase 3.5 back-compat; callers that
    have a resolved tenant should pass it so the row is tenant-scoped
    for future audit queries.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = MessageLog(
            business_id=business_id,
            wa_id=wa_id,
            role=role,
            direction=direction,
            channel=channel,
            text=text,
            msg_type=msg_type,
            external_msg_id=external_msg_id,
            images=images or [],
            meta=meta or {},
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def log_incoming_message(msg: IncomingMessage, channel: str) -> str:
    """Persist an incoming message from a customer/staff."""
    role = "customer"
    staff = await state.get_staff(msg.wa_id)
    if staff:
        role = staff.role.value

    return await log_message(
        wa_id=msg.wa_id,
        role=role,
        direction="inbound",
        channel=channel,
        text=msg.text or "",
        msg_type=msg.msg_type.value,
        external_msg_id=msg.msg_id,
        business_id=msg.business_id or None,
        meta={
            "sender_name": msg.sender_name or "",
            "button_reply_id": msg.button_reply_id or "",
            "list_reply_id": msg.list_reply_id or "",
        },
    )


async def update_status(
    *,
    external_msg_id: str,
    status: str,
    timestamp: str | None = None,
    error: dict | None = None,
) -> bool:
    """Append a delivery-status event to an outbound message's `meta` JSON.

    Called from the webhook handler when Meta sends a status update
    (sent / delivered / read / failed). Returns True if the row was
    found and updated, False if there's no matching external_msg_id
    (common when Meta sends status for messages we didn't log, e.g.
    templates fired by another process).

    The row's meta gains:
        meta.statuses = [{status, timestamp, error}, ...]
        meta.last_status = <latest>
    """
    if not external_msg_id:
        return False
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(MessageLog).where(MessageLog.external_msg_id == external_msg_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        # MessageLog.meta is a JSON column; mutating the dict in place
        # doesn't flag it dirty under SQLAlchemy. Re-assign to a new dict.
        meta = dict(row.meta or {})
        statuses = list(meta.get("statuses") or [])
        statuses.append(
            {"status": status, "timestamp": timestamp, "error": error}
        )
        meta["statuses"] = statuses
        meta["last_status"] = status
        if error:
            meta["last_error"] = error
        row.meta = meta
        await session.commit()
        return True


async def fetch_messages_for_wa_id(
    wa_id: str,
    *,
    since_id: str | None = None,
    limit: int = 500,
    business_id: str | None = None,
) -> list[dict]:
    """Fetch timeline messages for one wa_id, formatted for web UI.

    `business_id` scopes the query when provided — required for
    multi-tenant callers so a valid API key for tenant A can't read
    tenant B's transcripts (P3.5a #4). `None` preserves pre-P3.5a
    unscoped behavior for legacy single-tenant demo callers; all new
    callers must pass it.

    The anchor lookup (`since_id` -> created_at) also respects the
    filter — a since_id rowid on tenant B is invisible to tenant A's
    pagination.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        anchor_created_at = None
        if since_id:
            anchor_stmt = (
                select(MessageLog.created_at)
                .where(
                    MessageLog.id == since_id,
                    MessageLog.wa_id == wa_id,
                )
            )
            if business_id is not None:
                anchor_stmt = anchor_stmt.where(
                    MessageLog.business_id == business_id
                )
            anchor_stmt = anchor_stmt.limit(1)
            anchor_created_at = (await session.execute(anchor_stmt)).scalar_one_or_none()
            if anchor_created_at is None:
                return []

        stmt = select(MessageLog).where(MessageLog.wa_id == wa_id)
        if business_id is not None:
            stmt = stmt.where(MessageLog.business_id == business_id)
        if anchor_created_at is not None:
            stmt = stmt.where(MessageLog.created_at > anchor_created_at)
        stmt = stmt.order_by(MessageLog.created_at.asc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    messages = [
        {
            "id": row.id,
            "role": row.role,
            "text": row.text,
            "timestamp": row.created_at.isoformat(),
            "images": row.images or [],
            "is_escalation": bool((row.meta or {}).get("is_escalation", False)),
            "escalation_reason": (row.meta or {}).get("escalation_reason", ""),
            "msg_type": row.msg_type,
        }
        for row in rows
    ]

    return messages


async def list_conversations_from_logs(
    limit: int = 200,
    *,
    business_id: str | None = None,
) -> list[dict]:
    """Build owner-panel conversation summaries from message logs.

    `business_id` scopes the query when provided — owner panels for
    tenant B must not see tenant A's conversations (P3.5a #4).
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(MessageLog)
            .order_by(MessageLog.created_at.desc())
            .limit(max(limit * 20, 500))
        )
        if business_id is not None:
            stmt = stmt.where(MessageLog.business_id == business_id)
        rows = (await session.execute(stmt)).scalars().all()

    by_wa_id: "OrderedDict[str, MessageLog]" = OrderedDict()
    for row in rows:
        if row.wa_id not in by_wa_id:
            by_wa_id[row.wa_id] = row
        if len(by_wa_id) >= limit:
            break

    conversations: list[dict] = []
    for wa_id, last in by_wa_id.items():
        if await state.get_staff(wa_id):
            continue
        customer_name = f"Customer {wa_id[-4:]}" if len(wa_id) >= 4 else "Customer"
        conversations.append(
            {
                "customer_id": wa_id,
                "customer_name": customer_name,
                "last_message": last.text,
                "last_activity": last.created_at.isoformat(),
                "mode": "bot",
                "has_escalation": bool((last.meta or {}).get("is_escalation", False)),
            }
        )
    return conversations


async def delete_messages_for_wa_id(
    wa_id: str,
    *,
    business_id: str | None = None,
) -> int:
    """Delete all logged messages for one customer; return deleted row count.

    `business_id` scopes the delete when provided — pre-P3.5a a valid
    API key for tenant A could POST /api/reset with a customer_id from
    tenant B and wipe B's transcripts (P3.5a #4). `None` preserves the
    legacy unscoped behavior for single-tenant demos only.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = delete(MessageLog).where(MessageLog.wa_id == wa_id)
        if business_id is not None:
            stmt = stmt.where(MessageLog.business_id == business_id)
        result = await session.execute(stmt)
        await session.commit()
        return int(result.rowcount or 0)
