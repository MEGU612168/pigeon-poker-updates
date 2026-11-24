from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

from pigeon_poker.preflop_174_policy import (  # noqa: E402
    _scenarios,
    find_exact_preflop_174_scenario,
)


def _history(scenario: dict) -> list[dict]:
    return [
        {
            "position": item["position"],
            "action": item["action"],
            "size_bb": item.get("size_bb"),
        }
        for item in scenario.get("history", [])
    ]


def test_catalog_still_contains_exactly_174_source_scenarios():
    scenarios = _scenarios()
    assert len(scenarios) == 174
    assert {int(item["id"]) for item in scenarios} == set(range(128, 302))


def test_paid_range_lookup_never_uses_nearest_node_inference():
    assert find_exact_preflop_174_scenario("UTG", []) is None
    assert find_exact_preflop_174_scenario("UNKNOWN", []) is None
    assert find_exact_preflop_174_scenario("CO", [
        {"position": "UTG", "action": "raise", "size_bb": 99.0}
    ]) is None


def test_missing_raise_sizes_do_not_create_false_exact_matches():
    for scenario in _scenarios():
        history = _history(scenario)
        if any(item["action"] == "raise" and item.get("size_bb") is None
               for item in history):
            assert find_exact_preflop_174_scenario(scenario["position"], history) is None


def test_changed_raise_size_is_not_treated_as_the_original_situation():
    candidate = next(
        scenario for scenario in _scenarios()
        if any(item["action"] == "raise" and item.get("size_bb") is not None
               for item in scenario.get("history", []))
    )
    history = _history(candidate)
    index = next(i for i, item in enumerate(history)
                 if item["action"] == "raise" and item.get("size_bb") is not None)
    history[index]["size_bb"] = float(history[index]["size_bb"]) + 5.0
    assert find_exact_preflop_174_scenario(candidate["position"], history) is None


def test_allin_without_target_size_is_still_an_exact_action_class():
    scenario = next(
        scenario for scenario in _scenarios()
        if any(item.get("action") == "allin" and item.get("size_bb") is None
               for item in scenario.get("history", []))
    )
    history = _history(scenario)
    assert find_exact_preflop_174_scenario(scenario["position"], history) == int(scenario["id"])


def test_key_source_situations_146_and_147_keep_their_own_image_ids():
    by_id = {int(item["id"]): item for item in _scenarios()}
    for source_id in (146, 147):
        scenario = by_id[source_id]
        assert find_exact_preflop_174_scenario(
            scenario["position"], _history(scenario)
        ) == source_id


def test_all_unambiguous_fully_sized_histories_resolve_to_their_source_id():
    keyed = {}
    for scenario in _scenarios():
        history = _history(scenario)
        if any(item["action"] == "raise" and item.get("size_bb") is None
               for item in history):
            continue
        key = (scenario["position"], tuple(
            (x["position"], x["action"], x.get("size_bb")) for x in history
        ))
        keyed.setdefault(key, []).append(int(scenario["id"]))
    for (position, history_key), ids in keyed.items():
        history = [
            {"position": p, "action": a, "size_bb": size}
            for p, a, size in history_key
        ]
        result = find_exact_preflop_174_scenario(position, history)
        if len(ids) == 1:
            assert result == ids[0]
        else:
            assert result is None


def run_tests():
    tests = [
        test_catalog_still_contains_exactly_174_source_scenarios,
        test_paid_range_lookup_never_uses_nearest_node_inference,
        test_missing_raise_sizes_do_not_create_false_exact_matches,
        test_changed_raise_size_is_not_treated_as_the_original_situation,
        test_allin_without_target_size_is_still_an_exact_action_class,
        test_key_source_situations_146_and_147_keep_their_own_image_ids,
        test_all_unambiguous_fully_sized_histories_resolve_to_their_source_id,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174-range lookup tests")
