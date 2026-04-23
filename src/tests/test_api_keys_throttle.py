"""verify_api_key throttles last_used_at bumps to 1/min/key."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from database import get_session_factory
from db_models import ApiKey
from services.api_keys import mint_api_key, verify_api_key


@pytest.mark.asyncio
async def test_last_used_at_not_bumped_within_60s() -> None:
    """Two verifies <60s apart should touch last_used_at at most once."""
    biz = "demo-sharma-motors"
    minted = await mint_api_key(biz, description="throttle test")

    assert await verify_api_key(minted.plaintext) == biz

    async with get_session_factory()() as s:
        row = await s.get(ApiKey, minted.id)
        first_stamp = row.last_used_at
    assert first_stamp is not None

    # Second verify almost immediately — no DB bump.
    assert await verify_api_key(minted.plaintext) == biz
    async with get_session_factory()() as s:
        row = await s.get(ApiKey, minted.id)
        second_stamp = row.last_used_at
    assert second_stamp == first_stamp, (
        "last_used_at bumped within throttle window"
    )


@pytest.mark.asyncio
async def test_last_used_at_bumped_after_60s() -> None:
    """When the stored last_used_at is past the throttle window, re-bump."""
    biz = "demo-sharma-motors"
    minted = await mint_api_key(biz, description="throttle test 2")

    # Seed last_used_at to 120s in the past.
    stale = datetime.now(timezone.utc) - timedelta(seconds=120)
    async with get_session_factory()() as s:
        row = await s.get(ApiKey, minted.id)
        row.last_used_at = stale
        await s.commit()

    assert await verify_api_key(minted.plaintext) == biz
    async with get_session_factory()() as s:
        row = await s.get(ApiKey, minted.id)
        bumped = row.last_used_at
        # SQLite returns naive datetimes; normalize for comparison.
        if bumped.tzinfo is None:
            bumped = bumped.replace(tzinfo=timezone.utc)
        assert bumped > stale
