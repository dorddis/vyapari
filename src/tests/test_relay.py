"""Relay session lifecycle tests — 9 scenarios."""

import pytest

import state
from models import ConversationState, MessageRole, RelaySessionStatus
from services.relay import (
    close_relay,
    forward_to_customer,
    forward_to_staff,
    get_session_context,
    open_relay,
)
from tests.conftest import seed_customer, seed_owner, seed_sdr


@pytest.mark.asyncio
async def test_open_relay_creates_session():
    await seed_owner()
    await seed_customer()
    session, msg = await open_relay("919999888777", "919876543210")
    assert session is not None
    assert session.status == RelaySessionStatus.ACTIVE
    assert "Session with Ramesh Patil started" in msg

    # Conversation state should be RELAY_ACTIVE
    conv_state = await state.get_conversation_state("919876543210")
    assert conv_state == ConversationState.RELAY_ACTIVE


@pytest.mark.asyncio
async def test_close_relay_restores_active_state():
    await seed_owner()
    await seed_customer()
    await open_relay("919999888777", "919876543210")

    success, msg = await close_relay("919999888777")
    assert success is True
    assert "closed" in msg.lower()

    conv_state = await state.get_conversation_state("919876543210")
    assert conv_state == ConversationState.ACTIVE


@pytest.mark.asyncio
async def test_cannot_open_two_relays_same_customer():
    await seed_owner()
    await seed_sdr(wa_id="919111222333")
    await seed_customer()

    session1, _ = await open_relay("919999888777", "919876543210")
    assert session1 is not None

    session2, msg = await open_relay("919111222333", "919876543210")
    assert session2 is None
    assert "already" in msg.lower()


@pytest.mark.asyncio
async def test_forward_to_customer_stores_message():
    await seed_owner()
    await seed_customer()
    await open_relay("919999888777", "919876543210")

    customer_wa_id, text = await forward_to_customer("919999888777", "8.75L final hai")
    assert customer_wa_id == "919876543210"
    assert text == "8.75L final hai"

    # Message should be stored in conversation
    conv = await state.get_conversation("919876543210")
    messages = await state.get_messages(conv.id)
    owner_msgs = [m for m in messages if m.role == MessageRole.OWNER]
    assert len(owner_msgs) == 1
    assert owner_msgs[0].content == "8.75L final hai"


@pytest.mark.asyncio
async def test_forward_to_customer_dedupes_rapid_identical_messages():
    await seed_owner()
    await seed_customer()
    await open_relay("919999888777", "919876543210")

    customer_wa_id, text = await forward_to_customer("919999888777", "8.75L final hai")
    assert customer_wa_id == "919876543210"
    assert text == "8.75L final hai"

    customer_wa_id_2, text_2 = await forward_to_customer("919999888777", "8.75L final hai")
    assert customer_wa_id_2 is None
    assert "duplicate" in text_2.lower()

    conv = await state.get_conversation("919876543210")
    messages = await state.get_messages(conv.id)
    owner_msgs = [m for m in messages if m.role == MessageRole.OWNER]
    assert len(owner_msgs) == 1


@pytest.mark.asyncio
async def test_forward_to_staff_prefixes_with_name():
    await seed_owner()
    await seed_customer()
    await open_relay("919999888777", "919876543210")

    staff_wa_id, text = await forward_to_staff(
        "919876543210", "Done, kal aata hu", "Ramesh Patil"
    )
    assert staff_wa_id == "919999888777"
    assert text == "[Ramesh Patil]: Done, kal aata hu"


@pytest.mark.asyncio
async def test_forward_to_customer_no_session():
    result, msg = await forward_to_customer("919999888777", "hello")
    assert result is None
    assert "no active" in msg.lower()


@pytest.mark.asyncio
async def test_session_context_includes_messages():
    await seed_owner()
    await seed_customer()
    conv = await state.get_or_create_conversation("919876543210")
    await state.add_message(conv.id, MessageRole.CUSTOMER, "Koi SUV hai?")
    await state.add_message(conv.id, MessageRole.AGENT, "Haan! Nexon, Brezza, Venue available hai.")

    context = await get_session_context("919876543210")
    assert "Ramesh Patil" in context
    assert "Koi SUV hai?" in context
    assert "Nexon" in context


@pytest.mark.asyncio
async def test_close_nonexistent_session():
    success, msg = await close_relay("919999888777")
    assert success is False
    assert "no active" in msg.lower()
