"""Assignment actually writes to the DB."""

from __future__ import annotations

import json

import pytest

import state
from models import LeadStatus, StaffRole, StaffStatus
from vyapari_agents.tools.leads import tool_assign_lead


@pytest.mark.asyncio
async def test_assign_lead_persists_to_conversation() -> None:
    """tool_assign_lead -> DB conversation row actually has assigned_to set."""
    owner = "919000000101"
    customer_wa = "919000000201"
    await state.add_staff(
        wa_id=owner, name="Alice",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
    )
    await state.get_or_create_customer(customer_wa, name="Ramesh")
    await state.update_lead_status(customer_wa, LeadStatus.WARM)
    conv = await state.get_or_create_conversation(customer_wa)
    assert conv.assigned_to is None

    raw = await tool_assign_lead(customer_wa, owner)
    result = json.loads(raw)
    assert result["success"] is True, result

    conv_after = await state.get_conversation(customer_wa)
    assert conv_after.assigned_to == owner


@pytest.mark.asyncio
async def test_assign_lead_fails_cleanly_without_conversation() -> None:
    """Missing conversation -> tool returns success=False with a message."""
    owner = "919000000102"
    await state.add_staff(
        wa_id=owner, name="Alice",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
    )
    # Customer exists but no conversation row yet.
    await state.get_or_create_customer("919000000202", name="Mohan")

    raw = await tool_assign_lead("919000000202", owner)
    result = json.loads(raw)
    assert result["success"] is False
    assert "No conversation" in result["message"]


@pytest.mark.asyncio
async def test_state_assign_conversation_returns_false_when_missing() -> None:
    """Direct state API contract: returns False when there's no conversation."""
    ok = await state.assign_conversation("919000000999", "919000000199")
    assert ok is False
