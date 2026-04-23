"""Multi-tenant template catalog isolation (P3.5a #2).

Pre-P3.5a `services/templates.py` had a tenant-agnostic `_resolve_waba_id`
that returned `config.WHATSAPP_BUSINESS_ACCOUNT_ID` regardless of
business_id, and every Graph call hardcoded `Bearer {config.WHATSAPP_ACCESS_TOKEN}`.
A tenant's `register_template` / `sync_templates` silently hit the env
WABA with the env token — the onboarding success message literally
instructed operators to run scripts that cross-wrote Meta state.

These tests guard the fix by asserting that:
  - register_template(bid=A) posts to A's waba_id using A's access_token
  - sync_templates(bid=B) gets from B's waba_id using B's access_token
  - The env fallback never appears in any Graph call
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import delete

from channels import base as channel_base


class _MockResponse:
    def __init__(self, body: dict, *, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code
        self.content = b"{}"
        self.text = ""

    def json(self) -> dict:
        return self._body


class _CapturingClient:
    """httpx.AsyncClient stand-in that records URL + Authorization on every call.

    `register_template` fires one POST; `sync_templates` fires one or
    more GETs until pagination exhausts. The captor answers every call
    with a stable stub so the service-layer logic proceeds past the
    Graph hop and into the DB upsert.
    """

    def __init__(self, *, post_body: dict | None = None,
                 get_body: dict | None = None) -> None:
        self._post_body = post_body or {
            "id": "tpl-mock", "status": "PENDING", "category": "UTILITY",
        }
        self._get_body = get_body or {"data": [], "paging": {}}
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        self.calls.append({
            "method": "POST",
            "url": url,
            "auth": kwargs.get("headers", {}).get("Authorization", ""),
        })
        return _MockResponse(self._post_body)

    async def get(self, url, **kwargs):
        self.calls.append({
            "method": "GET",
            "url": url,
            "auth": kwargs.get("headers", {}).get("Authorization", ""),
            "params": kwargs.get("params"),
        })
        return _MockResponse(self._get_body)


@pytest_asyncio.fixture
async def two_tenants(monkeypatch):
    """Seed two businesses each with a WhatsApp channel carrying
    distinct (waba_id, access_token)."""
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())

    import config
    from database import get_session_factory
    from db_models import ApiKey, Business, MessageTemplate, WhatsAppChannel
    from services.tenant_onboarding import (
        onboard_business, provision_whatsapp_channel,
    )
    from services import business_config as bc

    async with get_session_factory()() as s:
        await s.execute(delete(MessageTemplate))
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        await s.execute(delete(Business).where(Business.id.notin_([config.DEFAULT_BUSINESS_ID])))
        await s.commit()
    bc.invalidate_cache()
    channel_base.reset_channel()

    await onboard_business("tenant-a", "Alpha Cars", "919110000001", vertical="used_cars")
    await onboard_business("tenant-b", "Beta Realty", "919220000002", vertical="real_estate")
    await provision_whatsapp_channel(
        "tenant-a", phone_number="919100000001", phone_number_id="pni-alpha",
        waba_id="waba-alpha", access_token="TOKEN_ALPHA",
        app_secret="SECRET_ALPHA",
    )
    await provision_whatsapp_channel(
        "tenant-b", phone_number="919200000002", phone_number_id="pni-beta",
        waba_id="waba-beta", access_token="TOKEN_BETA",
        app_secret="SECRET_BETA",
    )

    yield {"a_id": "tenant-a", "b_id": "tenant-b"}

    async with get_session_factory()() as s:
        await s.execute(delete(MessageTemplate))
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        await s.execute(delete(Business).where(Business.id.notin_([config.DEFAULT_BUSINESS_ID])))
        await s.commit()
    bc.invalidate_cache()
    channel_base.reset_channel()


@pytest.mark.asyncio
async def test_register_template_uses_tenant_waba_and_token(
    two_tenants, monkeypatch,
) -> None:
    """register_template(A) posts to /waba-alpha/... with TOKEN_ALPHA.
    register_template(B) posts to /waba-beta/... with TOKEN_BETA.
    Neither call carries the env default access_token.
    """
    import config
    # Make the env obviously different from either tenant — a fallback
    # would leak this value into `auth` below.
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN_MUST_NOT_LEAK")
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "ENV_WABA_MUST_NOT_LEAK")

    from services.templates import register_template

    cap_a = _CapturingClient()
    with patch("services.templates.httpx.AsyncClient", lambda: cap_a):
        await register_template(
            business_id=two_tenants["a_id"],
            name="welcome", language="en",
            components=[{"type": "BODY", "text": "hi from alpha"}],
        )
    cap_b = _CapturingClient()
    with patch("services.templates.httpx.AsyncClient", lambda: cap_b):
        await register_template(
            business_id=two_tenants["b_id"],
            name="welcome", language="en",
            components=[{"type": "BODY", "text": "hi from beta"}],
        )

    a_call = cap_a.calls[0]
    b_call = cap_b.calls[0]
    assert a_call["url"].endswith("/waba-alpha/message_templates"), a_call["url"]
    assert b_call["url"].endswith("/waba-beta/message_templates"), b_call["url"]
    assert "TOKEN_ALPHA" in a_call["auth"], a_call["auth"]
    assert "TOKEN_BETA" in b_call["auth"], b_call["auth"]
    assert "TOKEN_BETA" not in a_call["auth"]
    assert "TOKEN_ALPHA" not in b_call["auth"]
    assert "ENV_TOKEN_MUST_NOT_LEAK" not in a_call["auth"]
    assert "ENV_TOKEN_MUST_NOT_LEAK" not in b_call["auth"]
    assert "ENV_WABA_MUST_NOT_LEAK" not in a_call["url"]
    assert "ENV_WABA_MUST_NOT_LEAK" not in b_call["url"]


@pytest.mark.asyncio
async def test_sync_templates_uses_tenant_waba_and_token(
    two_tenants, monkeypatch,
) -> None:
    """sync_templates(A) GETs /waba-alpha/... with TOKEN_ALPHA;
    sync_templates(B) GETs /waba-beta/... with TOKEN_BETA.
    """
    import config
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN_MUST_NOT_LEAK")
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "ENV_WABA_MUST_NOT_LEAK")

    from services.templates import sync_templates

    cap_a = _CapturingClient(get_body={
        "data": [{"id": "t1", "name": "welcome", "language": "en",
                  "status": "APPROVED", "category": "UTILITY", "components": []}],
        "paging": {},
    })
    with patch("services.templates.httpx.AsyncClient", lambda: cap_a):
        n_a = await sync_templates(two_tenants["a_id"])

    cap_b = _CapturingClient(get_body={
        "data": [{"id": "t2", "name": "welcome", "language": "en",
                  "status": "APPROVED", "category": "UTILITY", "components": []}],
        "paging": {},
    })
    with patch("services.templates.httpx.AsyncClient", lambda: cap_b):
        n_b = await sync_templates(two_tenants["b_id"])

    assert n_a == 1
    assert n_b == 1
    # Exactly one GET per sync — empty paging terminates the loop.
    assert len(cap_a.calls) == 1 and cap_a.calls[0]["method"] == "GET"
    assert len(cap_b.calls) == 1 and cap_b.calls[0]["method"] == "GET"
    assert "/waba-alpha/message_templates" in cap_a.calls[0]["url"]
    assert "/waba-beta/message_templates" in cap_b.calls[0]["url"]
    assert "TOKEN_ALPHA" in cap_a.calls[0]["auth"]
    assert "TOKEN_BETA" in cap_b.calls[0]["auth"]
    assert "ENV_TOKEN_MUST_NOT_LEAK" not in cap_a.calls[0]["auth"]
    assert "ENV_TOKEN_MUST_NOT_LEAK" not in cap_b.calls[0]["auth"]
