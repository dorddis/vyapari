"""Tests for Phase 3.6 DB-backed webhook idempotency.

The in-memory `_processed_msg_ids` cache is best-effort; the
authoritative dedup store is the `processed_messages` table. These
tests bypass the cache to exercise the DB path directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import state
from db_models import ProcessedMessage
from database import get_session_factory


@pytest.fixture(autouse=True)
def _wipe_l1_cache():
    """The L1 cache is a module-global; clear it between tests."""
    state._processed_msg_ids.clear()
    yield
    state._processed_msg_ids.clear()


@pytest.mark.asyncio
async def test_mark_and_check_same_business():
    await state.mark_message_processed("wamid.x", business_id="biz-a")
    assert await state.is_message_processed("wamid.x", business_id="biz-a") is True


@pytest.mark.asyncio
async def test_different_business_not_deduped():
    """Same wamid in two tenants are independent events."""
    await state.mark_message_processed("wamid.collide", business_id="biz-a")
    assert await state.is_message_processed("wamid.collide", business_id="biz-b") is False


@pytest.mark.asyncio
async def test_is_message_processed_hits_db_without_l1_cache():
    """Simulate a fresh replica: DB row exists, L1 cache empty."""
    await state.mark_message_processed("wamid.y", business_id="biz-a")
    # Clear the in-process cache — the next check must hit the DB.
    state._processed_msg_ids.clear()
    assert await state.is_message_processed("wamid.y", business_id="biz-a") is True


@pytest.mark.asyncio
async def test_mark_twice_is_noop_not_error():
    """Race: two replicas mark_message_processed with the same key.
    The second one's INSERT collides on the PK; the call must not
    propagate an exception."""
    await state.mark_message_processed("wamid.dup", business_id="biz-a")
    # Clear cache so the second call doesn't short-circuit before DB.
    state._processed_msg_ids.clear()
    # Must not raise.
    await state.mark_message_processed("wamid.dup", business_id="biz-a")


@pytest.mark.asyncio
async def test_cleanup_processed_messages_drops_old_rows():
    await state.mark_message_processed("wamid.fresh", business_id="biz-a")
    await state.mark_message_processed("wamid.stale", business_id="biz-a")

    # Backdate one row
    async with get_session_factory()() as s:
        from sqlalchemy import update
        await s.execute(
            update(ProcessedMessage)
            .where(ProcessedMessage.wa_msg_id == "wamid.stale")
            .values(processed_at=datetime.now(timezone.utc) - timedelta(hours=72))
        )
        await s.commit()

    removed = await state.cleanup_processed_messages(older_than_hours=48)
    assert removed == 1

    async with get_session_factory()() as s:
        from sqlalchemy import select
        names = (await s.execute(select(ProcessedMessage.wa_msg_id))).scalars().all()
    assert "wamid.fresh" in names
    assert "wamid.stale" not in names


@pytest.mark.asyncio
async def test_is_message_processed_default_business_id():
    """Legacy call with no business_id defaults to the bootstrap id.
    Exercising this path keeps Phase 0-2 callers working during the
    gradual multi-tenant rollout."""
    await state.mark_message_processed("wamid.legacy")
    assert await state.is_message_processed("wamid.legacy") is True
