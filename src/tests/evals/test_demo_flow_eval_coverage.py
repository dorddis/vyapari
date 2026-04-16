"""Ensure the demo script is backed by explicit eval coverage."""

from __future__ import annotations

from tests.evals.helpers import high_priority_demo_group_ids, intent_groups_by_id


DEMO_FLOW_EXPECTED_PRIORITIES = {
    "customer_budget_search": "P0",
    "customer_vehicle_comparison": "P0",
    "customer_negotiation_and_last_price": "P0",
    "customer_rejection_and_sales_recovery": "P1",
    "customer_manipulation_and_false_claims": "P0",
    "customer_prompt_injection_and_off_topic": "P0",
    "owner_oracle_stats_and_leads": "P0",
    "owner_mark_sold_reserved_hold": "P0",
}


def test_demo_flow_has_dataset_backing_for_all_showpiece_features() -> None:
    groups = intent_groups_by_id()

    for group_id in high_priority_demo_group_ids():
        assert group_id in groups, f"Missing eval coverage for {group_id}"


def test_demo_flow_groups_have_sufficient_utterance_depth() -> None:
    groups = intent_groups_by_id()

    for group_id in high_priority_demo_group_ids():
        assert len(groups[group_id]["utterances"]) >= 6


def test_demo_flow_groups_match_expected_priorities() -> None:
    groups = intent_groups_by_id()

    for group_id, expected_priority in DEMO_FLOW_EXPECTED_PRIORITIES.items():
        assert groups[group_id]["priority"] == expected_priority


def test_demo_flow_acts_cover_customer_and_owner_paths() -> None:
    groups = intent_groups_by_id()
    roles = {groups[group_id]["role"] for group_id in high_priority_demo_group_ids()}

    assert roles == {"customer", "owner"}
