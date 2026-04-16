"""Owner data oracle - separate Gemini engine for business queries."""

import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL
from catalogue import get_business_context, get_catalogue_summary, BUSINESS, CATALOGUE
from message_store import list_conversations

genai.configure(api_key=GEMINI_API_KEY)

_oracle_history: list[dict] = []
MAX_HISTORY = 20


def _get_conversations_summary() -> str:
    convos = list_conversations()
    if not convos:
        return "No active conversations yet."
    lines = []
    for c in convos:
        line = (
            f"- {c['customer_name']} ({c['customer_id'][:8]}...): "
            f"{c['message_count']} msgs, mode={c['mode']}, "
            f'last: "{c["last_message"]}"'
        )
        lines.append(line)
    return "\n".join(lines)


def _build_system_prompt() -> str:
    biz = BUSINESS["business_name"]
    biz_ctx = get_business_context()
    cat_sum = get_catalogue_summary()
    convo_sum = _get_conversations_summary()

    return (
        f"You are the AI assistant for {biz}'s owner, Rajesh Sharma.\n"
        "You help manage the business through natural conversation.\n\n"
        "## Your Role\n"
        "- Answer questions about inventory, leads, conversations, and business operations\n"
        "- Execute catalogue management commands (mark sold, update price)\n"
        "- Provide business insights and suggestions\n"
        "- Use Hinglish naturally, you're talking to the boss\n\n"
        "## Rules\n"
        "- Keep responses SHORT and actionable\n"
        "- For catalogue commands, confirm clearly what you're doing\n"
        "- When asked about leads/conversations, reference the data below\n"
        "- Be proactive: suggest improvements, flag issues\n\n"
        f"## Business Info\n{biz_ctx}\n\n"
        f"## Current Inventory\n{cat_sum}\n\n"
        f"## Active Conversations\n{convo_sum}"
    )


def owner_query(query: str) -> dict:
    """Process an owner query. Returns {"text": str, "action": dict | None}."""
    global _oracle_history

    _oracle_history.append({"role": "user", "parts": [query]})

    if len(_oracle_history) > MAX_HISTORY:
        _oracle_history = _oracle_history[-MAX_HISTORY:]

    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=_build_system_prompt(),
    )
    chat = model.start_chat(history=_oracle_history[:-1])
    response = chat.send_message(query)
    reply = response.text.strip()

    _oracle_history.append({"role": "model", "parts": [reply]})

    action = _detect_catalogue_action(query)
    return {"text": reply, "action": action}


def _detect_catalogue_action(query: str) -> dict | None:
    """Detect if the owner query is a catalogue management command."""
    q = query.lower()

    sold_words = ["sold", "bik gaya", "bik gayi", "bech diya", "sell ho gaya"]
    if any(w in q for w in sold_words):
        for car in CATALOGUE["cars"]:
            if car.get("sold"):
                continue
            if car["model"].lower() in q:
                return {
                    "action": "mark_sold",
                    "car_id": car["id"],
                    "car_name": f"{car['year']} {car['make']} {car['model']}",
                }
    return None
