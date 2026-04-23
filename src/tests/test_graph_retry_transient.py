"""_post_message retries 429/502/503/504 with backoff."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import whatsapp


class _ScriptedBackend:
    """Shared queue of responses across multiple AsyncClient instantiations."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.attempts = 0


class _ScriptedClient:
    """httpx.AsyncClient stand-in reading from a shared backend so retries
    across separate AsyncClient contexts all draw from the same queue."""

    def __init__(self, backend: _ScriptedBackend) -> None:
        self._backend = backend

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kw):
        spec = self._backend._responses[self._backend.attempts]
        self._backend.attempts += 1
        return _Resp(spec)


class _Resp:
    def __init__(self, spec: dict) -> None:
        self.status_code = spec["status"]
        body = spec.get("body", {})
        self.content = b"{}" if body else b""
        self.text = ""
        self._body = body

    def json(self):
        return self._body


def _patched(responses: list[dict]) -> _ScriptedBackend:
    """Set up a patch of whatsapp.httpx.AsyncClient and return the backend."""
    return _ScriptedBackend(responses)


@pytest.mark.asyncio
async def test_retry_on_429_then_succeed(monkeypatch) -> None:
    monkeypatch.setattr("whatsapp.asyncio.sleep", lambda _d: _async_none())
    backend = _patched([
        {"status": 429, "body": {"error": {"code": 80007, "message": "rate limit"}}},
        {"status": 200, "body": {"messages": [{"id": "wamid.ok"}]}},
    ])
    with patch("whatsapp.httpx.AsyncClient", lambda: _ScriptedClient(backend)):
        result = await whatsapp._post_message({"to": "x", "type": "text"})
    assert result == {"messages": [{"id": "wamid.ok"}]}
    assert backend.attempts == 2


@pytest.mark.asyncio
async def test_retry_on_503_then_succeed(monkeypatch) -> None:
    monkeypatch.setattr("whatsapp.asyncio.sleep", lambda _d: _async_none())
    backend = _patched([
        {"status": 503, "body": {"error": {"code": 2, "message": "unavailable"}}},
        {"status": 502, "body": {"error": {"code": 2, "message": "bad gateway"}}},
        {"status": 200, "body": {"messages": [{"id": "wamid.ok"}]}},
    ])
    with patch("whatsapp.httpx.AsyncClient", lambda: _ScriptedClient(backend)):
        result = await whatsapp._post_message({"to": "x", "type": "text"})
    assert result["messages"][0]["id"] == "wamid.ok"
    assert backend.attempts == 3


@pytest.mark.asyncio
async def test_retries_exhausted_raises(monkeypatch) -> None:
    monkeypatch.setattr("whatsapp.asyncio.sleep", lambda _d: _async_none())
    backend = _patched([
        {"status": 503, "body": {"error": {"code": 2}}},
        {"status": 503, "body": {"error": {"code": 2}}},
        {"status": 503, "body": {"error": {"code": 2}}},
    ])
    with patch("whatsapp.httpx.AsyncClient", lambda: _ScriptedClient(backend)):
        with pytest.raises(whatsapp.GraphAPIError) as exc_info:
            await whatsapp._post_message({"to": "x", "type": "text"})
    assert exc_info.value.status_code == 503
    assert backend.attempts == 3


@pytest.mark.asyncio
async def test_does_not_retry_on_400(monkeypatch) -> None:
    """4xx client errors (other than 429) are permanent; no retry."""
    monkeypatch.setattr("whatsapp.asyncio.sleep", lambda _d: _async_none())
    backend = _patched([
        {"status": 400, "body": {"error": {"code": 131009, "message": "bad param"}}},
    ])
    with patch("whatsapp.httpx.AsyncClient", lambda: _ScriptedClient(backend)):
        with pytest.raises(whatsapp.GraphAPIError) as exc_info:
            await whatsapp._post_message({"to": "x", "type": "text"})
    assert exc_info.value.code == 131009
    assert backend.attempts == 1


async def _async_none():
    return None
