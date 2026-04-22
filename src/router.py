"""Message router — the central dispatcher.

Pure Python, NOT an LLM agent. Resolves sender role, checks conversation
state, and dispatches to the correct handler. Each handler is a stub that
the responsible team member fills in.

Routing table (from DESIGN_DOC.md Section 3a):

| Sender Role | State          | Message Type | Action            |
|-------------|----------------|-------------|-------------------|
| Customer    | ACTIVE         | any         | customer_agent    |
| Customer    | ESCALATED      | any         | customer_agent    |
| Customer    | RELAY_ACTIVE   | any         | relay_forward     |
| Unknown     | --             | /login      | auth_flow         |
| Unknown     | --             | other       | customer (new)    |
| Owner       | no relay       | any         | owner_agent       |
| Owner       | RELAY_ACTIVE   | no prefix   | relay_forward     |
| Owner       | RELAY_ACTIVE   | / prefix    | relay_command     |
| SDR         | no relay       | any         | sdr_agent         |
| SDR         | RELAY_ACTIVE   | no prefix   | relay_forward     |
| SDR         | RELAY_ACTIVE   | / prefix    | relay_command     |
"""

import logging

import config
import state
from models import (
    ConversationState,
    IncomingMessage,
    RoutingAction,
    RoutingDecision,
    StaffRole,
)

log = logging.getLogger("vyapari.router")


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

async def resolve_role(wa_id: str) -> tuple[str, str | None]:
    """Resolve sender role from Staff table.

    Returns (role_string, staff_name).
    role_string is one of: "owner", "sdr", "customer", "unknown".
    """
    staff = await state.get_staff(wa_id)
    if staff and staff.status.value == "active":
        return staff.role.value, staff.name
    if staff and staff.status.value == "invited":
        return "unknown", None  # still need to complete /login
    return "customer", None  # unknown numbers default to customer


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------

async def route_message(msg: IncomingMessage) -> RoutingDecision:
    """Determine what to do with an incoming message."""
    role, staff_name = await resolve_role(msg.wa_id)
    text = (msg.text or "").strip()
    prefix = config.COMMAND_PREFIX

    # --- Unknown sender ---
    if role == "unknown" or (role == "customer" and text.lower().startswith(f"{prefix}login")):
        # Check if this wa_id has a pending invite (status=invited)
        pending = await state.get_staff(msg.wa_id)
        if pending or text.lower().startswith(f"{prefix}login"):
            return RoutingDecision(
                role="unknown",
                action=RoutingAction.AUTH_FLOW,
            )

    # --- Staff (owner or SDR) ---
    if role in ("owner", "sdr"):
        relay = await state.get_active_relay_for_staff(msg.wa_id)
        if relay:
            if text.startswith(prefix):
                return RoutingDecision(
                    role=role,
                    action=RoutingAction.RELAY_COMMAND,
                    target_wa_id=relay.customer_wa_id,
                    staff_name=staff_name,
                )
            else:
                return RoutingDecision(
                    role=role,
                    action=RoutingAction.RELAY_FORWARD,
                    target_wa_id=relay.customer_wa_id,
                    staff_name=staff_name,
                )

        # No active relay — route to the appropriate agent
        action = (
            RoutingAction.OWNER_AGENT
            if role == "owner"
            else RoutingAction.SDR_AGENT
        )
        return RoutingDecision(
            role=role,
            action=action,
            staff_name=staff_name,
        )

    # --- Customer ---
    conv_state = await state.get_conversation_state(msg.wa_id)

    if conv_state == ConversationState.RELAY_ACTIVE:
        relay = await state.get_active_relay_for_customer(msg.wa_id)
        if relay:
            return RoutingDecision(
                role="customer",
                action=RoutingAction.RELAY_FORWARD,
                target_wa_id=relay.staff_wa_id,
                conversation_state=conv_state,
            )
        # Orphaned RELAY_ACTIVE state (e.g. after restart) — auto-recover
        log.warning(f"Orphaned RELAY_ACTIVE for {msg.wa_id}, recovering to ACTIVE")
        await state.set_conversation_state(msg.wa_id, ConversationState.ACTIVE)
        conv_state = ConversationState.ACTIVE

    # ACTIVE or ESCALATED — customer agent handles both
    return RoutingDecision(
        role="customer",
        action=RoutingAction.CUSTOMER_AGENT,
        conversation_state=conv_state,
    )


# ---------------------------------------------------------------------------
# Handler stubs (each team member fills in their own)
# ---------------------------------------------------------------------------

async def handle_customer_agent(msg: IncomingMessage, conv_state: ConversationState) -> str:
    """Run Customer Agent via OpenAI Agents SDK (Gemini fallback if no key)."""
    if not config.USE_OPENAI:
        try:
            from conversation import get_reply
            return get_reply(customer_id=msg.wa_id, message=msg.text or "")
        except Exception as e:
            log.error(f"Gemini fallback error: {e}")
            return "Sorry, I'm having trouble right now. Please try again!"

    from vyapari_agents.customer import run_customer_agent
    response = await run_customer_agent(
        msg.wa_id,
        msg.text or "",
        image_url=msg.media_url,
        business_id=msg.business_id,
    )

    # Send car images referenced in the reply
    if response.images:
        from channels.base import get_channel
        channel = get_channel()
        for img_url in response.images:
            try:
                await channel.send_image(msg.wa_id, img_url, caption="")
            except Exception as e:
                log.warning(f"Failed to send image {img_url}: {e}")

    # Push escalation notification to owner/assigned staff
    if response.is_escalation:
        await _push_escalation_notification(msg.wa_id, response)

    return response.text


async def _push_escalation_notification(customer_wa_id: str, response) -> None:
    """Send escalation notification to the assigned staff or owner."""
    from channels.base import get_channel

    # Find who to notify: assigned staff, or owner
    conv = await state.get_conversation(customer_wa_id)
    notify_wa_id = None
    if conv and conv.assigned_to:
        notify_wa_id = conv.assigned_to
    else:
        # Notify the owner
        staff_list = await state.list_staff()
        for s in staff_list:
            if s.role.value == "owner":
                notify_wa_id = s.wa_id
                break

    if not notify_wa_id:
        log.warning(f"No one to notify for escalation from {customer_wa_id}")
        return

    channel = get_channel()
    notification = (
        f"ESCALATION\n"
        f"{response.escalation_summary}\n\n"
        f"Reply here or open a session to chat with this customer."
    )
    try:
        await channel.send_text(notify_wa_id, notification)
        log.info(f"Escalation notification sent to {notify_wa_id}")
    except Exception as e:
        log.error(f"Failed to send escalation notification: {e}")


async def handle_owner_agent(msg: IncomingMessage, staff_name: str | None) -> str:
    """Run Owner Agent via OpenAI Agents SDK (Gemini fallback if no key)."""
    from services.owner_setup import (
        handle_owner_setup_message,
        should_handle_owner_setup,
    )

    if await should_handle_owner_setup(msg.wa_id, msg.text or ""):
        return await handle_owner_setup_message(msg.wa_id, msg.text or "")

    if not config.USE_OPENAI:
        try:
            from owner_agent import owner_query
            result = owner_query(msg.text or "")
            return result.get("text", "")
        except Exception as e:
            log.error(f"Gemini owner fallback error: {e}")
            return "Sorry, something went wrong."

    from vyapari_agents.owner import run_owner_agent
    return await run_owner_agent(
        msg.wa_id,
        msg.text or "",
        image_url=msg.media_url,
        business_id=msg.business_id,
    )


async def handle_sdr_agent(msg: IncomingMessage, staff_name: str | None) -> str:
    """Run SDR Agent (same as owner but with limited tools)."""
    if not config.USE_OPENAI:
        return "SDR agent requires OpenAI. Set OPENAI_API_KEY in .env."

    from vyapari_agents.owner import run_owner_agent
    return await run_owner_agent(
        msg.wa_id,
        msg.text or "",
        image_url=msg.media_url,
        business_id=msg.business_id,
    )


async def handle_relay_forward(msg: IncomingMessage, target_wa_id: str) -> str | None:
    """Forward message to the other party in the relay session.

    Returns None — relay is silent to the sender. The message is sent
    to the target via the channel adapter.
    """
    from services.relay import forward_to_customer, forward_to_staff
    from channels.base import get_channel

    text = msg.text or ""
    role, _ = await resolve_role(msg.wa_id)

    if role in ("owner", "sdr"):
        # Staff -> customer
        customer_wa_id, fwd_text = await forward_to_customer(msg.wa_id, text)
        if customer_wa_id:
            channel = get_channel()
            await channel.send_text(customer_wa_id, fwd_text)
    else:
        # Customer -> staff
        customer = await state.get_customer(msg.wa_id)
        name = customer.name if customer else "Customer"
        staff_wa_id, fwd_text = await forward_to_staff(msg.wa_id, text, name)
        if staff_wa_id:
            channel = get_channel()
            await channel.send_text(staff_wa_id, fwd_text)

    return None  # no reply to sender


async def handle_relay_command(msg: IncomingMessage, target_wa_id: str) -> str:
    """Fullstack 1 fills this in — parses /done, /switch, /number, etc."""
    text = (msg.text or "").strip()
    cmd = text.split()[0].lower() if text else ""

    if cmd == f"{config.COMMAND_PREFIX}done":
        session = await state.close_relay_session(msg.wa_id)
        if session:
            customer = await state.get_customer(session.customer_wa_id)
            name = customer.name if customer else "Customer"
            return f"Session with {name} closed. Agent resumed."
        return "No active session to close."

    if cmd == f"{config.COMMAND_PREFIX}help":
        return (
            "Relay commands:\n"
            f"  {config.COMMAND_PREFIX}done - Close session, agent resumes\n"
            f"  {config.COMMAND_PREFIX}help - This message\n"
            "\nEverything else you type is forwarded to the customer."
        )

    return f"Unknown command: {cmd}. Type {config.COMMAND_PREFIX}help for available commands."


async def handle_auth_flow(msg: IncomingMessage) -> str:
    """Handle /login + OTP verification."""
    from services.auth import handle_login_message
    return await handle_login_message(msg.wa_id, msg.text or "")


# ---------------------------------------------------------------------------
# Dispatch (the main entry point)
# ---------------------------------------------------------------------------

async def dispatch(msg: IncomingMessage) -> str | None:
    """Route and handle an incoming message. Returns reply text or None.

    This is the single entry point called by main.py's webhook handler
    and by web_api.py's REST endpoints.
    """
    # Idempotency check
    if await state.is_message_processed(msg.msg_id, business_id=msg.business_id or None):
        log.info(f"Duplicate message {msg.msg_id}, skipping")
        return None
    await state.mark_message_processed(msg.msg_id, business_id=msg.business_id or None)

    # Route first, THEN create records only for customers (not staff)
    decision = await route_message(msg)

    # Only create customer/conversation records for actual customers
    if decision.role in ("customer", "unknown"):
        await state.get_or_create_customer(
            msg.wa_id, name=msg.sender_name, business_id=msg.business_id or None,
        )
        await state.get_or_create_conversation(
            msg.wa_id, business_id=msg.business_id or None,
        )
        # Opens / extends the 24-hour customer-service window. Must run
        # BEFORE the agent dispatch below — even a crashing agent must not
        # lose the window signal, since the window ultimately belongs to
        # Meta's billing, not our own logic.
        if msg.business_id:
            try:
                from services.outbound import touch_inbound
                await touch_inbound(msg.business_id, msg.wa_id)
            except Exception:
                log.warning("touch_inbound failed for %s", msg.wa_id, exc_info=True)
    log.info(
        f"Routed {msg.wa_id} -> {decision.action.value} "
        f"(role={decision.role}, state={decision.conversation_state})"
    )

    # Dispatch to handler
    match decision.action:
        case RoutingAction.CUSTOMER_AGENT:
            return await handle_customer_agent(msg, decision.conversation_state)
        case RoutingAction.OWNER_AGENT:
            return await handle_owner_agent(msg, decision.staff_name)
        case RoutingAction.SDR_AGENT:
            return await handle_sdr_agent(msg, decision.staff_name)
        case RoutingAction.RELAY_FORWARD:
            return await handle_relay_forward(msg, decision.target_wa_id)
        case RoutingAction.RELAY_COMMAND:
            return await handle_relay_command(msg, decision.target_wa_id)
        case RoutingAction.AUTH_FLOW:
            return await handle_auth_flow(msg)
        case RoutingAction.IGNORE:
            return None
        case _:
            log.warning(f"Unhandled routing action: {decision.action}")
            return None
