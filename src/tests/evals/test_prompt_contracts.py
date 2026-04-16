"""Deterministic prompt and tool-contract checks.

These tests protect the behavioral contract we want before we tune the
prompts further with live GPT-5 evals.
"""

from __future__ import annotations

from vyapari_agents.prompts import (
    build_customer_system_prompt,
    build_owner_system_prompt,
    build_sdr_system_prompt,
)
from vyapari_agents.tools.catalogue import tool_mark_reserved, tool_mark_sold
from vyapari_agents.tools.communication import (
    tool_broadcast_message,
    tool_request_callback,
    tool_request_escalation,
)
from vyapari_agents.tools.leads import tool_assign_lead, tool_batch_followup
from vyapari_agents.tools.relay import tool_open_session
from vyapari_agents.tools.staff import tool_remove_staff


def test_customer_prompt_contains_tool_and_clarification_policy() -> None:
    prompt = build_customer_system_prompt("Ramesh", "warm")

    assert "## Tool Use Policy" in prompt
    assert "## Clarification Policy" in prompt
    assert "## Conversation Flow" in prompt
    assert "## Confirmation Rules" in prompt
    assert "run the search instead of asking a question" in prompt
    assert "After request_callback or request_escalation succeeds" in prompt


def test_owner_prompt_contains_copilot_and_confirmation_policy() -> None:
    prompt = build_owner_system_prompt("Rajesh", "owner")

    assert "## Tool Use Policy" in prompt
    assert "## Confirmation Rules" in prompt
    assert "## Relay Rules" in prompt
    assert "proactive business copilot" in prompt.lower()
    assert "Do not mark sold, reserve a car, remove staff, send a broadcast, or run batch follow-ups without explicit confirmation" in prompt
    assert "For assign_lead and update actions, confirm only when the target is ambiguous" in prompt


def test_sdr_prompt_keeps_role_boundaries() -> None:
    prompt = build_sdr_system_prompt("Raj")

    assert "You cannot modify the catalogue, settings, or FAQs" in prompt
    assert "Open relay sessions" in prompt
    assert "Keep responses SHORT and actionable" in prompt


def test_terminal_and_hard_confirm_tools_have_operational_docstrings() -> None:
    docstrings = {
        "tool_request_escalation": tool_request_escalation.__doc__ or "",
        "tool_request_callback": tool_request_callback.__doc__ or "",
        "tool_broadcast_message": tool_broadcast_message.__doc__ or "",
        "tool_mark_sold": tool_mark_sold.__doc__ or "",
        "tool_mark_reserved": tool_mark_reserved.__doc__ or "",
        "tool_assign_lead": tool_assign_lead.__doc__ or "",
        "tool_batch_followup": tool_batch_followup.__doc__ or "",
        "tool_open_session": tool_open_session.__doc__ or "",
        "tool_remove_staff": tool_remove_staff.__doc__ or "",
    }

    for name, doc in docstrings.items():
        assert "Use this tool when" in doc, name
        assert "Do not use this tool when" in doc, name
        assert "Before calling" in doc, name
        assert "After calling" in doc, name
        assert "terminal for the current action flow" in doc, name
