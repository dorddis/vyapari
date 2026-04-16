"""OTP authentication for staff onboarding.

Flow:
1. Owner tells agent: "Add Raj as SDR, 9876543210"
2. Agent calls add_staff tool -> generate_otp() -> returns OTP to owner
3. Owner shares OTP with Raj out-of-band
4. Raj messages the bot: /login
5. Bot: "Enter your 6-digit OTP"
6. Raj: 482910
7. Bot verifies -> maps wa_id to SDR role permanently

Uses pyotp (TOTP with 5-min window) + bcrypt for hash storage.
3-attempt lockout. Rate-limited to 1 OTP request per 60s per number.
"""

import time
from datetime import datetime, timedelta, timezone

import bcrypt
import pyotp

import state
from models import StaffRole, StaffStatus


# ---------------------------------------------------------------------------
# OTP generation
# ---------------------------------------------------------------------------

OTP_WINDOW_SECONDS = 300  # 5 minutes
MAX_ATTEMPTS = 3


def generate_otp() -> tuple[str, str]:
    """Generate a 6-digit OTP and its bcrypt hash.

    Returns (plaintext_otp, bcrypt_hash).
    """
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret, interval=OTP_WINDOW_SECONDS, digits=6)
    plaintext = totp.now()
    hashed = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
    return plaintext, hashed


def verify_otp(plaintext: str, hashed: str) -> bool:
    """Check an OTP against its bcrypt hash."""
    return bcrypt.checkpw(plaintext.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# Invite management
# ---------------------------------------------------------------------------

async def create_invite(
    wa_id: str,
    name: str,
    role: StaffRole = StaffRole.SDR,
    added_by: str | None = None,
) -> str:
    """Create a staff invite with OTP. Returns the plaintext OTP.

    The OTP is shown ONLY to the owner. Owner shares it out-of-band.
    """
    plaintext, hashed = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=OTP_WINDOW_SECONDS)

    await state.add_staff(
        wa_id=wa_id,
        name=name,
        role=role,
        status=StaffStatus.INVITED,
        otp_hash=hashed,
        otp_expires_at=expires_at,
        added_by=added_by,
    )

    return plaintext


async def verify_login(wa_id: str, otp_input: str) -> tuple[bool, str]:
    """Verify an OTP for a pending staff invite.

    Returns (success, message).
    Handles: expiry, wrong OTP, 3-attempt lockout.
    """
    staff = await state.get_staff(wa_id)

    # Check if there's even an invited record (get_staff filters out REMOVED
    # but we also need to find INVITED ones)
    if not staff:
        # Look directly — get_staff returns None for removed, but we need invited
        raw = state._staff.get(wa_id)
        if raw and raw.status == StaffStatus.INVITED:
            staff = raw
        else:
            return False, "No pending invite for this number. Ask your manager to add you."

    if staff.status == StaffStatus.ACTIVE:
        return True, f"You're already logged in as {staff.role.value}!"

    if staff.status == StaffStatus.REMOVED:
        return False, "Your access has been revoked. Contact your manager."

    if staff.status != StaffStatus.INVITED:
        return False, "No pending invite."

    # Check expiry
    if staff.otp_expires_at and datetime.now(timezone.utc) > staff.otp_expires_at:
        # Expire the invite
        await state.remove_staff(wa_id)
        return False, "OTP expired. Ask your manager to generate a new one."

    # Check attempts
    attempts = getattr(staff, "_login_attempts", 0)
    if attempts >= MAX_ATTEMPTS:
        await state.remove_staff(wa_id)
        return False, "Too many failed attempts. Ask your manager to re-add you."

    # Verify OTP
    if not staff.otp_hash:
        return False, "Invalid invite state. Ask your manager to re-add you."

    if verify_otp(otp_input.strip(), staff.otp_hash):
        await state.update_staff(
            wa_id,
            status=StaffStatus.ACTIVE,
            otp_hash=None,
            otp_expires_at=None,
            last_active=datetime.now(timezone.utc),
        )
        return True, f"Verified! Welcome {staff.name}, you're now logged in as {staff.role.value} at Sharma Motors."

    # Wrong OTP — increment and check if now locked out
    staff._login_attempts = attempts + 1  # type: ignore[attr-defined]
    if staff._login_attempts >= MAX_ATTEMPTS:  # type: ignore[attr-defined]
        await state.remove_staff(wa_id)
        return False, "Too many failed attempts. Ask your manager to re-add you."

    remaining = MAX_ATTEMPTS - staff._login_attempts  # type: ignore[attr-defined]
    return False, f"Wrong OTP. {remaining} attempt{'s' if remaining != 1 else ''} remaining."


# ---------------------------------------------------------------------------
# Login flow state machine (handles multi-message /login conversation)
# ---------------------------------------------------------------------------

# Track who is mid-login (wa_id -> True)
_login_in_progress: dict[str, bool] = {}


async def handle_login_message(wa_id: str, text: str) -> str:
    """Handle a message in the /login flow.

    Called by router.handle_auth_flow(). Manages the multi-step conversation:
    - First message: /login -> prompt for OTP
    - Second message: 6-digit code -> verify
    """
    text = text.strip()

    # Step 1: /login command -> prompt for OTP
    if text.lower().startswith("/login"):
        # Check if there's a pending invite
        raw = state._staff.get(wa_id)
        if raw and raw.status == StaffStatus.ACTIVE:
            return f"You're already logged in as {raw.role.value}!"

        if not raw or raw.status != StaffStatus.INVITED:
            return "No invite found for your number. Ask your manager to add you first."

        _login_in_progress[wa_id] = True
        return "Enter your 6-digit OTP:"

    # Step 2: OTP entry
    if wa_id in _login_in_progress:
        del _login_in_progress[wa_id]

        # Validate format
        if not text.isdigit() or len(text) != 6:
            return "Please enter a valid 6-digit OTP. Send /login to try again."

        success, message = await verify_login(wa_id, text)
        return message

    # Shouldn't reach here but handle gracefully
    return "Send /login to authenticate."


async def reset_auth_state() -> None:
    """Clear login state. Used in tests."""
    _login_in_progress.clear()
