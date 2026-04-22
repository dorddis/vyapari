"""Tests for services/business_config.py — tenant context loader + cache.

Covers:
- load_business_context happy path returns decrypted creds
- caching: second call within TTL does not re-query the DB
- invalidate_cache drops one tenant / all tenants
- BusinessNotFoundError when business_id is unknown
- NoActiveChannelError when business exists but channel row is missing
- resolve_business_id_from_phone_number_id hits + misses
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import delete

import config
from database import get_session_factory
from db_models import Business, WhatsAppChannel
from services import business_config as bc
from services.secrets import encrypt_secrets


BIZ = config.DEFAULT_BUSINESS_ID


@pytest_asyncio.fixture(autouse=True)
async def _per_test_setup(monkeypatch):
    """Seed an encryption key + wipe channel + business-config caches."""
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())
    # Wipe channel rows between tests (the Business row is seeded by conftest).
    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    bc.invalidate_cache()
    yield
    bc.invalidate_cache()


async def _make_channel(
    business_id: str = BIZ,
    phone_number: str = "919876543210",
    phone_number_id: str = "pni-default",
    waba_id: str = "waba-default",
    access_token: str = "EAAG_test_token",
    app_secret: str = "meta-app-secret",
) -> WhatsAppChannel:
    blob = encrypt_secrets(
        {
            "access_token": access_token,
            "app_secret": app_secret,
            "webhook_verify_token": "vt",
            "verification_pin": "0000",
        }
    )
    async with get_session_factory()() as s:
        ch = WhatsAppChannel(
            business_id=business_id,
            phone_number=phone_number,
            phone_number_id=phone_number_id,
            waba_id=waba_id,
            provider_config=blob,
            source="manual",
        )
        s.add(ch)
        await s.commit()
        await s.refresh(ch)
    return ch


# ---------------------------------------------------------------------------
# load_business_context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_business_context_happy_path():
    await _make_channel()
    ctx = await bc.load_business_context(BIZ)
    assert ctx.business_id == BIZ
    assert ctx.phone_number_id == "pni-default"
    assert ctx.access_token == "EAAG_test_token"
    assert ctx.app_secret == "meta-app-secret"
    assert ctx.waba_id == "waba-default"
    assert ctx.source == "manual"


@pytest.mark.asyncio
async def test_load_business_context_unknown_business_raises():
    with pytest.raises(bc.BusinessNotFoundError) as exc_info:
        await bc.load_business_context("nonexistent-biz")
    assert exc_info.value.business_id == "nonexistent-biz"


@pytest.mark.asyncio
async def test_load_business_context_no_channel_raises():
    # Business row exists (seeded by conftest) but no channel.
    with pytest.raises(bc.NoActiveChannelError) as exc_info:
        await bc.load_business_context(BIZ)
    assert exc_info.value.business_id == BIZ


@pytest.mark.asyncio
async def test_load_business_context_returns_latest_channel():
    """If multiple channels exist for the same business (e.g., re-onboarded),
    the most recently created one wins."""
    await _make_channel(phone_number_id="old-pni", phone_number="919111111111")
    await _make_channel(phone_number_id="new-pni", phone_number="919222222222",
                        access_token="EAAG_newer_token")
    bc.invalidate_cache()  # defeat the index cached by _make_channel reads
    ctx = await bc.load_business_context(BIZ)
    assert ctx.phone_number_id == "new-pni"
    assert ctx.access_token == "EAAG_newer_token"


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_business_context_caches_result(monkeypatch):
    """Two calls within TTL should hit the cache, not the DB."""
    await _make_channel()

    # Spy on select() invocations by patching the session's execute method.
    import services.business_config as bc_mod
    real_get_session_factory = bc_mod.get_session_factory

    call_counter = {"n": 0}

    def counting_factory():
        real = real_get_session_factory()

        class _Wrap:
            def __init__(self): self._inner = real()
            async def __aenter__(self):
                self._s = await self._inner.__aenter__()
                return self._s
            async def __aexit__(self, *a): return await self._inner.__aexit__(*a)

        return _Wrap()

    # We can't easily spy on DB hits without a real ORM interceptor; use a
    # call count on the outermost load_business_context internals instead.
    # Simpler: verify the cache by checking _cache is populated after call 1
    # and that _cache's tuple is returned unchanged on call 2.
    ctx1 = await bc.load_business_context(BIZ)
    assert BIZ in bc._cache

    # Mutate the DB behind the cache's back; cache should still serve stale.
    async with get_session_factory()() as s:
        stmt = (await s.execute(
            __import__("sqlalchemy").select(WhatsAppChannel).where(
                WhatsAppChannel.business_id == BIZ
            )
        ))
        row = stmt.scalar_one()
        row.source = "embedded_signup"
        await s.commit()

    ctx2 = await bc.load_business_context(BIZ)
    # Still 'manual' from the cached snapshot.
    assert ctx2.source == "manual"
    assert ctx2 is ctx1  # cache returns same frozen object


@pytest.mark.asyncio
async def test_invalidate_cache_single_tenant():
    await _make_channel()
    ctx1 = await bc.load_business_context(BIZ)
    bc.invalidate_cache(BIZ)
    assert BIZ not in bc._cache


@pytest.mark.asyncio
async def test_invalidate_cache_all():
    await _make_channel()
    await bc.load_business_context(BIZ)
    assert BIZ in bc._cache
    bc.invalidate_cache(None)
    assert bc._cache == {}
    assert bc._pnid_index == {}


# ---------------------------------------------------------------------------
# resolve_business_id_from_phone_number_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_pnid_hits_existing_channel():
    await _make_channel(phone_number_id="pni-xyz")
    result = await bc.resolve_business_id_from_phone_number_id("pni-xyz")
    assert result == BIZ


@pytest.mark.asyncio
async def test_resolve_pnid_miss_returns_none():
    result = await bc.resolve_business_id_from_phone_number_id("never-existed")
    assert result is None


@pytest.mark.asyncio
async def test_resolve_pnid_empty_string_returns_none():
    assert await bc.resolve_business_id_from_phone_number_id("") is None


@pytest.mark.asyncio
async def test_resolve_pnid_caches():
    await _make_channel(phone_number_id="pni-cached")
    # First call seeds the cache
    bid = await bc.resolve_business_id_from_phone_number_id("pni-cached")
    assert bid == BIZ
    assert "pni-cached" in bc._pnid_index
    # Remove the DB row while cache is hot
    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    # Cached hit still resolves (stale-but-serving)
    assert await bc.resolve_business_id_from_phone_number_id("pni-cached") == BIZ
