"""Webhook rejects oversize bodies before reading."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_webhook_rejects_oversize_content_length(monkeypatch) -> None:
    import config
    import main
    monkeypatch.setattr(config, "CHANNEL_MODE", "whatsapp")
    monkeypatch.setattr(config, "WHATSAPP_ENABLED", True)

    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        resp = await http.post(
            "/webhook",
            content=b"{}",
            headers={
                "Content-Type": "application/json",
                "content-length": str(5 * 1024 * 1024),
            },
        )
    assert resp.status_code == 413, resp.text
