"""Broadcast + batch_followup tools raise instead of lying."""

from __future__ import annotations

import pytest

from vyapari_agents.tools.communication import tool_broadcast_message
from vyapari_agents.tools.leads import tool_batch_followup


@pytest.mark.asyncio
async def test_broadcast_message_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await tool_broadcast_message("anything")


@pytest.mark.asyncio
async def test_batch_followup_raises_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await tool_batch_followup()


def test_owner_agent_does_not_expose_unwired_tools() -> None:
    """Owner tool list omits the two unimplemented tools."""
    from vyapari_agents.owner import owner_agent
    tool_names = {t.name for t in owner_agent.tools}
    assert "broadcast_message" not in tool_names
    assert "batch_followup" not in tool_names
