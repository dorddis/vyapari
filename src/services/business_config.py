"""Per-business runtime context loader.

Resolves a `business_id` (from a webhook's phone_number_id, an API key
lookup, or a hardcoded default during a migration window) into a
runtime `BusinessContext` the channel adapter + agent tools can
consume without knowing anything about the DB layout.

This is the replacement for every `config.WHATSAPP_ACCESS_TOKEN`
module-level read. Phase 3 ships the loader; Phase 3.3 migrates call
sites off the globals.

Key design choices:
- `BusinessContext` is a frozen dataclass carrying decrypted creds +
  Business row fields most adapters / services need. Callers should
  treat it as read-only — any mutation must go through the DB layer.
- Small in-process cache (60s TTL) so an LLM turn that sends 3 messages
  doesn't hit the DB 3x. Invalidated on channel config updates via
  `invalidate_cache(business_id)`.
- All error paths (unknown business, no whatsapp channel, decryption
  failure) raise loud exceptions — callers must handle explicitly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from sqlalchemy import select

from database import get_session_factory
from db_models import Business, WhatsAppChannel
from services.secrets import decrypt_secrets

log = logging.getLogger("vyapari.services.business_config")


_CACHE_TTL_SECONDS = 60


class BusinessNotFoundError(Exception):
    """Raised when the requested business_id has no row."""

    def __init__(self, business_id: str) -> None:
        super().__init__(f"No business with id {business_id!r}")
        self.business_id = business_id


class NoActiveChannelError(Exception):
    """Raised when a business exists but has no WhatsApp channel row.

    Expected during onboarding: the owner-setup wizard creates the
    business first, the channel second. Callers that need to send
    WhatsApp messages must handle this as 'not ready yet'.
    """

    def __init__(self, business_id: str) -> None:
        super().__init__(f"Business {business_id!r} has no whatsapp channel")
        self.business_id = business_id


@dataclass(frozen=True)
class BusinessContext:
    """Runtime context for per-request / per-tool work."""

    business_id: str
    business_name: str
    vertical: str
    # Channel creds, decrypted. `None` on any field if the channel row
    # isn't provisioned yet (onboarding in flight).
    phone_number: str
    phone_number_id: str
    waba_id: str
    access_token: str
    app_secret: str
    webhook_verify_token: str
    verification_pin: str = ""
    source: str = "manual"
    health_status: str = "pending"
    # The Business.settings JSONB, exposed as an immutable-ish dict.
    # Services that need per-tenant knobs (custom system prompts,
    # escalation thresholds) read from here.
    settings: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_cache: dict[str, tuple[float, BusinessContext]] = {}
# Reverse index: phone_number_id -> business_id. Populated by
# `resolve_business_id_from_phone_number_id` + invalidated on channel
# config updates.
_pnid_index: dict[str, tuple[float, str]] = {}


def invalidate_cache(business_id: str | None = None) -> None:
    """Drop cached entries.

    Pass a business_id to drop one tenant, or None to clear everything.
    Call this after mutating `whatsapp_channels.provider_config` or
    when an access token rotation completes.
    """
    if business_id is None:
        _cache.clear()
        _pnid_index.clear()
        return
    _cache.pop(business_id, None)
    # Also drop the reverse-index entry for any phone_number_id that
    # resolved to this business.
    stale = [pnid for pnid, (_, bid) in _pnid_index.items() if bid == business_id]
    for pnid in stale:
        _pnid_index.pop(pnid, None)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

async def load_business_context(business_id: str) -> BusinessContext:
    """Return a fresh or cached BusinessContext for the given id.

    Raises BusinessNotFoundError if the business row is missing;
    NoActiveChannelError if the business exists but has no whatsapp
    channel yet (onboarding not complete).
    """
    now = time.time()
    cached = _cache.get(business_id)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    session_factory = get_session_factory()
    async with session_factory() as session:
        biz = await session.get(Business, business_id)
        if biz is None:
            raise BusinessNotFoundError(business_id)

        stmt = (
            select(WhatsAppChannel)
            .where(WhatsAppChannel.business_id == business_id)
            .order_by(WhatsAppChannel.created_at.desc())
            .limit(1)
        )
        channel = (await session.execute(stmt)).scalar_one_or_none()
        if channel is None:
            raise NoActiveChannelError(business_id)

    try:
        secrets = decrypt_secrets(channel.provider_config or {})
    except Exception as exc:
        log.error(
            "Failed to decrypt provider_config for business %s channel %s: %s",
            business_id, channel.id, exc,
        )
        raise

    ctx = BusinessContext(
        business_id=biz.id,
        business_name=biz.name,
        vertical=biz.vertical or "",
        phone_number=channel.phone_number,
        phone_number_id=channel.phone_number_id,
        waba_id=channel.waba_id,
        access_token=secrets.get("access_token", ""),
        app_secret=secrets.get("app_secret", ""),
        webhook_verify_token=secrets.get("webhook_verify_token", ""),
        verification_pin=secrets.get("verification_pin", ""),
        source=channel.source,
        health_status=channel.health_status,
        settings=dict(biz.settings or {}),
    )
    _cache[business_id] = (now, ctx)
    _pnid_index[ctx.phone_number_id] = (now, ctx.business_id)
    return ctx


async def resolve_business_id_from_phone_number_id(
    phone_number_id: str,
) -> str | None:
    """Reverse-resolve an inbound webhook to the owning tenant.

    Returns the business_id, or None if no channel matches (the webhook
    is for a number we don't serve). Caches hits for _CACHE_TTL_SECONDS.
    """
    if not phone_number_id:
        return None
    now = time.time()
    cached = _pnid_index.get(phone_number_id)
    if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(WhatsAppChannel.business_id).where(
            WhatsAppChannel.phone_number_id == phone_number_id
        )
        business_id = (await session.execute(stmt)).scalar_one_or_none()
    if business_id is None:
        return None
    _pnid_index[phone_number_id] = (now, business_id)
    return business_id
