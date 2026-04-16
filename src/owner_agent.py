"""Deprecated compatibility shim.

This project is OpenAI-only. Legacy Gemini owner helpers have been removed.
"""


def owner_query(query: str) -> dict:
    """Return a deterministic message for stale import paths."""
    return {
        "text": "OpenAI is not configured yet. Set OPENAI_API_KEY to enable owner replies.",
        "action": None,
    }
