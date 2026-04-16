"""Owner onboarding flow for business setup basics."""

from __future__ import annotations

import re

import state
from catalogue import BUSINESS, get_customer_share_link, update_business_profile

SETUP_FIELD_ORDER = [
    "business_name",
    "business_type",
    "city",
    "contact_phone",
    "greeting",
    "faq_enabled",
]

FIELD_QUESTIONS = {
    "business_name": "Business name kya dikhana hai?",
    "business_type": "Business type bolo. Example: Used car dealer, real estate broker, etc.",
    "city": "Kaunsi city se operate karte ho?",
    "contact_phone": "Owner contact number kya rahega? WhatsApp number bhej do.",
    "greeting": "Customer ko first message me kya greeting bhejna hai?",
    "faq_enabled": (
        "Last bit: preset dealer FAQs on kar du? "
        "Isme financing, RC transfer, warranty, exchange aur test drive answers ready milenge. Reply yes or no."
    ),
}

SETUP_TRIGGER_PATTERNS = (
    "/setup",
    "setup kara do",
    "setup kar do",
    "owner setup",
    "business profile",
    "continue karo",
)

YES_PATTERNS = ("yes", "haan", "on kar do", "enable", "ok")
NO_PATTERNS = ("no", "nahi", "mat", "off", "disable")


async def should_handle_owner_setup(wa_id: str, text: str) -> bool:
    """Return True when the owner setup flow should intercept the message."""
    flow = await state.get_owner_setup(wa_id)
    if flow and flow.active:
        return True

    lowered = (text or "").strip().lower()
    return any(pattern in lowered for pattern in SETUP_TRIGGER_PATTERNS)


async def handle_owner_setup_message(wa_id: str, text: str) -> str:
    """Advance the owner onboarding flow and return the next prompt."""
    flow = await state.get_owner_setup(wa_id)
    if flow is None or not flow.active:
        flow = await state.start_owner_setup(wa_id)

    cleaned_text = (text or "").strip()
    lowered = cleaned_text.lower()

    if lowered.startswith("/setup"):
        await state.update_owner_setup(wa_id, current_step=_next_missing_field(flow.collected))
        flow = await state.get_owner_setup(wa_id)
        return _render_next_prompt(flow.collected, flow.current_step)

    extracted = _extract_fields(cleaned_text, flow.current_step)
    merged = {**flow.collected, **extracted}
    next_step = _next_missing_field(merged)

    if next_step is None:
        update_business_profile(
            business_name=merged["business_name"],
            business_type=merged["business_type"],
            city=merged["city"],
            contact_phone=merged["contact_phone"],
            greeting=merged["greeting"],
            faq_enabled=merged["faq_enabled"],
        )
        await state.update_owner_setup(wa_id, collected=merged, current_step="completed")
        await state.complete_owner_setup(wa_id)
        return _render_completion(merged)

    await state.update_owner_setup(
        wa_id,
        collected=merged,
        current_step=next_step,
    )
    return _render_next_prompt(merged, next_step)


def _next_missing_field(collected: dict) -> str | None:
    for field in SETUP_FIELD_ORDER:
        value = collected.get(field)
        if value is None:
            return field
        if isinstance(value, str) and not value.strip():
            return field
    return None


def _extract_fields(text: str, current_step: str) -> dict:
    lowered = text.lower()

    if "continue karo" in lowered or "continue" in lowered:
        return {}

    extracted: dict[str, object] = {}

    business_name = _extract_business_name(text, current_step)
    if business_name:
        extracted["business_name"] = business_name

    business_type = _extract_business_type(text)
    if business_type:
        extracted["business_type"] = business_type

    city = _extract_city(text)
    if city:
        extracted["city"] = city

    contact_phone = _extract_phone(text)
    if contact_phone:
        extracted["contact_phone"] = contact_phone

    faq_enabled = _extract_faq_preference(text)
    if faq_enabled is not None:
        extracted["faq_enabled"] = faq_enabled

    if current_step == "greeting" and text.strip():
        extracted["greeting"] = text.strip()

    return extracted


def _extract_business_name(text: str, current_step: str) -> str | None:
    match = re.search(r"([A-Za-z][A-Za-z0-9& ]{2,})\s+(?:naam hai|name is)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    if (
        current_step == "business_name"
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9& ]{2,}", text.strip())
        and not any(char.isdigit() for char in text)
    ):
        return text.strip()

    return None


def _extract_business_type(text: str) -> str | None:
    lowered = text.lower()
    if "used car" in lowered or "car dealer" in lowered:
        return "Used Car Dealer"
    if "real estate" in lowered:
        return "Real Estate"
    if "dealer" in lowered:
        cleaned = re.sub(r"\b(?:hu|hoon|setup|kara|kar|do)\b", "", text, flags=re.IGNORECASE).strip(" ,.")
        return cleaned.title() if cleaned else "Dealer"
    return None


def _extract_city(text: str) -> str | None:
    patterns = [
        r"([A-Za-z ]+)\s+se hu",
        r"city\s+(?:is|hai)\s+([A-Za-z ]+)",
        r"from\s+([A-Za-z ]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            city = match.group(1).strip(" ,.")
            return city.title()
    return None


def _extract_phone(text: str) -> str | None:
    digits = re.sub(r"\D", "", text)
    if len(digits) >= 10:
        if len(digits) == 10:
            digits = f"91{digits}"
        if not digits.startswith("91") and len(digits) < 12:
            digits = f"91{digits[-10:]}"
        return f"+{digits}"
    return None


def _extract_faq_preference(text: str) -> bool | None:
    lowered = text.lower()
    if any(re.search(rf"\b{re.escape(pattern)}\b", lowered) for pattern in YES_PATTERNS):
        return True
    if any(re.search(rf"\b{re.escape(pattern)}\b", lowered) for pattern in NO_PATTERNS):
        return False
    return None


def _render_next_prompt(collected: dict, current_step: str) -> str:
    progress_bits = []
    if collected.get("business_name"):
        progress_bits.append(f"Name: {collected['business_name']}")
    if collected.get("business_type"):
        progress_bits.append(f"Type: {collected['business_type']}")
    if collected.get("city"):
        progress_bits.append(f"City: {collected['city']}")
    if collected.get("contact_phone"):
        progress_bits.append(f"Contact: {collected['contact_phone']}")
    if collected.get("greeting"):
        progress_bits.append("Greeting: set")

    progress_text = " | ".join(progress_bits) if progress_bits else "No basics saved yet."
    return (
        "Owner setup in progress.\n"
        f"Saved so far: {progress_text}\n"
        f"{FIELD_QUESTIONS[current_step]}"
    )


def _render_completion(collected: dict) -> str:
    faq_text = "ON" if collected["faq_enabled"] else "OFF"
    share_link = get_customer_share_link()

    return (
        "Done. Your bot is live.\n"
        f"Business: {BUSINESS['business_name']}\n"
        f"Type: {BUSINESS['type']}\n"
        f"City: {BUSINESS['location']['city']}\n"
        f"Contact: {BUSINESS['contact']['phone_primary']}\n"
        f"FAQ presets: {faq_text}\n"
        f"Customer link: {share_link}\n"
        "Next: send your inventory PDF, Excel, photos, or plain text stock list and I'll turn it into live listings."
    )
