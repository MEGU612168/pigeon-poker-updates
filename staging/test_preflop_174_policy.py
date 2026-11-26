from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_1_3_101"
sys.path.insert(0, str(SOURCE))

from pigeon_poker.preflop_174_policy import (
    _HAND_INDEX, _HAND_ORDER, _actual_history, _choose_scenario, _filter_first_in_distribution, _position_map,
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
        self.next_to_act = actor_id
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
    assert 0 < summary["unique_action_history_count"] <= 174
    assert "duplicate_action_history_groups" in summary
    assert "unique_169_cell_strategy_matrix_count" in summary
    assert "ambiguous_duplicate_history_groups" in summary
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


def test_unmeasured_cell_is_not_fabricated_from_neighbouring_hands():
    scenario = next(item for item in _scenarios() if item["id"] == 153)
    distribution, inferred, method = _scenario_distribution(scenario, "K4s")
    assert inferred and method == "unmeasured-image-cell"
    assert distribution == {}



def test_unmatched_preflop_history_never_borrows_a_nearest_chart():
    import math
    scenario, inferred, distance = _choose_scenario(
        "CO", [event("utg", "raise", 7700)], FakeCPU().rng
    )
    assert scenario is None
    assert inferred
    assert math.isinf(distance)

    hand = FakeHand([event("utg", "raise", 7700)], "co", ("As", "Ah"))
    decision = choose_preflop_174_action(FakeTable(), hand, "co", FakeCPU())
    assert decision.source == "preflop-uncovered-legal-guardrail"
    assert decision.source_image_no is None
    assert decision.node_id == "UNMAPPED_PREFLOP_HISTORY"


def test_paid_raise_size_menu_is_hidden_for_unmatched_history():
    hand = FakeHand([event("utg", "raise", 7700)], "co", ("As", "Ah"))
    assert preflop_174_raise_size_options(FakeTable(), hand, "co") is None

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



def test_only_a_folded_to_me_prefix_matches_the_empty_first_in_chart():
    # A live BTN turn contains the UTG/HJ/CO folds. The 174 BTN RFI source
    # records those folds implicitly as an empty history.
    events = [event("utg", "fold"), event("hj", "fold"), event("co", "fold")]
    hand = FakeHand(events, "btn")
    history = _actual_history(FakeTable(), hand, "btn", _position_map(FakeTable(), hand))
    assert history == []
    scenario, inferred, distance = _choose_scenario("BTN", history, FakeCPU().rng)
    assert scenario["id"] == 131
    assert not inferred and distance == 0.0

    # A fold-only HJ prefix must resolve the HJ first-in node as well.
    hj_hand = FakeHand([event("utg", "fold")], "hj")
    hj_history = _actual_history(
        FakeTable(), hj_hand, "hj", _position_map(FakeTable(), hj_hand)
    )
    assert hj_history == []
    hj_scenario, inferred, distance = _choose_scenario("HJ", hj_history, FakeCPU().rng)
    assert hj_scenario["id"] == 129
    assert not inferred and distance == 0.0


def test_hj_first_in_cannot_limp_and_btn_first_in_uses_25bb_open():
    hj_hand = FakeHand([event("utg", "fold")], "hj")
    hj_decision = choose_preflop_174_action(FakeTable(), hj_hand, "hj", FakeCPU(seed=2))
    assert hj_decision.source_image_no == 129
    assert hj_decision.scenario_match_mode == "exact"
    assert hj_decision.action != "call"
    if hj_decision.action == "raise":
        assert hj_decision.amount == 200

    btn_hand = FakeHand(
        [event("utg", "fold"), event("hj", "fold"), event("co", "fold")],
        "btn",
    )
    btn_decision = choose_preflop_174_action(FakeTable(), btn_hand, "btn", FakeCPU(seed=2))
    assert btn_decision.source_image_no == 131
    assert btn_decision.scenario_match_mode == "exact"
    assert btn_decision.action != "call"
    if btn_decision.action == "raise":
        assert btn_decision.amount == 250


def test_first_in_guardrail_removes_open_limp_and_oversized_raise_in_inferred_nodes():
    distribution = {
        ("raise", 2.5): 0.50,
        ("raise", 27.0): 0.20,
        ("call", None): 0.20,
        ("fold", None): 0.10,
    }
    for position in ("UTG", "HJ", "CO", "BTN"):
        safe = _filter_first_in_distribution(position, [], distribution)
        assert safe == {
            ("raise", 2.5): 0.50,
            ("fold", None): 0.10,
        }
    # SB completion is an explicit action in source scenario #132.
    sb_safe = _filter_first_in_distribution("SB", [], distribution)
    assert ("call", None) in sb_safe


def _cards_for_hand_class(hand_class):
    ranks = "AKQJT98765432"
    if len(hand_class) == 2:
        return (hand_class[0] + "s", hand_class[1] + "h")
    high, low, suited = hand_class[0], hand_class[1], hand_class[2]
    return (high + "s", low + ("s" if suited == "s" else "h"))


def test_first_in_raise_size_controls_match_exact_hj_and_btn_scenarios():
    hj_hand = FakeHand([event("utg", "fold")], "hj")
    hj_result = preflop_174_raise_size_options(FakeTable(), hj_hand, "hj")
    assert hj_result is not None
    assert hj_result["scenario_id"] == 129
    assert hj_result["scenario_match_mode"] == "exact"
    assert {item["size_bb"] for item in hj_result["choices"]} == {2.0}
    assert all(item["enabled_for_hand"] for item in hj_result["choices"])

    btn_hand = FakeHand(
        [event("utg", "fold"), event("hj", "fold"), event("co", "fold")],
        "btn",
    )
    btn_result = preflop_174_raise_size_options(FakeTable(), btn_hand, "btn")
    assert btn_result is not None
    assert btn_result["scenario_id"] == 131
    assert btn_result["scenario_match_mode"] == "exact"
    assert {item["size_bb"] for item in btn_result["choices"]} == {2.5}
    assert all(item["enabled_for_hand"] for item in btn_result["choices"])


def test_situation_size_stays_visible_but_disabled_when_current_hand_never_raises():
    scenario = next(item for item in _scenarios() if int(item["id"]) == 131)
    hand_class = None
    for index, row in enumerate(scenario["hands"]):
        if not row:
            continue
        has_raise = any(
            str(scenario["action_options"][int(option_index)][0]).lower() == "raise"
            and float(frequency) > 0
            for option_index, frequency in row
        )
        if not has_raise:
            hand_class = _HAND_ORDER[index]
            break
    assert hand_class is not None

    hand = FakeHand(
        [event("utg", "fold"), event("hj", "fold"), event("co", "fold")],
        "btn",
        _cards_for_hand_class(hand_class),
    )
    result = preflop_174_raise_size_options(FakeTable(), hand, "btn")
    assert result is not None
    assert result["scenario_id"] == 131
    assert {item["size_bb"] for item in result["choices"]} == {2.5}
    assert all(item["frequency"] == 0.0 for item in result["choices"])
    assert all(not item["enabled_for_hand"] for item in result["choices"])



if __name__ == "__main__":
    tests = [
        test_all_174_scenarios_and_169_hand_classes_are_loaded,
        test_source_action_frequencies_and_separate_sizes,
        test_bb_vs_btn_open_matches_source_146_and_uses_13bb,
        test_same_actor_multiple_actions_are_preserved,
        test_scenario_251_actor_is_btn,
        test_unmeasured_cell_is_not_fabricated_from_neighbouring_hands,
        test_unmatched_preflop_history_never_borrows_a_nearest_chart,
        test_paid_raise_size_menu_is_hidden_for_unmatched_history,
        test_hero_raise_size_options_match_the_174_scenario_and_stay_legal,
        test_hero_raise_size_options_are_not_offered_outside_preflop_or_out_of_turn,
        test_preflop_policy_is_cpu_level_independent,
        test_only_a_folded_to_me_prefix_matches_the_empty_first_in_chart,
        test_hj_first_in_cannot_limp_and_btn_first_in_uses_25bb_open,
        test_first_in_guardrail_removes_open_limp_and_oversized_raise_in_inferred_nodes,
        test_first_in_raise_size_controls_match_exact_hj_and_btn_scenarios,
        test_situation_size_stays_visible_but_disabled_when_current_hand_never_raises,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174-scenario preflop policy tests")
