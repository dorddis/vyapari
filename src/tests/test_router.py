"""Router dispatch tests — 10 scenarios from the design doc routing table."""

import pytest

import state
from models import ConversationState, RoutingAction, StaffRole, StaffStatus
from router import route_message
from tests.conftest import (
    make_customer_msg,
    make_staff_msg,
    seed_customer,
    seed_owner,
    seed_relay,
    seed_sdr,
)


@pytest.mark.asyncio
async def test_unknown_number_regular_message():
    """Unknown phone number with regular text -> customer_agent."""
    msg = make_customer_msg(wa_id="919000000001", text="Show me cars")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.CUSTOMER_AGENT
    assert decision.role == "customer"


@pytest.mark.asyncio
async def test_unknown_number_login_command():
    """Unknown phone number with /login -> auth_flow."""
    msg = make_customer_msg(wa_id="919000000002", text="/login")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.AUTH_FLOW


@pytest.mark.asyncio
async def test_known_owner_no_relay():
    """Known owner with no active relay -> owner_agent."""
    await seed_owner(wa_id="919999888777")
    msg = make_staff_msg(wa_id="919999888777", text="kitne leads aaye?")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.OWNER_AGENT
    assert decision.role == "owner"


@pytest.mark.asyncio
async def test_known_sdr_no_relay():
    """Known SDR with no active relay -> sdr_agent."""
    await seed_sdr(wa_id="919111222333")
    msg = make_staff_msg(wa_id="919111222333", text="show me leads")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.SDR_AGENT
    assert decision.role == "sdr"


@pytest.mark.asyncio
async def test_owner_relay_active_no_prefix():
    """Owner with active relay, message WITHOUT / prefix -> relay_forward to customer."""
    await seed_owner(wa_id="919999888777")
    await seed_relay(staff_wa_id="919999888777", customer_wa_id="919876543210")
    msg = make_staff_msg(wa_id="919999888777", text="8.75L final hai bhai")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.RELAY_FORWARD
    assert decision.target_wa_id == "919876543210"


@pytest.mark.asyncio
async def test_owner_relay_active_with_prefix():
    """Owner with active relay, message WITH / prefix -> relay_command."""
    await seed_owner(wa_id="919999888777")
    await seed_relay(staff_wa_id="919999888777", customer_wa_id="919876543210")
    msg = make_staff_msg(wa_id="919999888777", text="/done")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.RELAY_COMMAND
    assert decision.target_wa_id == "919876543210"


@pytest.mark.asyncio
async def test_customer_in_relay_active():
    """Customer whose conversation is RELAY_ACTIVE -> relay_forward to staff."""
    await seed_owner(wa_id="919999888777")
    await seed_relay(staff_wa_id="919999888777", customer_wa_id="919876543210")
    msg = make_customer_msg(wa_id="919876543210", text="Done, kal aata hu")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.RELAY_FORWARD
    assert decision.target_wa_id == "919999888777"
    assert decision.conversation_state == ConversationState.RELAY_ACTIVE


@pytest.mark.asyncio
async def test_customer_in_active_state():
    """Customer with ACTIVE conversation -> customer_agent."""
    await seed_customer(wa_id="919876543210")
    msg = make_customer_msg(wa_id="919876543210", text="Koi SUV hai?")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.CUSTOMER_AGENT
    assert decision.conversation_state == ConversationState.ACTIVE


@pytest.mark.asyncio
async def test_customer_in_escalated_state():
    """Customer with ESCALATED conversation -> customer_agent (still responds)."""
    await seed_customer(wa_id="919876543210")
    await state.set_conversation_state(
        "919876543210", ConversationState.ESCALATED, "price negotiation"
    )
    msg = make_customer_msg(wa_id="919876543210", text="Best price kya hai?")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.CUSTOMER_AGENT
    assert decision.conversation_state == ConversationState.ESCALATED


@pytest.mark.asyncio
async def test_removed_staff_treated_as_customer():
    """Staff member who was removed -> treated as customer."""
    await state.add_staff(
        wa_id="919555666777",
        name="Removed Guy",
        role=StaffRole.SDR,
        status=StaffStatus.REMOVED,
    )
    msg = make_staff_msg(wa_id="919555666777", text="show me leads")
    decision = await route_message(msg)
    assert decision.action == RoutingAction.CUSTOMER_AGENT
    assert decision.role == "customer"
