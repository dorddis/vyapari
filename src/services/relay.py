"""Relay session management.

Handles the owner/SDR <-> customer relay lifecycle:
- Open session (with conversation summary + last N messages)
- Forward messages between parties
- Close session (manual or timeout)
- Session summary generation
"""

import state
from models import (
    ConversationState,
    MessageRole,
    RelaySessionRecord,
)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

async def open_relay(
    staff_wa_id: str,
    customer_wa_id: str,
) -> tuple[RelaySessionRecord | None, str]:
    """Open a relay session between staff and customer.

    Returns (session, context_message).
    Returns (None, error_message) if the customer is already in a relay.
    """
    # Check customer exists
    customer = await state.get_customer(customer_wa_id)
    if not customer:
        return None, "Customer not found."

    # Check conversation exists
    conversation = await state.get_conversation(customer_wa_id)
    if not conversation:
        return None, "No active conversation with this customer."

    # Create relay session (state.py handles the lock check)
    session = await state.create_relay_session(staff_wa_id, customer_wa_id)
    if not session:
        return None, "This customer is already in a relay session with another staff member."

    # Build context message
    context = await get_session_context(customer_wa_id)
    staff = await state.get_staff(staff_wa_id)
    staff_name = staff.name if staff else "Staff"

    msg = (
        f"Session with {customer.name} started.\n"
        f"Everything you type goes to the customer.\n"
        f"Use /done when finished. Use / for commands.\n\n"
        f"{context}"
    )
    return session, msg


async def close_relay(
    staff_wa_id: str,
    reason: str = "manual",
) -> tuple[bool, str]:
    """Close a relay session.

    Returns (success, message).
    """
    session = await state.close_relay_session(staff_wa_id, reason=reason)
    if not session:
        return False, "No active session to close."

    customer = await state.get_customer(session.customer_wa_id)
    name = customer.name if customer else "Customer"
    queued = await get_queued_escalations(staff_wa_id)

    if reason == "timeout":
        base_message = f"Session with {name} auto-closed (idle timeout). Agent resumed."
    else:
        base_message = f"Session with {name} closed. Agent resumed."

    if queued:
        return True, f"{base_message}\n\n{queued}"
    return True, base_message


async def get_queued_escalations(staff_wa_id: str) -> str:
    """Get escalations that fired while staff was in a relay session.

    Called after session close to show what was missed.
    """
    # For now, return empty — escalation queuing will be built with the agents
    # TODO: track escalations during relay and show them here
    notifications = await state.pop_staff_escalation_notifications(staff_wa_id)
    if not notifications:
        return ""

    lines = ["WHILE YOU WERE CHATTING:"]
    for notification in notifications:
        lines.append(
            f"- {notification.customer_name} ({notification.lead_status}) - {notification.summary}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Relay command helpers
# ---------------------------------------------------------------------------

async def get_active_session_customer(staff_wa_id: str) -> tuple[RelaySessionRecord | None, object | None]:
    """Return the active relay session and customer, if any."""
    session = await state.get_active_relay_for_staff(staff_wa_id)
    if not session:
        return None, None
    customer = await state.get_customer(session.customer_wa_id)
    return session, customer


async def get_relay_customer_number(staff_wa_id: str) -> str:
    """Return the active relay customer's phone number."""
    session, customer = await get_active_session_customer(staff_wa_id)
    if not session or not customer:
        return "No active session."
    return f"{customer.name}: +{customer.wa_id}"


async def get_relay_status(staff_wa_id: str) -> str:
    """Return current lead status and conversation metadata for the active relay."""
    session, customer = await get_active_session_customer(staff_wa_id)
    if not session or not customer:
        return "No active session."

    conversation = await state.get_conversation(customer.wa_id)
    messages = await state.get_messages(conversation.id) if conversation else []
    last_message = messages[-1].content if messages else "No messages yet."
    interested_cars = ", ".join(customer.interested_cars) if customer.interested_cars else "Browsing"
    escalation = conversation.escalation_reason if conversation and conversation.escalation_reason else "None"

    return (
        f"Current session: {customer.name}\n"
        f"Phone: +{customer.wa_id}\n"
        f"Lead status: {customer.lead_status.value}\n"
        f"Conversation state: {conversation.state.value if conversation else 'none'}\n"
        f"Interested cars: {interested_cars}\n"
        f"Escalation reason: {escalation}\n"
        f"Total messages: {len(messages)}\n"
        f"Last message: {last_message}"
    )


async def switch_relay_session(staff_wa_id: str, query: str) -> str:
    """Switch the active relay session to a different customer if the query resolves cleanly."""
    current_session, current_customer = await get_active_session_customer(staff_wa_id)
    if not current_session or not current_customer:
        return "No active session."

    matches = await state.list_customers(search_query=query, limit=10)
    matches = [customer for customer in matches if customer.wa_id != current_customer.wa_id]

    if not matches:
        return f"No customers found matching '{query}'. Current session with {current_customer.name} is still active."

    if len(matches) > 1:
        lines = [f"Multiple matches for '{query}'. Current session with {current_customer.name} is still active.", ""]
        for idx, customer in enumerate(matches, start=1):
            cars = ", ".join(customer.interested_cars) if customer.interested_cars else "browsing"
            lines.append(
                f"{idx}. {customer.name} - {cars} ({customer.lead_status.value.upper()})"
            )
        return "\n".join(lines)

    next_customer = matches[0]
    closed, close_message = await close_relay(staff_wa_id)
    if not closed:
        return close_message

    session, open_message = await open_relay(staff_wa_id, next_customer.wa_id)
    if not session:
        return open_message

    return f"{close_message}\n\n{open_message}"


# ---------------------------------------------------------------------------
# Message forwarding
# ---------------------------------------------------------------------------

async def forward_to_customer(
    staff_wa_id: str,
    text: str,
) -> tuple[str | None, str]:
    """Forward a staff message to the customer in their relay session.

    Returns (customer_wa_id, text_to_send) or (None, error).
    Stores the message in conversation history.
    """
    session = await state.get_active_relay_for_staff(staff_wa_id)
    if not session:
        return None, "No active relay session."

    # Store message in conversation history
    staff = await state.get_staff(staff_wa_id)
    role = MessageRole.OWNER if staff and staff.role.value == "owner" else MessageRole.SDR

    await state.add_message(
        conversation_id=session.conversation_id,
        role=role,
        content=text,
    )

    # Update relay activity
    await state.update_relay_last_active(staff_wa_id)

    return session.customer_wa_id, text


async def forward_to_staff(
    customer_wa_id: str,
    text: str,
    sender_name: str = "Customer",
) -> tuple[str | None, str]:
    """Forward a customer message to the staff member in the relay session.

    Returns (staff_wa_id, formatted_text) or (None, error).
    Stores the message in conversation history.
    """
    session = await state.get_active_relay_for_customer(customer_wa_id)
    if not session:
        return None, "No active relay session for this customer."

    # Store message in conversation history
    conv = await state.get_conversation(customer_wa_id)
    if conv:
        await state.add_message(
            conversation_id=conv.id,
            role=MessageRole.CUSTOMER,
            content=text,
        )

    # Format with sender name prefix
    formatted = f"[{sender_name}]: {text}"

    return session.staff_wa_id, formatted


# ---------------------------------------------------------------------------
# Context generation
# ---------------------------------------------------------------------------

async def get_session_context(
    customer_wa_id: str,
    last_n: int = 5,
) -> str:
    """Generate conversation context for relay session start.

    Returns formatted summary + last N messages.
    """
    customer = await state.get_customer(customer_wa_id)
    conversation = await state.get_conversation(customer_wa_id)

    if not customer or not conversation:
        return "No conversation history."

    messages = await state.get_messages(conversation.id)

    # Build summary
    parts = []
    parts.append("--- CONVERSATION SUMMARY ---")
    parts.append(f"Customer: {customer.name}")
    parts.append(f"Lead status: {customer.lead_status.value}")
    if customer.interested_cars:
        parts.append(f"Interested in: {', '.join(customer.interested_cars)}")
    if conversation.escalation_reason:
        parts.append(f"Escalation reason: {conversation.escalation_reason}")
    parts.append(f"Total messages: {len(messages)}")

    # Last N messages
    if messages:
        parts.append("")
        parts.append(f"--- LAST {min(last_n, len(messages))} MESSAGES ---")
        for msg in messages[-last_n:]:
            role_label = {
                MessageRole.CUSTOMER: "Customer",
                MessageRole.AGENT: "Agent",
                MessageRole.OWNER: "Owner",
                MessageRole.SDR: "SDR",
            }.get(msg.role, msg.role.value)
            parts.append(f"[{role_label}] {msg.content}")

    return "\n".join(parts)
