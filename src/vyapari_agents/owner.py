"""Owner + SDR Agents — OpenAI Agents SDK.

Owner gets 19 tools (full access). SDR gets 7 (read-only + relay).
Per-staff sessions via session_id = f"staff_{wa_id}".
"""

import logging

from agents import Agent, Runner, function_tool, RunContextWrapper, ModelSettings

import config
import state
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
async def mark_sold(item_id: int) -> str:
    """Mark a car as sold and notify interested customers."""
    return await tool_mark_sold(item_id)


@function_tool
def mark_reserved(item_id: int, customer_name: str, token_amount: float | None = None) -> str:
    """Reserve a car for a customer (token payment received)."""
    return tool_mark_reserved(item_id, customer_name, token_amount)


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
async def remove_staff(identifier: str) -> str:
    """Remove a staff member by phone number or name."""
    from vyapari_agents.tools.staff import tool_remove_staff
    return await tool_remove_staff(identifier)


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
async def parse_inventory_image(image_url: str) -> str:
    """Parse a car inventory image or PDF. Extracts car data and adds to catalogue.
    Use when the owner sends a photo, PDF, or screenshot of their stock list."""
    from vyapari_agents.tools.vision import tool_parse_inventory
    return await tool_parse_inventory(image_url)


@function_tool
async def parse_token_proof(image_url: str, car_name: str | None = None) -> str:
    """Parse a UPI/payment screenshot. Extracts amount, sender, status.
    Use when the owner forwards a token payment proof."""
    from vyapari_agents.tools.vision import tool_parse_token_screenshot
    return await tool_parse_token_screenshot(image_url, car_name)


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
        parse_inventory_image, parse_token_proof,
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

async def run_owner_agent(
    wa_id: str,
    message: str,
    image_url: str | None = None,
    *,
    business_id: str,
) -> str:
    """Run the Owner Agent for a single message turn.

    `business_id` is required — see StaffContext for the reasoning.
    """
    from models import MessageRole

    staff = await state.get_staff(wa_id)
    if not staff:
        return "Staff not found."

    relay = await state.get_active_relay_for_staff(wa_id)

    ctx = StaffContext(
        staff_id=wa_id,
        business_id=business_id,
        name=staff.name,
        role=staff.role.value,
        has_active_relay=relay is not None,
        active_relay_customer=relay.customer_wa_id if relay else None,
    )

    agent = owner_agent if staff.role.value == "owner" else sdr_agent

    # Build input — with image if provided (for PDF upload, token screenshots)
    if image_url:
        input_messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": message or "What is this?"},
                {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
            ],
        }]
    else:
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
