"""Relay tools — open session, get customer number."""

import json

import state
from services.relay import open_relay


async def tool_open_session(staff_wa_id: str, query: str) -> str:
    """Search for matching leads and open a relay session.

    If multiple matches, returns a numbered list for the owner to pick.
    If one match, opens the session directly.
    """
    # Search for matching customers
    customers = await state.list_customers(search_query=query, limit=10)

    if not customers:
        return json.dumps({
            "success": False,
            "data": None,
            "message": f"No customers found matching '{query}'.",
        })

    if len(customers) == 1:
        # Direct match — open session
        customer = customers[0]
        session, context_msg = await open_relay(staff_wa_id, customer.wa_id)
        if session:
            return json.dumps({
                "success": True,
                "data": {"customer": customer.name, "wa_id": customer.wa_id},
                "message": context_msg,
            })
        return json.dumps({"success": False, "data": None, "message": context_msg})

    # Multiple matches — show list
    leads = []
    for i, c in enumerate(customers, 1):
        conv = await state.get_conversation(c.wa_id)
        leads.append({
            "number": i,
            "name": c.name,
            "wa_id": c.wa_id,
            "status": c.lead_status.value,
            "interested_cars": c.interested_cars,
            "conversation_state": conv.state.value if conv else "none",
        })

    lines = [f"Active conversations matching '{query}':\n"]
    for lead in leads:
        cars = ", ".join(lead["interested_cars"]) if lead["interested_cars"] else "browsing"
        lines.append(
            f"  {lead['number']}. {lead['name']} -- {cars}\n"
            f"     Status: {lead['status'].upper()}"
        )
    lines.append("\nReply with the number to connect.")

    return json.dumps({
        "success": True,
        "data": leads,
        "message": "\n".join(lines),
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
