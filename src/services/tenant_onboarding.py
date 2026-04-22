"""Tenant onboarding service — create a Business + WhatsAppChannel row.

Phase 3 ops path: used manually by an admin after a business signs up
and provides their Meta credentials out-of-band. Phase 5 replaces this
with the Embedded Signup flow (owner clicks through Meta's OAuth,
tokens arrive via webhook, we provision the row server-side with no
human in the middle).

Two public helpers:

- `onboard_business(business_id, name, owner_phone, ...)` creates the
  businesses row. Raises BusinessExistsError if one exists.
- `provision_whatsapp_channel(business_id, phone_number, phone_number_id,
  waba_id, access_token, app_secret, ...)` creates the whatsapp_channels
  row with encrypted provider_config. Raises BusinessNotFoundError if
  the parent business is missing; ChannelAlreadyExistsError if the
  phone_number_id is already claimed by another row.

Together, these are the "ops command" surface for adding a tenant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from database import get_session_factory
from db_models import Business, WhatsAppChannel
from services.secrets import encrypt_secrets


class BusinessExistsError(Exception):
    def __init__(self, business_id: str) -> None:
        super().__init__(f"Business {business_id!r} already exists")
        self.business_id = business_id


class BusinessNotFoundError(Exception):
    def __init__(self, business_id: str) -> None:
        super().__init__(f"Business {business_id!r} not found")
        self.business_id = business_id


class ChannelAlreadyExistsError(Exception):
    def __init__(self, phone_number_id: str) -> None:
        super().__init__(
            f"A whatsapp_channels row already exists for phone_number_id={phone_number_id!r}"
        )
        self.phone_number_id = phone_number_id


async def onboard_business(
    business_id: str,
    name: str,
    owner_phone: str,
    *,
    vertical: str = "",
    type_: str = "",
    greeting: str = "",
) -> Business:
    """Create a new businesses row.

    `business_id` must be a stable identifier you choose (e.g. a slug).
    Raises BusinessExistsError if it already exists — onboarding is
    idempotent by requiring explicit deletion to retry.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        existing = await session.get(Business, business_id)
        if existing is not None:
            raise BusinessExistsError(business_id)
        row = Business(
            id=business_id,
            name=name,
            type=type_,
            vertical=vertical,
            owner_phone=owner_phone,
            greeting=greeting,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def provision_whatsapp_channel(
    business_id: str,
    phone_number: str,
    phone_number_id: str,
    waba_id: str,
    access_token: str,
    app_secret: str,
    *,
    webhook_verify_token: str = "",
    verification_pin: str = "",
    source: str = "manual",
) -> WhatsAppChannel:
    """Create a whatsapp_channels row + invalidate the adapter cache.

    Encrypts (access_token, app_secret, webhook_verify_token,
    verification_pin) via services/secrets before persistence.

    After this call, the next inbound webhook for `phone_number_id` will
    resolve to this business and outbound sends via
    `get_tenant_channel(business_id)` will use these credentials.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        biz = await session.get(Business, business_id)
        if biz is None:
            raise BusinessNotFoundError(business_id)

        # Reject if the phone_number_id is already owned by another row
        # (either this business or a different one — Meta pnids are globally
        # unique so the latter case would also be a misconfiguration).
        stmt = select(WhatsAppChannel).where(
            WhatsAppChannel.phone_number_id == phone_number_id
        )
        conflict = (await session.execute(stmt)).scalar_one_or_none()
        if conflict is not None:
            raise ChannelAlreadyExistsError(phone_number_id)

        provider_config = encrypt_secrets(
            {
                "access_token": access_token,
                "app_secret": app_secret,
                "webhook_verify_token": webhook_verify_token,
                "verification_pin": verification_pin,
            }
        )
        row = WhatsAppChannel(
            business_id=business_id,
            phone_number=phone_number,
            phone_number_id=phone_number_id,
            waba_id=waba_id,
            provider_config=provider_config,
            source=source,
            health_status="pending",
            last_verified_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)

    # Drop any cached business context / channel adapter so subsequent
    # requests pick up the new config immediately.
    try:
        from services import business_config as bc
        bc.invalidate_cache(business_id)
    except Exception:
        pass
    try:
        from channels.base import invalidate_channel
        invalidate_channel(business_id)
    except Exception:
        pass

    return row
