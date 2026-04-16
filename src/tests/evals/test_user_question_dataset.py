"""Schema and coverage tests for the utterance dataset."""

from __future__ import annotations

from tests.evals.helpers import dataset_path, intent_groups_by_id, load_dataset


REQUIRED_TOP_LEVEL_KEYS = {
    "dealer",
    "vertical",
    "purpose",
    "exhaustiveness_scope",
    "languages",
    "intent_groups",
}

REQUIRED_GROUP_KEYS = {
    "id",
    "role",
    "category",
    "priority",
    "expected_route",
    "expected_behavior",
    "utterances",
}


def test_dataset_file_exists() -> None:
    assert dataset_path().exists()


def test_dataset_top_level_schema() -> None:
    dataset = load_dataset()

    assert REQUIRED_TOP_LEVEL_KEYS.issubset(dataset.keys())
    assert dataset["dealer"] == "Sharma Motors"
    assert dataset["vertical"] == "used_car_dealership"
    assert "evals" in dataset["purpose"]
    assert set(dataset["languages"]) >= {"english", "hinglish", "romanized_hindi"}
    assert dataset["intent_groups"]


def test_all_intent_groups_have_required_fields() -> None:
    dataset = load_dataset()

    seen_ids: set[str] = set()
    for group in dataset["intent_groups"]:
        assert REQUIRED_GROUP_KEYS.issubset(group.keys())
        assert group["id"] not in seen_ids
        assert group["role"] in {"customer", "owner"}
        assert group["priority"] in {"P0", "P1"}
        assert group["expected_route"]
        assert group["expected_behavior"]
        assert isinstance(group["utterances"], list)
        assert len(group["utterances"]) >= 4
        assert all(isinstance(utt, str) and utt.strip() for utt in group["utterances"])
        seen_ids.add(group["id"])


def test_dataset_covers_both_customer_and_owner_paths() -> None:
    groups = load_dataset()["intent_groups"]
    roles = {group["role"] for group in groups}
    priorities = {group["priority"] for group in groups}

    assert roles == {"customer", "owner"}
    assert priorities >= {"P0", "P1"}


def test_high_risk_guardrail_groups_exist() -> None:
    groups = intent_groups_by_id()

    for group_id in (
        "customer_negotiation_and_last_price",
        "customer_human_handoff_requests",
        "customer_frustration_and_repetition",
        "customer_manipulation_and_false_claims",
        "customer_prompt_injection_and_off_topic",
        "owner_mark_sold_reserved_hold",
        "owner_escalation_and_hijack",
    ):
        assert group_id in groups

