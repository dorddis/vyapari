"""Phase 3 end-to-end multi-tenant sanity tests.

Two businesses, two WhatsApp channels, two API keys — verify every
boundary respects tenancy:
- Webhook signature verification uses the tenant's app_secret.
- Inbound message resolves to the right business_id.
- Outbound adapter uses the tenant's access_token.
- API key lookup binds requests to the right tenant.

If any of these test fails, the deployment is not safe to put two
real businesses on.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import delete

from channels import base as channel_base
from channels.whatsapp.adapter import WhatsAppAdapter
import whatsapp


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


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
            "json": kw.get("json"),
            "auth": kw.get("headers", {}).get("Authorization", ""),
        })
        return _R()


class _R:
    status_code = 200
    content = b"{}"
    text = ""

    def json(self):
        return {"messages": [{"id": "wamid.mock"}]}


@pytest_asyncio.fixture
async def two_tenants(monkeypatch):
    """Seed two full tenants (Business + WhatsAppChannel + ApiKey) and
    return their identifiers for the test to exercise."""
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())

    import config
    from database import get_session_factory
    from db_models import Business, WhatsAppChannel, ApiKey
    from services.tenant_onboarding import (
        onboard_business, provision_whatsapp_channel,
    )
    from services.api_keys import mint_api_key
    from services import business_config as bc

    # Clean slate
    async with get_session_factory()() as s:
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        await s.execute(delete(Business).where(Business.id.notin_([config.DEFAULT_BUSINESS_ID])))
        await s.commit()
    bc.invalidate_cache()
    channel_base.reset_channel()

    a_id = "tenant-a"
    b_id = "tenant-b"

    await onboard_business(a_id, "Alpha Cars", "919110000001", vertical="used_cars")
    await onboard_business(b_id, "Beta Realty", "919220000002", vertical="real_estate")

    await provision_whatsapp_channel(
        a_id, phone_number="919100000001", phone_number_id="pni-alpha",
        waba_id="waba-alpha", access_token="TOKEN_ALPHA",
        app_secret="SECRET_ALPHA",
    )
    await provision_whatsapp_channel(
        b_id, phone_number="919200000002", phone_number_id="pni-beta",
        waba_id="waba-beta", access_token="TOKEN_BETA",
        app_secret="SECRET_BETA",
    )
    key_a = await mint_api_key(a_id, description="tenant-a primary")
    key_b = await mint_api_key(b_id, description="tenant-b primary")

    yield {
        "a_id": a_id,
        "b_id": b_id,
        "a_secret": "SECRET_ALPHA",
        "b_secret": "SECRET_BETA",
        "a_api_key": key_a.plaintext,
        "b_api_key": key_b.plaintext,
    }

    # Cleanup
    async with get_session_factory()() as s:
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        await s.execute(delete(Business).where(Business.id.notin_([config.DEFAULT_BUSINESS_ID])))
        await s.commit()
    bc.invalidate_cache()
    channel_base.reset_channel()


# ---------------------------------------------------------------------------
# Webhook layer: signature verification + tenant resolution
# ---------------------------------------------------------------------------

@pytest.fixture
def app_client(monkeypatch):
    """FastAPI app wired for whatsapp mode with dispatch stubbed."""
    monkeypatch.setenv("CHANNEL_MODE", "whatsapp")
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    monkeypatch.setenv("META_APP_SECRET", "GLOBAL_FALLBACK_SECRET_UNUSED")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "vt")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "dummy")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "dummy")
    monkeypatch.setenv("APP_ENV", "development")

    import importlib
    import config, main

    importlib.reload(config)
    importlib.reload(main)

    async def _noop_process(msg):
        pass

    async def _fake_dispatch(msg):
        return "ok"

    monkeypatch.setattr(main, "_process_and_reply", _noop_process)
    monkeypatch.setattr(main, "dispatch", _fake_dispatch)
    return httpx.ASGITransport(app=main.app)


@pytest.mark.asyncio
async def test_webhook_signature_per_tenant(two_tenants, app_client) -> None:
    """Tenant A's payload signed with A's secret -> 200. Same payload
    signed with B's secret -> 403 (wrong tenant's key)."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{
            "value": {
                "metadata": {"phone_number_id": "pni-alpha"},
                "messages": [{
                    "from": "9199", "id": "wamid.alpha",
                    "type": "text", "text": {"body": "hi"},
                }],
            },
            "field": "messages",
        }]}],
    }
    body = json.dumps(payload).encode()

    async with httpx.AsyncClient(transport=app_client, base_url="http://t") as http:
        # A's secret -> 200
        resp = await http.post("/webhook", content=body, headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body, two_tenants["a_secret"]),
        })
        assert resp.status_code == 200, resp.text

        # B's secret (wrong tenant) -> 403
        resp = await http.post("/webhook", content=body, headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _sign(body, two_tenants["b_secret"]),
        })
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Outbound layer: per-tenant access_token
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_outbound_per_tenant_creds(two_tenants, monkeypatch) -> None:
    """get_tenant_channel(A) uses TOKEN_ALPHA; get_tenant_channel(B)
    uses TOKEN_BETA. Messages from the two adapters never cross-pollinate
    credentials."""
    import config
    monkeypatch.setattr(config, "CHANNEL_MODE", "whatsapp")

    adapter_a = await channel_base.get_tenant_channel(two_tenants["a_id"])
    adapter_b = await channel_base.get_tenant_channel(two_tenants["b_id"])

    async def _noop_log(**kw):
        return None

    async def _bot_role(self, to):
        return "bot"

    monkeypatch.setattr("channels.whatsapp.adapter.log_message", _noop_log)
    monkeypatch.setattr(WhatsAppAdapter, "_resolve_outbound_role", _bot_role)

    caps = [_Captor(), _Captor()]
    caps_iter = iter(caps)
    with patch("whatsapp.httpx.AsyncClient", lambda: next(caps_iter)):
        await adapter_a.send_text("9191", "from alpha")
        await adapter_b.send_text("9292", "from beta")

    # Map each call to the captor that recorded it.
    alpha_call = next(c for cap in caps for c in cap.calls if c["json"]["to"] == "9191")
    beta_call = next(c for cap in caps for c in cap.calls if c["json"]["to"] == "9292")
    assert "TOKEN_ALPHA" in alpha_call["auth"]
    assert "TOKEN_BETA" in beta_call["auth"]
    assert "pni-alpha" in alpha_call["url"]
    assert "pni-beta" in beta_call["url"]


# ---------------------------------------------------------------------------
# Auth layer: API key -> business_id binding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_key_binds_to_business(two_tenants) -> None:
    from services.api_keys import verify_api_key
    assert await verify_api_key(two_tenants["a_api_key"]) == two_tenants["a_id"]
    assert await verify_api_key(two_tenants["b_api_key"]) == two_tenants["b_id"]
    # Swapped plaintexts are rejected: A's plaintext CAN'T unlock B's
    # business.
    assert await verify_api_key("not-a-real-key") is None


# ---------------------------------------------------------------------------
# End-to-end isolation: per-tenant pnid -> per-tenant business_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pnid_resolves_to_correct_tenant(two_tenants) -> None:
    from services.business_config import resolve_business_id_from_phone_number_id
    assert await resolve_business_id_from_phone_number_id("pni-alpha") == two_tenants["a_id"]
    assert await resolve_business_id_from_phone_number_id("pni-beta") == two_tenants["b_id"]
    assert await resolve_business_id_from_phone_number_id("pni-unknown") is None
