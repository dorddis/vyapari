"""Per-business API key service.

Replaces the single shared `API_AUTH_TOKEN` with tenant-bound keys.
Each REST request arrives with `X-API-Key: <plaintext>`; the auth
middleware hashes it (SHA-256), looks up the `api_keys` row, and
binds the request to the matching `business_id`.

Security posture:
- Plaintext keys never land in the DB — we store the hash.
- Plaintext is shown ONCE at mint time. If a user loses theirs, they
  mint a new one and revoke the old.
- hmac.compare_digest is used on lookup. (SQL UNIQUE constraint makes
  this technically unnecessary for O(1) lookup, but belts+braces.)
- Revoking a key sets `revoked_at` rather than deleting — preserves
  the audit trail (who used the key, when).

Legacy compatibility:
- If no ApiKey row matches, callers can fall back to checking the
  legacy `config.API_AUTH_TOKEN` (caller decides). That fallback is
  strictly single-tenant — it doesn't identify a business.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone
from typing import NamedTuple

from sqlalchemy import select, update

from database import get_session_factory
from db_models import ApiKey


# 32 random bytes -> 43-char urlsafe-base64 plaintext. 256 bits of entropy.
_KEY_BYTE_LEN = 32


class MintedKey(NamedTuple):
    """Result of mint_api_key. The plaintext field is the ONLY time the
    caller gets the raw key — store it yourself or surface to the user."""
    id: str
    business_id: str
    plaintext: str
    key_prefix: str
    description: str


def _hash_key(plaintext: str) -> str:
    """SHA-256 hex digest of the plaintext key. Constant-time verification
    happens at lookup via DB UNIQUE + `hmac.compare_digest`."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def mint_api_key(
    business_id: str, description: str = "",
) -> MintedKey:
    """Generate + persist a fresh API key for a tenant.

    Returns MintedKey with the plaintext. Caller must surface it once
    and never re-derive — the DB only stores the hash.
    """
    plaintext = secrets.token_urlsafe(_KEY_BYTE_LEN)
    key_hash = _hash_key(plaintext)
    key_prefix = plaintext[:8]

    session_factory = get_session_factory()
    async with session_factory() as session:
        row = ApiKey(
            business_id=business_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            description=description,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    return MintedKey(
        id=row.id,
        business_id=business_id,
        plaintext=plaintext,
        key_prefix=key_prefix,
        description=description,
    )


# Throttle the last_used_at UPDATE. A key hammered at 100 req/sec would
# otherwise generate 100 row UPDATEs per second, creating write-lock
# contention with zero analytical value. One bump per minute is enough
# for audit ("when was this key last active"), and collapses the write
# amplification to 1 UPDATE/min/key max.
_LAST_USED_BUMP_INTERVAL_SECONDS = 60


async def verify_api_key(plaintext: str) -> str | None:
    """Return the business_id bound to `plaintext` if valid + un-revoked.

    Returns None when:
    - The key hash doesn't match any row.
    - The matching row is revoked.

    Updates `last_used_at` at most once per 60s per key — enough for
    "when was this key last active" analytics without hot-row contention
    under burst traffic.
    """
    if not plaintext:
        return None
    key_hash = _hash_key(plaintext)

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None

        # Only bump last_used_at if the stored value is older than our
        # throttle interval. One UPDATE per 60s per key, worst case.
        now = datetime.now(timezone.utc)
        last = row.last_used_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is None or (now - last).total_seconds() >= _LAST_USED_BUMP_INTERVAL_SECONDS:
            await session.execute(
                update(ApiKey)
                .where(ApiKey.id == row.id)
                .values(last_used_at=now)
            )
            await session.commit()
        return row.business_id


async def revoke_api_key(key_id: str) -> bool:
    """Mark a key revoked by id. Returns True if it existed + wasn't
    already revoked."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        row = await session.get(ApiKey, key_id)
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(timezone.utc)
        await session.commit()
        return True


async def list_api_keys(business_id: str) -> list[ApiKey]:
    """Admin helper — every key row for a tenant, including revoked."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = (
            select(ApiKey)
            .where(ApiKey.business_id == business_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())
