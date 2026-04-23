"""Pydantic validator regression for OwnerSendRequest."""

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
    """min_length + max_length bounds are enforced on every field."""
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
    """10MB message is rejected, not silently accepted."""
    with pytest.raises(ValidationError) as exc_info:
        OwnerSendRequest(customer_id="abc", message="X" * 10_000_000)
    errors = exc_info.value.errors()
    assert any(e["type"] == "string_too_long" for e in errors), errors


def test_no_duplicate_class_declarations_in_web_api() -> None:
    """Each request class is declared at most once (no validator shadowing)."""
    import inspect
    import web_api
    src = inspect.getsource(web_api)
    for name in ("OwnerSendRequest", "OwnerReleaseRequest", "OracleRequest"):
        count = src.count(f"class {name}(BaseModel)")
        assert count == 1, f"{name} declared {count} times"
