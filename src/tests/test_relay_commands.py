"""Relay command behavior tests."""

import pytest

import state
from models import LeadStatus, MessageRole
from router import handle_relay_command
from tests.conftest import make_staff_msg, seed_customer, seed_owner


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
