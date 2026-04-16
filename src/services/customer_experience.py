"""Customer-facing demo helpers for source-aware greetings and media."""

from __future__ import annotations

from catalogue import CATALOGUE
from channels.base import get_channel


def _car_label(car: dict) -> str:
    variant = f" {car['variant']}" if car.get("variant") else ""
    return f"{car['year']} {car['make']} {car['model']}{variant}"


def _match_source_car(source_car: str | None = None, source_video: str | None = None) -> dict | None:
    haystack = " ".join(part for part in [source_car or "", source_video or ""] if part).lower()
    if not haystack:
        return None

    for car in CATALOGUE["cars"]:
        label = _car_label(car).lower()
        make_model = f"{car['make']} {car['model']}".lower()
        if label in haystack or make_model in haystack:
            return car
        if car["model"].lower() in haystack:
            return car
    return None


def build_source_aware_greeting(
    source_car: str | None = None,
    source_video: str | None = None,
) -> tuple[str, list[str]]:
    car = _match_source_car(source_car, source_video)
    if not car:
        return (
            "Hey! Welcome to Sharma Motors. Looking for a specific car, or should I show you the best options in your budget?",
            [],
        )

    owner_count = "single owner" if int(car.get("num_owners", 1)) == 1 else f"{car['num_owners']} owners"
    greeting = (
        f"Hey! Saw you checking out our *{_car_label(car)}* video.\n\n"
        f"That one's {owner_count}, {car['fuel_type'].lower()}, just *Rs {car['price_lakhs']}L*. "
        "Want the full details, or are you looking at other options too?"
    )
    images = [url for url in [car.get("image_url")] + car.get("images", []) if url]
    return greeting, images[:1]


async def queue_catalogue_result_media(customer_wa_id: str, cars: list[dict], limit: int = 3) -> None:
    """Queue image previews for catalogue results in the active channel."""
    channel = get_channel()
    sent = 0
    for car in cars:
        if sent >= limit or not car:
            break
        image_url = car.get("image_url") or (car.get("images") or [None])[0]
        if not image_url:
            continue
        caption = f"{_car_label(car)} - Rs {car['price_lakhs']}L"
        await channel.send_image(customer_wa_id, image_url, caption)
        sent += 1
