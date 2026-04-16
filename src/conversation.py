"""Gemini-powered conversation engine for the sales agent."""

import re
import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL
from catalogue import (
    get_business_context,
    get_catalogue_summary,
    get_faq_text,
    BUSINESS,
    CATALOGUE,
)

genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = f"""You are the AI sales assistant for {BUSINESS['business_name']}, a used car dealership in Mumbai.

## Your personality
{BUSINESS['personality']['tone']}
Language: {BUSINESS['personality']['language_preference']}
Sales approach: {BUSINESS['personality']['sales_approach']}

## Rules
- ONLY answer based on the catalogue and FAQ data below. NEVER make up cars, prices, or specs.
- If a car isn't in the catalogue, say so honestly.
- Use Hinglish naturally. Match the customer's language.
- Keep responses SHORT (2-4 sentences max). This is WhatsApp, not email.
- Use WhatsApp formatting: *bold* for car names/prices, _italic_ for emphasis.
- When showing cars, format as a compact list (not a wall of text).
- When recommending cars, ALWAYS mention the car name (make + model) clearly.
- For pricing questions, always quote the listed price. Say "negotiation is possible, let me connect you with our team" for discount asks.
- If the customer seems ready to buy, visit, or negotiate price, say you'll connect them with the team.
- NEVER contradict the catalogue data.
- If you don't know something, say "Let me check with our team and get back to you."
- Don't reveal you're AI unless directly asked. Act like one of the dealer's salespeople.

## Business Info
{get_business_context()}

## Current Inventory ({BUSINESS['inventory_stats']['typical_stock']})
{get_catalogue_summary()}

## FAQs
{get_faq_text()}
"""

# Per-customer conversation history (in-memory for MVP)
_conversations: dict[str, list[dict]] = {}

MAX_HISTORY = 20

# Escalation detection phrases
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


def _detect_escalation(customer_msg: str, bot_reply: str) -> tuple[bool, str]:
    """Check if this exchange should trigger escalation."""
    customer_lower = customer_msg.lower()
    bot_lower = bot_reply.lower()

    for pattern in CUSTOMER_ESCALATION_TRIGGERS:
        if re.search(pattern, customer_lower):
            return True, f"Customer interested: {pattern}"

    for pattern in BOT_ESCALATION_MARKERS:
        if re.search(pattern, bot_lower):
            return True, "Bot offering to connect with team"

    return False, ""


def _extract_car_images(bot_reply: str) -> list[str]:
    """Find car references in bot text and return their image URLs."""
    images = []
    reply_lower = bot_reply.lower()
    for car in CATALOGUE["cars"]:
        if car.get("sold"):
            continue
        model_lower = car["model"].lower()
        # Match model name (e.g., "Creta", "Nexon", "Alto K10")
        if model_lower in reply_lower:
            url = car.get("image_url", "")
            if url and url not in images:
                images.append(url)
    return images[:3]  # Cap at 3


def get_reply(customer_id: str, message: str) -> str:
    """Process a customer message and return the bot's reply (text only)."""
    result = get_reply_rich(customer_id, message)
    return result["text"]


def get_reply_rich(customer_id: str, message: str) -> dict:
    """Process a customer message and return enriched reply.

    Returns: {"text": str, "images": [str], "is_escalation": bool, "escalation_reason": str}
    """
    if not GEMINI_API_KEY:
        return {
            "text": (
                "Message received. Agent replies are not configured yet. "
                "Set OPENAI_API_KEY or GEMINI_API_KEY to enable live responses."
            ),
            "images": [],
            "is_escalation": False,
            "escalation_reason": "",
        }

    if customer_id not in _conversations:
        _conversations[customer_id] = []

    history = _conversations[customer_id]
    history.append({"role": "user", "parts": [message]})

    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
        _conversations[customer_id] = history

    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
    )
    chat = model.start_chat(history=history[:-1])

    response = chat.send_message(message)
    reply = response.text.strip()

    history.append({"role": "model", "parts": [reply]})

    images = _extract_car_images(reply)
    is_escalation, reason = _detect_escalation(message, reply)

    return {
        "text": reply,
        "images": images,
        "is_escalation": is_escalation,
        "escalation_reason": reason,
    }


def inject_owner_message(customer_id: str, message: str) -> None:
    """Inject an owner message into Gemini history as a model turn.

    This preserves context when bot resumes after owner hijack.
    """
    if customer_id not in _conversations:
        _conversations[customer_id] = []
    _conversations[customer_id].append({"role": "model", "parts": [message]})
