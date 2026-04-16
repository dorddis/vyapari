"""Escalation detection tests — 6 scenarios."""

import pytest

from services.escalation import detect_escalation


@pytest.mark.asyncio
async def test_test_drive_triggers():
    triggered, reason = detect_escalation("Kal test drive le sakta hu?", "Sure!")
    assert triggered is True
    assert "test drive" in reason.lower()


@pytest.mark.asyncio
async def test_best_price_triggers():
    triggered, reason = detect_escalation("Best price kya hai?", "Listed at 7.5L.")
    assert triggered is True
    assert "best price" in reason.lower()


@pytest.mark.asyncio
async def test_baat_karo_triggers():
    triggered, reason = detect_escalation("Kisi se baat karo", "Of course!")
    assert triggered is True
    assert "baat karo" in reason.lower()


@pytest.mark.asyncio
async def test_bot_offering_connect_triggers():
    triggered, reason = detect_escalation(
        "I need more details",
        "Let me connect you with our team for more information."
    )
    assert triggered is True
    assert "connect" in reason.lower()


@pytest.mark.asyncio
async def test_normal_message_no_trigger():
    triggered, reason = detect_escalation(
        "Good morning, what cars do you have?",
        "We have 20 cars! Here are the top picks."
    )
    assert triggered is False
    assert reason == ""


@pytest.mark.asyncio
async def test_combined_customer_and_bot_triggers():
    triggered, reason = detect_escalation(
        "Can I book this car?",
        "I'll connect you with our team to arrange the booking."
    )
    assert triggered is True
