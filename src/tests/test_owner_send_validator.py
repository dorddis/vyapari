"""Pydantic validator regression for OwnerSendRequest (P3.5b #7).

web_api.py pre-P3.5b declared `OwnerSendRequest`, `OwnerReleaseRequest`,
and `OracleRequest` TWICE. The second, validator-less copies silently
shadowed the first — Python reassigns on repeated class declarations,
and the second definitions dropped `min_length` / `max_length=2000`.
A 10MB `message` in POST /owner/send passed validation, bypassing the
dispatch path's implicit OOM guard.

The fix deletes the duplicate declarations. These tests guard against
a regression that reintroduces them.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from web_api import OwnerReleaseRequest, OwnerSendRequest, OracleRequest


@pytest.mark.parametrize("cls,field,value,ok", [
    (OwnerSendRequest,    "message",    "a" * 2000,         True),
    (OwnerSendRequest,    "message",    "a" * 2001,         False),
    (OwnerSendRequest,    "message",    "",                 False),
    (OwnerSendRequest,    "customer_id","a" * 32,           True),
    (OwnerSendRequest,    "customer_id","a" * 33,           False),
    (OwnerSendRequest,    "customer_id","",                 False),
    (OwnerReleaseRequest, "customer_id","a" * 32,           True),
    (OwnerReleaseRequest, "customer_id","a" * 33,           False),
    (OwnerReleaseRequest, "customer_id","",                 False),
    (OracleRequest,       "query",      "a" * 2000,         True),
    (OracleRequest,       "query",      "a" * 2001,         False),
    (OracleRequest,       "query",      "",                 False),
])
def test_owner_requests_enforce_length_bounds(cls, field, value, ok) -> None:
    """min_length=1 + max_length caps must be enforced on every
    OwnerSend / OwnerRelease / Oracle request field.
    """
    # Build kwargs with sensible defaults for required fields
    base_kwargs = {
        OwnerSendRequest: {"customer_id": "abc", "message": "m"},
        OwnerReleaseRequest: {"customer_id": "abc"},
        OracleRequest: {"query": "q"},
    }[cls]
    kwargs = {**base_kwargs, field: value}

    if ok:
        instance = cls(**kwargs)
        assert getattr(instance, field) == value
    else:
        with pytest.raises(ValidationError):
            cls(**kwargs)


def test_owner_send_rejects_oom_scale_message() -> None:
    """Specific regression: the attack shape called out by the P3.5
    audit — a 10MB `message` must fail validation, not silently pass
    through to dispatch."""
    with pytest.raises(ValidationError) as exc_info:
        OwnerSendRequest(customer_id="abc", message="X" * 10_000_000)
    # Pydantic v2 reports the max_length constraint
    errors = exc_info.value.errors()
    assert any(
        e["type"] == "string_too_long" for e in errors
    ), f"Expected string_too_long, got {errors}"


def test_no_duplicate_class_declarations_in_web_api() -> None:
    """Structural guard: future contributors must not accidentally
    reintroduce the shadowing pattern that caused this bug. Reads the
    web_api.py source and asserts each target class is declared at most
    once."""
    import inspect
    import web_api
    src = inspect.getsource(web_api)
    for name in ("OwnerSendRequest", "OwnerReleaseRequest", "OracleRequest"):
        count = src.count(f"class {name}(BaseModel)")
        assert count == 1, (
            f"{name} declared {count} times in web_api.py; "
            f"duplicates silently shadow validators"
        )
