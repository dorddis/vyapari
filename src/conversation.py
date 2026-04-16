"""Deprecated compatibility shim.

This project is OpenAI-only. Legacy Gemini conversation helpers have been removed.
"""


def get_reply(customer_id: str, message: str) -> str:
    """Return a deterministic message for stale import paths."""
    return "OpenAI is not configured yet. Set OPENAI_API_KEY to enable agent replies."


def get_reply_rich(customer_id: str, message: str) -> dict:
    """Return a rich response shape for stale import paths."""
    return {
        "text": get_reply(customer_id, message),
        "images": [],
        "is_escalation": False,
        "escalation_reason": "",
    }


def inject_owner_message(customer_id: str, message: str) -> None:
    """No-op compatibility hook retained for legacy callers."""
    return None
