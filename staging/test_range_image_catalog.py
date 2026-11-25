from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

from pigeon_poker.preflop_174_policy import (  # noqa: E402
    _scenarios,
    _strict_range_history_matches,
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
    assert find_exact_preflop_174_scenario("UNKNOWN", []) is None
    # An impossible raise size must not be treated as a nearest-node match,
    # even if UTG has a legitimate empty-history source node.
    assert find_exact_preflop_174_scenario("UTG", [
        {"position": "UTG", "action": "raise", "size_bb": 9999.0}
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
        if (
            any(item.get("action") == "allin" and item.get("size_bb") is None
                for item in scenario.get("history", []))
            and not any(item.get("action") == "raise" and item.get("size_bb") is None
                        for item in scenario.get("history", []))
        )
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
        test_all_174_live_histories_resolve_to_their_own_paid_image,
        test_live_range_signature_invalidates_when_eligibility_or_history_changes,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174-range lookup tests")


class _LivePlayer:
    def __init__(self, player_id: str, position: str):
        self.player_id = player_id
        self.position = position


class _LiveHand:
    def __init__(self, events, next_to_act: str):
        # dealer_index=0 and this seat order give the six standard positions.
        self.players = [
            _LivePlayer("btn", "BTN"),
            _LivePlayer("sb", "SB"),
            _LivePlayer("bb", "BB"),
            _LivePlayer("utg", "UTG"),
            _LivePlayer("hj", "HJ"),
            _LivePlayer("co", "CO"),
        ]
        self.seat_by_id = {player.player_id: index for index, player in enumerate(self.players)}
        self.events = events
        self.next_to_act = next_to_act
        self.street = "preflop"
        self.finished = False
        self.big_blind = 100
        self.dealer_index = 0


class _LiveTable:
    dealer_index = 0


def _live_fixture_for_scenario(scenario: dict):
    from pigeon_poker.preflop_174_policy import POSITION_BY_SEAT_FROM_BUTTON

    player_by_position = {
        position: player_id
        for position, player_id in zip(
            POSITION_BY_SEAT_FROM_BUTTON,
            ("btn", "sb", "bb", "utg", "hj", "co"),
        )
    }
    events = []
    for item in scenario.get("history", []):
        action = str(item["action"]).lower()
        event = {
            "type": "action",
            "street": "preflop",
            "player_id": player_by_position[item["position"]],
            "player": player_by_position[item["position"]],
            "action": action,
        }
        if action == "raise":
            event["target"] = round(float(item["size_bb"]) * 100)
        events.append(event)
    actor_id = player_by_position[scenario["position"]]
    return _LiveTable(), _LiveHand(events, actor_id), actor_id


def test_all_174_live_histories_resolve_to_their_own_paid_image():
    from pigeon_poker.range_image_catalog import resolve_range_image_for_hand, range_image_png

    failures = []
    for scenario in _scenarios():
        table, hand, actor_id = _live_fixture_for_scenario(scenario)
        chart = resolve_range_image_for_hand(table, hand, actor_id)
        expected_id = int(scenario["id"])
        actual_id = int(chart["source_id"]) if chart else None
        if actual_id != expected_id:
            history = _history(scenario)
            candidates = [
                item for item in _scenarios()
                if item["position"] == scenario["position"]
                and _strict_range_history_matches(item.get("history", []), history)
            ]
            metadata = {
                key: value for key, value in scenario.items()
                if key not in {"hands", "history", "overall"}
            }
            candidate_details = []
            for item in candidates:
                matrix = json.dumps(item.get("hands", []), ensure_ascii=False, separators=(",", ":"))
                candidate_details.append({
                    "id": int(item["id"]),
                    "metadata": {
                        key: value for key, value in item.items()
                        if key not in {"hands", "history", "overall"}
                    },
                    "overall": item.get("overall"),
                    "matrix_sha256": hashlib.sha256(matrix.encode("utf-8")).hexdigest(),
                    "image_sha256": hashlib.sha256(range_image_png(int(item["id"]))).hexdigest(),
                })
            failures.append({
                "expected_id": expected_id,
                "actor": scenario["position"],
                "history": scenario.get("history", []),
                "actual_id": actual_id,
                "candidate_ids": [int(item["id"]) for item in candidates],
                "metadata": metadata,
                "candidate_details": candidate_details,
            })
    assert not failures, f"{len(failures)} / 174 live histories failed paid image resolution: {failures[:8]}"


def test_live_range_signature_invalidates_when_eligibility_or_history_changes():
    from pigeon_poker.range_image_catalog import live_range_lookup_signature

    table, hand, _actor_id = _live_fixture_for_scenario(_scenarios()[18])
    busy = live_range_lookup_signature(
        hand, current_hand_key="T:1", cash_deal_busy=True,
        dealer_index=table.dealer_index,
    )
    ready = live_range_lookup_signature(
        hand, current_hand_key="T:1", cash_deal_busy=False,
        dealer_index=table.dealer_index,
    )
    assert busy != ready

    before = live_range_lookup_signature(
        hand, current_hand_key="T:1", dealer_index=table.dealer_index,
    )
    # Changing an existing raise target without changing event count must
    # invalidate the cached image lookup too.
    raise_event = next((event for event in hand.events if event.get("action") == "raise"), None)
    if raise_event is not None:
        raise_event["target"] = int(raise_event["target"]) + 25
        after = live_range_lookup_signature(
            hand, current_hand_key="T:1", dealer_index=table.dealer_index,
        )
        assert before != after




if __name__ == "__main__":
    run_tests()
