"""Owner onboarding / setup flow tests."""

import pytest

import state
from catalogue import BUSINESS
from services.owner_setup import handle_owner_setup_message, should_handle_owner_setup
from tests.conftest import seed_owner


@pytest.mark.asyncio
async def test_setup_starts_and_asks_for_business_name():
    await seed_owner()

    reply = await handle_owner_setup_message("919999888777", "/setup")
    flow = await state.get_owner_setup("919999888777")

    assert flow is not None
    assert flow.active is True
    assert flow.current_step == "business_name"
    assert "business name" in reply.lower()


@pytest.mark.asyncio
async def test_setup_extracts_multiple_fields_and_moves_to_next_missing_step():
    await seed_owner()
    await handle_owner_setup_message("919999888777", "/setup")

    reply = await handle_owner_setup_message(
        "919999888777",
        "Sharma Motors naam hai, Mumbai se hu",
    )
    flow = await state.get_owner_setup("919999888777")

    assert flow.collected["business_name"] == "Sharma Motors"
    assert flow.collected["city"] == "Mumbai"
    assert flow.current_step == "business_type"
    assert "type" in reply.lower()


@pytest.mark.asyncio
async def test_setup_resume_keeps_progress_and_prompts_next_missing_field():
    await seed_owner()
    await handle_owner_setup_message("919999888777", "/setup")
    await handle_owner_setup_message(
        "919999888777",
        "Sharma Motors naam hai, Mumbai se hu",
    )

    reply = await handle_owner_setup_message(
        "919999888777",
        "Jahan se chhoda tha wahi se continue karo",
    )
    flow = await state.get_owner_setup("919999888777")

    assert flow.collected["business_name"] == "Sharma Motors"
    assert flow.collected["city"] == "Mumbai"
    assert flow.current_step == "business_type"
    assert "type" in reply.lower()


@pytest.mark.asyncio
async def test_setup_completion_updates_runtime_business_profile_and_finishes():
    await seed_owner()

    await handle_owner_setup_message("919999888777", "/setup")
    await handle_owner_setup_message(
        "919999888777",
        "Sharma Motors naam hai, Mumbai se hu",
    )
    await handle_owner_setup_message(
        "919999888777",
        "Used car dealer hu",
    )
    await handle_owner_setup_message(
        "919999888777",
        "+91 9988776655",
    )
    await handle_owner_setup_message(
        "919999888777",
        "Hey! Welcome to Sharma Motors. Budget batao aur main best options nikaalta hoon.",
    )
    reply = await handle_owner_setup_message(
        "919999888777",
        "haan preset faqs on kar do",
    )

    flow = await state.get_owner_setup("919999888777")

    assert flow is not None
    assert flow.active is False
    assert flow.completed_at is not None
    assert BUSINESS["business_name"] == "Sharma Motors"
    assert BUSINESS["type"] == "Used Car Dealer"
    assert BUSINESS["location"]["city"] == "Mumbai"
    assert BUSINESS["contact"]["phone_primary"] == "+919988776655"
    assert BUSINESS["greeting_message"].startswith("Hey! Welcome to Sharma Motors.")
    assert BUSINESS["settings"]["dealer_faq_presets_enabled"] is True
    assert "your bot is live" in reply.lower()
    assert "inventory" in reply.lower()
    assert "http://localhost:8000/" in reply


@pytest.mark.asyncio
async def test_only_setup_messages_or_active_flow_are_intercepted():
    await seed_owner()

    assert await should_handle_owner_setup("919999888777", "/setup") is True
    assert await should_handle_owner_setup("919999888777", "kitne leads aaye?") is False

    await handle_owner_setup_message("919999888777", "/setup")
    assert await should_handle_owner_setup("919999888777", "kitne leads aaye?") is True
