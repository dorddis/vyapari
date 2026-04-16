"""Shared test fixtures for the Vyapari Agent test suite."""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

# Add src to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

import state
from channels.base import reset_channel
from channels.web_clone.adapter import reset_outbox
from models import (
    ConversationState,
    IncomingMessage,
    LeadStatus,
    MessageType,
    StaffRole,
    StaffStatus,
)


# ---------------------------------------------------------------------------
# Auto-reset state before each test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def clean_state():
    """Reset all in-memory state before each test."""
    await state.reset_state()
    reset_channel()
    reset_outbox()
    yield
    await state.reset_state()
    reset_channel()
    reset_outbox()


# ---------------------------------------------------------------------------
# Message factories
# ---------------------------------------------------------------------------

def make_customer_msg(
    wa_id: str = "919876543210",
    text: str = "Hello",
    msg_id: str | None = None,
    sender_name: str = "Test Customer",
) -> IncomingMessage:
    """Create a customer IncomingMessage for testing."""
    return IncomingMessage(
        wa_id=wa_id,
        text=text,
        msg_id=msg_id or f"wamid.test_{uuid4().hex[:8]}",
        msg_type=MessageType.TEXT,
        sender_name=sender_name,
        timestamp=datetime.now(timezone.utc),
    )


def make_staff_msg(
    wa_id: str = "919999888777",
    text: str = "Hello",
    msg_id: str | None = None,
    sender_name: str = "Rajesh",
) -> IncomingMessage:
    """Create a staff (owner/SDR) IncomingMessage for testing."""
    return IncomingMessage(
        wa_id=wa_id,
        text=text,
        msg_id=msg_id or f"wamid.test_{uuid4().hex[:8]}",
        msg_type=MessageType.TEXT,
        sender_name=sender_name,
        timestamp=datetime.now(timezone.utc),
    )


def make_button_reply_msg(
    wa_id: str = "919876543210",
    button_id: str = "btn_test_drive",
    button_title: str = "Book Test Drive",
) -> IncomingMessage:
    """Create a button reply IncomingMessage for testing."""
    return IncomingMessage(
        wa_id=wa_id,
        text=None,
        msg_id=f"wamid.test_{uuid4().hex[:8]}",
        msg_type=MessageType.BUTTON_REPLY,
        button_reply_id=button_id,
        button_reply_title=button_title,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# State seeding helpers
# ---------------------------------------------------------------------------

async def seed_owner(
    wa_id: str = "919999888777", name: str = "Rajesh"
) -> None:
    """Seed the owner into state."""
    await state.add_staff(
        wa_id=wa_id,
        name=name,
        role=StaffRole.OWNER,
        status=StaffStatus.ACTIVE,
    )


async def seed_sdr(
    wa_id: str = "919111222333", name: str = "Raj"
) -> None:
    """Seed an SDR into state."""
    await state.add_staff(
        wa_id=wa_id,
        name=name,
        role=StaffRole.SDR,
        status=StaffStatus.ACTIVE,
    )


async def seed_customer(
    wa_id: str = "919876543210",
    name: str = "Ramesh Patil",
    lead_status: LeadStatus = LeadStatus.WARM,
) -> None:
    """Seed a customer with a conversation."""
    customer = await state.get_or_create_customer(wa_id, name)
    customer.lead_status = lead_status
    await state.get_or_create_conversation(wa_id)


async def seed_relay(
    staff_wa_id: str = "919999888777",
    customer_wa_id: str = "919876543210",
) -> None:
    """Seed an active relay session between staff and customer."""
    await seed_customer(customer_wa_id)
    await state.create_relay_session(staff_wa_id, customer_wa_id)
