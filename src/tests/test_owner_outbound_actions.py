"""Owner action side-effect tests for sold/reserved/broadcast/follow-up flows."""

from __future__ import annotations

from copy import deepcopy

import pytest

import state
from catalogue import CATALOGUE, get_car_detail
from channels.web_clone.adapter import get_pending_messages
from models import LeadStatus, MessageRole
from tests.conftest import seed_customer, seed_owner
from vyapari_agents.owner import request_owner_confirmation, run_owner_agent


@pytest.fixture(autouse=True)
def restore_catalogue_snapshot():
    snapshot = deepcopy(CATALOGUE["cars"])
    total_cars = CATALOGUE["total_cars"]
    yield
    CATALOGUE["cars"].clear()
    CATALOGUE["cars"].extend(snapshot)
    CATALOGUE["total_cars"] = total_cars


async def _conversation_messages(customer_wa_id: str) -> list[str]:
    conversation = await state.get_conversation(customer_wa_id)
    messages = await state.get_messages(conversation.id)
    return [message.content for message in messages]


@pytest.mark.asyncio
async def test_confirmed_mark_sold_notifies_interested_customers_and_logs_messages():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil", lead_status=LeadStatus.WARM)
    await seed_customer(wa_id="919876543211", name="Priya Shah", lead_status=LeadStatus.HOT)
    await seed_customer(wa_id="919876543212", name="Aman Jain", lead_status=LeadStatus.WARM)

    customer_a = await state.get_customer("919876543210")
    customer_b = await state.get_customer("919876543211")
    customer_c = await state.get_customer("919876543212")
    customer_a.interested_cars = ["Hyundai Creta"]
    customer_b.interested_cars = ["2021 Hyundai Creta SX"]
    customer_c.interested_cars = ["Tata Nexon"]

    creta = get_car_detail(11)
    replacement = get_car_detail(15)
    creta["sold"] = False
    creta.pop("reserved_by", None)
    replacement["sold"] = False
    replacement.pop("reserved_by", None)

    await request_owner_confirmation("919999888777", "mark_sold", {"item_id": 11})
    reply = await run_owner_agent("919999888777", "haan")

    outbound_a = get_pending_messages("919876543210")
    outbound_b = get_pending_messages("919876543211")
    outbound_c = get_pending_messages("919876543212")

    assert creta["sold"] is True
    assert "Marked 2021 Hyundai Creta SX as sold." in reply
    assert "Notified 2 interested customer(s)." in reply
    assert "Suggested 2024 Hyundai Creta SX(O) as the closest alternative." in reply
    assert len(outbound_a) == 1
    assert len(outbound_b) == 1
    assert outbound_c == []
    assert "2021 Hyundai Creta SX is now sold" in outbound_a[0]["content"]["body"]
    assert "2024 Hyundai Creta SX(O)" in outbound_a[0]["content"]["body"]
    assert "2021 Hyundai Creta SX is now sold" in outbound_b[0]["content"]["body"]

    messages_a = await _conversation_messages("919876543210")
    messages_b = await _conversation_messages("919876543211")
    assert any("2021 Hyundai Creta SX is now sold" in message for message in messages_a)
    assert any("2021 Hyundai Creta SX is now sold" in message for message in messages_b)


@pytest.mark.asyncio
async def test_confirmed_mark_reserved_notifies_other_interested_customers_only():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil", lead_status=LeadStatus.HOT)
    await seed_customer(wa_id="919876543211", name="Priya Shah", lead_status=LeadStatus.WARM)
    await seed_customer(wa_id="919876543212", name="Aman Jain", lead_status=LeadStatus.WARM)

    reserving_customer = await state.get_customer("919876543210")
    other_interested_customer = await state.get_customer("919876543211")
    unrelated_customer = await state.get_customer("919876543212")
    reserving_customer.interested_cars = ["Tata Nexon"]
    other_interested_customer.interested_cars = ["2023 Tata Nexon XZ+ (S)"]
    unrelated_customer.interested_cars = ["Hyundai Creta"]

    nexon = get_car_detail(12)
    nexon["sold"] = False
    nexon.pop("reserved_by", None)

    await request_owner_confirmation(
        "919999888777",
        "mark_reserved",
        {"item_id": 12, "customer_name": "Ramesh Patil", "token_amount": 25000},
    )
    reply = await run_owner_agent("919999888777", "yes")

    outbound_reserved_customer = get_pending_messages("919876543210")
    outbound_other_customer = get_pending_messages("919876543211")
    outbound_unrelated_customer = get_pending_messages("919876543212")

    assert nexon["reserved_by"] == "Ramesh Patil"
    assert "reserved for Ramesh Patil." in reply
    assert "Notified 1 interested customer(s)." in reply
    assert outbound_reserved_customer == []
    assert len(outbound_other_customer) == 1
    assert outbound_unrelated_customer == []
    assert "currently on hold for another buyer" in outbound_other_customer[0]["content"]["body"]
    assert "2023 Tata Nexon XZ+ (S)" in outbound_other_customer[0]["content"]["body"]


@pytest.mark.asyncio
async def test_confirmed_broadcast_sends_to_matching_customers_and_logs_history():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil", lead_status=LeadStatus.WARM)
    await seed_customer(wa_id="919876543211", name="Priya Shah", lead_status=LeadStatus.HOT)
    await seed_customer(wa_id="919876543212", name="Aman Jain", lead_status=LeadStatus.NEW)

    await request_owner_confirmation(
        "919999888777",
        "broadcast_message",
        {"message_text": "Fresh stock just landed. Reply if you want first access.", "filter_status": "warm"},
    )
    reply = await run_owner_agent("919999888777", "confirm")

    outbound_warm = get_pending_messages("919876543210")
    outbound_hot = get_pending_messages("919876543211")
    outbound_new = get_pending_messages("919876543212")

    assert "Broadcast sent to 2 customer(s)." in reply
    assert len(outbound_warm) == 1
    assert len(outbound_hot) == 1
    assert outbound_new == []
    assert outbound_warm[0]["content"]["body"] == "Fresh stock just landed. Reply if you want first access."
    assert outbound_hot[0]["content"]["body"] == "Fresh stock just landed. Reply if you want first access."

    warm_messages = await _conversation_messages("919876543210")
    hot_messages = await _conversation_messages("919876543211")
    assert warm_messages[-1] == "Fresh stock just landed. Reply if you want first access."
    assert hot_messages[-1] == "Fresh stock just landed. Reply if you want first access."


@pytest.mark.asyncio
async def test_confirmed_batch_followup_sends_personalized_messages():
    await seed_owner()
    await seed_customer(wa_id="919876543210", name="Ramesh Patil", lead_status=LeadStatus.WARM)
    await seed_customer(wa_id="919876543211", name="Priya Shah", lead_status=LeadStatus.HOT)
    await seed_customer(wa_id="919876543212", name="Aman Jain", lead_status=LeadStatus.NEW)

    customer_a = await state.get_customer("919876543210")
    customer_b = await state.get_customer("919876543211")
    customer_c = await state.get_customer("919876543212")
    customer_a.interested_cars = ["Hyundai Creta"]
    customer_b.interested_cars = ["Tata Nexon"]
    customer_c.interested_cars = ["Maruti Brezza"]

    conversation_a = await state.get_conversation("919876543210")
    conversation_b = await state.get_conversation("919876543211")
    await state.add_message(conversation_a.id, MessageRole.CUSTOMER, "Best price on the Creta?")
    await state.add_message(conversation_b.id, MessageRole.CUSTOMER, "Is Nexon still available?")

    await request_owner_confirmation(
        "919999888777",
        "batch_followup",
        {"date": "yesterday", "status_filter": "warm,hot"},
    )
    reply = await run_owner_agent("919999888777", "okay")

    outbound_warm = get_pending_messages("919876543210")
    outbound_hot = get_pending_messages("919876543211")
    outbound_new = get_pending_messages("919876543212")

    assert "Sent 2 follow-up(s)." in reply
    assert len(outbound_warm) == 1
    assert len(outbound_hot) == 1
    assert outbound_new == []
    assert "Hi Ramesh Patil" in outbound_warm[0]["content"]["body"]
    assert "Hyundai Creta" in outbound_warm[0]["content"]["body"]
    assert "Hi Priya Shah" in outbound_hot[0]["content"]["body"]
    assert "Tata Nexon" in outbound_hot[0]["content"]["body"]
