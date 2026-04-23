"""Multi-tenant wa_id endpoint isolation."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete

import state
from database import get_session_factory
from db_models import Business, Customer, MessageLog
from services.message_log import (
    delete_messages_for_wa_id,
    fetch_messages_for_wa_id,
    list_conversations_from_logs,
    log_message,
)


@pytest_asyncio.fixture
async def two_tenants_with_messages():
    """Seed two businesses with an overlapping wa_id and 3 scoped messages."""
    a_id = "wascope-tenant-a"
    b_id = "wascope-tenant-b"
    shared_wa_id = "919123456789"

    async with get_session_factory()() as s:
        await s.execute(delete(MessageLog).where(
            MessageLog.business_id.in_([a_id, b_id])
        ))
        await s.execute(delete(Customer).where(Customer.wa_id == shared_wa_id))
        await s.execute(delete(Business).where(Business.id.in_([a_id, b_id])))
        s.add(Business(id=a_id, name="A", type="", vertical="",
                       owner_phone="919100000001"))
        s.add(Business(id=b_id, name="B", type="", vertical="",
                       owner_phone="919200000002"))
        await s.commit()

    await log_message(
        wa_id=shared_wa_id, role="customer", direction="inbound",
        channel="whatsapp", text="hello from A side",
        business_id=a_id,
    )
    await log_message(
        wa_id=shared_wa_id, role="customer", direction="inbound",
        channel="whatsapp", text="HELLO FROM B SIDE",
        business_id=b_id,
    )
    await log_message(
        wa_id=shared_wa_id, role="bot", direction="outbound",
        channel="whatsapp", text="reply on B",
        business_id=b_id,
    )

    yield {
        "a_id": a_id, "b_id": b_id, "wa_id": shared_wa_id,
    }

    async with get_session_factory()() as s:
        await s.execute(delete(MessageLog).where(
            MessageLog.business_id.in_([a_id, b_id])
        ))
        await s.execute(delete(Customer).where(Customer.wa_id == shared_wa_id))
        await s.execute(delete(Business).where(Business.id.in_([a_id, b_id])))
        await s.commit()


# ---------------------------------------------------------------------------
# fetch_messages_for_wa_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_messages_scoped_to_tenant(two_tenants_with_messages) -> None:
    t = two_tenants_with_messages
    msgs_a = await fetch_messages_for_wa_id(t["wa_id"], business_id=t["a_id"])
    msgs_b = await fetch_messages_for_wa_id(t["wa_id"], business_id=t["b_id"])

    texts_a = {m["text"] for m in msgs_a}
    texts_b = {m["text"] for m in msgs_b}
    assert texts_a == {"hello from A side"}
    assert texts_b == {"HELLO FROM B SIDE", "reply on B"}
    assert "HELLO FROM B SIDE" not in texts_a
    assert "reply on B" not in texts_a


@pytest.mark.asyncio
async def test_fetch_messages_without_scope_is_global(
    two_tenants_with_messages,
) -> None:
    """Unscoped query returns all tenants' rows (back-compat)."""
    t = two_tenants_with_messages
    all_msgs = await fetch_messages_for_wa_id(t["wa_id"])
    assert len(all_msgs) == 3


# ---------------------------------------------------------------------------
# list_conversations_from_logs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_conversations_scoped_to_tenant(
    two_tenants_with_messages,
) -> None:
    t = two_tenants_with_messages
    await log_message(
        wa_id="919999111111", role="customer", direction="inbound",
        channel="whatsapp", text="only A", business_id=t["a_id"],
    )
    await log_message(
        wa_id="919999222222", role="customer", direction="inbound",
        channel="whatsapp", text="only B", business_id=t["b_id"],
    )

    convs_a = await list_conversations_from_logs(business_id=t["a_id"])
    convs_b = await list_conversations_from_logs(business_id=t["b_id"])

    wa_ids_a = {c["customer_id"] for c in convs_a}
    wa_ids_b = {c["customer_id"] for c in convs_b}
    assert "919999111111" in wa_ids_a
    assert "919999222222" in wa_ids_b
    assert "919999222222" not in wa_ids_a
    assert "919999111111" not in wa_ids_b


# ---------------------------------------------------------------------------
# delete_messages_for_wa_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_messages_scoped_to_tenant(
    two_tenants_with_messages,
) -> None:
    """Scoped delete leaves other tenants' rows with the same wa_id intact."""
    t = two_tenants_with_messages

    deleted_a = await delete_messages_for_wa_id(
        t["wa_id"], business_id=t["a_id"],
    )
    assert deleted_a == 1

    msgs_b = await fetch_messages_for_wa_id(t["wa_id"], business_id=t["b_id"])
    assert len(msgs_b) == 2
    msgs_a = await fetch_messages_for_wa_id(t["wa_id"], business_id=t["a_id"])
    assert msgs_a == []


# ---------------------------------------------------------------------------
# End-to-end through the FastAPI router
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_endpoint_respects_tenant_ownership(
    two_tenants_with_messages, monkeypatch,
) -> None:
    """POST /api/reset with a customer_id that doesn't belong to the
    caller's tenant must be a no-op for messages AND the customer row.

    Seeds a Customer row scoped to tenant A and asserts a request
    resolved to tenant B neither wipes A's messages nor touches A's
    customer state.
    """
    import config
    from channels import base as channel_base
    from fastapi import Request

    t = two_tenants_with_messages
    # Seed a Customer row owned by tenant A for the shared wa_id.
    await state.get_or_create_customer(
        t["wa_id"], name="A's customer", business_id=t["a_id"],
    )

    monkeypatch.setattr(config, "CHANNEL_MODE", "web_clone")
    # channels.base caches an _active_adapter at module scope; flipping
    # CHANNEL_MODE in monkeypatch does not evict the cache. Reset it so
    # _require_web_clone sees a freshly-constructed WebCloneAdapter — and
    # so subsequent tests running in whatsapp mode don't inherit our
    # WebCloneAdapter and silently drop extract_status_updates().
    channel_base.reset_channel()
    # Skip auth — we're exercising the scope logic, not the auth layer.
    async def _noop_auth(_req):
        return None
    monkeypatch.setattr("web_api._require_api_auth", _noop_auth)

    from web_api import reset_conversation, ResetRequest

    # Fake a Request whose _resolve_business_id returns tenant B.
    class _FakeState:
        business_id = t["b_id"]

    class _FakeRequest:
        state = _FakeState()
        headers: dict = {}

    await reset_conversation(
        ResetRequest(customer_id=t["wa_id"]), _FakeRequest(),
    )

    # Tenant A's messages and customer row are INTACT.
    msgs_a = await fetch_messages_for_wa_id(t["wa_id"], business_id=t["a_id"])
    assert len(msgs_a) == 1, "tenant-B's reset should not delete tenant-A's rows"

    customer = await state.get_customer(t["wa_id"])
    assert customer is not None
    assert customer.business_id == t["a_id"]

    # Evict cached adapter so subsequent whatsapp-mode tests see a fresh one.
    channel_base.reset_channel()


@pytest.mark.asyncio
async def test_staff_endpoint_is_tenant_scoped(monkeypatch) -> None:
    """GET /api/staff must only return the caller's business's staff."""
    import config
    from database import get_session_factory
    from db_models import Business, Staff, WhatsAppChannel
    from models import StaffRole, StaffStatus

    a_id = "staffep-tenant-a"
    b_id = "staffep-tenant-b"
    owner_a = "919110000030"
    owner_b = "919220000040"

    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        await s.execute(delete(Staff).where(Staff.wa_id.in_([owner_a, owner_b])))
        await s.execute(delete(Business).where(Business.id.in_([a_id, b_id])))
        s.add(Business(id=a_id, name="A", type="", vertical="",
                       owner_phone=owner_a))
        s.add(Business(id=b_id, name="B", type="", vertical="",
                       owner_phone=owner_b))
        await s.commit()
    await state.add_staff(wa_id=owner_a, name="Alice",
                          role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
                          business_id=a_id)
    await state.add_staff(wa_id=owner_b, name="Bob",
                          role=StaffRole.OWNER, status=StaffStatus.ACTIVE,
                          business_id=b_id)

    monkeypatch.setattr(config, "CHANNEL_MODE", "web_clone")
    from channels import base as channel_base
    channel_base.reset_channel()
    async def _noop_auth(_req):
        return None
    monkeypatch.setattr("web_api._require_api_auth", _noop_auth)

    from web_api import list_staff as list_staff_endpoint

    class _FakeStateA:
        business_id = a_id
    class _FakeRequestA:
        state = _FakeStateA()
        headers: dict = {}

    class _FakeStateB:
        business_id = b_id
    class _FakeRequestB:
        state = _FakeStateB()
        headers: dict = {}

    resp_a = await list_staff_endpoint(_FakeRequestA())
    resp_b = await list_staff_endpoint(_FakeRequestB())

    wa_ids_a = {s["wa_id"] for s in resp_a["staff"]}
    wa_ids_b = {s["wa_id"] for s in resp_b["staff"]}
    assert owner_a in wa_ids_a and owner_b not in wa_ids_a, wa_ids_a
    assert owner_b in wa_ids_b and owner_a not in wa_ids_b, wa_ids_b

    async with get_session_factory()() as s:
        await s.execute(delete(Staff).where(Staff.wa_id.in_([owner_a, owner_b])))
        await s.execute(delete(Business).where(Business.id.in_([a_id, b_id])))
        await s.commit()
    channel_base.reset_channel()


@pytest.mark.asyncio
async def test_legacy_token_binds_to_default_business_id(monkeypatch) -> None:
    """Legacy API_AUTH_TOKEN binds to DEFAULT_BUSINESS_ID, not a spoofed header."""
    import config
    from fastapi import HTTPException

    from web_api import _require_api_auth, _resolve_business_id

    monkeypatch.setattr(config, "API_AUTH_TOKEN", "legacy-shared-token")
    monkeypatch.setattr(config, "APP_ENV", "production")

    class _FakeReqState:
        business_id = None

    class _FakeRequest:
        def __init__(self, authorization: str, x_business_id: str | None) -> None:
            self.state = _FakeReqState()
            self.headers: dict = {"Authorization": authorization}
            if x_business_id is not None:
                self.headers["X-Business-Id"] = x_business_id

    spoof_req = _FakeRequest(
        authorization="Bearer legacy-shared-token",
        x_business_id="victim-tenant",
    )
    await _require_api_auth(spoof_req)
    assert spoof_req.state.business_id == config.DEFAULT_BUSINESS_ID
    assert _resolve_business_id(spoof_req) == config.DEFAULT_BUSINESS_ID


@pytest.mark.asyncio
async def test_x_business_id_header_ignored_in_production(monkeypatch) -> None:
    """Production ignores X-Business-Id entirely."""
    import config
    from web_api import _resolve_business_id

    monkeypatch.setattr(config, "APP_ENV", "production")

    class _Req:
        class state: business_id = None
        headers = {"X-Business-Id": "attacker-tenant"}

    bid = _resolve_business_id(_Req())
    assert bid == config.DEFAULT_BUSINESS_ID
    assert bid != "attacker-tenant"
