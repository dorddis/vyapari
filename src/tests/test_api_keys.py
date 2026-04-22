"""Tests for services/api_keys.py — per-business REST API key auth."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import config
from services.api_keys import (
    list_api_keys,
    mint_api_key,
    revoke_api_key,
    verify_api_key,
    _hash_key,
)


BIZ = config.DEFAULT_BUSINESS_ID


@pytest.mark.asyncio
async def test_mint_returns_plaintext_and_hash_is_stored():
    minted = await mint_api_key(BIZ, description="test key")
    assert minted.plaintext and len(minted.plaintext) >= 40
    assert minted.key_prefix == minted.plaintext[:8]
    assert minted.business_id == BIZ
    # The DB stores only the hash.
    rows = await list_api_keys(BIZ)
    assert any(r.key_hash == _hash_key(minted.plaintext) for r in rows)


@pytest.mark.asyncio
async def test_verify_api_key_returns_business_id():
    minted = await mint_api_key(BIZ)
    assert await verify_api_key(minted.plaintext) == BIZ


@pytest.mark.asyncio
async def test_verify_api_key_unknown_key_returns_none():
    assert await verify_api_key("completely-unknown-key-xxx") is None


@pytest.mark.asyncio
async def test_verify_api_key_empty_returns_none():
    assert await verify_api_key("") is None


@pytest.mark.asyncio
async def test_revoked_key_fails_verification():
    minted = await mint_api_key(BIZ)
    assert await verify_api_key(minted.plaintext) == BIZ
    ok = await revoke_api_key(minted.id)
    assert ok is True
    assert await verify_api_key(minted.plaintext) is None
    # Revoking twice is a no-op.
    assert await revoke_api_key(minted.id) is False


@pytest.mark.asyncio
async def test_each_key_is_unique_plaintext():
    m1 = await mint_api_key(BIZ)
    m2 = await mint_api_key(BIZ)
    assert m1.plaintext != m2.plaintext
    assert m1.id != m2.id


@pytest.mark.asyncio
async def test_last_used_at_bumps_on_verify():
    minted = await mint_api_key(BIZ)
    await verify_api_key(minted.plaintext)
    rows = await list_api_keys(BIZ)
    row = next(r for r in rows if r.id == minted.id)
    assert row.last_used_at is not None
    now = datetime.now(timezone.utc)
    # Normalize naive timestamps from SQLite
    last = row.last_used_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    assert (now - last) < timedelta(seconds=5)


@pytest.mark.asyncio
async def test_cross_tenant_lookup_independent():
    """Two tenants each mint a key. Verifying tenant-A's plaintext must
    never resolve to tenant-B's business_id."""
    from database import get_session_factory
    from db_models import Business
    # Seed a second business
    async with get_session_factory()() as s:
        existing = await s.get(Business, "biz-b")
        if existing is None:
            s.add(Business(id="biz-b", name="Other Business", owner_phone="9122"))
            await s.commit()

    m_a = await mint_api_key(BIZ)
    m_b = await mint_api_key("biz-b")

    assert await verify_api_key(m_a.plaintext) == BIZ
    assert await verify_api_key(m_b.plaintext) == "biz-b"
    # Crossed plaintexts never match
    assert await verify_api_key(m_a.plaintext[:-1] + "x") is None
