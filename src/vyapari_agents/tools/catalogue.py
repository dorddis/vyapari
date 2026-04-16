"""Catalogue tools — search, details, compare, availability, pricing.

Used by both Customer Agent and Owner Agent. Wraps catalogue.py functions
and returns ToolResponse-shaped dicts for the LLM.
"""

import json

from catalogue import BUSINESS, CATALOGUE, get_car_detail, mark_car_sold, search_cars


# ---------------------------------------------------------------------------
# Customer + Owner tools
# ---------------------------------------------------------------------------

def tool_search_catalogue(
    max_price: float | None = None,
    min_price: float | None = None,
    fuel_type: str | None = None,
    make: str | None = None,
    transmission: str | None = None,
    max_km: int | None = None,
) -> str:
    """Search the car catalogue with optional filters. Returns up to 5 matching cars."""
    results = search_cars(
        max_price=max_price,
        min_price=min_price,
        fuel_type=fuel_type,
        make=make,
        transmission=transmission,
    )

    # Filter by km if specified
    if max_km is not None:
        results = [c for c in results if c["km_driven"] <= max_km]

    # Exclude sold cars
    results = [c for c in results if not c.get("sold")]

    # Limit to 5
    results = results[:5]

    if not results:
        return json.dumps({
            "success": True,
            "data": [],
            "message": "No cars found matching your criteria.",
        })

    cars = []
    for car in results:
        entry = {
            "id": car["id"],
            "name": f"{car['year']} {car['make']} {car['model']} {car['variant']}",
            "price_lakhs": car["price_lakhs"],
            "fuel_type": car["fuel_type"],
            "km_driven": car["km_driven"],
            "color": car["color"],
            "highlight": car.get("highlights", [""])[0] if car.get("highlights") else "",
        }
        if car.get("image_url"):
            entry["image_url"] = car["image_url"]
        cars.append(entry)

    return json.dumps({
        "success": True,
        "data": cars,
        "message": f"Found {len(cars)} car{'s' if len(cars) != 1 else ''}.",
    })


def tool_get_item_details(item_id: int) -> str:
    """Get full details for a specific car by ID."""
    car = get_car_detail(item_id)
    if not car:
        return json.dumps({
            "success": False,
            "data": None,
            "message": f"Car with ID {item_id} not found.",
        })

    return json.dumps({
        "success": True,
        "data": car,
        "message": f"{car['year']} {car['make']} {car['model']} {car['variant']}",
    })


def tool_compare_items(item_id_1: int, item_id_2: int) -> str:
    """Compare two cars side by side."""
    car1 = get_car_detail(item_id_1)
    car2 = get_car_detail(item_id_2)

    if not car1:
        return json.dumps({"success": False, "data": None, "message": f"Car ID {item_id_1} not found."})
    if not car2:
        return json.dumps({"success": False, "data": None, "message": f"Car ID {item_id_2} not found."})

    comparison = {
        "car_1": {
            "name": f"{car1['year']} {car1['make']} {car1['model']} {car1['variant']}",
            "price_lakhs": car1["price_lakhs"],
            "fuel_type": car1["fuel_type"],
            "transmission": car1["transmission"],
            "km_driven": car1["km_driven"],
            "num_owners": car1["num_owners"],
            "color": car1["color"],
            "condition": car1["condition"],
            "highlights": car1.get("highlights", []),
        },
        "car_2": {
            "name": f"{car2['year']} {car2['make']} {car2['model']} {car2['variant']}",
            "price_lakhs": car2["price_lakhs"],
            "fuel_type": car2["fuel_type"],
            "transmission": car2["transmission"],
            "km_driven": car2["km_driven"],
            "num_owners": car2["num_owners"],
            "color": car2["color"],
            "condition": car2["condition"],
            "highlights": car2.get("highlights", []),
        },
    }

    return json.dumps({
        "success": True,
        "data": comparison,
        "message": f"Comparison: {comparison['car_1']['name']} vs {comparison['car_2']['name']}",
    })


def tool_check_availability(item_id: int) -> str:
    """Check if a car is available, sold, or reserved."""
    car = get_car_detail(item_id)
    if not car:
        return json.dumps({"success": False, "data": None, "message": f"Car ID {item_id} not found."})

    if car.get("sold"):
        status = "sold"
    elif car.get("reserved_by"):
        status = f"reserved by {car['reserved_by']}"
    else:
        status = "available"

    return json.dumps({
        "success": True,
        "data": {"id": item_id, "status": status},
        "message": f"{car['year']} {car['make']} {car['model']} is {status}.",
    })


def tool_get_pricing_info(item_id: int, down_payment_pct: float = 20) -> str:
    """Get EMI estimates and additional costs for a car."""
    car = get_car_detail(item_id)
    if not car:
        return json.dumps({"success": False, "data": None, "message": f"Car ID {item_id} not found."})

    price = car["price_lakhs"] * 100000  # convert to rupees
    down_payment = price * (down_payment_pct / 100)
    loan_amount = price - down_payment

    # EMI calculation: EMI = P * r * (1+r)^n / ((1+r)^n - 1)
    banks = BUSINESS.get("finance_partners", [
        {"name": "HDFC Bank", "min_rate": "8.5%"},
        {"name": "ICICI Bank", "min_rate": "8.75%"},
        {"name": "SBI", "min_rate": "8.3%"},
        {"name": "Axis Bank", "min_rate": "9.0%"},
    ])

    emi_table = []
    for bank in banks:
        rate_str = bank.get("min_rate", "9%").replace("%", "")
        try:
            annual_rate = float(rate_str)
        except ValueError:
            annual_rate = 9.0
        monthly_rate = annual_rate / 12 / 100

        for tenure_months in [36, 48, 60]:
            if monthly_rate > 0:
                emi = loan_amount * monthly_rate * (1 + monthly_rate) ** tenure_months / (
                    (1 + monthly_rate) ** tenure_months - 1
                )
            else:
                emi = loan_amount / tenure_months

            emi_table.append({
                "bank": bank["name"],
                "tenure_months": tenure_months,
                "emi": round(emi),
                "rate_pct": annual_rate,
            })

    additional_costs = {
        "rc_transfer": "Rs 300-600",
        "insurance_transfer": "Varies by insurer",
        "rto_agent": "Rs 1,000-5,000",
        "hypothecation_removal": "Rs 500-1,500 (if financed previously)",
    }

    return json.dumps({
        "success": True,
        "data": {
            "car": f"{car['year']} {car['make']} {car['model']}",
            "price_lakhs": car["price_lakhs"],
            "down_payment_pct": down_payment_pct,
            "down_payment": round(down_payment),
            "loan_amount": round(loan_amount),
            "emi_options": emi_table,
            "additional_costs": additional_costs,
        },
        "message": f"EMI options for {car['year']} {car['make']} {car['model']} at Rs {car['price_lakhs']}L",
    })


# ---------------------------------------------------------------------------
# Owner-only tools
# ---------------------------------------------------------------------------

def tool_add_item(
    make: str,
    model: str,
    year: int,
    price_lakhs: float,
    variant: str = "",
    fuel_type: str = "Petrol",
    transmission: str = "Manual",
    km_driven: int = 0,
    num_owners: int = 1,
    color: str = "",
    condition: str = "Good",
    description: str = "",
) -> str:
    """Add a new car to the catalogue."""
    max_id = max((c["id"] for c in CATALOGUE["cars"]), default=0)
    new_car = {
        "id": max_id + 1,
        "make": make,
        "model": model,
        "variant": variant,
        "year": year,
        "price_lakhs": price_lakhs,
        "fuel_type": fuel_type,
        "transmission": transmission,
        "km_driven": km_driven,
        "num_owners": num_owners,
        "color": color,
        "condition": condition,
        "description": description,
        "highlights": [],
        "images": [],
        "image_url": "",
        "sold": False,
    }
    CATALOGUE["cars"].append(new_car)
    CATALOGUE["total_cars"] = len([c for c in CATALOGUE["cars"] if not c.get("sold")])

    return json.dumps({
        "success": True,
        "data": {"id": new_car["id"]},
        "message": f"Added {year} {make} {model} at Rs {price_lakhs}L. ID: {new_car['id']}.",
    })


def tool_update_item(item_id: int, **fields) -> str:
    """Update fields on an existing car."""
    car = get_car_detail(item_id)
    if not car:
        return json.dumps({"success": False, "data": None, "message": f"Car ID {item_id} not found."})

    updated = []
    for key, value in fields.items():
        if key in car:
            car[key] = value
            updated.append(f"{key}={value}")

    if not updated:
        return json.dumps({"success": False, "data": None, "message": "No valid fields to update."})

    return json.dumps({
        "success": True,
        "data": {"id": item_id, "updated": updated},
        "message": f"Updated {car['year']} {car['make']} {car['model']}: {', '.join(updated)}.",
    })


async def tool_mark_sold(item_id: int, notify_interested: bool = True) -> str:
    """Mark a car as sold. Optionally notify customers who asked about it."""
    import state as _state

    car = mark_car_sold(item_id)
    if not car:
        return json.dumps({"success": False, "data": None, "message": f"Car ID {item_id} not found."})

    CATALOGUE["total_cars"] = len([c for c in CATALOGUE["cars"] if not c.get("sold")])
    car_name = f"{car['year']} {car['make']} {car['model']}"

    # Find customers who expressed interest in this car
    notified_count = 0
    if notify_interested:
        all_customers = await _state.list_customers(limit=100)
        car_model_lower = car["model"].lower()
        for customer in all_customers:
            if any(car_model_lower in ic.lower() for ic in customer.interested_cars):
                # Queue notification (will be sent via channel by the caller)
                notified_count += 1

    return json.dumps({
        "success": True,
        "data": {
            "id": item_id,
            "car": car_name,
            "notified_customers": notified_count,
        },
        "message": (
            f"Marked {car_name} as sold."
            + (f" {notified_count} interested customer{'s' if notified_count != 1 else ''} can be notified."
               if notified_count > 0 else "")
        ),
    })


def tool_mark_reserved(item_id: int, customer_name: str, token_amount: float | None = None) -> str:
    """Reserve a car for a customer (token received)."""
    car = get_car_detail(item_id)
    if not car:
        return json.dumps({"success": False, "data": None, "message": f"Car ID {item_id} not found."})

    car["reserved_by"] = customer_name
    token_info = f" Token: Rs {token_amount}" if token_amount else ""

    return json.dumps({
        "success": True,
        "data": {"id": item_id, "reserved_by": customer_name},
        "message": f"{car['year']} {car['make']} {car['model']} reserved for {customer_name}.{token_info}",
    })


def tool_get_catalogue_summary() -> str:
    """Get inventory overview — counts by category, price range, etc."""
    available = [c for c in CATALOGUE["cars"] if not c.get("sold")]
    sold = [c for c in CATALOGUE["cars"] if c.get("sold")]

    by_fuel = {}
    by_make = {}
    prices = []
    for car in available:
        by_fuel[car["fuel_type"]] = by_fuel.get(car["fuel_type"], 0) + 1
        by_make[car["make"]] = by_make.get(car["make"], 0) + 1
        prices.append(car["price_lakhs"])

    summary = {
        "total_available": len(available),
        "total_sold": len(sold),
        "by_fuel": by_fuel,
        "by_make": by_make,
        "price_range": f"Rs {min(prices):.1f}L - Rs {max(prices):.1f}L" if prices else "N/A",
        "avg_price": f"Rs {sum(prices) / len(prices):.1f}L" if prices else "N/A",
    }

    return json.dumps({
        "success": True,
        "data": summary,
        "message": f"{len(available)} cars available, {len(sold)} sold.",
    })
