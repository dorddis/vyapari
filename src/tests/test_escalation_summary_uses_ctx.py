"""Escalation summary reflects cars mentioned THIS turn, not the DB snapshot."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import state
from catalogue import CATALOGUE


@pytest.mark.asyncio
async def test_escalation_summary_includes_this_turn_car(monkeypatch) -> None:
    """A car mentioned this turn + escalation triggered -> car appears
    in escalation_summary's 'Car interest' line.

    Pre-fix the summary read customer.interested_cars (the DB snapshot
    taken at turn start, before auto-track appended the mentioned car),
    so the staff notification said 'browsing' even when the customer
    had clearly asked about a specific model.
    """
    from vyapari_agents.customer import run_customer_agent

    # Seed a customer fresh — no prior cars tracked.
    wa = "919000000501"
    await state.get_or_create_customer(wa, name="A")

    # Pick a model that exists in the catalogue.
    sample_model = next(
        car["model"] for car in CATALOGUE["cars"] if not car.get("sold")
    )

    # Stub the Runner so we don't hit OpenAI. The reply references the car.
    fake_result = type("_R", (), {
        "final_output": f"We have the {sample_model} available!",
    })()

    async def _fake_run(**kw):
        return fake_result

    # Force escalation.
    async def _fake_detect(_msg, _reply):
        return True, "customer explicitly asked for human"

    monkeypatch.setattr("vyapari_agents.customer.Runner.run", _fake_run)
    monkeypatch.setattr(
        "vyapari_agents.customer.detect_escalation", _fake_detect,
    )

    response = await run_customer_agent(
        wa, f"I want the {sample_model}", business_id="demo-sharma-motors",
    )

    assert response.is_escalation is True
    assert sample_model in response.escalation_summary, (
        f"Car {sample_model!r} should appear in escalation summary "
        f"but got: {response.escalation_summary!r}"
    )
    assert "browsing" not in response.escalation_summary
