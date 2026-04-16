"""Escalation detection — regex first pass + GPT-4.1 nano fallback.

Extracted from the prototype's conversation.py (lines 53-97) and extended
with an LLM classifier for ambiguous cases.
"""

import logging
import re

import config

log = logging.getLogger("vyapari.services.escalation")

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

# Known uppercase acronyms in car sales context (not frustration signals)
_KNOWN_ACRONYMS = {"SUV", "EMI", "SBI", "RTO", "CNG", "LED", "ABS", "EBD", "ESP", "USB", "GPS", "PDF", "OBV", "IDV", "NCB"}

# Negative sentiment signals that trigger the LLM fallback
_SENTIMENT_SIGNALS = [
    r"[!?]{2,}",         # multiple ! or ?
    r"waste", r"bakwas", r"bekar", r"fraud", r"scam",
    r"not happy", r"disappointed", r"angry", r"frustrated",
    r"kuch nahi", r"time waste", r"reply nahi",
]


def _has_real_caps_anger(text: str) -> bool:
    """Check for ALL CAPS words that aren't known acronyms (5+ chars)."""
    words = re.findall(r"\b[A-Z]{5,}\b", text)
    return any(w not in _KNOWN_ACRONYMS for w in words)


async def detect_escalation(customer_msg: str, bot_reply: str) -> tuple[bool, str]:
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
    ) or _has_real_caps_anger(customer_msg)

    if has_sentiment and config.USE_OPENAI:
        return await _classify_escalation_llm(customer_msg, bot_reply)

    return False, ""


async def _classify_escalation_llm(
    customer_msg: str, bot_reply: str
) -> tuple[bool, str]:
    """GPT-4.1 nano fallback for ambiguous escalation signals.

    Only called when regex doesn't match but sentiment signals are present.
    Uses AsyncOpenAI to avoid blocking the event loop.
    """
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
        response = await client.chat.completions.create(
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
    except Exception as e:
        log.warning(f"Escalation classifier error: {e}")

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
