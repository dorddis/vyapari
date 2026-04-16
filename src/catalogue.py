"""Load and query the demo catalogue + FAQs + business profile."""

import json
from config import DATA_DIR


def _load_json(filename: str) -> dict:
    with open(DATA_DIR / filename, "r", encoding="utf-8") as f:
        return json.load(f)


# Load once at import
BUSINESS = _load_json("business_profile.json")
CATALOGUE = _load_json("catalogue.json")
FAQS = _load_json("faqs.json")


def mark_car_sold(car_id: int) -> dict | None:
    """Mark a car as sold. Returns the car dict or None if not found."""
    for car in CATALOGUE["cars"]:
        if car["id"] == car_id:
            car["sold"] = True
            return car
    return None


def get_catalogue_summary() -> str:
    """Compact summary of all available (not sold) cars for system prompt context."""
    lines = []
    for car in CATALOGUE["cars"]:
        if car.get("sold"):
            continue
        line = (
            f"ID:{car['id']} | {car['year']} {car['make']} {car['model']} {car['variant']} | "
            f"{car['fuel_type']} {car['transmission']} | {car['km_driven']}km | "
            f"{car['num_owners']} owner(s) | {car['color']} | "
            f"Rs {car['price_lakhs']}L | {car['condition']}"
        )
        lines.append(line)
    return "\n".join(lines)


def get_car_detail(car_id: int) -> dict | None:
    """Get full details for a specific car."""
    for car in CATALOGUE["cars"]:
        if car["id"] == car_id:
            return car
    return None


def search_cars(
    max_price: float | None = None,
    min_price: float | None = None,
    fuel_type: str | None = None,
    make: str | None = None,
    transmission: str | None = None,
    category: str | None = None,
) -> list[dict]:
    """Filter catalogue by criteria."""
    results = CATALOGUE["cars"]
    if max_price is not None:
        results = [c for c in results if c["price_lakhs"] <= max_price]
    if min_price is not None:
        results = [c for c in results if c["price_lakhs"] >= min_price]
    if fuel_type:
        results = [c for c in results if c["fuel_type"].lower() == fuel_type.lower()]
    if make:
        results = [c for c in results if make.lower() in c["make"].lower()]
    if transmission:
        results = [c for c in results if c["transmission"].lower() == transmission.lower()]
    return results


def get_faq_text() -> str:
    """All FAQs as text for system prompt."""
    lines = []
    for faq in FAQS["faqs"]:
        lines.append(f"Q: {faq['question']}\nA: {faq['answer']}")
    return "\n\n".join(lines)


def get_business_context() -> str:
    """Business info for system prompt."""
    b = BUSINESS
    loc = b["location"]
    hrs = b["hours"]

    return f"""Business: {b['business_name']}
Type: {b['type']}
Owner: {b['owner']['name']} ({b['owner']['title']})
Address: {loc['address_line_1']}, {loc['address_line_2']}, {loc['area']}, {loc['city']} - {loc['pincode']}
Landmark: {loc['landmark']}
Phone: {b['contact']['phone_primary']}
WhatsApp: {b['contact']['whatsapp']}

Hours:
Mon-Sat: {hrs['monday']}
Sunday: {hrs['sunday']}

USPs: {', '.join(b['usp'])}

Services: {', '.join(b['services'])}

Price range: {b['inventory_stats']['price_range']}
Current stock: {CATALOGUE['total_cars']} cars"""
