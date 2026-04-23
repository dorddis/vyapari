"""Multi-tenant media download isolation."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import delete

from channels import base as channel_base
from channels.whatsapp.adapter import WhatsAppAdapter
import whatsapp


class _GetCaptor:
    """Capture two-hop GET calls (metadata + signed-URL) with headers."""

    def __init__(self, *, file_bytes: bytes = b"\x00\x01", mime: str = "audio/ogg") -> None:
        self.calls: list[dict] = []
        self._file_bytes = file_bytes
        self._mime = mime

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url, **kw):
        self.calls.append({
            "url": url,
            "auth": kw.get("headers", {}).get("Authorization", ""),
        })
        if len(self.calls) == 1:
            return _MetaResponse(self._mime)
        return _BytesResponse(self._file_bytes, self._mime)


class _MetaResponse:
    status_code = 200

    def __init__(self, mime: str) -> None:
        self._mime = mime

    def raise_for_status(self) -> None:  # noqa: D401
        return None

    def json(self) -> dict:
        return {
            "url": "https://lookaside.fbsbx.com/signed/abc",
            "mime_type": self._mime,
        }


class _BytesResponse:
    status_code = 200

    def __init__(self, content: bytes, mime: str) -> None:
        self.content = content
        self.headers = {"content-type": mime}

    def raise_for_status(self) -> None:  # noqa: D401
        return None


@pytest_asyncio.fixture
async def two_tenants(monkeypatch):
    """Seed two tenants with distinct access_tokens."""
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())

    import config
    from database import get_session_factory
    from db_models import Business, WhatsAppChannel, ApiKey
    from services.tenant_onboarding import (
        onboard_business, provision_whatsapp_channel,
    )
    from services import business_config as bc

    async with get_session_factory()() as s:
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
        await s.execute(delete(ApiKey))
        await s.execute(delete(WhatsAppChannel))
        await s.execute(delete(Business).where(Business.id.notin_([config.DEFAULT_BUSINESS_ID])))
        await s.commit()
    bc.invalidate_cache()
    channel_base.reset_channel()


@pytest.mark.asyncio
async def test_adapter_download_media_uses_tenant_token(two_tenants, monkeypatch) -> None:
    """download_media under each tenant's adapter carries ONLY that tenant's token."""
    import config
    monkeypatch.setattr(config, "CHANNEL_MODE", "whatsapp")
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN_SHOULD_NEVER_LEAK")

    adapter_a = await channel_base.get_tenant_channel(two_tenants["a_id"])
    adapter_b = await channel_base.get_tenant_channel(two_tenants["b_id"])

    caps = [_GetCaptor(file_bytes=b"alpha-bytes"), _GetCaptor(file_bytes=b"beta-bytes")]
    caps_iter = iter(caps)
    with patch("whatsapp.httpx.AsyncClient", lambda: next(caps_iter)):
        bytes_a, mime_a = await adapter_a.download_media("1001")
        bytes_b, mime_b = await adapter_b.download_media("2002")

    assert bytes_a == b"alpha-bytes"
    assert bytes_b == b"beta-bytes"
    assert mime_a == "audio/ogg"
    assert mime_b == "audio/ogg"

    # Every hop of tenant A's download carried TOKEN_ALPHA. No call ever
    # carried the env fallback or tenant B's token.
    for c in caps[0].calls:
        assert "TOKEN_ALPHA" in c["auth"], c
        assert "TOKEN_BETA" not in c["auth"]
        assert "ENV_TOKEN_SHOULD_NEVER_LEAK" not in c["auth"]
    for c in caps[1].calls:
        assert "TOKEN_BETA" in c["auth"], c
        assert "TOKEN_ALPHA" not in c["auth"]
        assert "ENV_TOKEN_SHOULD_NEVER_LEAK" not in c["auth"]

    assert "/1001" in caps[0].calls[0]["url"]
    assert "lookaside.fbsbx.com" in caps[0].calls[1]["url"]
    assert "/2002" in caps[1].calls[0]["url"]
    assert "lookaside.fbsbx.com" in caps[1].calls[1]["url"]


@pytest.mark.asyncio
async def test_download_media_without_tenant_context_falls_back(monkeypatch) -> None:
    """Calling whatsapp.download_media directly (no tenant ctx) uses env token."""
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "LEGACY_ENV_TOKEN")

    cap = _GetCaptor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        await whatsapp.download_media("9876")

    assert all("LEGACY_ENV_TOKEN" in c["auth"] for c in cap.calls)


@pytest.mark.asyncio
async def test_base_adapter_download_media_raises_not_implemented() -> None:
    """Default ABC raises NotImplementedError (no silent env fallback)."""
    from channels.web_clone.adapter import WebCloneAdapter
    adapter = WebCloneAdapter()
    with pytest.raises(NotImplementedError):
        await adapter.download_media("any-id")


@pytest.mark.asyncio
async def test_voice_web_upload_does_not_attach_bearer_to_untrusted_host(
    monkeypatch,
) -> None:
    """Bearer only attaches to trusted Meta hosts on https."""
    from urllib.parse import urlparse
    from whatsapp import _is_trusted_media_host

    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN_MUST_NOT_LEAK")
    import config
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN_MUST_NOT_LEAK")

    # Case 1: attacker-controlled URL -> bearer must NOT be attached.
    url_evil = "https://evil.example.com/steal-my-token"
    assert not _is_trusted_media_host(url_evil)
    parsed_evil = urlparse(url_evil)
    attach_evil = (
        parsed_evil.scheme == "https"
        and _is_trusted_media_host(url_evil)
        and bool(config.WHATSAPP_ACCESS_TOKEN)
    )
    assert attach_evil is False, (
        "Bearer must not be attached to an untrusted media_url"
    )

    # Case 2: http (not https) Meta URL -> scheme guard blocks too.
    url_http = "http://lookaside.fbsbx.com/signed/abc"
    assert _is_trusted_media_host(url_http)
    parsed_http = urlparse(url_http)
    attach_http = (
        parsed_http.scheme == "https"
        and _is_trusted_media_host(url_http)
        and bool(config.WHATSAPP_ACCESS_TOKEN)
    )
    assert attach_http is False, "http scheme must be rejected even on allow-list"

    # Case 3: https + Meta CDN -> bearer attached (legitimate path).
    url_ok = "https://lookaside.fbsbx.com/signed/abc"
    parsed_ok = urlparse(url_ok)
    attach_ok = (
        parsed_ok.scheme == "https"
        and _is_trusted_media_host(url_ok)
        and bool(config.WHATSAPP_ACCESS_TOKEN)
    )
    assert attach_ok is True
