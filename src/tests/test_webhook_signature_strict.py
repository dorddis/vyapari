"""Webhook signature strictness — no fallback when tenant resolved."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import delete, update


def _sign(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


GLOBAL_SECRET = "GLOBAL_APP_SECRET_SHARED_WITH_ALL_TENANTS"
TENANT_A_SECRET = "TENANT_A_ONLY_SECRET"


@pytest.fixture
def whatsapp_app(monkeypatch):
    """FastAPI app in whatsapp mode, stubs dispatch + background tasks."""
    monkeypatch.setenv("CHANNEL_MODE", "whatsapp")
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    monkeypatch.setenv("META_APP_SECRET", GLOBAL_SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "vt")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "dummy")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "dummy")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())

    import config
    import main
    importlib.reload(config)
    importlib.reload(main)

    async def _noop_process(msg):
        return None

    async def _fake_dispatch(msg):
        return None

    monkeypatch.setattr(main, "_process_and_reply", _noop_process)
    monkeypatch.setattr(main, "dispatch", _fake_dispatch)

    return main


@pytest_asyncio.fixture
async def tenant_a_channel():
    """Seed a WhatsAppChannel for the default business with a known secret."""
    import config
    from database import get_session_factory
    from db_models import ApiKey, WhatsAppChannel
    from services import business_config as bc
    from services.secrets import encrypt_secrets

    bc.invalidate_cache()
    async with get_session_factory()() as s:
        # Drop any lingering row from prior tests
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        s.add(
            WhatsAppChannel(
                business_id=config.DEFAULT_BUSINESS_ID,
                phone_number="919900000010",
                phone_number_id="pni-strict-a",
                waba_id="waba-a",
                provider_config=encrypt_secrets({
                    "access_token": "a-token",
                    "app_secret": TENANT_A_SECRET,
                    "webhook_verify_token": "vt-a",
                    "verification_pin": "",
                }),
            )
        )
        await s.commit()

    yield

    async with get_session_factory()() as s:
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    bc.invalidate_cache()


def _build_payload(pni: str) -> bytes:
    return json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{
            "value": {
                "metadata": {"phone_number_id": pni},
                "messages": [{
                    "from": "9199", "id": "wamid.strict",
                    "type": "text", "text": {"body": "hi"},
                }],
            },
            "field": "messages",
        }]}],
    }).encode("utf-8")


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolved_tenant_rejects_global_secret_signature(
    whatsapp_app, tenant_a_channel,
) -> None:
    """Resolved-tenant webhook signed with the global secret -> 403."""
    body = _build_payload("pni-strict-a")
    transport = httpx.ASGITransport(app=whatsapp_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.post(
            "/webhook", content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, GLOBAL_SECRET),
            },
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_resolved_tenant_accepts_tenant_secret_signature(
    whatsapp_app, tenant_a_channel,
) -> None:
    """Correct tenant secret still yields 200."""
    body = _build_payload("pni-strict-a")
    transport = httpx.ASGITransport(app=whatsapp_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.post(
            "/webhook", content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, TENANT_A_SECRET),
            },
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_tenant_with_unloadable_secret_returns_403(
    whatsapp_app, tenant_a_channel, monkeypatch,
) -> None:
    """Decrypt failure on a resolved tenant -> 403 (no global fallback)."""
    import config
    from database import get_session_factory
    from db_models import WhatsAppChannel
    from services import business_config as bc

    async with get_session_factory()() as s:
        await s.execute(
            update(WhatsAppChannel)
            .where(WhatsAppChannel.business_id == config.DEFAULT_BUSINESS_ID)
            .values(provider_config={"key_id": "primary", "ct": "not-a-real-token"})
        )
        await s.commit()
    bc.invalidate_cache()

    body = _build_payload("pni-strict-a")
    transport = httpx.ASGITransport(app=whatsapp_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.post(
            "/webhook", content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, GLOBAL_SECRET),
            },
        )
    assert resp.status_code == 403, resp.text


@pytest_asyncio.fixture
async def tenant_a_channel_with_empty_secret():
    """Seed a tenant channel whose app_secret is an empty string."""
    import config
    from database import get_session_factory
    from db_models import ApiKey, WhatsAppChannel
    from services import business_config as bc
    from services.secrets import encrypt_secrets

    bc.invalidate_cache()
    async with get_session_factory()() as s:
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        s.add(WhatsAppChannel(
            business_id=config.DEFAULT_BUSINESS_ID,
            phone_number="919900000011",
            phone_number_id="pni-empty-secret",
            waba_id="waba-a",
            provider_config=encrypt_secrets({
                "access_token": "a-token",
                "app_secret": "",
                "webhook_verify_token": "",
                "verification_pin": "",
            }),
        ))
        await s.commit()

    yield

    async with get_session_factory()() as s:
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    bc.invalidate_cache()


@pytest.mark.asyncio
async def test_resolved_tenant_with_empty_app_secret_returns_403(
    whatsapp_app, tenant_a_channel_with_empty_secret,
) -> None:
    """Empty string app_secret -> 403 (guards `not x` vs `is None` regression)."""
    body = _build_payload("pni-empty-secret")
    transport = httpx.ASGITransport(app=whatsapp_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.post(
            "/webhook", content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, GLOBAL_SECRET),
            },
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_unknown_pnid_falls_back_to_global(whatsapp_app) -> None:
    """Unknown pnid -> global META_APP_SECRET fallback (legacy single-tenant)."""
    from database import get_session_factory
    from db_models import WhatsAppChannel
    from services import business_config as bc
    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    bc.invalidate_cache()

    body = _build_payload("pni-completely-unknown")
    transport = httpx.ASGITransport(app=whatsapp_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.post(
            "/webhook", content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, GLOBAL_SECRET),
            },
        )
    assert resp.status_code == 200, resp.text
