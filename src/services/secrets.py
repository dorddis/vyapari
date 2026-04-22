"""Symmetric encryption for per-tenant secrets.

Phase 3 stores each business's WhatsApp access_token, app_secret,
webhook_verify_token, and verification_pin inside
`whatsapp_channels.provider_config` (JSONB). Those values are tenant
secrets — if one row leaks (SQL injection, misconfigured replica,
accidental log dump) the damage should stop at the row, not spread
across every tenant.

Design:
- Fernet (AES-128-CBC + HMAC-SHA256 in a standard authenticated envelope,
  from `cryptography`). A Fernet token is `"<timestamp>|<iv>|<ct>|<hmac>"`
  base64url-encoded.
- The key is loaded from env `VYAPARI_ENCRYPTION_KEY` at import time.
- Each stored blob carries a `key_id` string so we can rotate keys
  without re-encrypting the whole table at once: on read, we look up the
  key for that id; on write, we always use the primary key.
- For now there's only one key (`"primary"`). Phase 4+ will support a
  multi-key registry keyed by id.

Public API:
- `encrypt_secrets(plaintext: dict) -> dict` returns
  `{"key_id": "primary", "ct": "<base64 Fernet token>"}`.
- `decrypt_secrets(blob: dict) -> dict` returns the original plaintext.
- `generate_key()` emits a fresh Fernet key for ops when setting up env.

Failure modes:
- Missing env key: `encrypt_secrets` / `decrypt_secrets` raise
  RuntimeError. Every tenant-aware code path that touches secrets
  surfaces a loud error at first call rather than silently pickling to
  plaintext.
- Wrong key_id on read: raises RuntimeError with the key_id so ops can
  identify the key needed for rotation.
"""

from __future__ import annotations

import base64
import json
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("vyapari.services.secrets")


_ENV_VAR = "VYAPARI_ENCRYPTION_KEY"
_PRIMARY_KEY_ID = "primary"


def generate_key() -> str:
    """Emit a fresh Fernet key (base64-urlsafe, 32 bytes of entropy).

    Call from an ops shell when provisioning a new deployment:
        python -c "from services.secrets import generate_key; print(generate_key())"

    Then copy the output into the deployment's env as VYAPARI_ENCRYPTION_KEY.
    """
    return Fernet.generate_key().decode("utf-8")


def _load_key(key_id: str) -> bytes:
    """Return the raw key bytes for a given key_id.

    Only the primary key is currently supported. Multi-key rotation
    lands in Phase 4 (an env var listing {key_id: base64_key} pairs).
    """
    if key_id != _PRIMARY_KEY_ID:
        raise RuntimeError(
            f"Unknown key_id {key_id!r}. Phase 3 supports only "
            f"{_PRIMARY_KEY_ID!r}; key rotation is Phase 4."
        )
    env_value = os.getenv(_ENV_VAR, "")
    if not env_value.strip():
        raise RuntimeError(
            f"{_ENV_VAR} is not set. Generate one with "
            "`python -c 'from services.secrets import generate_key; "
            "print(generate_key())'` and put it in your .env."
        )
    try:
        # Validate it's a proper Fernet key (32 bytes base64-urlsafe).
        Fernet(env_value.encode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            f"{_ENV_VAR} is not a valid Fernet key (expected 32 bytes "
            f"base64-urlsafe): {exc}"
        ) from exc
    return env_value.encode("utf-8")


def encrypt_secrets(plaintext: dict) -> dict:
    """Encrypt a dict of tenant secrets. Returns a JSON-safe blob.

    Blob shape:
        {"key_id": "primary", "ct": "<Fernet token ascii>"}

    Caller stores this directly in a JSONB column. Never log either
    field — `ct` is not plaintext-safe (it's authenticated-encrypted)
    but noise in logs is still noise.
    """
    if not isinstance(plaintext, dict):
        raise TypeError(f"encrypt_secrets expects dict, got {type(plaintext).__name__}")
    key = _load_key(_PRIMARY_KEY_ID)
    f = Fernet(key)
    serialized = json.dumps(plaintext, ensure_ascii=False, sort_keys=True)
    token = f.encrypt(serialized.encode("utf-8"))
    return {"key_id": _PRIMARY_KEY_ID, "ct": token.decode("ascii")}


def decrypt_secrets(blob: dict) -> dict:
    """Decrypt a blob produced by encrypt_secrets.

    Raises RuntimeError for malformed blobs or key mismatch, InvalidToken
    (via `cryptography`) for tampered / wrong-key ciphertext.
    """
    if not isinstance(blob, dict):
        raise TypeError(f"decrypt_secrets expects dict, got {type(blob).__name__}")
    key_id = blob.get("key_id")
    ct = blob.get("ct")
    if not key_id or not ct:
        raise RuntimeError(
            f"decrypt_secrets: malformed blob (key_id={key_id!r}, ct present={bool(ct)})"
        )
    key = _load_key(key_id)
    f = Fernet(key)
    try:
        plaintext_bytes = f.decrypt(ct.encode("ascii"))
    except InvalidToken as exc:
        raise RuntimeError(
            f"decrypt_secrets: authentication failed for key_id={key_id!r}. "
            "Either the ciphertext was tampered with or the wrong key is "
            "configured for this row."
        ) from exc
    return json.loads(plaintext_bytes.decode("utf-8"))


def primary_key_is_configured() -> bool:
    """Cheap check — True if VYAPARI_ENCRYPTION_KEY is set + valid.

    Meant for startup guards and health checks; does not encrypt/decrypt."""
    try:
        _load_key(_PRIMARY_KEY_ID)
    except RuntimeError:
        return False
    return True
