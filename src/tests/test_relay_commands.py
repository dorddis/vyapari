"""Relay command behavior tests."""

import pytest

import state
from models import LeadStatus, MessageRole, RoutingAction
from router import handle_relay_command, route_message
from tests.conftest import make_staff_msg, seed_customer, seed_owner
from vyapari_agents.owner import run_owner_agent
from vyapari_agents.tools.relay import tool_open_session


@pytest.mark.asyncio
async def test_relay_number_returns_active_customer_number():
    await seed_owner()
    await seed_customer()
    await state.create_relay_session("919999888777", "919876543210")

    msg = make_staff_msg(wa_id="919999888777", text="/number")
    reply = await handle_relay_command(msg, "919876543210")

    assert "Ramesh Patil" in reply
    assert "+919876543210" in reply


@pytest.mark.asyncio
async def test_relay_status_returns_customer_state_and_message_count():
    await seed_owner()
    await seed_customer(lead_status=LeadStatus.HOT)
    conv = await state.get_or_create_conversation("919876543210")
    await state.add_message(conv.id, MessageRole.CUSTOMER, "Best price kya hai?")
    await state.create_relay_session("919999888777", "919876543210")

    msg = make_staff_msg(wa_id="919999888777", text="/status")
    reply = await handle_relay_command(msg, "919876543210")

    assert "Lead status: hot" in reply
    assert "Total messages: 1" in reply
    assert "Best price kya hai?" in reply


@pytest.mark.asyncio
async def test_relay_summary_regenerates_context():
    await seed_owner()
    await seed_customer()
    conv = await state.get_or_create_conversation("919876543210")
    await state.add_message(conv.id, MessageRole.CUSTOMER, "Kal aake dekh sakta hu?")
    await state.add_message(conv.id, MessageRole.AGENT, "Bilkul, 5 baje aa jaiye.")
    await state.create_relay_session("919999888777", "919876543210")

    msg = make_staff_msg(wa_id="919999888777", text="/summary")
    reply = await handle_relay_command(msg, "919876543210")

    assert "--- CONVERSATION SUMMARY ---" in reply
    assert "Kal aake dekh sakta hu?" in reply
    assert "Bilkul, 5 baje aa jaiye." in reply


@pytest.mark.asyncio
async def test_relay_switch_moves_to_unique_match():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil")
    await seed_customer(wa_id="919876543211", name="Priya Shah")
    await state.create_relay_session("919999888777", "919876543210")

    msg = make_staff_msg(wa_id="919999888777", text="/switch Priya")
    reply = await handle_relay_command(msg, "919876543210")
    active = await state.get_active_relay_for_staff("919999888777")

    assert "Session with Ramesh Patil closed" in reply
    assert "Session with Priya Shah started" in reply
    assert active is not None
    assert active.customer_wa_id == "919876543211"


@pytest.mark.asyncio
async def test_relay_switch_keeps_current_session_when_query_is_ambiguous():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil")
    await seed_customer(wa_id="919876543211", name="Priya Shah")
    await seed_customer(wa_id="919876543212", name="Priyansh Mehta")
    await state.create_relay_session("919999888777", "919876543210")

    msg = make_staff_msg(wa_id="919999888777", text="/switch Pri")
    reply = await handle_relay_command(msg, "919876543210")
    active = await state.get_active_relay_for_staff("919999888777")

    assert "Multiple matches for 'Pri'" in reply
    assert "Current session with Ramesh Patil is still active" in reply
    assert active is not None
    assert active.customer_wa_id == "919876543210"


@pytest.mark.asyncio
async def test_relay_note_saves_internal_note_without_affecting_session():
    await seed_owner()
    await seed_customer()
    await state.create_relay_session("919999888777", "919876543210")
    conversation = await state.get_conversation("919876543210")

    msg = make_staff_msg(wa_id="919999888777", text="/note Customer prefers white color")
    reply = await handle_relay_command(msg, "919876543210")
    notes = await state.get_internal_notes(conversation.id)
    active = await state.get_active_relay_for_staff("919999888777")

    assert reply == "Saved internal note for Ramesh Patil."
    assert len(notes) == 1
    assert notes[0].content == "Customer prefers white color"
    assert notes[0].note_type == "manual"
    assert active is not None


@pytest.mark.asyncio
async def test_relay_wrap_saves_compact_session_snapshot():
    await seed_owner()
    await seed_customer()
    conversation = await state.get_or_create_conversation("919876543210")
    await state.add_message(conversation.id, MessageRole.CUSTOMER, "Kal final price batana.")
    await state.add_message(conversation.id, MessageRole.AGENT, "Team se confirm karke batata hu.")
    await state.create_relay_session("919999888777", "919876543210")

    note_msg = make_staff_msg(wa_id="919999888777", text="/note Strong buyer, follow up tonight")
    await handle_relay_command(note_msg, "919876543210")

    wrap_msg = make_staff_msg(wa_id="919999888777", text="/wrap")
    reply = await handle_relay_command(wrap_msg, "919876543210")
    notes = await state.get_internal_notes(conversation.id)

    assert reply == "Saved session wrap for Ramesh Patil."
    assert len(notes) == 2
    assert notes[-1].note_type == "wrap"
    assert "CONVERSATION SUMMARY" in notes[-1].content
    assert "Strong buyer, follow up tonight" in notes[-1].content


@pytest.mark.asyncio
async def test_owner_number_reply_resolves_pending_open_session_without_llm(monkeypatch):
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil")
    await seed_customer(wa_id="919876543211", name="Ramesh Sharma")

    response = await tool_open_session("919999888777", "Ramesh")
    pending = await state.get_pending_relay_selection("919999888777")

    async def should_not_run(*args, **kwargs):
        raise AssertionError("LLM runner should not be called while resolving relay selection")

    monkeypatch.setattr("vyapari_agents.owner.Runner.run", should_not_run)

    reply = await run_owner_agent("919999888777", "2")
    active = await state.get_active_relay_for_staff("919999888777")
    selected_name = pending.options[1]["name"]
    selected_wa_id = pending.options[1]["wa_id"]

    assert "Reply with the number to connect" in response
    assert pending is not None
    assert f"Session with {selected_name} started" in reply
    assert active is not None
    assert active.customer_wa_id == selected_wa_id


@pytest.mark.asyncio
async def test_pending_switch_selection_routes_number_as_relay_command():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil")
    await seed_customer(wa_id="919876543211", name="Priya Shah")
    await seed_customer(wa_id="919876543212", name="Priyansh Mehta")
    await state.create_relay_session("919999888777", "919876543210")

    switch_msg = make_staff_msg(wa_id="919999888777", text="/switch Pri")
    await handle_relay_command(switch_msg, "919876543210")

    numeric_msg = make_staff_msg(wa_id="919999888777", text="1")
    decision = await route_message(numeric_msg)

    assert decision.action == RoutingAction.RELAY_COMMAND


@pytest.mark.asyncio
async def test_pending_switch_selection_number_opens_selected_customer():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil")
    await seed_customer(wa_id="919876543211", name="Priya Shah")
    await seed_customer(wa_id="919876543212", name="Priyansh Mehta")
    await state.create_relay_session("919999888777", "919876543210")

    switch_msg = make_staff_msg(wa_id="919999888777", text="/switch Pri")
    await handle_relay_command(switch_msg, "919876543210")
    pending = await state.get_pending_relay_selection("919999888777")

    select_msg = make_staff_msg(wa_id="919999888777", text="2")
    reply = await handle_relay_command(select_msg, "919876543210")
    active = await state.get_active_relay_for_staff("919999888777")
    selected_name = pending.options[1]["name"]
    selected_wa_id = pending.options[1]["wa_id"]

    assert "Session with Ramesh Patil closed" in reply
    assert f"Session with {selected_name} started" in reply
    assert active is not None
    assert active.customer_wa_id == selected_wa_id
