"""Escalation workflow tests beyond pure detection."""

from types import SimpleNamespace

import pytest

import state
from models import ConversationState, LeadStatus
from services.escalation import trigger_escalation
from services.relay import close_relay, open_relay
from tests.conftest import seed_customer, seed_owner, seed_sdr
from vyapari_agents.customer import run_customer_agent


@pytest.mark.asyncio
async def test_trigger_escalation_routes_to_assigned_sdr():
    await seed_owner()
    await seed_sdr(wa_id="919111222333", name="Raj")
    await seed_customer()

    conversation = await state.get_conversation("919876543210")
    conversation.assigned_to = "919111222333"

    success, message, target_staff = await trigger_escalation(
        "919876543210",
        "price negotiation",
        "Customer wants final price on Nexon",
    )

    notifications = await state.get_staff_escalation_notifications("919111222333")
    owner_notifications = await state.get_staff_escalation_notifications("919999888777")
    escalations = await state.get_escalations(conversation.id)

    assert success is True
    assert "queued" in message.lower()
    assert target_staff == "919111222333"
    assert len(escalations) == 1
    assert len(notifications) == 1
    assert notifications[0].summary == "Customer wants final price on Nexon"
    assert owner_notifications == []
    assert await state.get_conversation_state("919876543210") == ConversationState.ESCALATED


@pytest.mark.asyncio
async def test_trigger_escalation_defaults_to_owner_when_unassigned():
    await seed_owner()
    await seed_customer(lead_status=LeadStatus.HOT)

    conversation = await state.get_conversation("919876543210")
    success, _, target_staff = await trigger_escalation(
        "919876543210",
        "test drive intent",
        "Customer wants to visit tomorrow",
    )

    notifications = await state.get_staff_escalation_notifications("919999888777")
    escalations = await state.get_escalations(conversation.id)

    assert success is True
    assert target_staff == "919999888777"
    assert len(escalations) == 1
    assert len(notifications) == 1
    assert notifications[0].lead_status == "hot"


@pytest.mark.asyncio
async def test_customer_agent_fallback_escalation_persists_record_and_notification(monkeypatch):
    await seed_owner()
    await seed_customer()

    async def fake_run(*args, **kwargs):
        return SimpleNamespace(final_output="Let me connect you with our team for pricing.")

    monkeypatch.setattr("vyapari_agents.customer.Runner.run", fake_run)

    reply = await run_customer_agent("919876543210", "Best price kya hai?")
    conversation = await state.get_conversation("919876543210")
    escalations = await state.get_escalations(conversation.id)
    notifications = await state.get_staff_escalation_notifications("919999888777")

    assert "connect you with our team" in reply
    assert await state.get_conversation_state("919876543210") == ConversationState.ESCALATED
    assert len(escalations) == 1
    assert len(notifications) == 1
    assert "pricing" in notifications[0].summary.lower()


@pytest.mark.asyncio
async def test_close_relay_surfaces_queued_escalations():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil")
    await seed_customer(wa_id="919876543211", name="Priya Shah", lead_status=LeadStatus.HOT)

    await open_relay("919999888777", "919876543210")
    success, _, _ = await trigger_escalation(
        "919876543211",
        "price negotiation",
        "Priya asked for final price on Brezza",
    )

    success_close, message = await close_relay("919999888777")
    remaining_notifications = await state.get_staff_escalation_notifications("919999888777")

    assert success is True
    assert success_close is True
    assert "WHILE YOU WERE CHATTING:" in message
    assert "Priya Shah" in message
    assert "final price on Brezza" in message
    assert remaining_notifications == []
