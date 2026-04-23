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
async def test_assign_lead_autocreates_conversation_for_pre_assignment() -> None:
    """Owner pre-assigns a customer before they've messaged — tool creates
    the conversation row so the assignment sticks, rather than dead-ending."""
    owner = "919000000102"
    customer_wa = "919000000202"
    await state.add_staff(
        wa_id=owner, name="Alice",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
    )
    await state.get_or_create_customer(customer_wa, name="Mohan")
    # No conversation row yet.
    assert await state.get_conversation(customer_wa) is None

    raw = await tool_assign_lead(customer_wa, owner)
    result = json.loads(raw)
    assert result["success"] is True, result

    conv = await state.get_conversation(customer_wa)
    assert conv is not None
    assert conv.assigned_to == owner


@pytest.mark.asyncio
async def test_state_assign_conversation_returns_false_when_missing() -> None:
    """Direct state API contract: returns False when there's no conversation."""
    ok = await state.assign_conversation("919000000999", "919000000199")
    assert ok is False
