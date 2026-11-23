from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_1_3_101"
sys.path.insert(0, str(SOURCE))

from pigeon_poker.preflop_174_policy import (
    _HAND_INDEX, _actual_history, _choose_scenario, _position_map,
    _scenario_distribution, _scenarios, choose_preflop_174_action,
    preflop_174_catalog_summary, resolve_exact_preflop_174_scenario,
)


class FakePlayer:
    def __init__(self, player_id, name, cards=("As", "Ah")):
        self.player_id, self.name, self.hole_cards = player_id, name, cards
        self.position, self.stack = "", 10000


class FakeHand:
    def __init__(self, events, actor_id, cards=("As", "Ah"), legal=None):
        self.players = [
            FakePlayer("btn", "BTN"), FakePlayer("sb", "SB"),
            FakePlayer("bb", "BB"), FakePlayer("utg", "UTG"),
            FakePlayer("hj", "HJ"), FakePlayer("co", "CO"),
        ]
        self.seat_by_id = {p.player_id: i for i, p in enumerate(self.players)}
        next(p for p in self.players if p.player_id == actor_id).hole_cards = cards
        self.events, self.dealer_index, self.big_blind, self.street = events, 0, 100, "preflop"
        self._legal = legal or {
            "actions": ["raise", "call", "fold", "check", "all_in"],
            "to_call": 100, "raise_allowed": True, "min_target": 200, "max_target": 10000,
        }

    def player(self, player_id):
        return next(p for p in self.players if p.player_id == player_id)

    def legal_actions(self, player_id):
        return self._legal


class FakeTable:
    dealer_index = 0


class FakeCPU:
    def __init__(self, seed=5, level=1):
        self.rng = random.Random(seed)
        self.level = level
        self.archetype = "balanced"


def event(player_id, action, target=None):
    row = {"type": "action", "street": "preflop", "player_id": player_id, "action": action}
    if target is not None:
        row["target"] = target
    return row


def test_all_174_scenarios_and_169_hand_classes_are_loaded():
    summary = preflop_174_catalog_summary()
    assert summary["scenario_count"] == 174
    assert summary["hand_classes_per_scenario"] == 169
    assert summary["scenario_ids"] == list(range(128, 302))
    assert len(_HAND_INDEX) == 169
    assert all(len(item["hands"]) == 169 for item in _scenarios())


def test_source_action_frequencies_and_separate_sizes():
    for scenario in _scenarios():
        for row in scenario["hands"]:
            if row:
                assert abs(sum(float(freq) for _, freq in row) - 1.0) < 0.00002
        for action, size in scenario["action_options"]:
            if action == "raise":
                assert size is not None and float(size) > 0
    scenario = next(item for item in _scenarios() if item["id"] == 147)
    assert {float(size) for action, size in scenario["action_options"] if action == "raise"} == {3.0, 5.0}


def test_bb_vs_btn_open_matches_source_146_and_uses_13bb():
    events = [event("utg", "fold"), event("hj", "fold"), event("co", "fold"),
              event("btn", "raise", 250), event("sb", "fold")]
    hand = FakeHand(events, "bb", ("As", "Ah"), {
        "actions": ["raise", "call", "fold"], "to_call": 150,
        "raise_allowed": True, "min_target": 400, "max_target": 10000,
    })
    decision = choose_preflop_174_action(FakeTable(), hand, "bb", FakeCPU())
    assert decision.source == "preflop-174-scenario-policy"
    assert decision.source_image_no == 146
    assert decision.scenario_match_mode == "exact"
    assert decision.action == "raise" and decision.amount == 1300


def test_same_actor_multiple_actions_are_preserved():
    events = [event("utg", "raise", 200), event("sb", "raise", 1000),
              event("utg", "raise", 1900), event("sb", "raise", 4000),
              event("utg", "allin")]
    hand = FakeHand(events, "sb")
    history = _actual_history(FakeTable(), hand, "sb", _position_map(FakeTable(), hand))
    scenario, inferred, distance = _choose_scenario("SB", history, FakeCPU().rng)
    assert scenario["id"] == 180 and not inferred and distance == 0.0


def test_scenario_244_fullscreen_header_correction_matches_source_239():
    source = {int(item["id"]): item for item in _scenarios()}
    scenario_239 = source[239]
    scenario_244 = source[244]
    assert scenario_244["position"] == "BTN"
    assert scenario_244["history"] == scenario_239["history"]
    assert scenario_244["history"][-1]["position"] == "CO"
    assert scenario_244["history"][-1]["action"] == "fold"
    assert not any(
        str(item.get("action", "")).lower() == "allin"
        and str(item.get("position", "")).upper() == "CO"
        for item in scenario_244["history"]
    )


def test_scenarios_252_and_253_preserve_distinct_fullscreen_action_histories():
    by_id = {int(item["id"]): item for item in _scenarios()}
    history_252 = by_id[252]["history"]
    history_253 = by_id[253]["history"]
    assert by_id[252]["position"] == "BB"
    assert by_id[253]["position"] == "BB"
    assert [(e["position"], e["action"], e.get("size_bb")) for e in history_252] == [
        ("CO", "raise", 2.3),
        ("BTN", "raise", 7.5),
        ("SB", "fold", None),
        ("BB", "raise", 20.0),
        ("CO", "allin", 100.0),
        ("BTN", "fold", None),
    ]
    assert [(e["position"], e["action"], e.get("size_bb")) for e in history_253] == [
        ("CO", "raise", 2.3),
        ("BTN", "raise", 7.5),
        ("SB", "fold", None),
        ("BB", "raise", 20.0),
        ("CO", "fold", None),
        ("BTN", "allin", 100.0),
    ]
    assert history_252 != history_253
    assert by_id[252]["hands"] != by_id[253]["hands"]
    resolved_252 = resolve_exact_preflop_174_scenario("BB", list(history_252))
    resolved_253 = resolve_exact_preflop_174_scenario("BB", list(history_253))
    assert resolved_252 is not None and int(resolved_252["id"]) == 252
    assert resolved_253 is not None and int(resolved_253["id"]) == 253


def test_scenario_251_actor_is_btn():
    events = [event("co", "raise", 230), event("btn", "raise", 750),
              event("sb", "fold"), event("bb", "raise", 2000), event("co", "allin", 10000)]
    hand = FakeHand(events, "btn")
    history = _actual_history(FakeTable(), hand, "btn", _position_map(FakeTable(), hand))
    scenario, inferred, distance = _choose_scenario("BTN", history, FakeCPU().rng)
    assert scenario["id"] == 251 and not inferred and distance == 0.0


def test_exact_range_resolver_covers_all_174_histories_without_mixing_ranges():
    alias_groups = (
        (148, 288), (196, 205), (195, 204), (201, 211), (238, 243),
        (239, 244), (245, 251), (259, 263),
    )
    alias_pairs = {frozenset(group) for group in alias_groups}
    covered_ids = set()
    for source in _scenarios():
        source_id = int(source["id"])
        matched = resolve_exact_preflop_174_scenario(
            source["position"], list(source["history"])
        )
        if matched is None:
            candidates = [
                item for item in _scenarios()
                if item["position"] == source["position"]
                and len(item["history"]) == len(source["history"])
                and all(
                    str(want.get("position", "")).upper() == str(got.get("position", "")).upper()
                    and str(want.get("action", "")).lower() == str(got.get("action", "")).lower()
                    for want, got in zip(item["history"], source["history"])
                )
            ]
            print("UNRESOLVED 174 RANGE", source_id, source["history"],
                  "CANDIDATES", [(item["id"], item["history"]) for item in candidates])
        assert matched is not None, source_id
        assert matched["position"] == source["position"], source_id
        matched_id = int(matched["id"])
        if matched_id != source_id:
            assert frozenset((source_id, matched_id)) in alias_pairs, (
                source_id, matched_id
            )
            source_history = source["history"]
            matched_history = next(
                item["history"] for item in _scenarios()
                if int(item["id"]) == matched_id
            )
            assert source_history == matched_history, (source_id, matched_id)
        covered_ids.add(source_id)
    assert covered_ids == set(range(128, 302))


def test_identical_image_aliases_never_merge_different_action_histories():
    alias_groups = (
        (148, 288), (196, 205), (195, 204), (201, 211), (238, 243),
        (239, 244), (245, 251), (259, 263),
    )
    by_id = {int(item["id"]): item for item in _scenarios()}
    for first_id, second_id in alias_groups:
        first, second = by_id[first_id], by_id[second_id]
        first_match = resolve_exact_preflop_174_scenario(
            first["position"], list(first["history"])
        )
        second_match = resolve_exact_preflop_174_scenario(
            second["position"], list(second["history"])
        )
        assert first_match is not None and second_match is not None
        if first["history"] == second["history"]:
            assert int(first_match["id"]) == int(second_match["id"]) == min(
                first_id, second_id
            )
        else:
            assert int(first_match["id"]) == first_id
            assert int(second_match["id"]) == second_id


def test_exact_range_resolver_rejects_unlisted_or_size_mismatched_histories():
    source = next(item for item in _scenarios() if item["id"] == 146)
    wrong = [dict(item) for item in source["history"]]
    raise_event = next(item for item in wrong if item["action"] == "raise")
    raise_event["size_bb"] = float(raise_event["size_bb"]) + 0.5
    assert resolve_exact_preflop_174_scenario(source["position"], wrong) is None

    extra_action = [dict(item) for item in source["history"]]
    extra_action.append({"position": "UTG", "action": "fold", "size_bb": None})
    assert resolve_exact_preflop_174_scenario(source["position"], extra_action) is None
    assert resolve_exact_preflop_174_scenario("UNKNOWN", list(source["history"])) is None


def test_unclassified_cell_is_inferred_not_folded():
    scenario = next(item for item in _scenarios() if item["id"] == 153)
    distribution, inferred, method = _scenario_distribution(scenario, "K4s")
    assert inferred and method == "same-scenario-hand-neighbours"
    assert distribution and sum(distribution.values()) > 0.999


def test_preflop_policy_is_cpu_level_independent():
    source = (SOURCE / "pigeon_poker" / "preflop_174_policy.py").read_text(encoding="utf-8")
    assert "cpu.level" not in source and "cpu.archetype" not in source


if __name__ == "__main__":
    tests = [
        test_all_174_scenarios_and_169_hand_classes_are_loaded,
        test_source_action_frequencies_and_separate_sizes,
        test_bb_vs_btn_open_matches_source_146_and_uses_13bb,
        test_same_actor_multiple_actions_are_preserved,
        test_scenario_251_actor_is_btn,
        test_scenarios_252_and_253_preserve_distinct_fullscreen_action_histories,
        test_scenario_244_fullscreen_header_correction_matches_source_239,
        test_unclassified_cell_is_inferred_not_folded,
        test_exact_range_resolver_covers_all_174_histories_without_mixing_ranges,
        test_identical_image_aliases_never_merge_different_action_histories,
        test_exact_range_resolver_rejects_unlisted_or_size_mismatched_histories,
        test_preflop_policy_is_cpu_level_independent,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174-scenario preflop policy tests")
