"""/health/ready returns 503 when DB or secrets are unavailable."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_live_always_200() -> None:
    """/health/live is pure process-alive signal."""
    import main
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


@pytest.mark.asyncio
async def test_legacy_health_still_200() -> None:
    """Back-compat: /health still responds to live-probe callers."""
    import main
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_ready_200_when_deps_healthy(monkeypatch) -> None:
    """Both DB + encryption key available -> 200."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())
    import main
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_ready_503_when_encryption_key_missing(monkeypatch) -> None:
    """Missing VYAPARI_ENCRYPTION_KEY -> 503 (Fernet won't work)."""
    monkeypatch.delenv("VYAPARI_ENCRYPTION_KEY", raising=False)
    import main
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.get("/health/ready")
    assert resp.status_code == 503
    assert "secrets" in resp.text


@pytest.mark.asyncio
async def test_ready_503_when_db_down(monkeypatch) -> None:
    """DB session fails -> 503."""
    from cryptography.fernet import Fernet
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())

    class _BrokenFactory:
        def __call__(self):
            return self
        async def __aenter__(self):
            raise RuntimeError("db down")
        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(
        "database.get_session_factory", lambda: _BrokenFactory(),
    )
    import main
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.get("/health/ready")
    assert resp.status_code == 503
    assert "db" in resp.text
