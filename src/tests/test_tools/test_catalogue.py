"""Catalogue tool tests — 8 scenarios."""

import json

import pytest

from agents.tools.catalogue import (
    tool_check_availability,
    tool_compare_items,
    tool_get_item_details,
    tool_get_pricing_info,
    tool_mark_sold,
    tool_search_catalogue,
)


def _parse(result: str) -> dict:
    return json.loads(result)


def test_search_with_price_filter():
    result = _parse(tool_search_catalogue(max_price=5.0))
    assert result["success"] is True
    for car in result["data"]:
        assert car["price_lakhs"] <= 5.0
    assert len(result["data"]) <= 5


def test_search_no_filters_returns_max_5():
    result = _parse(tool_search_catalogue())
    assert result["success"] is True
    assert len(result["data"]) <= 5


def test_search_by_make():
    result = _parse(tool_search_catalogue(make="Tata"))
    assert result["success"] is True
    for car in result["data"]:
        assert "Tata" in car["name"]


def test_get_item_details_valid():
    result = _parse(tool_get_item_details(1))
    assert result["success"] is True
    assert result["data"]["id"] == 1


def test_get_item_details_invalid():
    result = _parse(tool_get_item_details(9999))
    assert result["success"] is False


def test_compare_items():
    result = _parse(tool_compare_items(1, 2))
    assert result["success"] is True
    assert "car_1" in result["data"]
    assert "car_2" in result["data"]


def test_mark_sold_and_check():
    # Find a car that's available
    search = _parse(tool_search_catalogue())
    if search["data"]:
        car_id = search["data"][0]["id"]
        sold = _parse(tool_mark_sold(car_id))
        assert sold["success"] is True

        avail = _parse(tool_check_availability(car_id))
        assert avail["data"]["status"] == "sold"


def test_pricing_info():
    result = _parse(tool_get_pricing_info(1))
    assert result["success"] is True
    assert "emi_options" in result["data"]
    assert len(result["data"]["emi_options"]) > 0
