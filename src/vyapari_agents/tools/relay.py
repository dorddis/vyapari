"""Relay tools - open session, get customer number."""

import json

import state
from services.relay import open_relay, stage_relay_selection


async def tool_open_session(staff_wa_id: str, query: str) -> str:
    """Search for matching leads and open a relay session.

    Use this tool when:
    - the owner or SDR wants to personally take over a customer conversation

    Do not use this tool when:
    - the request is only to inspect lead details without starting a relay
    - the customer target is too ambiguous to resolve

    Before calling:
    - search for the matching customer or lead first
    - if multiple matches exist, return the shortlist instead of forcing a session

    After calling:
    - confirm which session was opened or what shortlist must be resolved next
    - once a session is opened, treat that action as complete for the turn

    If multiple matches, returns a numbered list for the owner to pick.
    If one match, opens the session directly.

    This tool is terminal for the current action flow:
    - yes
    """
    customers = await state.list_customers(search_query=query, limit=10)

    if not customers:
        return json.dumps({
            "success": False,
            "data": None,
            "message": f"No customers found matching '{query}'.",
        })

    if len(customers) == 1:
        customer = customers[0]
        session, context_msg = await open_relay(staff_wa_id, customer.wa_id)
        if session:
            return json.dumps({
                "success": True,
                "data": {"customer": customer.name, "wa_id": customer.wa_id},
                "message": context_msg,
            })
        return json.dumps({"success": False, "data": None, "message": context_msg})

    leads = []
    for index, customer in enumerate(customers, start=1):
        conversation = await state.get_conversation(customer.wa_id)
        leads.append({
            "number": index,
            "name": customer.name,
            "wa_id": customer.wa_id,
            "status": customer.lead_status.value,
            "interested_cars": customer.interested_cars,
            "conversation_state": conversation.state.value if conversation else "none",
        })

    prompt = await stage_relay_selection(
        staff_wa_id=staff_wa_id,
        mode="open",
        query=query,
        customers=customers,
        heading=f"Active conversations matching '{query}':",
    )

    return json.dumps({
        "success": True,
        "data": leads,
        "message": prompt,
    })


async def tool_get_customer_number(customer_identifier: str) -> str:
    """Get a customer's phone number (for direct call)."""
    customer = await state.get_customer(customer_identifier)
    if not customer:
        results = await state.list_customers(search_query=customer_identifier, limit=1)
        customer = results[0] if results else None

    if not customer:
        return json.dumps({
            "success": False,
            "data": None,
            "message": f"Customer '{customer_identifier}' not found.",
        })

    return json.dumps({
        "success": True,
        "data": {
            "name": customer.name,
            "phone": customer.wa_id,
            "lead_status": customer.lead_status.value,
        },
        "message": f"{customer.name}: +{customer.wa_id}",
    })
