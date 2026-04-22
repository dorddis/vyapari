"""Outbound-message dispatcher — 24-hour customer-service window enforcement.

WhatsApp's policy: a business can send free-form (session) messages to a
customer only within 24 hours of that customer's most recent inbound
message. Outside the window, only Meta-approved templates may be sent.

This module owns the decision. Proactive flows (follow-ups, cold
reach-outs) call `send_reply` / `send_template_reply` /
`send_business_initiated` here instead of touching the channel adapter
directly; the dispatcher reads `customers.last_inbound_at` (populated by
`touch_inbound`) and picks session-vs-template.

The "inbound agent reply" path (main.py `_process_and_reply` -> agent ->
channel.send_text) intentionally bypasses this dispatcher: the window
is always open right after an inbound arrives, so the check is
redundant, and routing every reply through a service just to no-op is
not worth the extra hop. Phase 6's proactive flows (F2.6 day-1/3/7
follow-ups) are the first actual callers.

We chose to store the window timestamp as `Customer.last_inbound_at`
rather than a separate `customer_sessions` table: (customer, business)
is 1:1 on WhatsApp (one wa_id to one business), the grain matches, and
one fewer table is one less thing to keep consistent. If multi-channel
ever lands (the same contact on Instagram DM + WhatsApp), we'll split
then.

Key functions:
- `touch_inbound(business_id, customer_wa_id)` — called from router.dispatch
  on every inbound customer message. Sets `last_inbound_at` monotonically
  (never regresses) and clamps future timestamps to now().
- `is_within_24h_window(business_id, customer_wa_id)` — read helper with
  a 5-minute safety slack to beat clock skew.
- `send_reply(...)` — the proactive-send dispatcher. Free-form if inside
  window, template fallback if outside.
- `send_template_reply(...)` / `send_business_initiated(...)` —
  unconditional template send (OTP, broadcast, cold reach-out).

We intentionally DO NOT cache `last_inbound_at` in process — the value
changes every inbound and sub-millisecond freshness is cheap to query.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import select

from channels.base import get_channel
from database import get_session_factory
from db_models import Customer
from services.templates import get_approved_template

log = logging.getLogger("vyapari.services.outbound")

# Meta's documented customer-service window. 5-minute safety slack so a
# 23h59m send doesn't race against Meta's clock and fail with a 131047.
_WINDOW_HOURS = 24
_WINDOW_SLACK = timedelta(minutes=5)


class OutsideWindowError(Exception):
    """Raised by send_reply when outside the 24h window AND no fallback template."""

    def __init__(self, business_id: str, to: str) -> None:
        super().__init__(
            f"Cannot send session message to {to} for business {business_id}: "
            "outside 24-hour window and no fallback template provided."
        )
        self.business_id = business_id
        self.to = to


class TemplateNotApprovedError(Exception):
    """Raised when the requested template is not approved (or doesn't exist)."""

    def __init__(self, business_id: str, name: str, language: str) -> None:
        super().__init__(
            f"Template {name!r} ({language}) is not APPROVED for business "
            f"{business_id}. Register or await Meta approval before sending."
        )
        self.business_id = business_id
        self.name = name
        self.language = language


# ---------------------------------------------------------------------------
# Window tracking
# ---------------------------------------------------------------------------

async def touch_inbound(
    business_id: str, customer_wa_id: str, *, at: datetime | None = None
) -> None:
    """Record that an inbound customer message arrived. Opens / extends the
    24-hour window. Call once per inbound from the router — before the
    agent dispatch, so even agent crashes don't lose the window signal.

    Guarantees:
    - `last_inbound_at` is monotonically non-decreasing. A late-arriving
      webhook whose `at` is older than the current value is a no-op.
    - Values in the future are clamped to now(). Meta clock-skew,
      replayed webhooks, or a caller passing a future `at` must not be
      able to fake an open window longer than the policy allows.
    """
    now = datetime.now(timezone.utc)
    ts = at or now
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if ts > now:
        ts = now

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Customer row is guaranteed to exist by router.dispatch, but we
        # defend against races where this service is called before the
        # router has created it.
        stmt = select(Customer).where(
            Customer.business_id == business_id,
            Customer.wa_id == customer_wa_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            log.debug(
                "touch_inbound: no customer row for %s yet; skipping",
                customer_wa_id,
            )
            return
        # Monotonic write: never regress a newer stored timestamp.
        existing = row.last_inbound_at
        if existing is not None and existing.tzinfo is None:
            existing = existing.replace(tzinfo=timezone.utc)
        if existing is not None and existing >= ts:
            return
        row.last_inbound_at = ts
        await session.commit()


async def is_within_24h_window(
    business_id: str, customer_wa_id: str, *, now: datetime | None = None
) -> bool:
    """True if the dispatcher may send a free-form (session) message.

    Returns False if:
    - The customer has never sent us a message (last_inbound_at IS NULL)
    - The most recent inbound was more than 23h55m ago (24h - 5m slack)
    """
    current = now or datetime.now(timezone.utc)
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(Customer.last_inbound_at).where(
            Customer.business_id == business_id,
            Customer.wa_id == customer_wa_id,
        )
        last_inbound = (await session.execute(stmt)).scalar_one_or_none()
    if last_inbound is None:
        return False
    # SQLAlchemy returns DB timestamps as naive on SQLite; normalize to UTC.
    if last_inbound.tzinfo is None:
        last_inbound = last_inbound.replace(tzinfo=timezone.utc)
    age = current - last_inbound
    return age < timedelta(hours=_WINDOW_HOURS) - _WINDOW_SLACK


# ---------------------------------------------------------------------------
# Send helpers
# ---------------------------------------------------------------------------

def _validate_image_url(url: str | None) -> None:
    """Reject image header URLs that could be weaponized downstream.

    Meta itself rejects most malformed URLs, but we validate at the
    boundary so a caller bug (or Phase-3 self-serve template owner)
    can't trick us into fetching `javascript:` or a non-HTTP scheme
    into Meta's render pipeline, nor into writing it into message_logs
    where it would render in the owner dashboard.
    """
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"image_url must be http(s); got scheme={parsed.scheme!r} for {url!r}"
        )
    if not parsed.netloc:
        raise ValueError(f"image_url missing host: {url!r}")


async def send_template_reply(
    business_id: str,
    customer_wa_id: str,
    template_name: str,
    variables: list[str] | None = None,
    *,
    language: str = "en",
    image_url: str | None = None,
) -> str:
    """Send an approved template. Always valid — templates reset the window.

    Raises TemplateNotApprovedError if the template isn't APPROVED in our
    catalog. Admins must call services.templates.register_template first
    and wait for Meta to approve before calling this.

    Returns the outbound message id from the channel adapter. Failures
    from the channel adapter's Graph call go through the adapter's own
    failed-id handling (P1.8).
    """
    _validate_image_url(image_url)

    tmpl = await get_approved_template(business_id, template_name, language)
    if tmpl is None:
        raise TemplateNotApprovedError(business_id, template_name, language)

    channel = get_channel()
    return await channel.send_template(
        to=customer_wa_id,
        template_name=template_name,
        language=language,
        params=variables,
        image_url=image_url,
    )


# Semantic alias — "business-initiated" is the Meta term for any outbound
# we start (vs. a customer-initiated reply). Always uses a template.
send_business_initiated = send_template_reply


async def send_reply(
    business_id: str,
    customer_wa_id: str,
    text: str,
    *,
    fallback_template: str | None = None,
    fallback_variables: list[str] | None = None,
    fallback_language: str = "en",
    fallback_image_url: str | None = None,
) -> str:
    """Send a reply, picking session text vs. template based on the window.

    Inside the 24-hour window -> channel.send_text(text).
    Outside the window:
      - If `fallback_template` is given, send it via send_template_reply.
      - Else raise OutsideWindowError so the caller knows why.

    The `text` argument is ALWAYS used inside the window. The fallback
    params describe what to send instead, not what to add to `text`.
    """
    if await is_within_24h_window(business_id, customer_wa_id):
        channel = get_channel()
        return await channel.send_text(customer_wa_id, text)

    if fallback_template is None:
        raise OutsideWindowError(business_id, customer_wa_id)

    log.info(
        "Customer %s outside 24h window for business %s; "
        "falling back to template %s (%s)",
        customer_wa_id, business_id, fallback_template, fallback_language,
    )
    return await send_template_reply(
        business_id=business_id,
        customer_wa_id=customer_wa_id,
        template_name=fallback_template,
        variables=fallback_variables,
        language=fallback_language,
        image_url=fallback_image_url,
    )
