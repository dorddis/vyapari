"""send_template_reply invalidates the local row when Meta rejects it."""

from __future__ import annotations

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import delete

import state
from models.enums import MessageTemplateStatus
from services.outbound import (
    TemplateNotApprovedError, send_template_reply,
)
from whatsapp import GraphAPIError


@pytest_asyncio.fixture(autouse=True)
async def _setup(monkeypatch):
    import config
    monkeypatch.setenv("VYAPARI_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "CHANNEL_MODE", "whatsapp")

    from channels import base as channel_base
    from database import get_session_factory
    from db_models import ApiKey, MessageTemplate, WhatsAppChannel
    from services import business_config as bc
    from services.tenant_onboarding import provision_whatsapp_channel
    from services.templates import _upsert_from_meta

    async with get_session_factory()() as s:
        await s.execute(delete(ApiKey))
        await s.execute(delete(MessageTemplate))
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    bc.invalidate_cache()
    channel_base.reset_channel()

    await provision_whatsapp_channel(
        config.DEFAULT_BUSINESS_ID,
        phone_number="919100000099",
        phone_number_id="pnid-paused-test",
        waba_id="waba-x",
        access_token="tok",
        app_secret="sec",
        webhook_verify_token="",
        verification_pin="",
    )
    await _upsert_from_meta(config.DEFAULT_BUSINESS_ID, {
        "id": "t", "name": "welcome", "language": "en",
        "status": "APPROVED", "category": "UTILITY", "components": [],
    })
    await state.get_or_create_customer("919000000701", name="X")

    yield

    async with get_session_factory()() as s:
        await s.execute(delete(MessageTemplate))
        await s.execute(delete(WhatsAppChannel))
        await s.commit()
    bc.invalidate_cache()
    channel_base.reset_channel()


@pytest.mark.asyncio
async def test_template_graph_error_invalidates_local_row(monkeypatch) -> None:
    """Meta rejects with a template-policy code -> row flipped to PAUSED."""
    import config
    from channels import base as channel_base

    async def raising_send_template(**kw):
        raise GraphAPIError(
            "Graph API 400: template paused",
            status_code=400,
            code=132001,  # in _TEMPLATE_UNSENDABLE_CODES
            body={"error": {"code": 132001}},
        )

    channel = await channel_base.get_tenant_channel(config.DEFAULT_BUSINESS_ID)
    monkeypatch.setattr(channel, "send_template", raising_send_template)

    with pytest.raises(TemplateNotApprovedError):
        await send_template_reply(
            config.DEFAULT_BUSINESS_ID, "919000000701", "welcome",
        )

    from services.templates import list_templates
    rows = await list_templates(config.DEFAULT_BUSINESS_ID)
    assert len(rows) == 1
    assert rows[0].status == MessageTemplateStatus.PAUSED.value


@pytest.mark.asyncio
async def test_non_template_graph_error_propagates(monkeypatch) -> None:
    """Graph errors with non-template codes (e.g. 429 rate-limit) bubble up."""
    import config
    from channels import base as channel_base

    async def raising_send_template(**kw):
        raise GraphAPIError(
            "Graph API 429: rate limited",
            status_code=429,
            code=80007,
            body={"error": {"code": 80007}},
        )

    channel = await channel_base.get_tenant_channel(config.DEFAULT_BUSINESS_ID)
    monkeypatch.setattr(channel, "send_template", raising_send_template)

    with pytest.raises(GraphAPIError):
        await send_template_reply(
            config.DEFAULT_BUSINESS_ID, "919000000701", "welcome",
        )

    # Row is untouched (still APPROVED).
    from services.templates import list_templates
    rows = await list_templates(config.DEFAULT_BUSINESS_ID)
    assert rows[0].status == MessageTemplateStatus.APPROVED.value
