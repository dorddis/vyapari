"""Dataset contract tests from TESTING.md section 12."""

import json
from pathlib import Path


DATASET_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "user_question_dataset.json"
)


def _load_dataset() -> dict:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_dataset_01_top_level_schema_sanity():
    """DATASET-01: File parses and required top-level keys exist."""
    assert DATASET_PATH.exists(), f"Dataset file missing: {DATASET_PATH}"

    dataset = _load_dataset()
    required_keys = {
        "dealer",
        "vertical",
        "purpose",
        "languages",
        "intent_groups",
    }
    assert required_keys.issubset(set(dataset.keys()))
    assert isinstance(dataset["intent_groups"], list)
    assert len(dataset["intent_groups"]) > 0


def test_dataset_02_intent_group_schema_sanity():
    """DATASET-02: Every intent group has required non-empty fields."""
    dataset = _load_dataset()
    required_fields = {
        "id",
        "role",
        "category",
        "priority",
        "expected_route",
        "expected_behavior",
        "utterances",
    }

    seen_ids: set[str] = set()
    for group in dataset["intent_groups"]:
        assert required_fields.issubset(set(group.keys()))

        group_id = str(group["id"]).strip()
        assert group_id
        assert group_id not in seen_ids
        seen_ids.add(group_id)

        assert group["role"] in {"customer", "owner"}
        assert group["priority"] in {"P0", "P1"}
        assert str(group["category"]).strip()
        assert str(group["expected_route"]).strip()
        assert str(group["expected_behavior"]).strip()


def test_dataset_03_utterance_coverage_non_empty():
    """DATASET-03: No empty utterance groups and no blank utterances."""
    dataset = _load_dataset()
    for group in dataset["intent_groups"]:
        utterances = group["utterances"]
        assert isinstance(utterances, list)
        assert len(utterances) > 0
        assert all(isinstance(u, str) and u.strip() for u in utterances)


def test_dataset_high_priority_groups_present():
    """TESTING.md 12.6: High-priority subset should exist in the dataset."""
    dataset = _load_dataset()
    group_ids = {group["id"] for group in dataset["intent_groups"]}

    high_priority_subset = {
        "customer_greeting_openers",
        "customer_budget_search",
        "customer_segment_and_constraints",
        "customer_brand_model_search",
        "customer_specific_vehicle_details",
        "customer_vehicle_comparison",
        "customer_negotiation_and_last_price",
        "customer_test_drive_visit_location_hours",
        "customer_human_handoff_requests",
        "customer_frustration_and_repetition",
        "customer_manipulation_and_false_claims",
        "customer_prompt_injection_and_off_topic",
        "owner_mark_sold_reserved_hold",
        "owner_oracle_stats_and_leads",
        "owner_escalation_and_hijack",
    }

    missing = high_priority_subset - group_ids
    assert not missing, f"Missing high-priority intent groups: {sorted(missing)}"
