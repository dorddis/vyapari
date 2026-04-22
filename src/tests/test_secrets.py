"""Tests for services/secrets.py — Fernet-based tenant-secret encryption.

No DB, no network. Exercises encrypt/decrypt round-trip, tampered-input
rejection, unknown-key-id error, missing-env error, and the
primary_key_is_configured health helper.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from services import secrets


def _set_key(monkeypatch) -> str:
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", key)
    return key


def test_encrypt_decrypt_round_trip(monkeypatch):
    _set_key(monkeypatch)
    original = {
        "access_token": "EAAG_live_sekret",
        "app_secret": "meta-app-hash",
        "webhook_verify_token": "vt_1234",
        "verification_pin": "5678",
    }
    blob = secrets.encrypt_secrets(original)
    assert "ct" in blob and "key_id" in blob
    assert blob["key_id"] == "primary"
    # Ciphertext must not equal plaintext substrings anywhere
    assert "EAAG_live_sekret" not in blob["ct"]
    assert "meta-app-hash" not in blob["ct"]

    recovered = secrets.decrypt_secrets(blob)
    assert recovered == original


def test_round_trip_preserves_unicode(monkeypatch):
    """Hindi/Hinglish owner names in verification_pin etc. must round-trip."""
    _set_key(monkeypatch)
    original = {"name": "राजेश कुमार", "emoji_note": "chill 🔒"}
    recovered = secrets.decrypt_secrets(secrets.encrypt_secrets(original))
    assert recovered == original


def test_encrypt_rejects_non_dict(monkeypatch):
    _set_key(monkeypatch)
    with pytest.raises(TypeError, match="expects dict"):
        secrets.encrypt_secrets("not a dict")  # type: ignore[arg-type]


def test_decrypt_rejects_non_dict(monkeypatch):
    _set_key(monkeypatch)
    with pytest.raises(TypeError, match="expects dict"):
        secrets.decrypt_secrets("not a dict")  # type: ignore[arg-type]


def test_decrypt_rejects_malformed_blob(monkeypatch):
    _set_key(monkeypatch)
    for bad in (
        {},
        {"key_id": "primary"},  # no ct
        {"ct": "abc"},  # no key_id
        {"key_id": "", "ct": "abc"},
        {"key_id": "primary", "ct": ""},
    ):
        with pytest.raises(RuntimeError, match="malformed blob"):
            secrets.decrypt_secrets(bad)


def test_decrypt_rejects_tampered_ciphertext(monkeypatch):
    _set_key(monkeypatch)
    blob = secrets.encrypt_secrets({"x": "y"})
    # Flip a few bytes in the middle — Fernet's HMAC will fail verification.
    ct = blob["ct"]
    tampered = ct[:10] + ("A" if ct[10] != "A" else "B") + ct[11:]
    with pytest.raises(RuntimeError, match="authentication failed"):
        secrets.decrypt_secrets({"key_id": "primary", "ct": tampered})


def test_decrypt_rejects_unknown_key_id(monkeypatch):
    _set_key(monkeypatch)
    blob = secrets.encrypt_secrets({"x": "y"})
    with pytest.raises(RuntimeError, match="Unknown key_id"):
        secrets.decrypt_secrets({"key_id": "rotate-v2", "ct": blob["ct"]})


def test_encrypt_raises_when_env_key_missing(monkeypatch):
    monkeypatch.delenv("VYAPARI_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="VYAPARI_ENCRYPTION_KEY is not set"):
        secrets.encrypt_secrets({"x": "y"})


def test_encrypt_raises_on_whitespace_env_key(monkeypatch):
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", "    ")
    with pytest.raises(RuntimeError, match="VYAPARI_ENCRYPTION_KEY is not set"):
        secrets.encrypt_secrets({"x": "y"})


def test_encrypt_raises_on_invalid_fernet_key(monkeypatch):
    # Not 32 bytes base64-urlsafe
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", "obviously-not-a-fernet-key")
    with pytest.raises(RuntimeError, match="not a valid Fernet key"):
        secrets.encrypt_secrets({"x": "y"})


def test_primary_key_is_configured(monkeypatch):
    monkeypatch.delenv("VYAPARI_ENCRYPTION_KEY", raising=False)
    assert secrets.primary_key_is_configured() is False
    _set_key(monkeypatch)
    assert secrets.primary_key_is_configured() is True


def test_generate_key_returns_valid_fernet_key():
    """generate_key must produce something Fernet can round-trip."""
    k = secrets.generate_key()
    assert isinstance(k, str) and len(k) > 32
    # Should instantiate without error.
    f = Fernet(k.encode("utf-8"))
    round = f.decrypt(f.encrypt(b"hi"))
    assert round == b"hi"
