"""Upload endpoints enforce Content-Length + MIME whitelist."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client(monkeypatch):
    import config
    import main
    monkeypatch.setattr(config, "APP_ENV", "development")
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "")
    monkeypatch.setattr(config, "CHANNEL_MODE", "web_clone")
    from channels import base as channel_base
    channel_base.reset_channel()
    # Bare TestClient — no lifespan, no reload; conftest.init_db already
    # set up the in-memory SQLite engine.
    client = TestClient(main.app, raise_server_exceptions=False)
    yield client
    channel_base.reset_channel()


def test_upload_image_rejects_oversize_content_length(test_client) -> None:
    resp = test_client.post(
        "/api/upload-image",
        headers={"content-length": str(20 * 1024 * 1024)},
        data={"wa_id": "919000000601"},
        files={"file": ("big.jpg", io.BytesIO(b"x"), "image/jpeg")},
    )
    assert resp.status_code == 413, resp.text


def test_upload_image_rejects_unsupported_mime(test_client) -> None:
    resp = test_client.post(
        "/api/upload-image",
        data={"wa_id": "919000000602"},
        files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/x-msdownload")},
    )
    assert resp.status_code == 415, resp.text


def test_voice_rejects_unsupported_mime(test_client) -> None:
    resp = test_client.post(
        "/api/voice",
        data={"wa_id": "919000000603"},
        files={"file": ("bad.txt", io.BytesIO(b"not audio"), "text/plain")},
    )
    assert resp.status_code == 415, resp.text


def test_voice_rejects_oversize_content_length(test_client) -> None:
    resp = test_client.post(
        "/api/voice",
        headers={"content-length": str(20 * 1024 * 1024)},
        data={"wa_id": "919000000604"},
        files={"file": ("big.ogg", io.BytesIO(b"x"), "audio/ogg")},
    )
    assert resp.status_code == 413, resp.text
