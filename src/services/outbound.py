"""Outbound customer messaging helpers for owner-triggered actions."""

from __future__ import annotations

from models import LeadStatus, MessageRole

import state
from channels.base import get_channel


def _customer_status_filter(filter_status: str) -> list[LeadStatus] | None:
    if filter_status == "all":
        return None

    mapping = {
        "hot": [LeadStatus.HOT],
        "warm": [LeadStatus.WARM, LeadStatus.HOT],
        "recent": [LeadStatus.NEW, LeadStatus.WARM, LeadStatus.HOT],
    }
    return mapping.get(filter_status)


def _parse_followup_status_filter(status_filter: str) -> list[LeadStatus]:
    valid_statuses = {status.value: status for status in LeadStatus}
    statuses = [
        valid_statuses[value.strip().lower()]
        for value in status_filter.split(",")
        if value.strip().lower() in valid_statuses
    ]
    if not statuses:
        return [LeadStatus.WARM, LeadStatus.HOT]
    return statuses


async def send_customer_text(customer_wa_id: str, text: str) -> str:
    """Send an outbound text and mirror it into conversation history."""
    conversation = await state.get_or_create_conversation(customer_wa_id)
    channel = get_channel()
    message_id = await channel.send_text(customer_wa_id, text)
    await state.add_message(
        conversation.id,
        MessageRole.AGENT,
        text,
        wa_msg_id=message_id,
    )
    return message_id


async def execute_broadcast_message(
    message_text: str,
    filter_status: str = "all",
) -> dict:
    customers = await state.list_customers(
        status_filter=_customer_status_filter(filter_status),
        limit=1000,
    )

    recipients = []
    for customer in customers:
        await send_customer_text(customer.wa_id, message_text)
        recipients.append({
            "name": customer.name,
            "wa_id": customer.wa_id,
            "status": customer.lead_status.value,
        })

    return {
        "recipient_count": len(recipients),
        "recipients": recipients,
        "message_text": message_text,
    }


async def _build_followup_message(customer) -> str:
    interest = customer.interested_cars[0] if customer.interested_cars else "our latest stock"
    conversation = await state.get_conversation(customer.wa_id)
    recent_customer_line = ""
    if conversation:
        messages = await state.get_messages(conversation.id)
        for message in reversed(messages):
            if message.role == MessageRole.CUSTOMER:
                recent_customer_line = message.content.strip()
                break

    base = f"Hi {customer.name}, following up from Sharma Motors about the {interest}."
    if recent_customer_line:
        return (
            f"{base} You had asked: \"{recent_customer_line}\" "
            "Reply here if you want the latest price, photos, or a visit slot."
        )
    return (
        f"{base} Reply here if you want the latest price, photos, or a visit slot."
    )


async def execute_batch_followup(
    date: str = "yesterday",
    status_filter: str = "warm,hot",
) -> dict:
    customers = await state.list_customers(
        status_filter=_parse_followup_status_filter(status_filter),
        limit=50,
    )

    followups = []
    for customer in customers:
        message_text = await _build_followup_message(customer)
        await send_customer_text(customer.wa_id, message_text)
        followups.append({
            "name": customer.name,
            "wa_id": customer.wa_id,
            "status": customer.lead_status.value,
            "interested_cars": customer.interested_cars,
            "sent_message": message_text,
            "date": date,
        })

    return {
        "followup_count": len(followups),
        "followups": followups,
        "date": date,
        "status_filter": status_filter,
    }
