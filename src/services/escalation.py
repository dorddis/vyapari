"""Escalation detection — regex first pass + GPT-5.4-mini fallback.

Extracted from the prototype's conversation.py (lines 53-97) and extended
with an LLM classifier for ambiguous cases.
"""

import re

import config
import state
from models import ConversationState

# ---------------------------------------------------------------------------
# Regex patterns (from prototype, proven in testing)
# ---------------------------------------------------------------------------

CUSTOMER_ESCALATION_TRIGGERS = [
    r"test drive", r"visit", r"showroom", r"best price", r"final price",
    r"last price", r"kitna kam", r"token", r"book", r"call me",
    r"baat karo", r"talk to someone", r"talk to a person", r"human",
    r"manager", r"negotiate", r"discount", r"kab aa sakta",
    r"dekhne aa", r"Sunday", r"Saturday",
]

BOT_ESCALATION_MARKERS = [
    r"connect you with", r"connect you to", r"let me connect",
    r"our team will", r"team member", r"someone from our team",
    r"will get back", r"arrange.*callback", r"have them call",
]

# Negative sentiment signals that trigger the LLM fallback
_SENTIMENT_SIGNALS = [
    r"[A-Z]{3,}",       # ALL CAPS (3+ chars)
    r"[!?]{2,}",         # multiple ! or ?
    r"waste", r"bakwas", r"bekar", r"fraud", r"scam",
    r"not happy", r"disappointed", r"angry", r"frustrated",
    r"kuch nahi", r"time waste", r"reply nahi",
]


async def _resolve_owner_staff_wa_id() -> str:
    """Find the active owner staff record, falling back to config if needed."""
    staff_members = await state.list_staff()
    for staff_member in staff_members:
        if staff_member.role.value == "owner" and staff_member.status.value == "active":
            return staff_member.wa_id
    return config.DEFAULT_OWNER_PHONE


def detect_escalation(customer_msg: str, bot_reply: str) -> tuple[bool, str]:
    """Check if this exchange should trigger escalation.

    Returns (should_escalate, reason_string).
    First pass: regex matching (fast, deterministic).
    Second pass: LLM classifier if regex misses but sentiment signals present.
    """
    customer_lower = customer_msg.lower()
    bot_lower = bot_reply.lower()

    # Pass 1: regex on customer message
    for pattern in CUSTOMER_ESCALATION_TRIGGERS:
        if re.search(pattern, customer_lower):
            return True, f"Customer trigger: {pattern}"

    # Pass 2: regex on bot reply (bot already offering handoff)
    for pattern in BOT_ESCALATION_MARKERS:
        if re.search(pattern, bot_lower):
            return True, "Agent offering to connect with team"

    # Pass 3: check for negative sentiment signals -> LLM fallback
    has_sentiment = any(
        re.search(p, customer_msg) for p in _SENTIMENT_SIGNALS
    )
    if has_sentiment and config.USE_OPENAI:
        return _classify_escalation_llm(customer_msg, bot_reply)

    return False, ""


async def trigger_escalation(
    customer_wa_id: str,
    reason: str,
    summary: str = "",
) -> tuple[bool, str, str | None]:
    """Persist an escalation and queue a staff notification."""
    conversation = await state.get_conversation(customer_wa_id)
    customer = await state.get_customer(customer_wa_id)

    if not conversation or not customer:
        return False, "No conversation found.", None

    await state.set_conversation_state(
        customer_wa_id,
        ConversationState.ESCALATED,
        reason,
    )
    escalation = await state.add_escalation(
        conversation.id,
        trigger=reason,
        summary=summary,
    )

    target_staff_wa_id = conversation.assigned_to or await _resolve_owner_staff_wa_id()
    target_staff = await state.get_staff(target_staff_wa_id)
    if not target_staff or target_staff.status.value != "active":
        target_staff_wa_id = await _resolve_owner_staff_wa_id()

    await state.queue_staff_escalation_notification(
        staff_wa_id=target_staff_wa_id,
        escalation_id=escalation.id,
        conversation_id=conversation.id,
        customer_wa_id=customer.wa_id,
        customer_name=customer.name,
        lead_status=customer.lead_status.value,
        trigger=reason,
        summary=summary or reason,
    )

    return True, f"Escalated {customer.name}. Staff notification queued.", target_staff_wa_id


def _classify_escalation_llm(
    customer_msg: str, bot_reply: str
) -> tuple[bool, str]:
    """GPT-5.4-mini fallback for ambiguous escalation signals.

    Only called when regex doesn't match but sentiment signals are present.
    Synchronous (blocking) because it's a quick classification call.
    """
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=config.OPENAI_CLASSIFIER_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an escalation classifier for a used car sales chatbot. "
                        "Decide if the customer message indicates frustration, buying intent, "
                        "or need for human intervention. Respond with ONLY 'yes' or 'no'."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Customer: {customer_msg}\n"
                        f"Bot reply: {bot_reply}\n\n"
                        "Should this be escalated to a human? (yes/no)"
                    ),
                },
            ],
            max_tokens=5,
            temperature=0,
        )
        answer = response.choices[0].message.content.strip().lower()
        if answer.startswith("yes"):
            return True, "LLM classifier detected escalation signal"
    except Exception:
        pass  # fail open — don't escalate if classifier errors

    return False, ""


def extract_car_images(
    bot_reply: str, catalogue_cars: list[dict]
) -> list[str]:
    """Find car references in bot text and return their image URLs.

    Extracted from prototype conversation.py lines 84-97.
    """
    images = []
    reply_lower = bot_reply.lower()
    for car in catalogue_cars:
        if car.get("sold"):
            continue
        model_lower = car["model"].lower()
        if model_lower in reply_lower:
            url = car.get("image_url", "")
            if url and url not in images:
                images.append(url)
    return images[:3]
