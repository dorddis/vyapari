"""Web demo customer flow tests for greeting bootstrap and queued media."""

from __future__ import annotations

import pytest

import state
from catalogue import get_car_detail
from channels.web_clone.adapter import get_pending_messages
from services.customer_experience import queue_catalogue_result_media
from web_api import ChatRequest, ChatStartRequest, customer_chat, customer_chat_start


@pytest.mark.asyncio
async def test_customer_chat_start_returns_source_aware_greeting_and_persists_source():
    response = await customer_chat_start(
        ChatStartRequest(
            customer_id="919876543210",
            customer_name="Ramesh Patil",
            source="creta_reel_apr16",
            source_car="2021 Hyundai Creta SX",
            source_video="2021 Hyundai Creta SX Diesel Walkthrough",
        )
    )

    customer = await state.get_customer("919876543210")
    conversation = await state.get_conversation("919876543210")
    messages = await state.get_messages(conversation.id)

    assert "2021 Hyundai Creta SX" in response["reply"]
    assert response["images"]
    assert customer is not None
    assert customer.source == "creta_reel_apr16"
    assert len(messages) == 1
    assert "2021 Hyundai Creta SX" in messages[0].content


@pytest.mark.asyncio
async def test_queue_catalogue_result_media_enqueues_image_messages():
    cars = [get_car_detail(11), get_car_detail(12), get_car_detail(7)]

    await queue_catalogue_result_media("919876543210", cars)
    pending = get_pending_messages("919876543210")

    assert len(pending) == 3
    assert all(message["type"] == "image" for message in pending)
    assert "2021 Hyundai Creta SX" in pending[0]["content"]["caption"]


@pytest.mark.asyncio
async def test_customer_chat_returns_queued_media_messages(monkeypatch):
    async def fake_dispatch(msg):
        await queue_catalogue_result_media(msg.wa_id, [get_car_detail(11)])
        return "Here are some strong SUV options."

    monkeypatch.setattr("web_api.dispatch", fake_dispatch)

    response = await customer_chat(
        ChatRequest(
            customer_id="919876543210",
            customer_name="Ramesh Patil",
            message="Koi SUV hai 10 lakh ke under?",
            source="creta_reel_apr16",
        )
    )

    customer = await state.get_customer("919876543210")

    assert response["reply"] == "Here are some strong SUV options."
    assert len(response["messages"]) == 1
    assert response["messages"][0]["type"] == "image"
    assert customer is not None
    assert customer.source == "creta_reel_apr16"
