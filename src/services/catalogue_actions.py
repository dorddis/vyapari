"""Catalogue action helpers with customer-facing side effects."""

from __future__ import annotations

from catalogue import CATALOGUE, get_car_detail, mark_car_sold

import state
from services.outbound import send_customer_text


def format_car_label(car: dict) -> str:
    variant = f" {car['variant']}" if car.get("variant") else ""
    return f"{car['year']} {car['make']} {car['model']}{variant}"


def _normalize(text: str) -> str:
    return " ".join(
        "".join(char.lower() if char.isalnum() else " " for char in text).split()
    )


def _car_aliases(car: dict) -> set[str]:
    aliases = {
        _normalize(format_car_label(car)),
        _normalize(f"{car['make']} {car['model']}"),
        _normalize(str(car["model"])),
    }
    if car.get("variant"):
        aliases.add(_normalize(f"{car['make']} {car['model']} {car['variant']}"))
        aliases.add(_normalize(f"{car['model']} {car['variant']}"))
    if car.get("color"):
        aliases.add(_normalize(f"{car['color']} {car['model']}"))
    return {alias for alias in aliases if alias}


def _interest_matches_car(interest: str, car: dict) -> bool:
    normalized_interest = _normalize(interest)
    if not normalized_interest:
        return False

    for alias in _car_aliases(car):
        if alias in normalized_interest or normalized_interest in alias:
            return True
    return False


def _choose_replacement_car(item_id: int) -> dict | None:
    target = get_car_detail(item_id)
    if not target:
        return None

    available = [
        car
        for car in CATALOGUE["cars"]
        if car["id"] != item_id and not car.get("sold") and not car.get("reserved_by")
    ]
    if not available:
        return None

    return min(
        available,
        key=lambda car: (
            0 if car["model"].lower() == target["model"].lower() else 1,
            0 if car["make"].lower() == target["make"].lower() else 1,
            abs(float(car["price_lakhs"]) - float(target["price_lakhs"])),
        ),
    )


async def _find_interested_customers(
    item_id: int,
    exclude_customer_name: str | None = None,
) -> list:
    car = get_car_detail(item_id)
    if not car:
        return []

    excluded_name = _normalize(exclude_customer_name or "")
    customers = await state.list_customers(limit=1000)
    matches = []
    for customer in customers:
        if excluded_name and _normalize(customer.name) == excluded_name:
            continue
        if any(_interest_matches_car(interest, car) for interest in customer.interested_cars):
            matches.append(customer)
    return matches


async def execute_mark_sold(item_id: int) -> dict:
    car = mark_car_sold(item_id)
    if not car:
        return {
            "success": False,
            "data": None,
            "message": f"Car ID {item_id} not found.",
        }

    CATALOGUE["total_cars"] = len([item for item in CATALOGUE["cars"] if not item.get("sold")])

    car_label = format_car_label(car)
    replacement = _choose_replacement_car(item_id)
    replacement_label = format_car_label(replacement) if replacement else None
    interested_customers = await _find_interested_customers(item_id)

    notified = []
    for customer in interested_customers:
        text = f"Quick update from Sharma Motors: the {car_label} is now sold."
        if replacement_label:
            text += f" If you're still looking, the {replacement_label} is the closest available alternative."
        await send_customer_text(customer.wa_id, text)
        notified.append({"name": customer.name, "wa_id": customer.wa_id})

    message = f"Marked {car_label} as sold."
    if notified:
        message += f" Notified {len(notified)} interested customer(s)."
        if replacement_label:
            message += f" Suggested {replacement_label} as the closest alternative."

    return {
        "success": True,
        "data": {
            "id": item_id,
            "car": car_label,
            "notified_count": len(notified),
            "notified_customers": notified,
            "replacement": replacement_label,
        },
        "message": message,
    }


async def execute_mark_reserved(
    item_id: int,
    customer_name: str,
    token_amount: float | None = None,
) -> dict:
    car = get_car_detail(item_id)
    if not car:
        return {
            "success": False,
            "data": None,
            "message": f"Car ID {item_id} not found.",
        }

    car["reserved_by"] = customer_name
    car_label = format_car_label(car)
    replacement = _choose_replacement_car(item_id)
    replacement_label = format_car_label(replacement) if replacement else None
    interested_customers = await _find_interested_customers(
        item_id,
        exclude_customer_name=customer_name,
    )

    notified = []
    for customer in interested_customers:
        text = (
            f"Quick update from Sharma Motors: the {car_label} is currently on hold for another buyer."
        )
        if replacement_label:
            text += f" If you'd like, we can show you the {replacement_label} instead."
        await send_customer_text(customer.wa_id, text)
        notified.append({"name": customer.name, "wa_id": customer.wa_id})

    token_info = f" Token: Rs {token_amount}" if token_amount is not None else ""
    message = f"{car_label} reserved for {customer_name}.{token_info}"
    if notified:
        message += f" Notified {len(notified)} interested customer(s)."
        if replacement_label:
            message += f" Suggested {replacement_label} as the closest alternative."

    return {
        "success": True,
        "data": {
            "id": item_id,
            "reserved_by": customer_name,
            "token_amount": token_amount,
            "notified_count": len(notified),
            "notified_customers": notified,
            "replacement": replacement_label,
        },
        "message": message,
    }
