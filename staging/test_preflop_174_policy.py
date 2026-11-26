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
    preflop_174_catalog_summary, preflop_174_raise_size_options,
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


def test_scenario_251_actor_is_btn():
    events = [event("co", "raise", 230), event("btn", "raise", 750),
              event("sb", "fold"), event("bb", "raise", 2000), event("co", "allin", 10000)]
    hand = FakeHand(events, "btn")
    history = _actual_history(FakeTable(), hand, "btn", _position_map(FakeTable(), hand))
    scenario, inferred, distance = _choose_scenario("BTN", history, FakeCPU().rng)
    assert scenario["id"] == 251 and not inferred and distance == 0.0


def test_unclassified_cell_is_inferred_not_folded():
    scenario = next(item for item in _scenarios() if item["id"] == 153)
    distribution, inferred, method = _scenario_distribution(scenario, "K4s")
    assert inferred and method == "same-scenario-hand-neighbours"
    assert distribution and sum(distribution.values()) > 0.999


def test_hero_raise_size_options_match_the_174_scenario_and_stay_legal():
    events = [event("utg", "fold"), event("hj", "fold"), event("co", "fold"),
              event("btn", "raise", 250), event("sb", "fold")]
    hand = FakeHand(events, "bb", ("As", "Ah"), {
        "actions": ["raise", "call", "fold"], "to_call": 150,
        "raise_allowed": True, "min_target": 400, "max_target": 10000,
    })
    hand.next_to_act = "bb"
    result = preflop_174_raise_size_options(FakeTable(), hand, "bb")
    assert result is not None
    assert result["scenario_id"] == 146
    assert result["scenario_match_mode"] == "exact"
    assert result["hand_class"] == "AA"
    assert result["choices"]
    assert all(400 <= choice["amount"] <= 10000 for choice in result["choices"])
    assert {choice["size_bb"] for choice in result["choices"]} == {13.0}
    assert {choice["amount"] for choice in result["choices"]} == {1300}


def test_hero_raise_size_options_are_not_offered_outside_preflop_or_out_of_turn():
    events = [event("utg", "fold"), event("hj", "fold"), event("co", "fold"),
              event("btn", "raise", 250), event("sb", "fold")]
    hand = FakeHand(events, "bb", ("As", "Ah"))
    hand.next_to_act = "bb"
    hand.street = "flop"
    assert preflop_174_raise_size_options(FakeTable(), hand, "bb") is None
    hand.street = "preflop"
    hand.next_to_act = "btn"
    assert preflop_174_raise_size_options(FakeTable(), hand, "bb") is None



def test_preflop_policy_is_cpu_level_independent():
    source = (SOURCE / "pigeon_poker" / "preflop_174_policy.py").read_text(encoding="utf-8")
    assert "cpu.level" not in source and "cpu.archetype" not in source


def test_print_first_in_174_source_action_audit():
    # Diagnostic against the authoritative 174 source matrix, not assumptions
    # from UI defaults. First-in means the prior action history has no voluntary
    # call/raise/all-in; blind checks/folds are not first-in limps.
    for position in ("UTG", "HJ", "CO", "BTN", "SB", "BB"):
        for scenario in _scenarios():
            if scenario["position"] != position:
                continue
            history = scenario.get("history", [])
            if any(item.get("action") in {"call", "raise", "allin"}
                   for item in history):
                continue
            used = {int(option_index) for row in scenario["hands"] for option_index, freq in row if float(freq) > 0}
            options = [
                (str(action), None if size is None else float(size))
                for index, (action, size) in enumerate(scenario["action_options"])
                if index in used
            ]
            raises = sorted({size for action, size in options if action == "raise"})
            calls = [item for item in options if item[0] == "call"]
            print(
                "FIRST_IN_AUDIT",
                "id=", scenario["id"],
                "position=", position,
                "history=", [(x.get("position"), x.get("action"), x.get("size_bb")) for x in history],
                "raise_sizes=", raises,
                "has_call=", bool(calls),
                "options=", options,
                "overall=", scenario.get("overall", []),
            )



if __name__ == "__main__":
    tests = [
        test_all_174_scenarios_and_169_hand_classes_are_loaded,
        test_source_action_frequencies_and_separate_sizes,
        test_bb_vs_btn_open_matches_source_146_and_uses_13bb,
        test_same_actor_multiple_actions_are_preserved,
        test_scenario_251_actor_is_btn,
        test_unclassified_cell_is_inferred_not_folded,
        test_hero_raise_size_options_match_the_174_scenario_and_stay_legal,
        test_hero_raise_size_options_are_not_offered_outside_preflop_or_out_of_turn,
        test_preflop_policy_is_cpu_level_independent,
        test_print_first_in_174_source_action_audit,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174-scenario preflop policy tests")
