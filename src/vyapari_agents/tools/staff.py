"""Staff management tools — add, remove, list."""

import json

import state
from models import StaffRole
from services.auth import create_invite


async def tool_add_staff(
    name: str,
    wa_id: str,
    role: str = "sdr",
    added_by: str | None = None,
) -> str:
    """Add a new staff member and generate an OTP invite."""
    # Validate role
    try:
        staff_role = StaffRole(role.lower())
    except ValueError:
        return json.dumps({
            "success": False,
            "data": None,
            "message": f"Invalid role '{role}'. Use 'owner' or 'sdr'.",
        })

    # Check if already exists
    existing = state._staff.get(wa_id)
    if existing and existing.status.value != "removed":
        return json.dumps({
            "success": False,
            "data": None,
            "message": f"{wa_id} is already registered as {existing.role.value}.",
        })

    otp = await create_invite(wa_id, name, staff_role, added_by=added_by)

    return json.dumps({
        "success": True,
        "data": {"name": name, "wa_id": wa_id, "role": role, "otp": otp},
        "message": f"Added {name} as {role}. OTP: {otp}. Share this with them. Expires in 5 minutes.",
    })


async def tool_remove_staff(identifier: str) -> str:
    """Remove a staff member by wa_id or name."""
    # Try direct wa_id
    removed = await state.remove_staff(identifier)
    if removed:
        return json.dumps({
            "success": True,
            "data": {"wa_id": identifier},
            "message": f"Removed {identifier}. Their active sessions have been closed.",
        })

    # Try name search
    all_staff = await state.list_staff()
    matches = [s for s in all_staff if identifier.lower() in s.name.lower()]
    if len(matches) == 1:
        removed = await state.remove_staff(matches[0].wa_id)
        return json.dumps({
            "success": True,
            "data": {"name": matches[0].name, "wa_id": matches[0].wa_id},
            "message": f"Removed {matches[0].name}.",
        })
    if len(matches) > 1:
        names = [f"{s.name} ({s.wa_id})" for s in matches]
        return json.dumps({
            "success": False,
            "data": {"matches": names},
            "message": f"Multiple matches: {', '.join(names)}. Specify the phone number.",
        })

    return json.dumps({
        "success": False,
        "data": None,
        "message": f"Staff member '{identifier}' not found.",
    })


async def tool_list_staff() -> str:
    """List all active and invited staff members."""
    staff_list = await state.list_staff()

    data = [
        {
            "name": s.name,
            "wa_id": s.wa_id,
            "role": s.role.value,
            "status": s.status.value,
            "last_active": s.last_active.isoformat() if s.last_active else "never",
        }
        for s in staff_list
    ]

    return json.dumps({
        "success": True,
        "data": data,
        "message": f"{len(data)} staff member{'s' if len(data) != 1 else ''}.",
    })
