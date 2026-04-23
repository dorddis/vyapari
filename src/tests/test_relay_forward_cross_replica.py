"""Relay forward dedup uses Postgres advisory lock (cross-replica)."""

from __future__ import annotations

import asyncio

import pytest

import state
from models import MessageRole, StaffRole, StaffStatus
from services.relay import forward_to_customer


@pytest.mark.asyncio
async def test_concurrent_duplicate_forwards_deduplicated() -> None:
    """Two concurrent identical forwards within the 2s window -> one stored message."""
    staff = "919000000901"
    customer = "919000000911"
    await state.add_staff(
        wa_id=staff, name="S",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
    )
    await state.get_or_create_customer(customer, name="C")
    await state.get_or_create_conversation(customer)
    session = await state.create_relay_session(staff, customer)
    assert session

    # Fire two identical forwards concurrently.
    r1, r2 = await asyncio.gather(
        forward_to_customer(staff, "hello there"),
        forward_to_customer(staff, "hello there"),
    )

    # Exactly one landed a customer message; the other was dedup'd.
    stored = await state.get_messages(session.conversation_id)
    staff_msgs = [m for m in stored if m.role == MessageRole.OWNER]
    assert len(staff_msgs) == 1, (
        f"Expected 1 stored OWNER message, got {len(staff_msgs)}: "
        f"{[m.content for m in staff_msgs]}"
    )


@pytest.mark.asyncio
async def test_forward_uses_advisory_lock_helper(monkeypatch) -> None:
    """forward_to_customer routes its dedup through state._pg_advisory_lock."""
    staff = "919000000902"
    customer = "919000000912"
    await state.add_staff(
        wa_id=staff, name="S",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
    )
    await state.get_or_create_customer(customer, name="C")
    await state.get_or_create_conversation(customer)
    session = await state.create_relay_session(staff, customer)
    assert session

    calls: list[str] = []
    import contextlib

    @contextlib.asynccontextmanager
    async def spy_lock(key):
        calls.append(key)
        yield

    monkeypatch.setattr("state._pg_advisory_lock", spy_lock)

    await forward_to_customer(staff, "x")
    assert len(calls) == 1
    assert calls[0].startswith("relay_fwd_")
