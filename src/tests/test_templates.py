"""Tests for services/templates.py — register / sync / lookup.

Uses the in-memory SQLite from conftest.py. Mocks httpx at call sites
that would hit the Graph API.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete

import config
from database import get_session_factory
from db_models import MessageTemplate
from services import templates as svc
from services.templates import (
    _normalize_status,
    _upsert_from_meta,
    get_approved_template,
    list_templates,
    register_template,
    sync_templates,
)


BIZ = config.DEFAULT_BUSINESS_ID


@pytest_asyncio.fixture(autouse=True)
async def _clean_templates():
    """Wipe message_templates between tests.

    conftest.clean_state resets most state tables but was authored before
    Phase 2 added message_templates. Scope the cleanup to this module
    to avoid touching the global fixture.
    """
    session_factory = get_session_factory()
    async with session_factory() as s:
        await s.execute(delete(MessageTemplate))
        await s.commit()
    yield


class _MockResponse:
    def __init__(self, body: dict, *, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code
        # _raise_if_graph_error reads .content to decide whether to parse
        # JSON; .text is only used when JSON parsing fails.
        self.content = b"{}" if body is not None else b""
        self.text = ""

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:  # pragma: no cover — unused now
        return None


class _MockClient:
    def __init__(self, *, post_body: dict | None = None,
                 get_pages: list[dict] | None = None) -> None:
        self.post_body = post_body or {}
        self.get_pages = list(get_pages or [])
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kwargs):
        self.posts.append({"url": url, "json": kwargs.get("json")})
        return _MockResponse(self.post_body)

    async def get(self, url, **kwargs):
        self.gets.append({"url": url, "params": kwargs.get("params")})
        if not self.get_pages:
            return _MockResponse({"data": [], "paging": {}})
        return _MockResponse(self.get_pages.pop(0))


# ---------------------------------------------------------------------------
# _normalize_status — enum mapping from Meta's uppercase values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("meta_status,expected", [
    ("APPROVED", "approved"),
    ("PENDING", "pending"),
    ("REJECTED", "rejected"),
    ("PAUSED", "paused"),
    ("DISABLED", "disabled"),
    # "scheduled for deletion" must not be sendable; maps to DISABLED
    # so the dispatcher treats it as unavailable (not "Meta may re-enable").
    ("PENDING_DELETION", "disabled"),
    ("DELETED", "disabled"),
    ("IN_APPEAL", "pending"),
    ("LIMIT_EXCEEDED", "paused"),
    ("UNKNOWN_FUTURE_VALUE", "pending"),
    (None, "pending"),
    ("", "pending"),
])
def test_normalize_status(meta_status, expected):
    assert _normalize_status(meta_status) == expected


# ---------------------------------------------------------------------------
# _upsert_from_meta — DB upserts; unique (business_id, name, language)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_from_meta_inserts_new_row():
    await _upsert_from_meta(BIZ, {
        "id": "tpl-1", "name": "followup_24h", "language": "en",
        "status": "PENDING", "category": "UTILITY", "components": [],
    })
    rows = await list_templates(BIZ)
    assert len(rows) == 1
    assert rows[0].name == "followup_24h"
    assert rows[0].status == "pending"
    assert rows[0].meta_template_id == "tpl-1"


@pytest.mark.asyncio
async def test_upsert_from_meta_updates_existing_row():
    await _upsert_from_meta(BIZ, {
        "id": "tpl-1", "name": "followup_24h", "language": "en",
        "status": "PENDING", "category": "UTILITY", "components": [],
    })
    # Same (name, language) -> update not insert
    await _upsert_from_meta(BIZ, {
        "id": "tpl-1", "name": "followup_24h", "language": "en",
        "status": "APPROVED", "category": "UTILITY",
        "components": [{"type": "BODY", "text": "Hi"}],
    })
    rows = await list_templates(BIZ)
    assert len(rows) == 1
    assert rows[0].status == "approved"
    assert rows[0].components == [{"type": "BODY", "text": "Hi"}]


@pytest.mark.asyncio
async def test_upsert_from_meta_stores_rejection_reason():
    await _upsert_from_meta(BIZ, {
        "id": "tpl-1", "name": "risky", "language": "en",
        "status": "REJECTED", "category": "MARKETING",
        "reason": "Violates Meta policy on unsolicited outreach.",
        "components": [],
    })
    rows = await list_templates(BIZ)
    assert rows[0].status == "rejected"
    assert "Violates" in rows[0].rejected_reason


# ---------------------------------------------------------------------------
# get_approved_template / list_templates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_approved_template_returns_only_approved():
    await _upsert_from_meta(BIZ, {
        "id": "tpl-p", "name": "pending_one", "language": "en",
        "status": "PENDING", "category": "UTILITY", "components": [],
    })
    await _upsert_from_meta(BIZ, {
        "id": "tpl-a", "name": "approved_one", "language": "en",
        "status": "APPROVED", "category": "UTILITY", "components": [],
    })
    assert await get_approved_template(BIZ, "pending_one", "en") is None
    assert await get_approved_template(BIZ, "approved_one", "en") is not None
    # Wrong language -> None
    assert await get_approved_template(BIZ, "approved_one", "hi") is None


@pytest.mark.asyncio
async def test_list_templates_filters_by_status():
    await _upsert_from_meta(BIZ, {
        "id": "a", "name": "a", "language": "en", "status": "APPROVED",
        "category": "UTILITY", "components": [],
    })
    await _upsert_from_meta(BIZ, {
        "id": "r", "name": "r", "language": "en", "status": "REJECTED",
        "category": "UTILITY", "components": [],
    })
    all_rows = await list_templates(BIZ)
    approved = await list_templates(BIZ, status="approved")
    assert len(all_rows) == 2
    assert len(approved) == 1
    assert approved[0].name == "a"


# ---------------------------------------------------------------------------
# register_template — submits + persists; no waba -> raises
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_register_template_submits_and_persists(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "waba-1")
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "tok")
    cap = _MockClient(post_body={"id": "meta-id-1", "status": "PENDING",
                                 "category": "UTILITY"})
    with patch("services.templates.httpx.AsyncClient", lambda: cap):
        row = await register_template(
            business_id=BIZ, name="welcome", language="en",
            components=[{"type": "BODY", "text": "Hi"}],
        )
    assert row.meta_template_id == "meta-id-1"
    assert row.status == "pending"
    assert row.components == [{"type": "BODY", "text": "Hi"}]
    # Posted URL matches /{waba}/message_templates
    assert cap.posts[0]["url"].endswith("/waba-1/message_templates")


@pytest.mark.asyncio
async def test_register_template_local_upsert_on_same_name(monkeypatch):
    """If the caller (or a future retry loop) invokes register_template
    twice AND Meta accepts both calls (test-only scenario — real Meta
    rejects duplicates with 2388023; covered separately in
    test_register_template_graph_error_raises_structured), the local row
    should be updated in place rather than a new row inserted.

    This is purely a unit test of the upsert's unique-constraint path.
    """
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "waba-1")
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "tok")
    cap = _MockClient(post_body={"id": "meta-v1", "status": "PENDING",
                                 "category": "UTILITY"})
    with patch("services.templates.httpx.AsyncClient", lambda: cap):
        await register_template(BIZ, "welcome", "en",
                                [{"type": "BODY", "text": "v1"}])

    cap2 = _MockClient(post_body={"id": "meta-v2", "status": "PENDING",
                                  "category": "UTILITY"})
    with patch("services.templates.httpx.AsyncClient", lambda: cap2):
        row = await register_template(BIZ, "welcome", "en",
                                      [{"type": "BODY", "text": "v2"}])

    rows = await list_templates(BIZ)
    # Still just one row (unique constraint); updated to v2 content
    assert len(rows) == 1
    assert row.components == [{"type": "BODY", "text": "v2"}]
    # Rejection reason cleared on re-submit (PENDING starts fresh)
    assert row.rejected_reason is None


@pytest.mark.asyncio
async def test_register_template_raises_when_waba_unset(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "")
    with pytest.raises(RuntimeError, match="WHATSAPP_BUSINESS_ACCOUNT_ID"):
        await register_template(BIZ, "n", "en", [])


# ---------------------------------------------------------------------------
# sync_templates — paginated GET, upserts, tolerates per-row errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sync_templates_single_page(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "waba-1")
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "tok")
    cap = _MockClient(get_pages=[
        {"data": [
            {"id": "t1", "name": "a", "language": "en", "status": "APPROVED",
             "category": "UTILITY", "components": []},
            {"id": "t2", "name": "b", "language": "en", "status": "PENDING",
             "category": "MARKETING", "components": []},
        ], "paging": {}},
    ])
    with patch("services.templates.httpx.AsyncClient", lambda: cap):
        n = await sync_templates(BIZ)
    assert n == 2
    rows = await list_templates(BIZ)
    assert {r.name for r in rows} == {"a", "b"}


@pytest.mark.asyncio
async def test_sync_templates_breaks_on_stuck_cursor(monkeypatch):
    """If Meta ever returns the same cursor twice, break — don't infinite-loop."""
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "waba-1")
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "tok")
    cap = _MockClient(get_pages=[
        {"data": [{"id": "t1", "name": "a", "language": "en", "status": "APPROVED",
                   "category": "UTILITY", "components": []}],
         "paging": {"cursors": {"after": "stuck"}, "next": "https://.../next"}},
        {"data": [{"id": "t2", "name": "b", "language": "en", "status": "APPROVED",
                   "category": "UTILITY", "components": []}],
         "paging": {"cursors": {"after": "stuck"}, "next": "https://.../next"}},
        # If the break condition is broken, a 3rd page would be requested
        # and MockClient.get_pages would run out -> default empty payload.
    ])
    with patch("services.templates.httpx.AsyncClient", lambda: cap):
        n = await sync_templates(BIZ)
    # First page written fully, second page written, third page refused.
    assert n == 2
    # Exactly 2 GETs: first seeds cursor='stuck', second sees no advance.
    assert len(cap.gets) == 2


@pytest.mark.asyncio
async def test_sync_templates_graph_error_raises_structured(monkeypatch):
    """Graph errors must surface as GraphAPIError, not a bare HTTPError."""
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "waba-1")
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "tok")
    from whatsapp import GraphAPIError

    class _ErrClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw):
            return _MockResponse(
                {"error": {"code": 190, "message": "Access token expired"}},
                status_code=401,
            )

    with patch("services.templates.httpx.AsyncClient", lambda: _ErrClient()):
        with pytest.raises(GraphAPIError) as exc_info:
            await sync_templates(BIZ)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == 190


@pytest.mark.asyncio
async def test_register_template_graph_error_raises_structured(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "waba-1")
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "tok")
    from whatsapp import GraphAPIError

    class _DupClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw):
            return _MockResponse(
                {"error": {"code": 2388023, "message": "Message template already exists"}},
                status_code=400,
            )

    with patch("services.templates.httpx.AsyncClient", lambda: _DupClient()):
        with pytest.raises(GraphAPIError) as exc_info:
            await register_template(BIZ, "dup", "en", [{"type": "BODY", "text": "x"}])
    assert exc_info.value.code == 2388023
    # Row should NOT have been upserted (error happened before local write).
    rows = await list_templates(BIZ, status="pending")
    assert not any(r.name == "dup" for r in rows)


@pytest.mark.asyncio
async def test_sync_templates_paginates(monkeypatch):
    monkeypatch.setattr(config, "WHATSAPP_BUSINESS_ACCOUNT_ID", "waba-1")
    monkeypatch.setattr(config, "WHATSAPP_ACCESS_TOKEN", "tok")
    cap = _MockClient(get_pages=[
        {"data": [{"id": "t1", "name": "a", "language": "en", "status": "APPROVED",
                   "category": "UTILITY", "components": []}],
         "paging": {"cursors": {"after": "cur1"}, "next": "https://.../next"}},
        {"data": [{"id": "t2", "name": "b", "language": "en", "status": "APPROVED",
                   "category": "UTILITY", "components": []}],
         "paging": {}},
    ])
    with patch("services.templates.httpx.AsyncClient", lambda: cap):
        n = await sync_templates(BIZ)
    assert n == 2
    assert len(cap.gets) == 2
    # Second call carries `after=cur1`
    assert cap.gets[1]["params"].get("after") == "cur1"
