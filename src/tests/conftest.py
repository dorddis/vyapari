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

# Force SQLite for tests BEFORE any other imports touch the DB
import config
import database
config.DATABASE_URL = "sqlite+aiosqlite://"  # in-memory SQLite
database._engine = None
database._async_session = None

from catalogue import reset_runtime_data
import state
from models import (
    ConversationState,
    IncomingMessage,
    LeadStatus,
    MessageType,
    StaffRole,
    StaffStatus,
)


# ---------------------------------------------------------------------------
# DB setup (once per session)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True, scope="session")
async def _init_test_db():
    """Create all tables in in-memory SQLite once for the test session."""
    await database.init_db()
    yield
    await database.close_db()


# ---------------------------------------------------------------------------
# Auto-reset state before each test
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(autouse=True)
async def clean_state():
    """Reset all DB state before each test.

    Does NOT seed the default owner — tests that need one call seed_owner()
    explicitly (avoids conflict with tests using 919876543210 as customer).
    """
    await state.reset_state()
    # Only seed the business row (needed for FK constraints), not the owner
    async with database.get_session_factory()() as s:
        import db_models as M
        biz = await s.get(M.Business, config.DEFAULT_BUSINESS_ID)
        if not biz:
            s.add(M.Business(
                id=config.DEFAULT_BUSINESS_ID,
                name=config.DEFAULT_BUSINESS_NAME,
                type="dealership",
                vertical=config.DEFAULT_BUSINESS_VERTICAL,
                owner_phone=config.DEFAULT_OWNER_PHONE,
            ))
            await s.commit()
    reset_runtime_data()
    yield
    await state.reset_state()
    reset_runtime_data()


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
    await state.get_or_create_customer(wa_id, name)
    await state.update_lead_status(wa_id, lead_status)
    await state.get_or_create_conversation(wa_id)


async def seed_relay(
    staff_wa_id: str = "919999888777",
    customer_wa_id: str = "919876543210",
) -> None:
    """Seed an active relay session between staff and customer."""
    await seed_customer(customer_wa_id)
    await state.create_relay_session(staff_wa_id, customer_wa_id)
