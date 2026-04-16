"""Lead management tools — active leads, details, stats, assignment, batch followup."""

import json

import state
from models import LeadStatus, MessageRole


async def tool_get_active_leads(
    status_filter: str | None = None,
    search_query: str | None = None,
    limit: int = 10,
) -> str:
    """Get active leads, optionally filtered by status or search query."""
    filter_list = None
    if status_filter:
        mapping = {
            "hot": [LeadStatus.HOT],
            "warm": [LeadStatus.WARM],
            "new": [LeadStatus.NEW],
            "quiet": [LeadStatus.QUIET],
            "converted": [LeadStatus.CONVERTED],
            "all": None,
        }
        filter_list = mapping.get(status_filter.lower())

    customers = await state.list_customers(
        status_filter=filter_list,
        search_query=search_query,
        limit=limit,
    )

    leads = []
    for c in customers:
        conv = await state.get_conversation(c.wa_id)
        msgs = await state.get_messages(conv.id) if conv else []
        last_msg = msgs[-1] if msgs else None

        leads.append({
            "name": c.name,
            "wa_id": c.wa_id,
            "status": c.lead_status.value,
            "interested_cars": c.interested_cars,
            "last_message": last_msg.content[:80] if last_msg else "",
            "last_message_role": last_msg.role.value if last_msg else "",
            "last_active": c.last_message_at.isoformat() if c.last_message_at else "",
        })

    return json.dumps({
        "success": True,
        "data": leads,
        "message": f"{len(leads)} lead{'s' if len(leads) != 1 else ''} found.",
    })


async def tool_get_lead_details(identifier: str) -> str:
    """Get full details for a customer by wa_id, phone, or name search."""
    # Try exact wa_id first
    customer = await state.get_customer(identifier)

    # Try search if not found
    if not customer:
        results = await state.list_customers(search_query=identifier, limit=1)
        customer = results[0] if results else None

    if not customer:
        return json.dumps({"success": False, "data": None, "message": f"Customer '{identifier}' not found."})

    conv = await state.get_conversation(customer.wa_id)
    msgs = await state.get_messages(conv.id) if conv else []

    # Build conversation summary
    msg_summary = []
    for msg in msgs[-10:]:  # last 10
        role_label = {"customer": "C", "agent": "A", "owner": "O", "sdr": "S"}.get(msg.role.value, "?")
        msg_summary.append(f"[{role_label}] {msg.content[:100]}")

    return json.dumps({
        "success": True,
        "data": {
            "name": customer.name,
            "wa_id": customer.wa_id,
            "lead_status": customer.lead_status.value,
            "source": customer.source,
            "interested_cars": customer.interested_cars,
            "created_at": customer.created_at.isoformat(),
            "last_message_at": customer.last_message_at.isoformat(),
            "conversation_state": conv.state.value if conv else "none",
            "escalation_reason": conv.escalation_reason if conv else "",
            "total_messages": len(msgs),
            "recent_messages": msg_summary,
        },
        "message": f"Lead details for {customer.name}.",
    })


async def tool_get_stats(period: str = "today") -> str:
    """Get business stats for a period (today/week/month)."""
    # For MVP: aggregate from in-memory state
    all_customers = await state.list_customers(limit=1000)

    by_status = {}
    for c in all_customers:
        s = c.lead_status.value
        by_status[s] = by_status.get(s, 0) + 1

    total_conversations = len(state._conversations)
    total_messages = sum(len(msgs) for msgs in state._messages.values())

    # Top queried cars (from interested_cars across customers)
    car_mentions: dict[str, int] = {}
    for c in all_customers:
        for car in c.interested_cars:
            car_mentions[car] = car_mentions.get(car, 0) + 1
    top_cars = sorted(car_mentions.items(), key=lambda x: x[1], reverse=True)[:5]

    return json.dumps({
        "success": True,
        "data": {
            "period": period,
            "total_leads": len(all_customers),
            "by_status": by_status,
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "top_queried_cars": [{"car": c, "count": n} for c, n in top_cars],
        },
        "message": f"{len(all_customers)} total leads. {by_status.get('hot', 0)} hot.",
    })


async def tool_assign_lead(customer_identifier: str, staff_identifier: str) -> str:
    """Assign a lead to a specific staff member."""
    # Find customer
    customer = await state.get_customer(customer_identifier)
    if not customer:
        results = await state.list_customers(search_query=customer_identifier, limit=1)
        customer = results[0] if results else None
    if not customer:
        return json.dumps({"success": False, "data": None, "message": f"Customer '{customer_identifier}' not found."})

    # Find staff
    staff = await state.get_staff(staff_identifier)
    if not staff:
        all_staff = await state.list_staff()
        matches = [s for s in all_staff if staff_identifier.lower() in s.name.lower()]
        staff = matches[0] if matches else None
    if not staff:
        return json.dumps({"success": False, "data": None, "message": f"Staff '{staff_identifier}' not found."})

    # Assign
    conv = await state.get_conversation(customer.wa_id)
    if conv:
        conv.assigned_to = staff.wa_id

    return json.dumps({
        "success": True,
        "data": {"customer": customer.name, "staff": staff.name},
        "message": f"Assigned {customer.name} to {staff.name}.",
    })


async def tool_batch_followup(
    date: str = "yesterday",
    status_filter: str = "warm,hot",
) -> str:
    """Generate and send personalized follow-ups for leads.

    Loads each customer's conversation history, generates a personalized
    follow-up, and sends it. Uses template if outside 24hr window.

    For now: returns what WOULD be sent. Actual LLM generation + sending
    will be wired when the agents are running.
    """
    statuses = [LeadStatus(s.strip().lower()) for s in status_filter.split(",") if s.strip().lower() in [e.value for e in LeadStatus]]
    if not statuses:
        statuses = [LeadStatus.WARM, LeadStatus.HOT]

    customers = await state.list_customers(status_filter=statuses, limit=50)

    followups = []
    for c in customers:
        conv = await state.get_conversation(c.wa_id)
        msgs = await state.get_messages(conv.id) if conv else []
        last_customer_msg = ""
        for msg in reversed(msgs):
            if msg.role == MessageRole.CUSTOMER:
                last_customer_msg = msg.content[:80]
                break

        followups.append({
            "name": c.name,
            "wa_id": c.wa_id,
            "status": c.lead_status.value,
            "interested_cars": c.interested_cars,
            "last_message": last_customer_msg,
            # TODO: generate personalized message via LLM (asyncio.gather)
            "suggested_followup": f"Hi {c.name}, still thinking about the {c.interested_cars[0] if c.interested_cars else 'car'}?",
        })

    return json.dumps({
        "success": True,
        "data": followups,
        "message": f"{len(followups)} follow-ups ready to send.",
    })
