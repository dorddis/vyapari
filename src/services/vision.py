"""GPT-5.4 Vision service — image analysis for inventory, payments, and car ID.

Uses AsyncOpenAI with Pydantic structured output (beta.chat.completions.parse)
for reliable JSON extraction. No manual JSON parsing needed.

Supports both URL and base64 image input.
"""

import base64
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

import config

log = logging.getLogger("vyapari.services.vision")

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _image_content(
    image_url: str | None = None,
    image_bytes: bytes | None = None,
    detail: str = "high",
) -> dict:
    """Build the image content block for the API call."""
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": detail},
        }
    if image_url:
        return {
            "type": "image_url",
            "image_url": {"url": image_url, "detail": detail},
        }
    raise ValueError("Either image_url or image_bytes must be provided")


# ---------------------------------------------------------------------------
# Pydantic schemas for structured vision output
# ---------------------------------------------------------------------------

class ParsedCar(BaseModel):
    make: str = ""
    model: str = ""
    variant: str = ""
    year: int = 2023
    price_lakhs: float | None = None
    fuel_type: str = "Petrol"
    transmission: str = "Manual"
    km_driven: int = 0
    num_owners: int = 1
    color: str = ""
    condition: str = "Good"
    description: str = ""


class UnclearItem(BaseModel):
    item: str
    issue: str


class InventoryParseResult(BaseModel):
    cars: list[ParsedCar] = Field(default_factory=list)
    unclear: list[UnclearItem] = Field(default_factory=list)
    total_found: int = 0


class UPITransaction(BaseModel):
    transaction_status: str | None = None
    amount: float | None = None
    sender_name: str | None = None
    sender_upi_id: str | None = None
    receiver_name: str | None = None
    receiver_upi_id: str | None = None
    transaction_id: str | None = None
    date: str | None = None
    time: str | None = None
    upi_app: str | None = None
    note: str | None = None
    confidence: str = "low"


class CarIdentification(BaseModel):
    make: str | None = None
    model: str | None = None
    variant_guess: str | None = None
    year_range: str | None = None
    color: str | None = None
    confidence: str = "low"
    features_visible: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Inventory parsing (PDF/image -> car list)
# ---------------------------------------------------------------------------

_INVENTORY_SYSTEM = (
    "You are a used car inventory parser for the Indian market. "
    "Extract structured car data from the image. The image may be a PDF page, "
    "spreadsheet screenshot, handwritten price list, or photos of cars. "
    "Prices are in Indian Lakhs. Common brands: Maruti, Hyundai, Tata, Honda, "
    "Toyota, Mahindra, Kia. If a price is missing, put it in the unclear array."
)


async def parse_inventory_image(
    image_url: str | None = None,
    image_bytes: bytes | None = None,
) -> InventoryParseResult:
    """Parse a car inventory image/PDF and return structured car data."""
    try:
        client = _get_client()
        response = await client.beta.chat.completions.parse(
            model=config.OPENAI_MAIN_MODEL,
            messages=[
                {"role": "system", "content": _INVENTORY_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all car listings from this image."},
                        _image_content(image_url=image_url, image_bytes=image_bytes),
                    ],
                },
            ],
            response_format=InventoryParseResult,
            max_tokens=4096,
            temperature=0,
        )

        result = response.choices[0].message.parsed
        if result:
            log.info(f"Inventory parsed: {result.total_found} cars found")
            return result

        return InventoryParseResult()

    except Exception as e:
        log.error(f"Vision inventory parsing failed: {e}", exc_info=True)
        return InventoryParseResult()


# ---------------------------------------------------------------------------
# Token/payment proof parsing
# ---------------------------------------------------------------------------

_TOKEN_SYSTEM = (
    "You are a payment screenshot parser for an Indian used car dealership. "
    "Extract payment/transaction details from UPI, bank transfer, or payment app screenshots. "
    "Common apps: Google Pay, PhonePe, Paytm, BHIM. Amount in rupees (not lakhs). "
    "Set confidence to high/medium/low based on image clarity."
)


async def parse_token_proof(
    image_url: str | None = None,
    image_bytes: bytes | None = None,
) -> UPITransaction:
    """Parse a UPI/payment screenshot and extract transaction details."""
    try:
        client = _get_client()
        response = await client.beta.chat.completions.parse(
            model=config.OPENAI_MAIN_MODEL,
            messages=[
                {"role": "system", "content": _TOKEN_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract payment details from this screenshot."},
                        _image_content(image_url=image_url, image_bytes=image_bytes, detail="high"),
                    ],
                },
            ],
            response_format=UPITransaction,
            max_tokens=1024,
            temperature=0,
        )

        result = response.choices[0].message.parsed
        if result:
            log.info(f"Token proof parsed: Rs {result.amount} from {result.sender_name}")
            return result

        return UPITransaction()

    except Exception as e:
        log.error(f"Vision token parsing failed: {e}", exc_info=True)
        return UPITransaction()


# ---------------------------------------------------------------------------
# Car identification from photo
# ---------------------------------------------------------------------------

_CAR_ID_SYSTEM = (
    "You are a car identification expert for the Indian used car market. "
    "Identify the car make and model from a photo. Focus on Indian market cars "
    "(Maruti, Hyundai, Tata, Honda, Toyota, Mahindra, Kia, etc.). "
    "Set confidence to high/medium/low/none."
)


async def identify_car_from_photo(
    image_url: str | None = None,
    image_bytes: bytes | None = None,
) -> CarIdentification:
    """Identify a car from a photo."""
    try:
        client = _get_client()
        response = await client.beta.chat.completions.parse(
            model=config.OPENAI_MAIN_MODEL,
            messages=[
                {"role": "system", "content": _CAR_ID_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Identify this car."},
                        _image_content(image_url=image_url, image_bytes=image_bytes, detail="low"),
                    ],
                },
            ],
            response_format=CarIdentification,
            max_tokens=512,
            temperature=0,
        )

        result = response.choices[0].message.parsed
        if result:
            log.info(f"Car identified: {result.make} {result.model} ({result.confidence})")
            return result

        return CarIdentification()

    except Exception as e:
        log.error(f"Vision car ID failed: {e}", exc_info=True)
        return CarIdentification()
