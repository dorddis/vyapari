"""Owner + SDR Agents — OpenAI Agents SDK.

Owner gets 19 tools (full access). SDR gets 7 (read-only + relay).
Per-staff sessions via session_id = f"staff_{wa_id}".
"""

import json
import logging

from agents import Agent, Runner, function_tool, RunContextWrapper, ModelSettings

import config
import state
from catalogue import get_car_detail
from vyapari_agents.context import StaffContext
from vyapari_agents.prompts import build_owner_system_prompt, build_sdr_system_prompt
from vyapari_agents.tools.catalogue import (
    tool_add_item,
    tool_check_availability,
    tool_get_catalogue_summary,
    tool_get_item_details,
    tool_mark_reserved,
    tool_mark_sold,
    tool_search_catalogue,
    tool_update_item,
)
from vyapari_agents.tools.business import (
    tool_add_faq,
    tool_get_business_info,
    tool_get_faq_answer,
    tool_update_greeting,
)

log = logging.getLogger("vyapari.agents.owner")

HARD_CONFIRM_ACTIONS = {
    "mark_sold",
    "mark_reserved",
    "remove_staff",
    "broadcast_message",
    "batch_followup",
}
CONFIRM_WORDS = {"yes", "y", "haan", "ha", "confirm", "confirmed", "ok", "okay", "kar do"}
CANCEL_WORDS = {"no", "n", "cancel", "stop", "mat karo", "nahin", "nahi"}


def _parse_tool_message(result: str) -> str:
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return result
    return payload.get("message", result)


def _describe_car(item_id: int) -> str | None:
    car = get_car_detail(item_id)
    if not car:
        return None
    return f"{car['year']} {car['make']} {car['model']} {car['variant']} (ID {item_id})"


async def _resolve_staff_for_confirmation(identifier: str) -> tuple[str, str] | None:
    direct = await state.get_staff(identifier)
    if direct:
        return direct.wa_id, direct.name

    all_staff = await state.list_staff()
    matches = [staff for staff in all_staff if identifier.lower() in staff.name.lower()]
    if len(matches) == 1:
        return matches[0].wa_id, matches[0].name
    return None


async def _count_broadcast_recipients(filter_status: str) -> int:
    from models import LeadStatus

    status_filter = None
    if filter_status != "all":
        mapping = {
            "hot": [LeadStatus.HOT],
            "warm": [LeadStatus.WARM, LeadStatus.HOT],
            "recent": [LeadStatus.NEW, LeadStatus.WARM, LeadStatus.HOT],
        }
        status_filter = mapping.get(filter_status)
    recipients = await state.list_customers(status_filter=status_filter, limit=1000)
    return len(recipients)


async def _count_followup_recipients(status_filter: str) -> int:
    from models import LeadStatus

    valid_statuses = {status.value: status for status in LeadStatus}
    statuses = [
        valid_statuses[value.strip()]
        for value in status_filter.split(",")
        if value.strip() in valid_statuses
    ]
    if not statuses:
        statuses = [LeadStatus.WARM, LeadStatus.HOT]
    recipients = await state.list_customers(status_filter=statuses, limit=1000)
    return len(recipients)


async def request_owner_confirmation(
    staff_wa_id: str,
    action_name: str,
    payload: dict,
) -> str:
    """Stage a hard-confirm owner action and return the human-facing prompt."""
    if action_name not in HARD_CONFIRM_ACTIONS:
        raise ValueError(f"Action '{action_name}' is not hard-confirmed.")

    if action_name == "mark_sold":
        description = _describe_car(payload["item_id"])
        if not description:
            return _parse_tool_message(tool_mark_sold(payload["item_id"]))
        summary = f"mark {description} as sold"
        prompt = f"Confirm sale update: {description}. Reply YES to confirm or NO to cancel."
    elif action_name == "mark_reserved":
        description = _describe_car(payload["item_id"])
        if not description:
            return _parse_tool_message(tool_mark_reserved(**payload))
        token_amount = payload.get("token_amount")
        token_text = f" with token Rs {token_amount}" if token_amount is not None else ""
        summary = f"reserve {description} for {payload['customer_name']}{token_text}"
        prompt = (
            f"Confirm reservation: {description} for {payload['customer_name']}{token_text}. "
            "Reply YES to confirm or NO to cancel."
        )
    elif action_name == "remove_staff":
        resolved = await _resolve_staff_for_confirmation(payload["identifier"])
        if not resolved:
            from vyapari_agents.tools.staff import tool_remove_staff
            return _parse_tool_message(await tool_remove_staff(payload["identifier"]))
        resolved_wa_id, resolved_name = resolved
        payload = {**payload, "identifier": resolved_wa_id, "resolved_name": resolved_name}
        summary = f"remove {resolved_name} ({resolved_wa_id})"
        prompt = f"Confirm staff removal: {resolved_name} ({resolved_wa_id}). Reply YES to confirm or NO to cancel."
    elif action_name == "broadcast_message":
        recipient_count = await _count_broadcast_recipients(payload["filter_status"])
        summary = f"broadcast to {recipient_count} customer(s)"
        prompt = (
            f"Confirm broadcast to {recipient_count} customer(s) with filter '{payload['filter_status']}': "
            f"\"{payload['message_text']}\" Reply YES to confirm or NO to cancel."
        )
    elif action_name == "batch_followup":
        recipient_count = await _count_followup_recipients(payload["status_filter"])
        summary = (
            f"send batch follow-ups to {recipient_count} lead(s) "
            f"for {payload['date']} with filter '{payload['status_filter']}'"
        )
        prompt = (
            f"Confirm batch follow-up for {recipient_count} lead(s) "
            f"for {payload['date']} with filter '{payload['status_filter']}'. "
            "Reply YES to confirm or NO to cancel."
        )
    else:
        raise ValueError(f"Unsupported action '{action_name}'.")

    await state.set_pending_owner_action(
        staff_wa_id=staff_wa_id,
        action_name=action_name,
        payload=payload,
        summary=summary,
        confirmation_prompt=prompt,
    )
    return prompt


async def _execute_pending_owner_action(action_name: str, payload: dict) -> str:
    if action_name == "mark_sold":
        from services.catalogue_actions import execute_mark_sold

        result = await execute_mark_sold(payload["item_id"])
        return result["message"]
    if action_name == "mark_reserved":
        from services.catalogue_actions import execute_mark_reserved

        result = await execute_mark_reserved(**payload)
        return result["message"]
    if action_name == "remove_staff":
        from vyapari_agents.tools.staff import tool_remove_staff
        return _parse_tool_message(await tool_remove_staff(payload["identifier"]))
    if action_name == "broadcast_message":
        from vyapari_agents.tools.communication import tool_broadcast_message
        return _parse_tool_message(
            await tool_broadcast_message(payload["message_text"], payload["filter_status"])
        )
    if action_name == "batch_followup":
        from vyapari_agents.tools.leads import tool_batch_followup
        return _parse_tool_message(
            await tool_batch_followup(payload["date"], payload["status_filter"])
        )
    return "Pending action type is not supported."


async def handle_pending_owner_confirmation(staff_wa_id: str, message: str) -> str | None:
    """Resolve a queued owner confirmation without another LLM turn."""
    pending = await state.get_pending_owner_action(staff_wa_id)
    if not pending:
        return None

    normalized = " ".join((message or "").strip().lower().split())
    if normalized in CONFIRM_WORDS:
        try:
            return await _execute_pending_owner_action(pending.action_name, pending.payload)
        finally:
            await state.clear_pending_owner_action(staff_wa_id)
    if normalized in CANCEL_WORDS:
        await state.clear_pending_owner_action(staff_wa_id)
        return f"Cancelled. I did not {pending.summary}."
    return f"{pending.confirmation_prompt} Pending action is still waiting."


def _confirmation_tool_result(action_name: str, prompt: str) -> str:
    return json.dumps({
        "success": False,
        "data": {
            "confirmation_required": True,
            "action_name": action_name,
        },
        "message": prompt,
    })


# ---------------------------------------------------------------------------
# Owner-only tool wrappers
# ---------------------------------------------------------------------------

@function_tool
def search_catalogue(
    max_price: float | None = None,
    min_price: float | None = None,
    fuel_type: str | None = None,
    make: str | None = None,
    transmission: str | None = None,
    max_km: int | None = None,
) -> str:
    """Search the car catalogue with optional filters."""
    return tool_search_catalogue(max_price, min_price, fuel_type, make, transmission, max_km)


@function_tool
def get_item_details(item_id: int) -> str:
    """Get full details for a specific car."""
    return tool_get_item_details(item_id)


@function_tool
def check_availability(item_id: int) -> str:
    """Check if a car is available, sold, or reserved."""
    return tool_check_availability(item_id)


@function_tool
def get_business_info() -> str:
    """Get dealership address, hours, contact."""
    return tool_get_business_info()


@function_tool
def get_faq_answer(topic: str) -> str:
    """Find FAQ answers about a topic."""
    return tool_get_faq_answer(topic)


@function_tool
def add_item(
    make: str,
    model: str,
    year: int,
    price_lakhs: float,
    variant: str = "",
    fuel_type: str = "Petrol",
    transmission: str = "Manual",
    km_driven: int = 0,
    num_owners: int = 1,
    color: str = "",
    condition: str = "Good",
) -> str:
    """Add a new car to the catalogue."""
    return tool_add_item(make, model, year, price_lakhs, variant, fuel_type,
                         transmission, km_driven, num_owners, color, condition)


@function_tool
def update_item(item_id: int, field: str, value: str) -> str:
    """Update a field on a car. E.g. update_item(5, "price_lakhs", "7.8")."""
    # Convert numeric values
    try:
        if field in ("price_lakhs", "km_driven", "num_owners", "year"):
            value = float(value) if "." in str(value) else int(value)
    except ValueError:
        pass
    return tool_update_item(item_id, **{field: value})


@function_tool
async def mark_sold(
    ctx: RunContextWrapper[StaffContext],
    item_id: int,
) -> str:
    """Mark a car as sold."""
    prompt = await request_owner_confirmation(
        ctx.context.staff_id,
        "mark_sold",
        {"item_id": item_id},
    )
    return _confirmation_tool_result("mark_sold", prompt)


@function_tool
async def mark_reserved(
    ctx: RunContextWrapper[StaffContext],
    item_id: int,
    customer_name: str,
    token_amount: float | None = None,
) -> str:
    """Reserve a car for a customer (token payment received)."""
    prompt = await request_owner_confirmation(
        ctx.context.staff_id,
        "mark_reserved",
        {
            "item_id": item_id,
            "customer_name": customer_name,
            "token_amount": token_amount,
        },
    )
    return _confirmation_tool_result("mark_reserved", prompt)


@function_tool
def get_catalogue_summary() -> str:
    """Get inventory overview — counts, price range, by fuel type and make."""
    return tool_get_catalogue_summary()


@function_tool
def add_faq(question: str, answer: str, category: str = "General") -> str:
    """Add a new FAQ entry."""
    return tool_add_faq(question, answer, category)


@function_tool
def update_greeting(new_greeting: str) -> str:
    """Update the business greeting message."""
    return tool_update_greeting(new_greeting)


@function_tool
async def get_active_leads(
    status_filter: str | None = None,
    search_query: str | None = None,
    limit: int = 10,
) -> str:
    """Get active leads, optionally filtered by status or search query."""
    from vyapari_agents.tools.leads import tool_get_active_leads
    return await tool_get_active_leads(status_filter, search_query, limit)


@function_tool
async def get_lead_details(identifier: str) -> str:
    """Get full details for a customer by phone number or name."""
    from vyapari_agents.tools.leads import tool_get_lead_details
    return await tool_get_lead_details(identifier)


@function_tool
async def get_stats(period: str = "today") -> str:
    """Get business stats — lead counts, top queried cars, by status."""
    from vyapari_agents.tools.leads import tool_get_stats
    return await tool_get_stats(period)


@function_tool
async def open_session(
    ctx: RunContextWrapper[StaffContext],
    query: str,
) -> str:
    """Open a relay session to chat with a customer. Search by name or car."""
    from vyapari_agents.tools.relay import tool_open_session
    return await tool_open_session(ctx.context.staff_id, query)


@function_tool
async def get_customer_number(identifier: str) -> str:
    """Get a customer's phone number for direct call."""
    from vyapari_agents.tools.relay import tool_get_customer_number
    return await tool_get_customer_number(identifier)


@function_tool
async def add_staff(
    ctx: RunContextWrapper[StaffContext],
    name: str,
    wa_id: str,
    role: str = "sdr",
) -> str:
    """Add a new staff member and generate an OTP invite."""
    from vyapari_agents.tools.staff import tool_add_staff
    return await tool_add_staff(name, wa_id, role, added_by=ctx.context.staff_id)


@function_tool
async def remove_staff(
    ctx: RunContextWrapper[StaffContext],
    identifier: str,
) -> str:
    """Remove a staff member by phone number or name."""
    prompt = await request_owner_confirmation(
        ctx.context.staff_id,
        "remove_staff",
        {"identifier": identifier},
    )
    return _confirmation_tool_result("remove_staff", prompt)


@function_tool
async def list_staff() -> str:
    """List all active and invited staff members."""
    from vyapari_agents.tools.staff import tool_list_staff
    return await tool_list_staff()


@function_tool
async def assign_lead(customer_identifier: str, staff_identifier: str) -> str:
    """Assign a lead to a specific staff member."""
    from vyapari_agents.tools.leads import tool_assign_lead
    return await tool_assign_lead(customer_identifier, staff_identifier)


@function_tool
async def broadcast_message(
    ctx: RunContextWrapper[StaffContext],
    message_text: str,
    filter_status: str = "all",
) -> str:
    """Send a message to multiple customers."""
    prompt = await request_owner_confirmation(
        ctx.context.staff_id,
        "broadcast_message",
        {
            "message_text": message_text,
            "filter_status": filter_status,
        },
    )
    return _confirmation_tool_result("broadcast_message", prompt)


@function_tool
async def batch_followup(
    ctx: RunContextWrapper[StaffContext],
    date: str = "yesterday",
    status_filter: str = "warm,hot",
) -> str:
    """Generate and send personalized follow-ups for leads from a date."""
    prompt = await request_owner_confirmation(
        ctx.context.staff_id,
        "batch_followup",
        {
            "date": date,
            "status_filter": status_filter,
        },
    )
    return _confirmation_tool_result("batch_followup", prompt)


# ---------------------------------------------------------------------------
# Agent definitions
# ---------------------------------------------------------------------------

def _owner_instructions(ctx: RunContextWrapper[StaffContext], agent: Agent) -> str:
    return build_owner_system_prompt(ctx.context.name, ctx.context.role)


def _sdr_instructions(ctx: RunContextWrapper[StaffContext], agent: Agent) -> str:
    return build_sdr_system_prompt(ctx.context.name)


_model_settings = ModelSettings(
    reasoning={"effort": "low"},  # GPT-5.4 tool calling fix
)

owner_agent = Agent[StaffContext](
    name="Sharma Motors Business Oracle",
    instructions=_owner_instructions,
    tools=[
        search_catalogue, get_item_details, check_availability, get_business_info,
        get_faq_answer, add_item, update_item, mark_sold, mark_reserved,
        get_catalogue_summary, add_faq, update_greeting,
        get_active_leads, get_lead_details, get_stats, assign_lead,
        open_session, get_customer_number,
        add_staff, remove_staff, list_staff,
        broadcast_message, batch_followup,
    ],
    model=config.OPENAI_MAIN_MODEL,
    model_settings=_model_settings,
)

sdr_agent = Agent[StaffContext](
    name="Sharma Motors SDR Agent",
    instructions=_sdr_instructions,
    tools=[
        search_catalogue, get_item_details, check_availability, get_business_info,
        get_active_leads, get_lead_details,
        open_session, get_customer_number,
    ],
    model=config.OPENAI_MAIN_MODEL,
    model_settings=_model_settings,
)


# ---------------------------------------------------------------------------
# Run functions (called from router handlers)
# ---------------------------------------------------------------------------

async def run_owner_agent(wa_id: str, message: str) -> str:
    """Run the Owner Agent for a single message turn."""
    from models import MessageRole
    from services.relay import handle_pending_relay_selection

    staff = await state.get_staff(wa_id)
    if not staff:
        return "Staff not found."

    pending_confirmation_reply = await handle_pending_owner_confirmation(wa_id, message)
    if pending_confirmation_reply is not None:
        return pending_confirmation_reply

    pending_selection_reply = await handle_pending_relay_selection(wa_id, message)
    if pending_selection_reply is not None:
        return pending_selection_reply

    relay = await state.get_active_relay_for_staff(wa_id)

    ctx = StaffContext(
        staff_id=wa_id,
        name=staff.name,
        role=staff.role.value,
        has_active_relay=relay is not None,
        active_relay_customer=relay.customer_wa_id if relay else None,
    )

    agent = owner_agent if staff.role.value == "owner" else sdr_agent

    # Build conversation history (owner's thread, last 20 messages)
    # Owner doesn't have a "conversation" in the customer sense — use a
    # simple list with just the current message for now. Multi-turn owner
    # context comes from the agent's tool results (get_active_leads, etc.)
    input_messages = [{"role": "user", "content": message}]

    try:
        result = await Runner.run(
            starting_agent=agent,
            input=input_messages,
            context=ctx,
        )
        return result.final_output or "I couldn't process that. Try again."
    except Exception as e:
        log.error(f"Owner agent error for {wa_id}: {e}", exc_info=True)
        return "Sorry, something went wrong. Try again."
