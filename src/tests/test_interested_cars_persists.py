"""Auto-tracked interested cars actually persist to the DB."""

from __future__ import annotations

import pytest

import state


@pytest.mark.asyncio
async def test_update_customer_interested_cars_persists() -> None:
    """State API round-trips interested_cars."""
    wa = "919000000301"
    await state.get_or_create_customer(wa, name="A")

    await state.update_customer_interested_cars(wa, ["Creta", "Nexon"])
    after = await state.get_customer(wa)
    assert after.interested_cars == ["Creta", "Nexon"]


@pytest.mark.asyncio
async def test_customer_record_list_is_copyable() -> None:
    """list(customer.interested_cars) gives an independent list.

    This is the shape-guard for the customer.py:239 fix: the CustomerRecord
    snapshot from the DB must be safely copyable so auto-track mutations
    don't also mutate the snapshot.
    """
    wa = "919000000302"
    await state.get_or_create_customer(wa, name="B")
    await state.update_customer_interested_cars(wa, ["Creta"])
    customer = await state.get_customer(wa)

    copy_a = list(customer.interested_cars)
    copy_a.append("Nexon")
    assert customer.interested_cars == ["Creta"]
    assert copy_a == ["Creta", "Nexon"]
