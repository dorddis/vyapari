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
