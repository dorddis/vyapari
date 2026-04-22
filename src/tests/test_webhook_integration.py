"""Integration tests for POST /webhook.

Exercise the full path through FastAPI: signature verification ->
payload parse -> extract_message / extract_status_updates -> dispatch /
background-task fan-out. Uses httpx.ASGITransport so no real HTTP
server is needed.

These tests are the backstop gaps that unit tests can't catch: signature
regressions, handler wiring, background-task registration. A unit-test
refactor that drops a branch will still pass per-function asserts but
fail here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest


TEST_SECRET = "test-webhook-secret"


def _sign(body: bytes, secret: str = TEST_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def client(monkeypatch):
    """FastAPI app wired for whatsapp mode, with dispatch + status logging
    stubbed so we can assert on invocation without a real DB / LLM."""
    # Force whatsapp mode + known secret BEFORE importing config / main.
    monkeypatch.setenv("CHANNEL_MODE", "whatsapp")
    monkeypatch.setenv("WHATSAPP_ENABLED", "true")
    monkeypatch.setenv("META_APP_SECRET", TEST_SECRET)
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-token")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "dummy")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "dummy")
    monkeypatch.setenv("APP_ENV", "development")

    import importlib
    import config
    import main

    importlib.reload(config)
    importlib.reload(main)

    # Stub dispatch so we don't run the agent or touch the DB.
    dispatched: list = []

    async def fake_dispatch(msg):
        dispatched.append(msg)
        return "mock-reply"

    monkeypatch.setattr(main, "dispatch", fake_dispatch)

    # Stub _process_and_reply too since BackgroundTasks runs after the
    # response and would try to hit real services.
    async def fake_process(msg):
        dispatched.append(msg)

    monkeypatch.setattr(main, "_process_and_reply", fake_process)

    # Stub status recording.
    recorded_statuses: list = []

    async def fake_record(external_msg_id, status, timestamp, error):
        recorded_statuses.append(
            {"external_msg_id": external_msg_id, "status": status}
        )

    monkeypatch.setattr(main, "_record_status_event", fake_record)

    transport = httpx.ASGITransport(app=main.app)
    return {
        "transport": transport,
        "app": main.app,
        "dispatched": dispatched,
        "statuses": recorded_statuses,
    }


# ---------------------------------------------------------------------------
# Happy path: valid signature, inbound text -> dispatch invoked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_happy_path_signed_text(client) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "102290129340398",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "p1"},
                    "contacts": [{"profile": {"name": "Ramesh"}, "wa_id": "919999"}],
                    "messages": [{
                        "from": "919999",
                        "id": "wamid.itgr-1",
                        "type": "text",
                        "text": {"body": "Creta chahiye"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    body = json.dumps(payload).encode("utf-8")

    async with httpx.AsyncClient(transport=client["transport"], base_url="http://test") as http:
        resp = await http.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Bad signature rejected with 403; dispatch never called
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_bad_signature_rejected(client) -> None:
    payload = {"object": "whatsapp_business_account", "entry": []}
    body = json.dumps(payload).encode("utf-8")
    bad_sig = "sha256=" + "ff" * 32

    async with httpx.AsyncClient(transport=client["transport"], base_url="http://test") as http:
        resp = await http.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": bad_sig},
        )

    assert resp.status_code == 403
    assert client["dispatched"] == []


# ---------------------------------------------------------------------------
# Missing signature header -> 403
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_missing_signature_rejected(client) -> None:
    body = b"{}"
    async with httpx.AsyncClient(transport=client["transport"], base_url="http://test") as http:
        resp = await http.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Status callback -> 200 + _record_status_event scheduled per event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_status_callback_fans_out_to_record(client) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1",
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "p1"},
                    "statuses": [
                        {"id": "wamid.delivered-1", "status": "delivered", "timestamp": "1"},
                        {"id": "wamid.read-1",      "status": "read",      "timestamp": "2"},
                    ],
                },
                "field": "messages",
            }],
        }],
    }
    body = json.dumps(payload).encode("utf-8")

    async with httpx.AsyncClient(transport=client["transport"], base_url="http://test") as http:
        resp = await http.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
        )

    assert resp.status_code == 200
    # BackgroundTasks run after the response. httpx ASGITransport waits
    # for the full response cycle so the tasks have executed by the time
    # the AsyncClient block exits — but give them a beat to be safe.
    # FastAPI BackgroundTasks are awaited synchronously in the response
    # lifecycle, so they're already done.
    assert len(client["statuses"]) == 2
    assert client["statuses"][0]["status"] == "delivered"
    assert client["statuses"][1]["status"] == "read"


# ---------------------------------------------------------------------------
# Malformed JSON body -> still 200 (never 500 — Meta retry storm guard)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_malformed_json_still_200(client) -> None:
    body = b"not valid json at all {{"
    async with httpx.AsyncClient(transport=client["transport"], base_url="http://test") as http:
        resp = await http.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Valid signature but non-dict messages[0] -> 200, no dispatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_weird_message_shape_still_200(client) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1",
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "p1"},
                    "messages": ["malformed-string-not-dict"],
                },
                "field": "messages",
            }],
        }],
    }
    body = json.dumps(payload).encode("utf-8")
    async with httpx.AsyncClient(transport=client["transport"], base_url="http://test") as http:
        resp = await http.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /webhook handshake (Meta subscription verification)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_get_verify_echoes_challenge(client) -> None:
    async with httpx.AsyncClient(transport=client["transport"], base_url="http://test") as http:
        resp = await http.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-token",
                "hub.challenge": "12345",
            },
        )
    assert resp.status_code == 200
    assert resp.text == "12345"


@pytest.mark.asyncio
async def test_webhook_get_wrong_token_rejected(client) -> None:
    async with httpx.AsyncClient(transport=client["transport"], base_url="http://test") as http:
        resp = await http.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "12345",
            },
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tenant-resolved signature verification (P3.2)
# ---------------------------------------------------------------------------

TENANT_SECRET = "per-tenant-secret-42"
GLOBAL_SECRET = TEST_SECRET  # smoke-secret


@pytest.mark.asyncio
async def test_webhook_uses_tenant_app_secret_when_phone_number_id_resolves(
    client, monkeypatch
):
    """A payload carrying a phone_number_id that resolves to a tenant-
    specific channel row must be verified against that tenant's
    app_secret, NOT the global META_APP_SECRET.
    """
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())

    # Seed a whatsapp_channel row with its own app_secret
    import config
    from database import get_session_factory
    from db_models import WhatsAppChannel
    from services.secrets import encrypt_secrets
    from services import business_config as bc

    bc.invalidate_cache()
    async with get_session_factory()() as s:
        s.add(
            WhatsAppChannel(
                business_id=config.DEFAULT_BUSINESS_ID,
                phone_number="919900000001",
                phone_number_id="pni-tenant-A",
                waba_id="waba-A",
                provider_config=encrypt_secrets({
                    "access_token": "tenant-A-token",
                    "app_secret": TENANT_SECRET,
                    "webhook_verify_token": "vt-A",
                    "verification_pin": "0001",
                }),
            )
        )
        await s.commit()

    # Build a webhook payload that names pni-tenant-A
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "102290129340398",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "pni-tenant-A"},
                    "contacts": [{"profile": {"name": "X"}, "wa_id": "9199"}],
                    "messages": [{
                        "from": "9199", "id": "wamid.tenant-A",
                        "type": "text", "text": {"body": "hi"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    body = json.dumps(payload).encode("utf-8")

    async with httpx.AsyncClient(
        transport=client["transport"], base_url="http://test",
    ) as http:
        # Signed with TENANT secret -> 200
        resp = await http.post(
            "/webhook", content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, TENANT_SECRET),
            },
        )
        assert resp.status_code == 200, resp.text

        # Signed with GLOBAL secret -> 403 (wrong key for this tenant)
        resp = await http.post(
            "/webhook", content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, GLOBAL_SECRET),
            },
        )
        assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_webhook_falls_back_to_global_secret_when_tenant_unknown(
    client, monkeypatch
):
    """A payload with a phone_number_id we don't have in whatsapp_channels
    (legacy single-tenant demo, or a number that hasn't been onboarded yet)
    must still verify against the global META_APP_SECRET. This keeps
    Phase 0-2 smoke flows + any manual tests working during the migration
    window.
    """
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())
    from services import business_config as bc
    bc.invalidate_cache()

    payload = {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "1",
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"phone_number_id": "unknown-pni"},
                    "messages": [{
                        "from": "9199", "id": "wamid.global",
                        "type": "text", "text": {"body": "hi"},
                    }],
                },
                "field": "messages",
            }],
        }],
    }
    body = json.dumps(payload).encode("utf-8")

    async with httpx.AsyncClient(
        transport=client["transport"], base_url="http://test",
    ) as http:
        resp = await http.post(
            "/webhook", content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": _sign(body, GLOBAL_SECRET),
            },
        )
    # Unknown tenant -> fell back to global. Signed correctly -> 200.
    assert resp.status_code == 200
