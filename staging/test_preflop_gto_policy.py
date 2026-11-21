from __future__ import annotations

import random
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "source_1_3_101"
sys.path.insert(0, str(SOURCE))

from pigeon_poker import preflop_gto_strategy as policy
from test_preflop_gto_integrity import (
    test_all_screenshot_nodes_contain_a_complete_169_hand_matrix,
    test_every_screenshot_raise_size_has_a_combo_weighted_modal_result,
    test_gto_size_lookup_is_position_and_history_only_not_hole_card_dependent,
    test_only_the_new_policy_is_the_runtime_preflop_source,
)


class FakePlayer:
    def __init__(self, player_id, position, cards=("As", "Kd"), stack=10000):
        self.player_id = player_id
        self.position = position
        self.hole_cards = tuple(cards)
        self.stack = stack
        self.street_contribution = 0
        self.eligible = True
        self.name = player_id


class FakeHand:
    def __init__(self, events=None, holecards=None, legal=None, stacks=None):
        self.dealer_index = 0
        self.big_blind = 100
        self.pot = 150
        self.current_bet = 100
        self.street = "preflop"
        self.board = ()
        self.events = list(events or [])
        holecards = holecards or {}
        stacks = stacks or {}
        # With dealer index 0, seats clockwise are BTN, SB, BB, UTG, HJ, CO.
        positions = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
        self.players = [
            FakePlayer("p" + pos, pos, holecards.get(pos, ("As", "Kd")),
                       stacks.get(pos, 10000))
            for pos in positions
        ]
        self.seat_by_id = {p.player_id: i for i, p in enumerate(self.players)}
        self._legal = legal or {}

    def player(self, player_id):
        return next(p for p in self.players if p.player_id == player_id)

    def legal_actions(self, player_id):
        return dict(self._legal.get(player_id, {
            "actions": ["fold", "call", "check", "raise", "all_in"],
            "to_call": 100,
            "raise_allowed": True,
            "min_target": 200,
            "max_target": 10000,
        }))


class FakeTable:
    dealer_index = 0


class FakeCPU:
    def __init__(self, seed=7):
        self.level = 5
        self.archetype = "balanced"
        self.rng = random.Random(seed)


def action(player, name, target_bb=None):
    event = {
        "type": "action",
        "street": "preflop",
        "player_id": "p" + player,
        "action": name,
    }
    if target_bb is not None:
        event["target"] = int(round(target_bb * 100))
        event["amount"] = int(round(target_bb * 100))
    return event


def legal_for(actor, *, to_call=100, min_target=200, max_target=10000,
              actions=("fold", "call", "check", "raise", "all_in")):
    return {
        "p" + actor: {
            "actions": list(actions), "to_call": to_call,
            "raise_allowed": "raise" in actions or "bet" in actions,
            "min_target": min_target, "max_target": max_target,
        }
    }


def _test_schema2_screenshot_policy_metadata():
    summary = policy.coverage_summary()
    assert summary["schema"] == 2
    assert summary["exact_screenshot_nodes"] >= 27
    assert summary["archive_screenshots"] == 174
    assert summary["fixed_2_5bb_opening"] is False
    data = policy._data()
    assert data["schema"] == 2

    staging = Path(__file__).resolve().parent
    current_package = staging / "source_1_3_101" / "pigeon_poker"
    assert not (current_package / "preflop_screenshot_ranges.py").exists()
    assert not (staging / "preflop_screenshot_ranges_75.py").exists()
    assert not (staging / "preflop_range_policy.py").exists()
    assert not (staging / "preflop_range_data.py").exists()
    assert not hasattr(policy, "_supports_100bb_effective_stack")
    # No legacy implementation may remain in any archived source snapshot.
    assert not list(staging.rglob("preflop_screenshot_ranges.py"))
    assert not list(staging.rglob("preflop_screenshot_ranges_75.py"))
    assert not list(staging.rglob("preflop_range_policy.py"))
    assert not list(staging.rglob("preflop_range_data*.py"))
    assert not list(staging.glob("preflop-screenshot-module.part-*"))

    repo_root = staging.parent
    app_main = (current_package.parent / "PigeonPoker.pyw").read_text(encoding="utf-8")
    assert "preflop_screenshot_ranges" not in app_main
    workflow_root = repo_root / ".github" / "workflows"
    workflow_sources = [
        item.read_text(encoding="utf-8")
        for item in workflow_root.iterdir()
        if item.is_file() and item.suffix.lower() in {".yml", ".yaml"}
    ]
    retired_tokens = (
        "preflop_screenshot_ranges",
        "preflop_range_policy",
        "preflop_range_data",
        "preflop_autonomous",
        "12,675",
        "75-node",
    )
    for workflow_source in workflow_sources:
        for token in retired_tokens:
            assert token not in workflow_source, f"Retired preflop reference {token!r} remains in a workflow"


def _test_position_specific_open_sizes_replace_fixed_2_5bb():
    cases = [
        ("HJ", [action("UTG", "fold")], 200),
        ("CO", [action("UTG", "fold"), action("HJ", "fold")], 230),
        ("BTN", [action("UTG", "fold"), action("HJ", "fold"),
                 action("CO", "fold")], 250),
        ("SB", [action("UTG", "fold"), action("HJ", "fold"),
                action("CO", "fold"), action("BTN", "fold")], 300),
        ("UTG", [], 200),
    ]
    for pos, events, expected in cases:
        hand = FakeHand(events=events, legal=legal_for(
            pos, to_call=50 if pos == "SB" else 100,
            min_target=100, max_target=10000,
        ))
        target = policy.preflop_gto_situation_size(FakeTable(), hand, "p" + pos)
        assert target == expected, (pos, target, expected)


def _test_screenshot_open_ranges_match_aggregate_frequencies():
    data = policy._data()["nodes_by_id"]
    assert abs(data["02_HJ_OPEN"]["action_totals"]["raise"] - 19.6) < 0.2
    assert abs(data["03_CO_OPEN"]["action_totals"]["raise"] - 28.9) < 0.2
    assert abs(data["04_BTN_OPEN"]["action_totals"]["raise"] - 42.0) < 0.2
    assert abs(data["05_SB_OPEN"]["action_totals"]["raise"] - 37.5) < 0.2
    assert abs(data["05_SB_OPEN"]["action_totals"]["call"] - 11.1) < 0.2


def _test_threebet_size_matrix_uses_opener_and_hero_position():
    cases = [
        ("HJ", [action("UTG", "raise", 2.0)], 650),
        ("CO", [action("UTG", "raise", 2.0)], 650),
        ("BTN", [action("UTG", "raise", 2.0)], 750),
        ("SB", [action("UTG", "raise", 2.0)], 1000),
        ("BB", [action("UTG", "raise", 2.0)], 1200),
        ("CO", [action("HJ", "raise", 2.0)], 650),
        ("BTN", [action("HJ", "raise", 2.0)], 750),
        ("SB", [action("HJ", "raise", 2.0)], 1100),
        ("BB", [action("HJ", "raise", 2.0)], 1230),
        ("BTN", [action("CO", "raise", 2.3)], 750),
        ("SB", [action("CO", "raise", 2.3)], 1150),
        ("BB", [action("CO", "raise", 2.3)], 1350),
        ("SB", [action("BTN", "raise", 2.5)], 1200),
        ("BB", [action("BTN", "raise", 2.5)], 1300),
        ("BB", [action("SB", "raise", 3.0)], 1000),
    ]
    for actor, events, expected in cases:
        hand = FakeHand(events=events, legal=legal_for(
            actor, to_call=200, min_target=300, max_target=10000,
        ))
        target = policy.preflop_gto_situation_size(FakeTable(), hand, "p" + actor)
        assert target == expected, (actor, events, target, expected)


def _test_sb_limp_bb_uses_two_raise_sizes():
    hand = FakeHand(
        events=[action("SB", "call", 1.0)],
        legal=legal_for("BB", to_call=0, min_target=200,
                        actions=("check", "raise", "fold")),
    )
    opts = policy.preflop_gto_action_options(FakeTable(), hand, "pBB")
    assert opts["node_id"] == "21_BB_VS_SB_LIMP"
    sizes = {
        item["amount_bb"] for item in opts["actions"]
        if item["action"].startswith("raise") and item["amount_bb"] is not None
    }
    assert sizes == {3.0, 5.0}
    assert policy.preflop_gto_situation_size(FakeTable(), hand, "pBB") == 500


def _test_cold_fourbet_and_original_opener_fourbet_sizes():
    history = [action("UTG", "raise", 2.0), action("HJ", "raise", 6.5)]
    cases = [("CO", 1400), ("BTN", 1400), ("BB", 1900)]
    for actor, expected in cases:
        hand = FakeHand(events=history, legal=legal_for(
            actor, to_call=650, min_target=1300, max_target=10000,
        ))
        target = policy.preflop_gto_situation_size(FakeTable(), hand, "p" + actor)
        assert target == expected, (actor, target, expected)

    opener_hand = FakeHand(events=history, legal=legal_for(
        "UTG", to_call=450, min_target=1300, max_target=10000,
    ))
    assert policy.preflop_gto_situation_size(
        FakeTable(), opener_hand, "pUTG"
    ) == 1900


def _test_deep_btn_bb_fourbet_tree_is_recognised():
    history = [
        action("BTN", "raise", 2.5),
        action("BB", "raise", 13.0),
    ]
    hand = FakeHand(events=history, legal=legal_for(
        "BTN", to_call=1300, min_target=2600, max_target=10000,
    ))
    opts = policy.preflop_gto_action_options(FakeTable(), hand, "pBTN")
    assert opts["node_id"] == "26_BTN_VS_BB_3BET"
    assert policy.preflop_gto_situation_size(FakeTable(), hand, "pBTN") == 2700

    facing_fourbet = FakeHand(
        events=history + [action("BTN", "raise", 27.0)],
        legal=legal_for("BB", to_call=1400, min_target=5400, max_target=10000),
    )
    opts2 = policy.preflop_gto_action_options(FakeTable(), facing_fourbet, "pBB")
    assert opts2["node_id"] == "27_BB_VS_BTN_4BET"
    assert policy.preflop_gto_situation_size(FakeTable(), facing_fourbet, "pBB") is None

    facing_shove = FakeHand(
        events=history + [
            action("BTN", "raise", 27.0),
            action("BB", "allin", 100.0),
        ],
        legal=legal_for("BTN", to_call=7300, min_target=10000,
                        actions=("call", "fold")),
    )
    opts3 = policy.preflop_gto_action_options(FakeTable(), facing_shove, "pBTN")
    assert opts3["node_id"] == "28_BTN_VS_BB_5BET"
    assert policy.preflop_gto_situation_size(FakeTable(), facing_shove, "pBTN") is None


def _test_missing_nodes_use_position_size_and_history_inference():
    # HJ facing a BTN open was not separately captured. The model infers an
    # OOP 3-bet size from the 2.5 BB open, rather than reverting to 2.5 BB.
    hand = FakeHand(
        events=[action("BTN", "raise", 2.5)],
        legal=legal_for("HJ", to_call=250, min_target=500, max_target=10000),
    )
    opts = policy.preflop_gto_action_options(FakeTable(), hand, "pHJ")
    assert opts["inferred"] is True
    assert opts["source"] == "gto-rule-inference"
    assert opts["suggested_raise_target"] == 1250

    # A custom 2.5 BB UTG open must not be incorrectly matched to the 2.0 BB
    # UTG screenshot line; the size extrapolates using the observed ratio.
    custom = FakeHand(
        events=[action("UTG", "raise", 2.5)],
        legal=legal_for("HJ", to_call=250, min_target=500, max_target=10000),
    )
    custom_size = policy.preflop_gto_situation_size(FakeTable(), custom, "pHJ")
    assert custom_size not in (650, None)
    assert 800 <= custom_size <= 830


def _test_multiway_squeeze_size_is_larger_than_headsup_threebet():
    headsup = FakeHand(
        events=[action("UTG", "raise", 2.0)],
        legal=legal_for("BTN", to_call=200, min_target=400, max_target=10000),
    )
    multiway = FakeHand(
        events=[action("UTG", "raise", 2.0), action("CO", "call", 2.0)],
        legal=legal_for("BTN", to_call=200, min_target=400, max_target=10000),
    )
    a = policy.preflop_gto_situation_size(FakeTable(), headsup, "pBTN")
    b = policy.preflop_gto_situation_size(FakeTable(), multiway, "pBTN")
    assert b > a


def _test_stack_depth_changes_inferred_threebet_size():
    deep = FakeHand(
        events=[action("UTG", "raise", 2.0)],
        legal=legal_for("HJ", to_call=200, min_target=400, max_target=10000),
        stacks={"HJ": 10000, "UTG": 10000},
    )
    shallow = FakeHand(
        events=[action("UTG", "raise", 2.0)],
        legal=legal_for("HJ", to_call=200, min_target=400, max_target=10000),
        stacks={"HJ": 5000, "UTG": 5000},
    )
    deep_size = policy.preflop_gto_situation_size(FakeTable(), deep, "pHJ")
    shallow_size = policy.preflop_gto_situation_size(FakeTable(), shallow, "pHJ")
    assert shallow_size < deep_size


def _test_cpu_action_uses_new_node_range_and_preserves_legality():
    hand = FakeHand(
        events=[action("UTG", "fold")],
        holecards={"HJ": ("As", "Ah")},
        legal=legal_for("HJ", to_call=100, min_target=200, max_target=10000),
    )
    decision = policy.choose_preflop_action(
        FakeTable(), hand, "pHJ", FakeCPU()
    )
    assert decision.action == "raise"
    assert decision.amount == 200
    assert decision.source == "new-screenshot-gto"
    assert decision.node_id == "02_HJ_OPEN"
    # The strategy is advisory to the CPU only; it never modifies the user's action.
    assert hand.legal_actions("pHJ")["actions"] == [
        "fold", "call", "check", "raise", "all_in"
    ]


def _test_opponent_range_estimator_uses_new_preflop_policy():
    hand = FakeHand(
        events=[action("UTG", "fold"), action("HJ", "raise", 2.0)],
        holecards={"HJ": ("As", "Ah"), "BTN": ("Qs", "Qh")},
    )
    estimate = policy.estimate_preflop_opponent_ranges(
        FakeTable(), hand, exclude_player_id="pBTN"
    )
    assert estimate["supported"] is True
    assert "pHJ" in estimate["players"]
    row = estimate["players"]["pHJ"]
    assert row["supported"] is True
    assert row["source"] == "new screenshot node"
    assert row["hand_class_probabilities"]


def run_tests():
    tests = [
        _test_schema2_screenshot_policy_metadata,
        _test_position_specific_open_sizes_replace_fixed_2_5bb,
        _test_screenshot_open_ranges_match_aggregate_frequencies,
        _test_threebet_size_matrix_uses_opener_and_hero_position,
        _test_sb_limp_bb_uses_two_raise_sizes,
        _test_cold_fourbet_and_original_opener_fourbet_sizes,
        _test_deep_btn_bb_fourbet_tree_is_recognised,
        _test_missing_nodes_use_position_size_and_history_inference,
        _test_multiway_squeeze_size_is_larger_than_headsup_threebet,
        _test_stack_depth_changes_inferred_threebet_size,
        _test_cpu_action_uses_new_node_range_and_preserves_legality,
        _test_opponent_range_estimator_uses_new_preflop_policy,
        test_all_screenshot_nodes_contain_a_complete_169_hand_matrix,
        test_every_screenshot_raise_size_has_a_combo_weighted_modal_result,
        test_gto_size_lookup_is_position_and_history_only_not_hole_card_dependent,
        test_only_the_new_policy_is_the_runtime_preflop_source,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "new GTO preflop tests")


if __name__ == "__main__":
    run_tests()
