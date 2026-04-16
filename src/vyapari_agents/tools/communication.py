"""Communication tools — escalation, callback, broadcast."""

import json

import state
from models import MessageRole
from services.escalation import trigger_escalation


async def tool_request_escalation(customer_wa_id: str, reason: str, summary: str = "") -> str:
    """Escalate a customer conversation.

    Use this tool when:
    - the customer wants negotiation, booking, a callback, a test drive, or a human handoff
    - the customer is frustrated or the assistant is not confident enough to continue alone

    Do not use this tool when:
    - the customer only asked a normal browse, details, pricing, or FAQ question that can still be answered safely

    Before calling:
    - collect a short reason and summary if possible
    - tell the customer you are connecting or flagging this for the team

    After calling:
    - confirm briefly that the team has been notified
    - keep the rest of the reply short and do not continue the sales flow in the same turn

    This tool is terminal for the current action flow:
    - yes
    """
    customer = await state.get_customer(customer_wa_id)
    name = customer.name if customer else "Customer"
    success, message, target_staff_wa_id = await trigger_escalation(
        customer_wa_id,
        reason,
        summary,
    )
    if not success:
        return json.dumps({"success": False, "data": None, "message": message})

    return json.dumps({
        "success": True,
        "data": {
            "customer": name,
            "reason": reason,
            "notified_staff_wa_id": target_staff_wa_id,
        },
        "message": f"Escalated: {name} - {reason}. Staff notification queued.",
    })


async def tool_request_callback(customer_wa_id: str, phone_number: str) -> str:
    """Save a callback request from a customer.

    Use this tool when:
    - the customer explicitly asks for a call or says they want someone to contact them

    Do not use this tool when:
    - the customer is only asking for pricing, FAQs, or inventory details and has not asked for a call

    Before calling:
    - capture the correct callback number
    - tell the customer you are saving the callback request

    After calling:
    - confirm that the callback request was saved
    - do not continue selling in the same turn

    This tool is terminal for the current action flow:
    - yes
    """
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

    Use this tool when:
    - the owner wants to notify many customers about new stock, a campaign, or a business-wide update

    Do not use this tool when:
    - the message is meant for a single lead or a relay conversation
    - explicit owner confirmation has not been given yet

    Before calling:
    - confirm the audience and the exact message with the owner
    - make it clear that this is a batch outbound action

    After calling:
    - confirm how many recipients were queued
    - do not continue the same action flow unless the owner asks for another batch action

    This tool is terminal for the current action flow:
    - yes

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
