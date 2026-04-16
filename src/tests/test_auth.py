"""OTP authentication tests -- 8 scenarios."""

import pytest
import pytest_asyncio

import state
from models import StaffRole, StaffStatus
from services.auth import create_invite, handle_login_message, reset_auth_state, verify_login


@pytest_asyncio.fixture(autouse=True)
async def _clean_auth():
    await reset_auth_state()
    yield
    await reset_auth_state()


@pytest.mark.asyncio
async def test_generate_otp_returns_6_digits():
    otp = await create_invite("919111000001", "Test SDR", StaffRole.SDR)
    assert len(otp) == 6
    assert otp.isdigit()


@pytest.mark.asyncio
async def test_create_invite_stores_staff_as_invited():
    await create_invite("919111000002", "Raj", StaffRole.SDR, added_by="919999888777")
    staff = await state.get_staff_raw("919111000002")
    assert staff is not None
    assert staff.status == StaffStatus.INVITED
    assert staff.name == "Raj"
    assert staff.role == StaffRole.SDR
    assert staff.otp_hash is not None


@pytest.mark.asyncio
async def test_correct_otp_activates_staff():
    otp = await create_invite("919111000003", "Raj", StaffRole.SDR)
    success, msg = await verify_login("919111000003", otp)
    assert success is True
    assert "Verified" in msg
    staff = await state.get_staff("919111000003")
    assert staff.status == StaffStatus.ACTIVE
    assert staff.otp_hash is None


@pytest.mark.asyncio
async def test_wrong_otp_increments_attempts():
    await create_invite("919111000004", "Raj", StaffRole.SDR)
    success, msg = await verify_login("919111000004", "000000")
    assert success is False
    assert "remaining" in msg.lower()


@pytest.mark.asyncio
async def test_three_wrong_attempts_locks_out():
    await create_invite("919111000005", "Raj", StaffRole.SDR)
    await verify_login("919111000005", "000001")
    await verify_login("919111000005", "000002")
    success, msg = await verify_login("919111000005", "000003")
    assert success is False
    assert "too many" in msg.lower() or "re-add" in msg.lower()


@pytest.mark.asyncio
async def test_no_invite_returns_error():
    success, msg = await verify_login("919111000006", "123456")
    assert success is False
    assert "no pending invite" in msg.lower() or "no invite" in msg.lower()


@pytest.mark.asyncio
async def test_login_flow_full_conversation():
    """Test the multi-message /login flow end-to-end."""
    otp = await create_invite("919111000007", "Raj", StaffRole.SDR)

    # Step 1: /login
    reply = await handle_login_message("919111000007", "/login")
    assert "otp" in reply.lower()

    # Step 2: enter OTP
    reply = await handle_login_message("919111000007", otp)
    assert "verified" in reply.lower() or "welcome" in reply.lower()

    # Staff is now active
    staff = await state.get_staff("919111000007")
    assert staff.status == StaffStatus.ACTIVE


@pytest.mark.asyncio
async def test_already_active_staff_told_so():
    """Active staff trying /login again should be told they're already in."""
    await state.add_staff(
        wa_id="919111000008",
        name="Already Active",
        role=StaffRole.SDR,
        status=StaffStatus.ACTIVE,
    )
    reply = await handle_login_message("919111000008", "/login")
    assert "already logged in" in reply.lower()
