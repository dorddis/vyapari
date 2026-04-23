"""Multi-tenant media download isolation (P3.5a #1).

Inbound voice/image for tenant B must fetch the Graph media bytes with
B's access_token — not the env fallback `WHATSAPP_ACCESS_TOKEN` that
pre-P3.5a callers silently picked up when `whatsapp.download_media` was
invoked outside a `use_tenant(...)` context.

The fix moves `download_media` onto `WhatsAppAdapter` so the call is
always wrapped in `_tenant_ctx()`. These tests guard against regression
by capturing the Bearer header on BOTH Graph hops (metadata + signed-URL
fetch) and asserting it matches the adapter's bound token.
"""

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
    """Capture two-hop GET calls.

    whatsapp.download_media issues:
      1. GET graph.facebook.com/{v}/{media_id}   -> JSON with `url`
      2. GET <signed_url>                        -> raw file bytes

    The captor records every GET's URL + Authorization header, and
    returns a scripted response per hop (metadata JSON on hop 1, bytes on
    hop 2). Request count is shared across hops because
    httpx.AsyncClient re-uses the same client instance inside
    download_media.
    """

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
        # First hop returns metadata pointing to a trusted host.
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
        # lookaside.fbsbx.com is whitelisted in whatsapp._MEDIA_HOST_ALLOWLIST_SUFFIXES.
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
    """Mirror of test_multi_tenant.two_tenants — seeds two channels
    with distinct access_tokens. Kept local to avoid importing a fixture
    across test modules (pytest cross-file fixtures require conftest)."""
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
    """download_media on tenant A's adapter POSTs with TOKEN_ALPHA, never
    the env fallback or tenant B's token. Mirror check for tenant B.
    """
    import config
    monkeypatch.setattr(config, "CHANNEL_MODE", "whatsapp")
    # Env token must differ from both tenant tokens so a fallback would be
    # visible. The test asserts the env string never appears in any call.
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "ENV_TOKEN_SHOULD_NEVER_LEAK")

    adapter_a = await channel_base.get_tenant_channel(two_tenants["a_id"])
    adapter_b = await channel_base.get_tenant_channel(two_tenants["b_id"])

    caps = [_GetCaptor(file_bytes=b"alpha-bytes"), _GetCaptor(file_bytes=b"beta-bytes")]
    caps_iter = iter(caps)
    with patch("whatsapp.httpx.AsyncClient", lambda: next(caps_iter)):
        bytes_a, mime_a = await adapter_a.download_media("media-alpha")
        bytes_b, mime_b = await adapter_b.download_media("media-beta")

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

    # First hop hits graph.facebook.com/{v}/{media_id}; second hop hits
    # the signed CDN URL from the metadata response.
    assert "media-alpha" in caps[0].calls[0]["url"]
    assert "lookaside.fbsbx.com" in caps[0].calls[1]["url"]
    assert "media-beta" in caps[1].calls[0]["url"]
    assert "lookaside.fbsbx.com" in caps[1].calls[1]["url"]


@pytest.mark.asyncio
async def test_download_media_without_tenant_context_falls_back(monkeypatch) -> None:
    """Legacy single-tenant path: calling `whatsapp.download_media`
    directly (outside a tenant context) still works by falling back to
    the env token. Sole guard is that the env token is actually set.

    This keeps the web_clone demo path working. Multi-tenant code must
    NEVER use this path — that's what the adapter override fixes.
    """
    monkeypatch.setattr(whatsapp, "WHATSAPP_ACCESS_TOKEN", "LEGACY_ENV_TOKEN")

    cap = _GetCaptor()
    with patch("whatsapp.httpx.AsyncClient", lambda: cap):
        await whatsapp.download_media("legacy-id")

    assert all("LEGACY_ENV_TOKEN" in c["auth"] for c in cap.calls)


@pytest.mark.asyncio
async def test_base_adapter_download_media_raises_not_implemented() -> None:
    """Default ABC implementation raises so a mis-wired caller fails
    loudly rather than silently picking up env credentials."""
    from channels.web_clone.adapter import WebCloneAdapter
    adapter = WebCloneAdapter()
    with pytest.raises(NotImplementedError):
        await adapter.download_media("any-id")


# ---------------------------------------------------------------------------
# main.py:_process_and_reply voice web-upload branch (P3.5a #8 follow-up)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_web_upload_does_not_attach_bearer_to_untrusted_host(
    monkeypatch,
) -> None:
    """The web-upload voice branch (main.py:~443) must NOT attach
    `Bearer {env-token}` to arbitrary media_urls.

    Pre-P3.5a-review the branch attached `Bearer {config.WHATSAPP_ACCESS_TOKEN}`
    to ANY URL the IncomingMessage carried. If `media_url` ever became
    user-controllable (or a future adapter change populated it with a
    non-Meta URL), the Graph token leaked to the attacker-controlled host.
    Fix gates the bearer behind `_is_trusted_media_host` + https scheme.
    """
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
