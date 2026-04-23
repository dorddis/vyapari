"""Message template catalog service.

Three responsibilities:

1. **Register** a template with Meta (`POST /{waba_id}/message_templates`).
   We store it locally as PENDING; Meta review typically takes hours but
   can run days for MARKETING templates.
2. **Sync** template status from Meta (`GET /{waba_id}/message_templates`).
   Called on a schedule and after an `/account_updates` webhook (Phase 4).
   Upserts by (business_id, name, language), updating status /
   rejected_reason / meta_template_id / last_synced_at.
3. **Lookup** — `get_approved_template(business_id, name, language)` — the
   read path the outbound dispatcher uses before sending outside the
   24-hour customer-service window.

Meta API surface we talk to (all at `graph.facebook.com/{api_version}/{waba_id}`):
- `GET /message_templates` — paginated list, returns everything regardless
  of status.
- `POST /message_templates` — submits a new one for review.
- `DELETE /message_templates?name=<n>` — future (Phase 3+).

The module intentionally does NOT send user-facing messages. For that,
see `services/outbound.py`, which loads approved templates via
`get_approved_template` and hands them to `channels.whatsapp.send_template`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

import config
from database import get_session_factory
from db_models import MessageTemplate
from models.enums import MessageTemplateStatus
from services.business_config import BusinessContext, load_business_context
from whatsapp import GraphAPIError

log = logging.getLogger("vyapari.services.templates")


# ---------------------------------------------------------------------------
# Graph API endpoints
# ---------------------------------------------------------------------------

def _templates_endpoint(waba_id: str) -> str:
    """URL for /{waba_id}/message_templates."""
    return f"https://graph.facebook.com/{config.WHATSAPP_API_VERSION}/{waba_id}/message_templates"


async def _load_graph_ctx(business_id: str) -> BusinessContext:
    """Resolve the tenant's WABA id + access_token for Graph calls.

    Pre-P3.5a this module read `config.WHATSAPP_BUSINESS_ACCOUNT_ID` and
    `config.WHATSAPP_ACCESS_TOKEN` unconditionally — every tenant's
    register/sync hit the env WABA with the env token, silently cross-
    writing Meta state. Now each call threads business_id through to
    `whatsapp_channels` so Graph hops carry THAT tenant's creds.

    Raises `NoActiveChannelError` / `BusinessNotFoundError` on the usual
    paths (channel row not yet provisioned, business_id unknown). A
    provisioned channel with an empty waba_id surfaces the same
    RuntimeError Phase 2 used to raise — keeps the failure shape for ops.
    """
    ctx = await load_business_context(business_id)
    if not ctx.waba_id:
        raise RuntimeError(
            f"whatsapp_channels.waba_id is empty for business {business_id!r}; "
            "cannot call Meta template endpoints."
        )
    if not ctx.access_token:
        raise RuntimeError(
            f"whatsapp_channels.access_token is empty for business "
            f"{business_id!r}; re-provision the channel."
        )
    return ctx


# ---------------------------------------------------------------------------
# Meta status mapping
# ---------------------------------------------------------------------------

# Meta returns template statuses in uppercase; we normalize to our enum.
_META_STATUS_MAP: dict[str, str] = {
    "APPROVED": MessageTemplateStatus.APPROVED.value,
    "PENDING": MessageTemplateStatus.PENDING.value,
    "REJECTED": MessageTemplateStatus.REJECTED.value,
    "PAUSED": MessageTemplateStatus.PAUSED.value,
    "DISABLED": MessageTemplateStatus.DISABLED.value,
    # "scheduled for deletion" — we must not send these. Map to DISABLED
    # so the dispatcher treats them as unavailable (not "Meta may re-
    # enable", which is the PAUSED semantic).
    "PENDING_DELETION": MessageTemplateStatus.DISABLED.value,
    "DELETED": MessageTemplateStatus.DISABLED.value,
    # Meta's policy-review states. Keep as PENDING so the dispatcher
    # waits for a verdict; IN_APPEAL is "customer is challenging a
    # rejection," still not sendable.
    "IN_APPEAL": MessageTemplateStatus.PENDING.value,
    # Limit exceeded = Meta paused submissions; treat as PAUSED so ops
    # can see it and intervene, rather than silently hiding it.
    "LIMIT_EXCEEDED": MessageTemplateStatus.PAUSED.value,
}


def _normalize_status(meta_status: str | None) -> str:
    if not meta_status:
        return MessageTemplateStatus.PENDING.value
    return _META_STATUS_MAP.get(meta_status.upper(), MessageTemplateStatus.PENDING.value)


def _raise_if_graph_error(resp: httpx.Response, context: str) -> dict:
    """Parse a Graph response; raise GraphAPIError on error, else return body.

    Mirrors whatsapp._post_message's contract so ops + logs get the
    same structured error shape whether the Graph call came from the
    channel adapter or from services/templates.
    """
    try:
        body = resp.json() if resp.content else {}
    except Exception:
        body = {"raw_text": resp.text}

    if resp.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        code = (err or {}).get("code") if isinstance(err, dict) else None
        raise GraphAPIError(
            f"Graph API {context} failed {resp.status_code}: {err or body}",
            status_code=resp.status_code,
            code=code,
            body=body if isinstance(body, dict) else {},
        )
    if isinstance(body, dict) and "error" in body:
        err = body["error"]
        code = err.get("code") if isinstance(err, dict) else None
        raise GraphAPIError(
            f"Graph API {context} error in {resp.status_code}: {err}",
            status_code=resp.status_code,
            code=code,
            body=body,
        )
    return body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def register_template(
    business_id: str,
    name: str,
    language: str,
    components: list[dict],
    category: str = "UTILITY",
) -> MessageTemplate:
    """Submit a template to Meta for approval and persist as PENDING locally.

    Re-registering an existing (business_id, name, language) updates the
    local row — Meta rejects duplicate registrations, but the caller may
    want to bump components after a rejection and re-submit.

    Raises httpx.HTTPError on non-2xx Meta responses (bad access token,
    malformed components, rate limit). The caller should log + surface.
    """
    ctx = await _load_graph_ctx(business_id)
    payload = {
        "name": name,
        "category": category.upper(),
        "language": language,
        "components": components,
    }
    headers = {
        "Authorization": f"Bearer {ctx.access_token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _templates_endpoint(ctx.waba_id),
            json=payload,
            headers=headers,
            timeout=30,
        )
    body = _raise_if_graph_error(resp, f"register_template({name}/{language})")

    meta_template_id = body.get("id")
    status_raw = body.get("status")  # e.g. "PENDING"
    status = _normalize_status(status_raw)

    # Upsert locally.
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(MessageTemplate).where(
            MessageTemplate.business_id == business_id,
            MessageTemplate.name == name,
            MessageTemplate.language == language,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = MessageTemplate(
                business_id=business_id,
                name=name,
                language=language,
                category=category.upper(),
                components=components,
                status=status,
                meta_template_id=meta_template_id,
                last_synced_at=datetime.now(timezone.utc),
            )
            session.add(row)
        else:
            row.category = category.upper()
            row.components = components
            row.status = status
            row.rejected_reason = None
            row.meta_template_id = meta_template_id
            row.last_synced_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(row)
        log.info(
            "Registered template %s / %s for %s -> status=%s (meta_id=%s)",
            name, language, business_id, status, meta_template_id,
        )
        return row


async def sync_templates(business_id: str) -> int:
    """Fetch all templates from Meta and upsert into the local table.

    Returns the number of rows upserted. Called on a schedule + after
    `message_template_status_update` webhooks (Phase 4).

    Raises httpx.HTTPError on Meta failure. Local DB writes are best-effort
    per-row; one bad row does not abort the whole sync.
    """
    ctx = await _load_graph_ctx(business_id)
    headers = {"Authorization": f"Bearer {ctx.access_token}"}

    upserted = 0
    cursor: str | None = None
    async with httpx.AsyncClient() as client:
        while True:
            params: dict = {"limit": 100}
            if cursor:
                params["after"] = cursor
            resp = await client.get(
                _templates_endpoint(ctx.waba_id),
                params=params,
                headers=headers,
                timeout=30,
            )
            body = _raise_if_graph_error(resp, "sync_templates")
            data = body.get("data") or []
            for meta_tmpl in data:
                try:
                    await _upsert_from_meta(business_id, meta_tmpl)
                    upserted += 1
                except Exception:
                    log.exception(
                        "Failed to upsert template %s for %s",
                        meta_tmpl.get("name"), business_id,
                    )
            next_cursor = (body.get("paging") or {}).get("cursors", {}).get("after")
            # Stop conditions:
            # - No cursor -> last page.
            # - next_cursor == cursor -> Meta returned the same cursor we
            #   just sent (stuck pagination); break to prevent infinite loop.
            # `paging.next` is intentionally ignored: cursor advancement is
            # the only authoritative signal.
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    log.info("Synced %d templates for business %s", upserted, business_id)
    return upserted


async def _upsert_from_meta(business_id: str, meta_tmpl: dict) -> None:
    """Upsert a single Meta template dict into the local table."""
    name = meta_tmpl.get("name")
    language = meta_tmpl.get("language")
    if not name or not language:
        return
    components = meta_tmpl.get("components") or []
    status = _normalize_status(meta_tmpl.get("status"))
    category = (meta_tmpl.get("category") or "UTILITY").upper()
    meta_template_id = meta_tmpl.get("id")
    # Meta includes rejection reasons in the `quality_score` / `reason`
    # field depending on the API version; store whichever is present.
    rejected_reason = (
        meta_tmpl.get("reason")
        or meta_tmpl.get("rejected_reason")
        or None
    )

    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(MessageTemplate).where(
            MessageTemplate.business_id == business_id,
            MessageTemplate.name == name,
            MessageTemplate.language == language,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if row is None:
            row = MessageTemplate(
                business_id=business_id,
                name=name,
                language=language,
                category=category,
                components=components,
                status=status,
                rejected_reason=rejected_reason,
                meta_template_id=meta_template_id,
                last_synced_at=now,
            )
            session.add(row)
        else:
            row.category = category
            row.components = components
            row.status = status
            row.rejected_reason = rejected_reason
            row.meta_template_id = meta_template_id
            row.last_synced_at = now
        await session.commit()


async def get_approved_template(
    business_id: str,
    name: str,
    language: str = "en",
) -> MessageTemplate | None:
    """Return the approved template row, or None if not found / not approved.

    The outbound dispatcher uses this before sending outside the 24-hour
    customer-service window. A None return means "cannot reach this
    customer right now" — the caller must decide whether to raise, queue,
    or pick a fallback template.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(MessageTemplate).where(
            MessageTemplate.business_id == business_id,
            MessageTemplate.name == name,
            MessageTemplate.language == language,
            MessageTemplate.status == MessageTemplateStatus.APPROVED.value,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        return row


async def list_templates(
    business_id: str,
    *,
    status: str | None = None,
) -> list[MessageTemplate]:
    """Read helper for admin panels / scripts. Optionally filter by status."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(MessageTemplate).where(MessageTemplate.business_id == business_id)
        if status:
            stmt = stmt.where(MessageTemplate.status == status)
        return list((await session.execute(stmt)).scalars().all())
