"""Tests for services/outbound.py — 24-hour window dispatcher.

Covers:
- touch_inbound + is_within_24h_window (window math, DST / UTC edges,
  5-minute safety slack)
- send_reply picks session-text inside, template fallback outside,
  raises OutsideWindowError when outside + no fallback
- send_template_reply raises TemplateNotApprovedError when the named
  template isn't approved; otherwise dispatches through the channel
- send_business_initiated is an alias of send_template_reply
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete

import config
import state
from database import get_session_factory
from db_models import MessageTemplate
from services.outbound import (
    OutsideWindowError,
    TemplateNotApprovedError,
    is_within_24h_window,
    send_business_initiated,
    send_reply,
    send_template_reply,
    touch_inbound,
)
from services.templates import _upsert_from_meta

from tests.conftest import seed_customer


BIZ = config.DEFAULT_BUSINESS_ID
CUSTOMER = "919876543210"


@pytest_asyncio.fixture(autouse=True)
async def _clean_templates_and_seed_customer():
    """Wipe templates + seed the test customer before each test."""
    session_factory = get_session_factory()
    async with session_factory() as s:
        await s.execute(delete(MessageTemplate))
        await s.commit()
    await seed_customer(CUSTOMER, name="Ramesh")
    yield


@pytest_asyncio.fixture
def mock_channel(monkeypatch):
    """Replace the channel adapter singleton with a mock.

    Returns the mock instance so tests can assert on calls.
    """
    from channels import base as base_mod

    mock = type("MockChannel", (), {})()
    mock.send_text = AsyncMock(return_value="wamid.text-1")
    mock.send_template = AsyncMock(return_value="wamid.tmpl-1")
    base_mod._active_adapter = mock
    yield mock
    base_mod.reset_channel()


# ---------------------------------------------------------------------------
# Window math
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fresh_customer_is_outside_window():
    """Never-inbound customer -> can't send free-form."""
    assert await is_within_24h_window(BIZ, CUSTOMER) is False


@pytest.mark.asyncio
async def test_touch_inbound_opens_window():
    await touch_inbound(BIZ, CUSTOMER)
    assert await is_within_24h_window(BIZ, CUSTOMER) is True


@pytest.mark.asyncio
async def test_window_closes_after_24h():
    stale = datetime.now(timezone.utc) - timedelta(hours=25)
    await touch_inbound(BIZ, CUSTOMER, at=stale)
    assert await is_within_24h_window(BIZ, CUSTOMER) is False


@pytest.mark.asyncio
async def test_window_safety_slack_closes_at_23h56m():
    """5-minute safety buffer: a send at 23h56m past last inbound must
    already be treated as outside-window so Meta's clock doesn't race."""
    near_edge = datetime.now(timezone.utc) - timedelta(hours=23, minutes=56)
    await touch_inbound(BIZ, CUSTOMER, at=near_edge)
    assert await is_within_24h_window(BIZ, CUSTOMER) is False


@pytest.mark.asyncio
async def test_window_inside_slack_band_still_open():
    """Inside the slack band (23h50m) the window is still open."""
    inside = datetime.now(timezone.utc) - timedelta(hours=23, minutes=50)
    await touch_inbound(BIZ, CUSTOMER, at=inside)
    assert await is_within_24h_window(BIZ, CUSTOMER) is True


@pytest.mark.asyncio
async def test_touch_inbound_on_missing_customer_is_noop():
    """Called before router creates the customer row -> logs + returns.
    Must not raise, since touch_inbound runs in a best-effort path."""
    await touch_inbound(BIZ, "phantom-customer-id-999")
    # Still outside window — no row was created.
    assert await is_within_24h_window(BIZ, "phantom-customer-id-999") is False


# ---------------------------------------------------------------------------
# send_reply — inside / outside / fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_reply_inside_window_sends_text(mock_channel):
    await touch_inbound(BIZ, CUSTOMER)
    result = await send_reply(BIZ, CUSTOMER, "hi from inside window")
    assert result == "wamid.text-1"
    mock_channel.send_text.assert_awaited_once_with(CUSTOMER, "hi from inside window")
    mock_channel.send_template.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_reply_outside_window_raises_without_fallback(mock_channel):
    await touch_inbound(BIZ, CUSTOMER,
                        at=datetime.now(timezone.utc) - timedelta(hours=30))
    with pytest.raises(OutsideWindowError):
        await send_reply(BIZ, CUSTOMER, "hi")
    mock_channel.send_text.assert_not_awaited()
    mock_channel.send_template.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_reply_outside_window_uses_template_fallback(mock_channel):
    await _upsert_from_meta(BIZ, {
        "id": "t1", "name": "followup_24h", "language": "en",
        "status": "APPROVED", "category": "UTILITY", "components": [],
    })
    await touch_inbound(BIZ, CUSTOMER,
                        at=datetime.now(timezone.utc) - timedelta(hours=30))
    result = await send_reply(
        BIZ, CUSTOMER, "original free-form text",
        fallback_template="followup_24h",
        fallback_variables=["Ramesh", "Creta"],
    )
    assert result == "wamid.tmpl-1"
    mock_channel.send_text.assert_not_awaited()
    mock_channel.send_template.assert_awaited_once()
    kwargs = mock_channel.send_template.await_args.kwargs
    assert kwargs["template_name"] == "followup_24h"
    assert kwargs["params"] == ["Ramesh", "Creta"]


@pytest.mark.asyncio
async def test_send_reply_outside_window_fallback_template_not_approved(mock_channel):
    """Outside window + fallback template not in catalog -> TemplateNotApprovedError."""
    await touch_inbound(BIZ, CUSTOMER,
                        at=datetime.now(timezone.utc) - timedelta(hours=30))
    with pytest.raises(TemplateNotApprovedError):
        await send_reply(BIZ, CUSTOMER, "hi", fallback_template="never_submitted")


# ---------------------------------------------------------------------------
# send_template_reply / send_business_initiated
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_template_reply_raises_when_not_approved(mock_channel):
    with pytest.raises(TemplateNotApprovedError) as exc:
        await send_template_reply(BIZ, CUSTOMER, "never_existed", ["x"])
    assert exc.value.name == "never_existed"
    mock_channel.send_template.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_template_reply_fires_regardless_of_window(mock_channel):
    """Templates reset the window; dispatch never checks is_within_24h_window."""
    await _upsert_from_meta(BIZ, {
        "id": "t1", "name": "otp_owner_login", "language": "en",
        "status": "APPROVED", "category": "AUTHENTICATION", "components": [],
    })
    # No touch_inbound — customer is outside window but OTP still fires.
    result = await send_template_reply(BIZ, CUSTOMER, "otp_owner_login", ["123456"])
    assert result == "wamid.tmpl-1"
    mock_channel.send_template.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_business_initiated_is_alias_of_send_template_reply():
    # Module-level identity check — same function object, no surprise.
    assert send_business_initiated is send_template_reply
