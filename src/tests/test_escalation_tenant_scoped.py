"""Multi-tenant escalation notification isolation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete

import state
from models import StaffRole, StaffStatus


@pytest_asyncio.fixture
async def two_tenants_with_owners():
    """Seed two businesses and one owner per tenant."""
    import config
    from database import get_session_factory
    from db_models import Business, Staff, WhatsAppChannel

    a_id = "escal-tenant-a"
    b_id = "escal-tenant-b"
    owner_a = "919110000010"
    owner_b = "919220000020"

    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        await s.execute(delete(Staff).where(Staff.wa_id.in_([owner_a, owner_b])))
        await s.execute(delete(Business).where(Business.id.in_([a_id, b_id])))
        s.add(Business(id=a_id, name="Alpha", type="", vertical="",
                       owner_phone=owner_a))
        s.add(Business(id=b_id, name="Beta", type="", vertical="",
                       owner_phone=owner_b))
        await s.commit()

    await state.add_staff(
        wa_id=owner_a, name="Alice",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
        business_id=a_id,
    )
    await state.add_staff(
        wa_id=owner_b, name="Bob",
        role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
        business_id=b_id,
    )

    yield {
        "a_id": a_id, "b_id": b_id,
        "owner_a": owner_a, "owner_b": owner_b,
    }

    async with get_session_factory()() as s:
        await s.execute(delete(Staff).where(Staff.wa_id.in_([owner_a, owner_b])))
        await s.execute(delete(Business).where(Business.id.in_([a_id, b_id])))
        await s.commit()


# ---------------------------------------------------------------------------
# state.list_staff tenant-scoping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_staff_scoped_to_business(two_tenants_with_owners) -> None:
    t = two_tenants_with_owners
    staff_a = await state.list_staff(business_id=t["a_id"])
    staff_b = await state.list_staff(business_id=t["b_id"])

    assert {s.wa_id for s in staff_a} == {t["owner_a"]}
    assert {s.wa_id for s in staff_b} == {t["owner_b"]}


@pytest.mark.asyncio
async def test_list_staff_unscoped_is_global(two_tenants_with_owners) -> None:
    """Back-compat: omitting business_id returns every non-removed row."""
    t = two_tenants_with_owners
    all_staff = await state.list_staff()
    wa_ids = {s.wa_id for s in all_staff}
    assert t["owner_a"] in wa_ids
    assert t["owner_b"] in wa_ids


@pytest.mark.asyncio
async def test_escalation_pages_only_same_tenant_owner(
    two_tenants_with_owners, monkeypatch,
) -> None:
    """An escalation stamped business_id=B pages B's owner, never A's."""
    from router import _push_escalation_notification

    t = two_tenants_with_owners
    sent: list[tuple[str, str]] = []

    class _CaptureChannel:
        async def send_text(self, to: str, text: str) -> None:
            sent.append((to, text))

    async def _fake_get_tenant_channel(business_id: str):
        return _CaptureChannel()

    monkeypatch.setattr(
        "channels.base.get_tenant_channel", _fake_get_tenant_channel,
    )

    customer_b = "919220000099"
    response = SimpleNamespace(
        escalation_summary="Customer wants immediate callback",
    )
    await _push_escalation_notification(
        customer_b, response, business_id=t["b_id"],
    )

    assert len(sent) == 1
    recipient, body = sent[0]
    assert recipient == t["owner_b"], (
        f"Expected tenant-B owner {t['owner_b']!r}, got {recipient!r}"
    )
    assert t["owner_a"] != recipient
    assert "ESCALATION" in body


@pytest.mark.asyncio
async def test_escalation_with_no_staff_logs_and_skips(
    two_tenants_with_owners, monkeypatch, caplog,
) -> None:
    """No owner on this tenant -> no notification (no cross-tenant fallthrough)."""
    from router import _push_escalation_notification

    t = two_tenants_with_owners
    async with __import__("database").get_session_factory()() as s:
        from sqlalchemy import delete as _delete
        from db_models import Staff
        await s.execute(_delete(Staff).where(Staff.wa_id == t["owner_a"]))
        await s.commit()

    sent: list[tuple[str, str]] = []

    class _CaptureChannel:
        async def send_text(self, to: str, text: str) -> None:
            sent.append((to, text))

    async def _fake_get_tenant_channel(business_id: str):
        return _CaptureChannel()

    monkeypatch.setattr(
        "channels.base.get_tenant_channel", _fake_get_tenant_channel,
    )

    response = SimpleNamespace(escalation_summary="test")
    await _push_escalation_notification(
        "919110000050", response, business_id=t["a_id"],
    )

    assert sent == [], f"Should not fall through to other tenants, got {sent}"


@pytest.mark.asyncio
async def test_escalation_refuses_to_send_without_business_id(
    two_tenants_with_owners, monkeypatch,
) -> None:
    """Empty business_id -> skip; no fall-through to unscoped list_staff."""
    from router import _push_escalation_notification

    sent: list[tuple[str, str]] = []

    class _CaptureChannel:
        async def send_text(self, to: str, text: str) -> None:
            sent.append((to, text))

    async def _fake_get_tenant_channel(business_id: str):
        return _CaptureChannel()

    monkeypatch.setattr(
        "channels.base.get_tenant_channel", _fake_get_tenant_channel,
    )

    response = SimpleNamespace(escalation_summary="test")
    await _push_escalation_notification(
        "919000000001", response, business_id="",
    )
    assert sent == []
