"""relay_expiry_loop survives per-session send failures."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import state
from models import ConversationState
from models import StaffRole, StaffStatus


@pytest.mark.asyncio
async def test_one_failing_tenant_does_not_abort_others(monkeypatch) -> None:
    """Two expired sessions, first send_text fails — second still fires."""
    from channels import base as channel_base
    import main

    # Two staff on different tenants, each with a customer + expired session.
    biz_a = "expiry-biz-a"
    biz_b = "expiry-biz-b"

    from database import get_session_factory
    from sqlalchemy import delete as _delete
    from db_models import Business, Customer, RelaySession, Staff, Conversation

    staff_a = "919000000801"
    staff_b = "919000000802"
    cust_a = "919000000811"
    cust_b = "919000000812"

    async with get_session_factory()() as s:
        await s.execute(_delete(RelaySession).where(RelaySession.staff_wa_id.in_(
            [staff_a, staff_b]
        )))
        await s.execute(_delete(Conversation).where(Conversation.customer_wa_id.in_(
            [cust_a, cust_b]
        )))
        await s.execute(_delete(Customer).where(Customer.wa_id.in_([cust_a, cust_b])))
        await s.execute(_delete(Staff).where(Staff.wa_id.in_([staff_a, staff_b])))
        await s.execute(_delete(Business).where(Business.id.in_([biz_a, biz_b])))
        s.add(Business(id=biz_a, name="A", type="", vertical="",
                       owner_phone=staff_a))
        s.add(Business(id=biz_b, name="B", type="", vertical="",
                       owner_phone=staff_b))
        await s.commit()

    await state.add_staff(
        wa_id=staff_a, name="StaffA",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE, business_id=biz_a,
    )
    await state.add_staff(
        wa_id=staff_b, name="StaffB",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE, business_id=biz_b,
    )
    await state.get_or_create_customer(cust_a, name="X", business_id=biz_a)
    await state.get_or_create_customer(cust_b, name="Y", business_id=biz_b)
    await state.get_or_create_conversation(cust_a, business_id=biz_a)
    await state.get_or_create_conversation(cust_b, business_id=biz_b)

    # Create relay sessions and force both to be expired-ready.
    session_a = await state.create_relay_session(staff_a, cust_a)
    session_b = await state.create_relay_session(staff_b, cust_b)
    assert session_a and session_b

    # Fake expired-sessions return + per-tenant channel behavior.
    async def fake_check_expired():
        return [session_a, session_b]

    sent: list[tuple[str, str, str]] = []

    class _AdapterA:
        business_id = biz_a
        async def send_text(self, to, text):
            raise RuntimeError("tenant A credentials invalid")

    class _AdapterB:
        business_id = biz_b
        async def send_text(self, to, text):
            sent.append((biz_b, to, text))

    async def fake_get_tenant_channel(business_id: str):
        return _AdapterA() if business_id == biz_a else _AdapterB()

    monkeypatch.setattr(
        "state.check_expired_relay_sessions", fake_check_expired,
    )
    monkeypatch.setattr(
        "channels.base.get_tenant_channel", fake_get_tenant_channel,
    )

    # Run ONE iteration of the loop body manually (the real loop is an
    # infinite while; we don't want to sleep).
    import asyncio as _asyncio
    original_sleep = _asyncio.sleep

    async def one_shot_sleep(_d):
        # Cancel ourselves to exit after one iteration.
        raise _asyncio.CancelledError()

    monkeypatch.setattr("main.asyncio.sleep", one_shot_sleep)

    try:
        await main.relay_expiry_loop()
    except _asyncio.CancelledError:
        pass

    # Tenant A's send_text raised; tenant B's fired successfully.
    assert any(s[0] == biz_b for s in sent), (
        "tenant B must still receive notifications after tenant A's failure"
    )
    # Cleanup
    async with get_session_factory()() as s:
        await s.execute(_delete(RelaySession))
        await s.execute(_delete(Conversation))
        await s.execute(_delete(Customer).where(Customer.wa_id.in_([cust_a, cust_b])))
        await s.execute(_delete(Staff).where(Staff.wa_id.in_([staff_a, staff_b])))
        await s.execute(_delete(Business).where(Business.id.in_([biz_a, biz_b])))
        await s.commit()
