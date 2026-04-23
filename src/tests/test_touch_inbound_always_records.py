"""router.dispatch always stamps the 24h window, even when msg.business_id is empty."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import state
from models import IncomingMessage, MessageType


@pytest.mark.asyncio
async def test_dispatch_stamps_inbound_with_default_business_id(monkeypatch) -> None:
    """An IncomingMessage with empty business_id routes touch_inbound
    against default_business_id, not skipped."""
    import config
    from router import dispatch

    captured: list[tuple[str, str]] = []

    async def fake_touch_inbound(business_id, wa_id):
        captured.append((business_id, wa_id))

    monkeypatch.setattr(
        "services.outbound.touch_inbound", fake_touch_inbound,
    )
    # Stub the agent handlers so dispatch doesn't hit OpenAI.
    monkeypatch.setattr(
        "router.handle_customer_agent",
        lambda msg, conv_state: _async_return(""),
    )

    wa = "919000000401"
    await state.get_or_create_customer(wa, name="X")
    await state.get_or_create_conversation(wa)

    msg = IncomingMessage(
        wa_id=wa,
        text="hi",
        msg_id=f"wamid.touchtest_{datetime.now(timezone.utc).timestamp()}",
        msg_type=MessageType.TEXT,
        business_id="",
    )
    await dispatch(msg)

    assert captured, "touch_inbound was not called"
    biz_ids = {bid for bid, _ in captured}
    assert config.DEFAULT_BUSINESS_ID in biz_ids
    assert (config.DEFAULT_BUSINESS_ID, wa) in captured


@pytest.mark.asyncio
async def test_dispatch_uses_customer_business_id_over_empty_msg_business_id(
    monkeypatch,
) -> None:
    """If msg.business_id is empty but the customer already exists under
    tenant A, touch_inbound stamps tenant A's window — not the bootstrap
    default. This is the cross-tenant stamp-miss the logic review flagged."""
    from router import dispatch

    captured: list[tuple[str, str]] = []

    async def fake_touch_inbound(business_id, wa_id):
        captured.append((business_id, wa_id))

    monkeypatch.setattr(
        "services.outbound.touch_inbound", fake_touch_inbound,
    )
    monkeypatch.setattr(
        "router.handle_customer_agent",
        lambda msg, conv_state: _async_return(""),
    )

    tenant_a = "tenant-existing-a"
    async with __import__("database").get_session_factory()() as s:
        from sqlalchemy import delete as _delete
        from db_models import Business, Customer
        await s.execute(_delete(Customer).where(Customer.wa_id == "919000000402"))
        await s.execute(_delete(Business).where(Business.id == tenant_a))
        s.add(Business(id=tenant_a, name="A", type="", vertical="",
                       owner_phone="919100000001"))
        await s.commit()

    wa = "919000000402"
    await state.get_or_create_customer(wa, name="Y", business_id=tenant_a)
    await state.get_or_create_conversation(wa, business_id=tenant_a)

    msg = IncomingMessage(
        wa_id=wa,
        text="hi",
        msg_id=f"wamid.biz_touch_{datetime.now(timezone.utc).timestamp()}",
        msg_type=MessageType.TEXT,
        business_id="",
    )
    await dispatch(msg)

    assert (tenant_a, wa) in captured, (
        f"Expected stamp against tenant {tenant_a!r}, got {captured}"
    )


async def _async_return(value):
    return value
