"""Webhook verification and signature tests from TESTING.md section 7."""

import hashlib
import hmac

import httpx
import pytest

import config
import main


class _NonMessageChannel:
    """Channel stub that treats all webhook payloads as non-message events."""

    def extract_message(self, payload: dict):
        return None


def _signature(secret: str, raw_body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.mark.asyncio
async def test_webhook_verify_accepts_valid_token(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "verify-token")

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-token",
                "hub.challenge": "12345",
            },
        )

    assert response.status_code == 200
    assert response.text == "12345"


@pytest.mark.asyncio
async def test_webhook_verify_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_VERIFY_TOKEN", "verify-token")

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong-token",
                "hub.challenge": "12345",
            },
        )

    assert response.status_code == 403
    assert response.text == "Forbidden"


@pytest.mark.asyncio
async def test_webhook_post_requires_app_secret_when_whatsapp_enabled(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_ENABLED", True)
    monkeypatch.setattr(config, "META_APP_SECRET", "")

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/webhook", json={"object": "whatsapp_business_account"}
        )

    assert response.status_code == 503
    assert "not configured" in response.text.lower()


@pytest.mark.asyncio
async def test_webhook_post_rejects_invalid_signature(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_ENABLED", True)
    monkeypatch.setattr(config, "META_APP_SECRET", "top-secret")

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/webhook",
            json={"object": "whatsapp_business_account"},
            headers={"X-Hub-Signature-256": "sha256=invalid"},
        )

    assert response.status_code == 403
    assert response.text == "Forbidden"


@pytest.mark.asyncio
async def test_webhook_post_handles_non_message_payload(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_ENABLED", False)
    monkeypatch.setattr(main, "get_channel", lambda: _NonMessageChannel())

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/webhook", json={"object": "whatsapp_business_account"}
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_signature_helper_accepts_valid_hash(monkeypatch):
    monkeypatch.setattr(config, "META_APP_SECRET", "app-secret")
    raw_body = b'{"object":"whatsapp_business_account","entry":[]}'
    valid_signature = _signature(config.META_APP_SECRET, raw_body)

    assert main._is_valid_whatsapp_signature(raw_body, valid_signature) is True
    assert main._is_valid_whatsapp_signature(raw_body, "sha256=bad") is False
    assert main._is_valid_whatsapp_signature(raw_body, None) is False
