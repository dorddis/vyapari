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


async def _async_return(value):
    return value
