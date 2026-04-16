"""Helpers for dataset-driven eval tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dataset_path() -> Path:
    """Return the canonical utterance dataset path for this repo."""
    return Path(__file__).resolve().parents[3] / "data" / "user_question_dataset.json"


def load_dataset() -> dict[str, Any]:
    """Load the utterance dataset used for evals and manual testing."""
    path = dataset_path()
    return json.loads(path.read_text(encoding="utf-8"))


def intent_groups_by_id() -> dict[str, dict[str, Any]]:
    """Return intent groups keyed by dataset ID."""
    dataset = load_dataset()
    return {group["id"]: group for group in dataset["intent_groups"]}


def high_priority_demo_group_ids() -> list[str]:
    """Return the eval groups that directly map to the scripted demo flow."""
    return [
        "customer_budget_search",
        "customer_vehicle_comparison",
        "customer_negotiation_and_last_price",
        "customer_rejection_and_sales_recovery",
        "customer_manipulation_and_false_claims",
        "customer_prompt_injection_and_off_topic",
        "owner_oracle_stats_and_leads",
        "owner_mark_sold_reserved_hold",
    ]
