"""Tests for services/tenant_onboarding.py."""

from __future__ import annotations

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import delete

from database import get_session_factory
from db_models import Business, WhatsAppChannel
from services.tenant_onboarding import (
    BusinessExistsError,
    BusinessNotFoundError,
    ChannelAlreadyExistsError,
    onboard_business,
    provision_whatsapp_channel,
)
from services.secrets import decrypt_secrets


@pytest_asyncio.fixture(autouse=True)
async def _clean(monkeypatch):
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())
    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        # Keep the seeded default business, drop test-added ones only.
        await s.commit()
    yield
    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel))
        # Also drop businesses the test might have added, except the seed
        # (which conftest.clean_state re-creates each test anyway).
        await s.execute(
            delete(Business).where(Business.id.notin_(["demo-sharma-motors"]))
        )
        await s.commit()


@pytest.mark.asyncio
async def test_onboard_business_creates_row():
    biz = await onboard_business(
        business_id="biz-new", name="New Co",
        owner_phone="9198", vertical="retail",
    )
    assert biz.id == "biz-new"
    assert biz.name == "New Co"
    assert biz.vertical == "retail"


@pytest.mark.asyncio
async def test_onboard_business_rejects_duplicate():
    await onboard_business("biz-dup", "Dup Co", "9198")
    with pytest.raises(BusinessExistsError):
        await onboard_business("biz-dup", "Different Name", "9199")


@pytest.mark.asyncio
async def test_provision_channel_encrypts_secrets():
    await onboard_business("biz-ch", "Ch Co", "9198")
    ch = await provision_whatsapp_channel(
        business_id="biz-ch",
        phone_number="919999",
        phone_number_id="pni-ch",
        waba_id="waba-ch",
        access_token="tok_sekret",
        app_secret="app_sekret",
        webhook_verify_token="vt",
        verification_pin="1234",
    )
    # The stored provider_config is encrypted — doesn't contain plaintext
    assert "tok_sekret" not in str(ch.provider_config)
    assert "app_sekret" not in str(ch.provider_config)
    # Round-trip via decrypt_secrets
    recovered = decrypt_secrets(ch.provider_config)
    assert recovered["access_token"] == "tok_sekret"
    assert recovered["app_secret"] == "app_sekret"


@pytest.mark.asyncio
async def test_provision_channel_requires_existing_business():
    with pytest.raises(BusinessNotFoundError):
        await provision_whatsapp_channel(
            business_id="biz-missing",
            phone_number="919", phone_number_id="pni-x",
            waba_id="w", access_token="t", app_secret="a",
        )


@pytest.mark.asyncio
async def test_provision_channel_rejects_duplicate_pnid():
    """A phone_number_id can only be claimed by one row globally."""
    await onboard_business("biz-first", "First", "9198")
    await onboard_business("biz-second", "Second", "9199")

    await provision_whatsapp_channel(
        business_id="biz-first",
        phone_number="919000000001", phone_number_id="pni-shared",
        waba_id="w1", access_token="t1", app_secret="a1",
    )
    with pytest.raises(ChannelAlreadyExistsError):
        await provision_whatsapp_channel(
            business_id="biz-second",
            phone_number="919000000002", phone_number_id="pni-shared",
            waba_id="w2", access_token="t2", app_secret="a2",
        )


@pytest.mark.asyncio
async def test_provision_channel_invalidates_caches():
    """After provisioning, business_config cache + per-business adapter
    cache are cleared so the next request picks up fresh creds."""
    from services import business_config as bc
    from channels import base as channel_base

    await onboard_business("biz-inv", "Inv Co", "9198")
    await provision_whatsapp_channel(
        business_id="biz-inv",
        phone_number="919000000003", phone_number_id="pni-inv",
        waba_id="w", access_token="t1", app_secret="a",
    )
    # Load context -> seeds the cache
    ctx = await bc.load_business_context("biz-inv")
    assert ctx.access_token == "t1"
    assert "biz-inv" in bc._cache

    # Re-provision simulates an edit — we can't actually re-provision the
    # same pnid, so we drop and re-add to test invalidation.
    async with get_session_factory()() as s:
        await s.execute(delete(WhatsAppChannel).where(
            WhatsAppChannel.business_id == "biz-inv"
        ))
        await s.commit()
    await provision_whatsapp_channel(
        business_id="biz-inv",
        phone_number="919000000003", phone_number_id="pni-inv",
        waba_id="w", access_token="t2-rotated", app_secret="a",
    )
    # Cache was invalidated by provision — next load sees new token
    ctx2 = await bc.load_business_context("biz-inv")
    assert ctx2.access_token == "t2-rotated"
