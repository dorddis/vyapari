"""Tests for Phase 3.4 per-business adapter + whatsapp.py tenant contextvar.

Key invariant: two WhatsAppAdapter instances constructed with different
(access_token, phone_number_id) must produce outbound Graph API calls
with THEIR respective credentials — the tenant contextvar is task-local
and never leaks across instances.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from channels import base as base_mod
from channels.whatsapp.adapter import WhatsAppAdapter
import whatsapp


# ---------------------------------------------------------------------------
# Captor — records (url, auth_header) on each POST
# ---------------------------------------------------------------------------

class _Captor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, url, **kw):
        self.calls.append({
            "url": url,
            "auth": kw.get("headers", {}).get("Authorization", ""),
            "json": kw.get("json"),
        })
        resp = _R()
        return resp


class _R:
    status_code = 200
    content = b"{}"
    text = ""

    def json(self):
        return {"messages": [{"id": "wamid.mock"}]}


# ---------------------------------------------------------------------------
# Stub outbound logging + role resolution so the adapter doesn't DB-roundtrip.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    async def _noop_log(**kwargs):
        return None

    async def _bot_role(self, to):
        return "bot"

    monkeypatch.setattr("channels.whatsapp.adapter.log_message", _noop_log)
    monkeypatch.setattr(WhatsAppAdapter, "_resolve_outbound_role", _bot_role)
    yield


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_channels_and_adapter_cache():
    """Keep tests hermetic: wipe any whatsapp_channels rows the test
    inserted + clear the per-business adapter cache before/after."""
    from sqlalchemy import delete
    from database import get_session_factory
    from db_models import WhatsAppChannel
    from services import business_config as bc

    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    base_mod.reset_channel()
    bc.invalidate_cache()
    yield
    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    base_mod.reset_channel()
    bc.invalidate_cache()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unbound_adapter_uses_module_env_creds(monkeypatch):
    """Adapter constructed with no args falls back to WHATSAPP_ACCESS_TOKEN."""
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN_DEFAULT")
    monkeypatch.setattr(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "env-pnid")

    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        await WhatsAppAdapter().send_text("919999", "hi")

    assert cap.calls[0]["auth"] == "Bearer ENV_TOKEN_DEFAULT"
    assert "env-pnid" in cap.calls[0]["url"]


@pytest.mark.asyncio
async def test_bound_adapter_uses_per_tenant_creds(monkeypatch):
    """Adapter with explicit creds overrides the module-level env."""
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN_DEFAULT")
    monkeypatch.setattr(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "env-pnid")

    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        adapter = WhatsAppAdapter(
            access_token="TENANT_A_TOKEN",
            phone_number_id="pni-tenant-a",
        )
        await adapter.send_text("919999", "hi")

    assert cap.calls[0]["auth"] == "Bearer TENANT_A_TOKEN"
    assert "pni-tenant-a" in cap.calls[0]["url"]
    assert "env-pnid" not in cap.calls[0]["url"]


@pytest.mark.asyncio
async def test_two_adapters_dont_leak_creds_concurrently(monkeypatch):
    """Concurrent sends from two tenant-bound adapters must each use
    their own credentials. Guards against ContextVar leakage."""
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN")

    cap_a = _Captor()
    cap_b = _Captor()

    # Route each adapter's httpx to its own captor.
    captors_iter = iter([cap_a, cap_b])
    with patch("whatsapp.httpx.AsyncClient", lambda: next(captors_iter)):
        adapter_a = WhatsAppAdapter(access_token="TOKEN_A", phone_number_id="pni-a")
        adapter_b = WhatsAppAdapter(access_token="TOKEN_B", phone_number_id="pni-b")
        await asyncio.gather(
            adapter_a.send_text("911", "hi from A"),
            adapter_b.send_text("922", "hi from B"),
        )

    # The order in which asyncio.gather runs them is impl-defined, but
    # each captor should have exactly one call with ITS tenant's token.
    # Map each captor's call to the adapter it belongs to via the wa_id.
    all_calls = cap_a.calls + cap_b.calls
    a_call = next(c for c in all_calls if c["json"]["to"] == "911")
    b_call = next(c for c in all_calls if c["json"]["to"] == "922")
    assert a_call["auth"] == "Bearer TOKEN_A", a_call
    assert b_call["auth"] == "Bearer TOKEN_B", b_call
    assert "pni-a" in a_call["url"]
    assert "pni-b" in b_call["url"]


@pytest.mark.asyncio
async def test_tenant_contextvar_resets_after_send(monkeypatch):
    """After a bound send, a subsequent unbound send falls back to env."""
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN")
    monkeypatch.setattr(whatsapp, "WHATSAPP_PHONE_NUMBER_ID", "env-pnid")

    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        bound = WhatsAppAdapter(access_token="BOUND_TOK", phone_number_id="bound-pnid")
        await bound.send_text("911", "first")
        unbound = WhatsAppAdapter()
        await unbound.send_text("922", "second")

    assert cap.calls[0]["auth"] == "Bearer BOUND_TOK"
    assert cap.calls[1]["auth"] == "Bearer ENV_TOKEN"


# ---------------------------------------------------------------------------
# get_tenant_channel: async factory resolves + binds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tenant_channel_returns_bound_adapter(monkeypatch):
    """With a whatsapp_channels row present, get_tenant_channel returns
    a WhatsAppAdapter bound to that tenant's access_token."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())

    import config
    monkeypatch.setattr(config, "CHANNEL_MODE", "whatsapp")
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN")

    base_mod.reset_channel()

    from database import get_session_factory
    from db_models import WhatsAppChannel
    from services.secrets import encrypt_secrets
    from services import business_config as bc
    bc.invalidate_cache()

    async with get_session_factory()() as s:
        s.add(WhatsAppChannel(
            business_id=config.DEFAULT_BUSINESS_ID,
            phone_number="919900000001",
            phone_number_id="pni-tenant-alpha",
            waba_id="waba-alpha",
            provider_config=encrypt_secrets({
                "access_token": "ALPHA_ACCESS_TOKEN",
                "app_secret": "alpha-secret",
                "webhook_verify_token": "vt-alpha",
                "verification_pin": "0001",
            }),
        ))
        await s.commit()

    adapter = await base_mod.get_tenant_channel(config.DEFAULT_BUSINESS_ID)
    assert isinstance(adapter, WhatsAppAdapter)

    cap = _Captor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        await adapter.send_text("911", "hi alpha")

    assert cap.calls[0]["auth"] == "Bearer ALPHA_ACCESS_TOKEN"
    assert "pni-tenant-alpha" in cap.calls[0]["url"]

    # Same call should hit the cache.
    same = await base_mod.get_tenant_channel(config.DEFAULT_BUSINESS_ID)
    assert same is adapter


@pytest.mark.asyncio
async def test_invalidate_channel_clears_cache(monkeypatch):
    import config
    monkeypatch.setattr(config, "CHANNEL_MODE", "whatsapp")
    base_mod.reset_channel()
    base_mod._per_business_adapters["biz-x"] = WhatsAppAdapter()
    assert "biz-x" in base_mod._per_business_adapters
    base_mod.invalidate_channel("biz-x")
    assert "biz-x" not in base_mod._per_business_adapters
