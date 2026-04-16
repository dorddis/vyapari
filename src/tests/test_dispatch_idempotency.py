"""Dispatch idempotency tests from TESTING.md webhook retry scenarios."""

import pytest

import router
from models import ConversationState, RoutingAction, RoutingDecision
from tests.conftest import make_customer_msg


@pytest.mark.asyncio
async def test_dispatch_deduplicates_duplicate_message_id(monkeypatch):
    calls = 0

    async def fake_route_message(msg):
        return RoutingDecision(
            role="customer",
            action=RoutingAction.CUSTOMER_AGENT,
            conversation_state=ConversationState.ACTIVE,
        )

    async def fake_handle_customer_agent(msg, conv_state):
        nonlocal calls
        calls += 1
        return "stub-reply"

    monkeypatch.setattr(router, "route_message", fake_route_message)
    monkeypatch.setattr(router, "handle_customer_agent", fake_handle_customer_agent)

    msg = make_customer_msg(
        wa_id="919700000001",
        text="Hi",
        msg_id="wamid.duplicate_001",
    )

    first = await router.dispatch(msg)
    second = await router.dispatch(msg)

    assert first == "stub-reply"
    assert second is None
    assert calls == 1
