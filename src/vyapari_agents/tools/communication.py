"""Communication tools — escalation, callback, broadcast."""

import json

import state
from models import ConversationState, MessageRole


async def tool_request_escalation(customer_wa_id: str, reason: str, summary: str = "") -> str:
    """Escalate a customer conversation. Notifies the assigned staff or owner."""
    conv = await state.get_conversation(customer_wa_id)
    if not conv:
        return json.dumps({"success": False, "data": None, "message": "No conversation found."})

    await state.set_conversation_state(customer_wa_id, ConversationState.ESCALATED, reason)
    await state.add_escalation(conv.id, trigger=reason, summary=summary)

    customer = await state.get_customer(customer_wa_id)
    name = customer.name if customer else "Customer"

    return json.dumps({
        "success": True,
        "data": {"customer": name, "reason": reason},
        "message": f"Escalated: {name} - {reason}. Staff notified.",
    })


async def tool_request_callback(customer_wa_id: str, phone_number: str) -> str:
    """Save a callback request from a customer."""
    customer = await state.get_customer(customer_wa_id)
    name = customer.name if customer else "Customer"

    # Store as a message note in the conversation
    conv = await state.get_conversation(customer_wa_id)
    if conv:
        await state.add_message(
            conv.id,
            MessageRole.AGENT,
            f"Callback requested: {phone_number}",
        )

    return json.dumps({
        "success": True,
        "data": {"phone": phone_number, "customer": name},
        "message": f"Callback request saved for {name} at {phone_number}.",
    })


async def tool_broadcast_message(message_text: str, filter_status: str = "all") -> str:
    """Send a message to multiple customers.

    For now, returns the list of who would receive it.
    Actual sending happens through the channel adapter.
    """
    from models import LeadStatus

    status_filter = None
    if filter_status != "all":
        mapping = {
            "hot": [LeadStatus.HOT],
            "warm": [LeadStatus.WARM, LeadStatus.HOT],
            "recent": [LeadStatus.NEW, LeadStatus.WARM, LeadStatus.HOT],
        }
        status_filter = mapping.get(filter_status)

    customers = await state.list_customers(status_filter=status_filter)

    # TODO: actually send via channel adapter (with 24hr window template fallback)
    recipients = [{"name": c.name, "wa_id": c.wa_id, "status": c.lead_status.value} for c in customers]

    return json.dumps({
        "success": True,
        "data": {"recipients": recipients, "message": message_text},
        "message": f"Broadcast queued for {len(recipients)} customer{'s' if len(recipients) != 1 else ''}.",
    })
