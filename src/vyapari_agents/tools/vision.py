"""Vision tools — image-based inventory parsing, payment proof, car identification.

These tools use GPT-5.4 vision (via services/vision.py) with Pydantic
structured output for reliable extraction. No manual JSON parsing.
"""

import json
import logging

import state
from services.vision import (
    identify_car_from_photo,
    parse_inventory_image,
    parse_token_proof,
)
from vyapari_agents.tools.catalogue import tool_add_item, tool_search_catalogue

log = logging.getLogger("vyapari.tools.vision")


async def tool_parse_inventory(image_url: str) -> str:
    """Parse a car inventory image/PDF and add cars to the catalogue.

    Sends the image to GPT-5.4 vision, extracts car data, adds each car.
    Returns summary of what was added and what needs clarification.
    """
    result = await parse_inventory_image(image_url=image_url)

    if not result.cars and not result.unclear:
        return json.dumps({
            "success": False,
            "data": None,
            "message": "Could not find any car listings in the image. Try a clearer photo or PDF.",
        })

    added = []
    failed = []

    for car in result.cars:
        if car.price_lakhs is None or car.price_lakhs == 0:
            result.unclear.append(type(result.unclear[0]) if result.unclear else type('obj', (), {'item': '', 'issue': ''})())
            continue

        try:
            add_result = json.loads(tool_add_item(
                make=car.make,
                model=car.model,
                year=car.year,
                price_lakhs=car.price_lakhs,
                variant=car.variant,
                fuel_type=car.fuel_type,
                transmission=car.transmission,
                km_driven=car.km_driven,
                num_owners=car.num_owners,
                color=car.color,
                condition=car.condition,
                description=car.description,
            ))
            if add_result["success"]:
                added.append(f"{car.year} {car.make} {car.model}")
        except Exception as e:
            failed.append(f"{car.make} {car.model}: {e}")

    # Cars with no price go to unclear
    no_price = [c for c in result.cars if c.price_lakhs is None or c.price_lakhs == 0]
    unclear_items = [{"item": f"{c.make} {c.model}", "issue": "No price listed"} for c in no_price]
    unclear_items += [{"item": u.item, "issue": u.issue} for u in result.unclear]

    unclear_text = ""
    if unclear_items:
        lines = [f"- {item['item']}: {item['issue']}" for item in unclear_items]
        unclear_text = "\n\nNeed your input on:\n" + "\n".join(lines)

    message = f"Found {result.total_found} cars. Added {len(added)} successfully."
    if failed:
        message += f" {len(failed)} failed."
    message += unclear_text

    return json.dumps({
        "success": True,
        "data": {
            "added": added,
            "failed": failed,
            "unclear": unclear_items,
            "total_found": result.total_found,
        },
        "message": message,
    })


async def tool_parse_token_screenshot(
    image_url: str,
    car_name: str | None = None,
) -> str:
    """Parse a UPI/payment screenshot and extract transaction details.

    Returns payment info (amount, sender, status) for the owner to confirm
    before marking a car as reserved.
    """
    result = await parse_token_proof(image_url=image_url)

    if not result.amount:
        return json.dumps({
            "success": False,
            "data": None,
            "message": "Could not extract payment details from the screenshot. Try a clearer image.",
        })

    if result.transaction_status and result.transaction_status.lower() != "success":
        return json.dumps({
            "success": False,
            "data": result.model_dump(),
            "message": f"Payment status is '{result.transaction_status}', not 'success'. Please verify.",
        })

    # Try to match sender to a customer
    customer_match = None
    if result.sender_name:
        customers = await state.list_customers(search_query=result.sender_name, limit=1)
        if customers:
            customer_match = customers[0]

    data = result.model_dump()
    data["customer_matched"] = customer_match.name if customer_match else None
    data["customer_wa_id"] = customer_match.wa_id if customer_match else None

    message = f"Token proof: Rs {result.amount} from {result.sender_name or 'unknown'}."
    if result.confidence == "high":
        message += " (high confidence)"
    if customer_match:
        message += f" Matched to customer: {customer_match.name}."
    if car_name:
        message += f" Car: {car_name}."
    message += " Confirm to mark as reserved."

    return json.dumps({
        "success": True,
        "data": data,
        "message": message,
    })


async def tool_identify_car(image_url: str) -> str:
    """Identify a car from a photo and search for matches in the catalogue."""
    result = await identify_car_from_photo(image_url=image_url)

    if result.confidence == "none" or not result.make:
        return json.dumps({
            "success": False,
            "data": result.model_dump(),
            "message": "Could not identify the car from this photo. Can you describe what you're looking for?",
        })

    # Search catalogue for matches
    search_result = json.loads(tool_search_catalogue(make=result.make))
    matches = search_result.get("data", [])

    model_lower = result.model.lower() if result.model else ""
    exact_matches = [m for m in matches if model_lower in m.get("name", "").lower()] if model_lower else matches

    car_desc = f"{result.make} {result.model}" if result.model else result.make
    features = result.features_visible
    features_text = f" Features spotted: {', '.join(features)}." if features else ""

    if exact_matches:
        message = f"That looks like a {car_desc} ({result.confidence} confidence).{features_text} We have {len(exact_matches)} in stock!"
    elif matches:
        message = f"That looks like a {car_desc} ({result.confidence} confidence).{features_text} We don't have that exact model, but we have {len(matches)} other {result.make} cars."
    else:
        message = f"That looks like a {car_desc} ({result.confidence} confidence).{features_text} We don't have any {result.make} cars right now."

    return json.dumps({
        "success": True,
        "data": {
            "identified": result.model_dump(),
            "catalogue_matches": exact_matches or matches,
        },
        "message": message,
    })
