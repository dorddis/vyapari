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
) -> str:
    """Persist one message row and return generated DB id."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = MessageLog(
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
        meta={
            "sender_name": msg.sender_name or "",
            "button_reply_id": msg.button_reply_id or "",
            "list_reply_id": msg.list_reply_id or "",
        },
    )


async def fetch_messages_for_wa_id(
    wa_id: str,
    *,
    since_id: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Fetch timeline messages for one wa_id, formatted for web UI."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(MessageLog)
            .where(MessageLog.wa_id == wa_id)
            .order_by(MessageLog.created_at.asc())
            .limit(limit)
        )
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

    if not since_id:
        return messages

    found = False
    result: list[dict] = []
    for message in messages:
        if found:
            result.append(message)
        if message["id"] == since_id:
            found = True
    return result


async def list_conversations_from_logs(limit: int = 200) -> list[dict]:
    """Build owner-panel conversation summaries from message logs."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(MessageLog)
            .order_by(MessageLog.created_at.desc())
            .limit(max(limit * 20, 500))
        )
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


async def delete_messages_for_wa_id(wa_id: str) -> int:
    """Delete all logged messages for one customer and return deleted row count."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            delete(MessageLog).where(MessageLog.wa_id == wa_id)
        )
        await session.commit()
        return int(result.rowcount or 0)
