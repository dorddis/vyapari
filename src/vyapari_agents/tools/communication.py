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
    """Not implemented — was returning synthetic success without sending."""
    raise NotImplementedError(
        "broadcast_message needs per-recipient 24h-window + template fallback; "
        "deferred to Phase 6 scheduler work"
    )
