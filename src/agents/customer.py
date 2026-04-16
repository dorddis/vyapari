"""Customer Agent — OpenAI Agents SDK.

Per-customer sessions. Each customer gets their own conversation history
via session_id = f"customer_{wa_id}". The agent has 9 tools for browsing
inventory, comparing cars, getting pricing, and escalating.

Research findings applied:
- reasoning.effort = "low" (GPT-5.4 tool calling fix)
- Explicit "just execute the tool" in system prompt
- await Runner.run() (never run_sync in FastAPI)
- Max tool calls capped via model_settings
"""

import json
import logging

from agents import Agent, Runner, function_tool, RunContextWrapper, ModelSettings
from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX

import config
import state
from agents.context import CustomerContext
from agents.prompts import build_customer_system_prompt
from agents.tools.catalogue import (
    tool_check_availability,
    tool_compare_items,
    tool_get_item_details,
    tool_get_pricing_info,
    tool_search_catalogue,
)
from agents.tools.business import tool_get_business_info, tool_get_faq_answer
from services.escalation import detect_escalation

log = logging.getLogger("vyapari.agents.customer")


# ---------------------------------------------------------------------------
# Tool wrappers (adapt plain functions to @function_tool with context)
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
    """Search the car catalogue with optional filters. Returns up to 5 matching cars."""
    return tool_search_catalogue(max_price, min_price, fuel_type, make, transmission, max_km)


@function_tool
def get_item_details(item_id: int) -> str:
    """Get full details for a specific car by its ID number."""
    return tool_get_item_details(item_id)


@function_tool
def compare_items(item_id_1: int, item_id_2: int) -> str:
    """Compare two cars side by side by their ID numbers."""
    return tool_compare_items(item_id_1, item_id_2)


@function_tool
def get_faq_answer(topic: str) -> str:
    """Find FAQ answers about a topic (financing, warranty, documents, test drive, etc)."""
    return tool_get_faq_answer(topic)


@function_tool
def get_pricing_info(item_id: int, down_payment_pct: float = 20) -> str:
    """Get EMI estimates and additional costs for a car."""
    return tool_get_pricing_info(item_id, down_payment_pct)


@function_tool
def check_availability(item_id: int) -> str:
    """Check if a specific car is available, sold, or reserved."""
    return tool_check_availability(item_id)


@function_tool
def get_business_info() -> str:
    """Get dealership address, hours, contact info, and landmark."""
    return tool_get_business_info()


@function_tool
async def request_escalation(
    ctx: RunContextWrapper[CustomerContext],
    reason: str,
    summary: str = "",
) -> str:
    """Escalate this conversation to a human staff member. Use when the customer
    wants to negotiate price, book a test drive, talk to someone, or is frustrated."""
    from agents.tools.communication import tool_request_escalation

    result = await tool_request_escalation(ctx.context.customer_id, reason, summary)
    ctx.context.conversation_state = "escalated"
    return result


@function_tool
async def request_callback(
    ctx: RunContextWrapper[CustomerContext],
    phone_number: str,
) -> str:
    """Save a callback request when the customer wants a phone call."""
    from agents.tools.communication import tool_request_callback

    return await tool_request_callback(ctx.context.customer_id, phone_number)


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

def _build_instructions(ctx: RunContextWrapper[CustomerContext], agent: Agent) -> str:
    """Dynamic instructions — built per-request with customer context."""
    return build_customer_system_prompt(
        customer_name=ctx.context.name,
        lead_status=ctx.context.lead_status,
    )


customer_agent = Agent[CustomerContext](
    name="Sharma Motors Sales Agent",
    instructions=_build_instructions,
    tools=[
        search_catalogue,
        get_item_details,
        compare_items,
        get_faq_answer,
        get_pricing_info,
        check_availability,
        get_business_info,
        request_escalation,
        request_callback,
    ],
    model=config.OPENAI_MAIN_MODEL,
    model_settings=ModelSettings(
        reasoning={"effort": "low"},  # GPT-5.4 tool calling fix
    ),
)


# ---------------------------------------------------------------------------
# Run the agent (called from router.handle_customer_agent)
# ---------------------------------------------------------------------------

async def run_customer_agent(wa_id: str, message: str) -> str:
    """Run the Customer Agent for a single message turn.

    Manages session loading, context creation, and post-run escalation detection.
    Returns the agent's reply text.
    """
    # Load customer + conversation state
    customer = await state.get_or_create_customer(wa_id)
    conversation = await state.get_or_create_conversation(wa_id)

    # Build context
    ctx = CustomerContext(
        customer_id=wa_id,
        name=customer.name,
        phone=wa_id,
        lead_status=customer.lead_status.value,
        interested_cars=customer.interested_cars,
        conversation_state=conversation.state.value,
        conversation_id=conversation.id,
        source=customer.source,
    )

    # Store customer message
    from models import MessageRole
    await state.add_message(conversation.id, MessageRole.CUSTOMER, message)

    # Run the agent
    try:
        result = await Runner.run(
            starting_agent=customer_agent,
            input=message,
            context=ctx,
        )
        reply = result.final_output or "I'm sorry, I couldn't process that. Please try again."
    except Exception as e:
        log.error(f"Customer agent error for {wa_id}: {e}", exc_info=True)
        reply = "Sorry, I'm having trouble right now. Please try again in a moment!"

    # Store agent reply
    await state.add_message(conversation.id, MessageRole.AGENT, reply)

    # Post-run escalation detection
    should_escalate, reason = detect_escalation(message, reply)
    if should_escalate and conversation.state.value != "escalated":
        from models import ConversationState
        await state.set_conversation_state(wa_id, ConversationState.ESCALATED, reason)
        log.info(f"Escalation detected for {wa_id}: {reason}")

    # Update interested cars from context (tools may have mutated it)
    if ctx.interested_cars != customer.interested_cars:
        customer.interested_cars = ctx.interested_cars

    return reply
