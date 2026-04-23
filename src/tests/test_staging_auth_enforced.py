"""Auth is required in non-dev environments even without legacy token."""

from __future__ import annotations

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_staging_without_legacy_token_still_requires_auth(monkeypatch) -> None:
    """APP_ENV=staging + no API_AUTH_TOKEN -> Unauthorized (not bypass)."""
    import config
    from web_api import _require_api_auth

    monkeypatch.setattr(config, "APP_ENV", "staging")
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "")

    class _Req:
        class state: business_id = None
        headers: dict = {}

    with pytest.raises(HTTPException) as exc_info:
        await _require_api_auth(_Req())
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_production_without_any_token_still_requires_auth(monkeypatch) -> None:
    import config
    from web_api import _require_api_auth

    monkeypatch.setattr(config, "APP_ENV", "production")
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "")

    class _Req:
        class state: business_id = None
        headers: dict = {}

    with pytest.raises(HTTPException) as exc_info:
        await _require_api_auth(_Req())
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_development_without_token_bypasses_auth(monkeypatch) -> None:
    """Dev without any token is unauthenticated — matches existing tests."""
    import config
    from web_api import _require_api_auth

    monkeypatch.setattr(config, "APP_ENV", "development")
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "")

    class _Req:
        class state: business_id = None
        headers: dict = {}

    await _require_api_auth(_Req())  # no raise
