"""Owner runtime behavior tests for confirmations and routing boundaries."""

from __future__ import annotations

from copy import deepcopy

import pytest

import state
from catalogue import CATALOGUE, get_car_detail
from models import LeadStatus
from router import dispatch
from tests.conftest import make_customer_msg, make_staff_msg, seed_customer, seed_owner, seed_sdr
from vyapari_agents.owner import request_owner_confirmation, run_owner_agent


@pytest.fixture(autouse=True)
def restore_catalogue_snapshot():
    snapshot = deepcopy(CATALOGUE["cars"])
    total_cars = CATALOGUE["total_cars"]
    yield
    CATALOGUE["cars"].clear()
    CATALOGUE["cars"].extend(snapshot)
    CATALOGUE["total_cars"] = total_cars


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action_name", "payload", "seed_fn", "expected_text"),
    [
        ("mark_sold", {"item_id": 1}, None, "Confirm sale update"),
        (
            "mark_reserved",
            {"item_id": 2, "customer_name": "Ramesh", "token_amount": 5000},
            None,
            "Confirm reservation",
        ),
        (
            "remove_staff",
            {"identifier": "919111222333"},
            "staff",
            "Confirm staff removal",
        ),
        (
            "broadcast_message",
            {"message_text": "Fresh stock aaya hai", "filter_status": "warm"},
            "customers",
            "Confirm broadcast to 2 customer(s)",
        ),
        (
            "batch_followup",
            {"date": "yesterday", "status_filter": "warm,hot"},
            "customers",
            "Confirm batch follow-up for 2 lead(s)",
        ),
    ],
)
async def test_request_owner_confirmation_stages_pending_action(
    action_name,
    payload,
    seed_fn,
    expected_text,
):
    await seed_owner()
    if seed_fn == "staff":
        await seed_sdr(name="Raj")
    if seed_fn == "customers":
        await seed_customer(wa_id="919876543210", name="Ramesh", lead_status=LeadStatus.WARM)
        await seed_customer(wa_id="919876543211", name="Priya", lead_status=LeadStatus.HOT)

    if action_name in {"mark_sold", "mark_reserved"}:
        car = get_car_detail(payload["item_id"])
        car["sold"] = False
        car.pop("reserved_by", None)

    reply = await request_owner_confirmation("919999888777", action_name, payload)
    pending = await state.get_pending_owner_action("919999888777")

    assert pending is not None
    assert pending.action_name == action_name
    assert expected_text in reply
    assert "Reply YES to confirm or NO to cancel." in reply


@pytest.mark.asyncio
async def test_run_owner_agent_confirms_pending_action_without_llm(monkeypatch):
    await seed_owner()
    car = get_car_detail(1)
    car["sold"] = False

    await request_owner_confirmation("919999888777", "mark_sold", {"item_id": 1})

    async def should_not_run(*args, **kwargs):
        raise AssertionError("LLM runner should not be called for a pending confirmation")

    monkeypatch.setattr("vyapari_agents.owner.Runner.run", should_not_run)

    reply = await run_owner_agent("919999888777", "haan")
    pending = await state.get_pending_owner_action("919999888777")

    assert "Marked" in reply
    assert pending is None
    assert get_car_detail(1)["sold"] is True


@pytest.mark.asyncio
async def test_run_owner_agent_cancels_pending_action_without_llm(monkeypatch):
    await seed_owner()
    car = get_car_detail(2)
    car["sold"] = False
    car.pop("reserved_by", None)

    await request_owner_confirmation(
        "919999888777",
        "mark_reserved",
        {"item_id": 2, "customer_name": "Ramesh", "token_amount": 5000},
    )

    async def should_not_run(*args, **kwargs):
        raise AssertionError("LLM runner should not be called when cancellation is pending")

    monkeypatch.setattr("vyapari_agents.owner.Runner.run", should_not_run)

    reply = await run_owner_agent("919999888777", "no")
    pending = await state.get_pending_owner_action("919999888777")

    assert "Cancelled." in reply
    assert pending is None
    assert get_car_detail(2).get("reserved_by") is None


@pytest.mark.asyncio
async def test_run_owner_agent_repeats_prompt_for_non_confirmation(monkeypatch):
    await seed_owner()
    await request_owner_confirmation("919999888777", "mark_sold", {"item_id": 1})

    async def should_not_run(*args, **kwargs):
        raise AssertionError("LLM runner should not be called while confirmation is still pending")

    monkeypatch.setattr("vyapari_agents.owner.Runner.run", should_not_run)

    reply = await run_owner_agent("919999888777", "what was the color again?")
    pending = await state.get_pending_owner_action("919999888777")

    assert "Pending action is still waiting." in reply
    assert "Reply YES to confirm or NO to cancel." in reply
    assert pending is not None


@pytest.mark.asyncio
async def test_dispatch_owner_message_does_not_create_customer_state(monkeypatch):
    await seed_owner()
    owner_msg = make_staff_msg(wa_id="919999888777", text="Aaj kitne leads aaye?")

    async def fake_handle_owner_agent(msg, staff_name):
        return "12 leads today."

    monkeypatch.setattr("router.handle_owner_agent", fake_handle_owner_agent)

    reply = await dispatch(owner_msg)

    assert reply == "12 leads today."
    assert await state.get_customer("919999888777") is None
    assert await state.get_conversation("919999888777") is None


@pytest.mark.asyncio
async def test_dispatch_customer_message_still_creates_customer_state(monkeypatch):
    customer_msg = make_customer_msg(wa_id="919876543210", text="Koi SUV hai?")

    async def fake_handle_customer_agent(msg, conv_state):
        return "Haan, kuch SUVs available hain."

    monkeypatch.setattr("router.handle_customer_agent", fake_handle_customer_agent)

    reply = await dispatch(customer_msg)

    assert reply == "Haan, kuch SUVs available hain."
    assert await state.get_customer("919876543210") is not None
    assert await state.get_conversation("919876543210") is not None
