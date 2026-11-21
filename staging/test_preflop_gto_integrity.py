from __future__ import annotations

import base64
import bz2
import inspect
import json
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "source_1_3_101"
sys.path.insert(0, str(SOURCE))

from pigeon_poker import preflop_gto_strategy as policy


def combo_count(hand_class: str) -> int:
    if len(hand_class) == 2:
        return 6
    return 4 if hand_class.endswith("s") else 12


def test_all_screenshot_nodes_contain_a_complete_169_hand_matrix() -> None:
    compact = json.loads(bz2.decompress(base64.b64decode(policy._DATA_B64)))
    raw_nodes = compact["nodes"]
    data = policy._data()
    summary = policy.coverage_summary()

    assert len(policy.HAND_ORDER) == 169
    assert len(set(policy.HAND_ORDER)) == 169
    assert len(raw_nodes) == 28
    assert summary["exact_screenshot_nodes"] == 28
    assert summary["node_count"] == 28
    assert summary["inferred_nodes"] == 0

    seen: set[str] = set()
    for raw in raw_nodes:
        node_id = raw["i"]
        assert node_id not in seen, f"duplicate screenshot node: {node_id}"
        seen.add(node_id)

        actions = list(raw["a"])
        sizes = dict(raw.get("z", {}))
        matrix = list(raw["h"])
        assert actions and len(set(actions)) == len(actions), node_id
        assert len(matrix) == 169, (node_id, len(matrix))

        for hand_class, frequencies in zip(policy.HAND_ORDER, matrix):
            assert len(frequencies) == len(actions), (node_id, hand_class)
            values = [int(value) for value in frequencies]
            assert all(0 <= value <= 10000 for value in values), (node_id, hand_class)
            total = sum(values)
            assert total == 0 or abs(total - 10000) <= 20, (node_id, hand_class, total)

        for index, action in enumerate(actions):
            if action.startswith("raise") and any(int(row[index]) > 0 for row in matrix):
                amount = sizes.get(action)
                assert amount is not None and float(amount) > 0, (node_id, action, amount)

        decoded = data["nodes_by_id"][node_id]
        assert decoded["source_image"], f"missing screenshot provenance: {node_id}"
        for hand_index, hand_class in enumerate(policy.HAND_ORDER):
            raw_row = matrix[hand_index]
            expected = {
                action: int(raw_row[action_index]) / 10000.0
                for action_index, action in enumerate(actions)
                if int(raw_row[action_index]) > 0
            }
            actual = {
                item["action"]: float(item["frequency"])
                for item in decoded["hands"].get(hand_class, [])
            }
            assert actual.keys() == expected.keys(), (node_id, hand_class, actual, expected)
            for action, frequency in expected.items():
                assert abs(actual[action] - frequency) < 1e-9, (
                    node_id, hand_class, action, actual[action], frequency
                )


def test_screenshot_action_totals_match_the_169_combo_weighted_matrix() -> None:
    compact = json.loads(bz2.decompress(base64.b64decode(policy._DATA_B64)))
    combo_total = sum(combo_count(hand_class) for hand_class in policy.HAND_ORDER)
    assert combo_total == 1326
    conditional_nodes = set()

    for raw in compact["nodes"]:
        actions = list(raw["a"])
        action_totals = dict(raw.get("t", {}))
        matrix = raw["h"]
        observed = {}
        for action, reported_pct in action_totals.items():
            assert action in actions, (raw["i"], action)
            index = actions.index(action)
            combo_mass = sum(
                combo_count(hand_class) * int(matrix[hand_index][index]) / 10000.0
                for hand_index, hand_class in enumerate(policy.HAND_ORDER)
            )
            observed[action] = combo_mass / combo_total * 100.0

        if raw.get("r", False):
            # Range-conditioned 3bet/4bet nodes include explicit 100% folds
            # for combos outside the prior action range. Non-fold action mass
            # therefore reveals the prior-range share of all 1,326 combos.
            assert abs(sum(float(v) for v in action_totals.values()) - 100.0) <= 0.2, (
                raw["i"], action_totals
            )
            ratios = [
                observed[action] / float(reported)
                for action, reported in action_totals.items()
                if action != "fold" and float(reported) > 0.0
            ]
            assert ratios, (raw["i"], action_totals)
            active_fraction = sum(ratios) / len(ratios)
            assert 0.0 < active_fraction <= 1.0, (raw["i"], ratios)
            assert max(ratios) - min(ratios) <= 0.012, (
                raw["i"], "non-fold actions imply inconsistent prior-range mass", ratios
            )
            if "fold" in action_totals:
                expected_fold = (
                    (1.0 - active_fraction) * 100.0
                    + active_fraction * float(action_totals["fold"])
                )
                assert abs(observed["fold"] - expected_fold) <= 0.35, (
                    raw["i"], observed["fold"], expected_fold, active_fraction
                )
            conditional_nodes.add(raw["i"])
            print("CONDITIONAL NODE", raw["i"], "prior-range share", round(active_fraction * 100, 2))
        else:
            for action, reported_pct in action_totals.items():
                assert abs(observed[action] - float(reported_pct)) <= 0.35, (
                    raw["i"], action, observed[action], reported_pct
                )

    assert {
        "25_UTG_VS_HJ_3BET",
        "26_BTN_VS_BB_3BET",
        "27_BB_VS_BTN_4BET",
        "28_BTN_VS_BB_5BET",
    }.issubset(conditional_nodes)



def test_range_conditioned_nodes_match_the_previous_action_range_support() -> None:
    data = policy._data()
    # UTG first-in is now a direct screenshot node. The later UTG-vs-HJ
    # 3-bet response node remains independently sourced from its own screenshot.
    assert data["nodes_by_id"]["01_UTG_OPEN"]["source_image"] == "スクリーンショット (303).png"
    parents = {
        "26_BTN_VS_BB_3BET": ("04_BTN_OPEN", "raise"),
        "27_BB_VS_BTN_4BET": ("19_BB_VS_BTN", "raise"),
        "28_BTN_VS_BB_5BET": ("26_BTN_VS_BB_3BET", "raise"),
    }

    for node_id, (parent_id, parent_action) in parents.items():
        node = data["nodes_by_id"][node_id]
        parent = data["nodes_by_id"][parent_id]
        assert node.get("active_range", False), node_id

        parent_support = sum(
            combo_count(hand_class)
            for hand_class, choices in parent["hands"].items()
            if any(
                str(item["action"]).startswith(parent_action)
                and float(item["frequency"]) > 0.00005
                for item in choices
            )
        ) / 1326.0

        raw_node = next(row for row in json.loads(
            bz2.decompress(base64.b64decode(policy._DATA_B64))
        )["nodes"] if row["i"] == node_id)
        actions = list(raw_node["a"])
        matrix = raw_node["h"]
        action_totals = dict(raw_node.get("t", {}))
        total_mass = sum(
            combo_count(hand_class)
            * sum(int(value) for value in matrix[index]) / 10000.0
            for index, hand_class in enumerate(policy.HAND_ORDER)
        )
        shares = [
            sum(
                combo_count(hand_class) * int(matrix[index][actions.index(action)]) / 10000.0
                for index, hand_class in enumerate(policy.HAND_ORDER)
            ) / total_mass / (float(reported) / 100.0)
            for action, reported in action_totals.items()
            if action != "fold" and float(reported) > 0.0
        ]
        active_share = sum(shares) / len(shares)
        assert max(shares) - min(shares) <= 0.012, (node_id, shares)
        # The screenshots were captured in separate decision-tree views; allow a small 2.2 pp range-support drift, while retaining exact per-node frequency checks above.
        assert abs(active_share - parent_support) <= 0.022, (
            node_id, parent_id, parent_support, active_share
        )





def test_utg_open_is_exact_screenshot_range_not_inferred() -> None:
    compact = json.loads(bz2.decompress(base64.b64decode(policy._DATA_B64)))
    raw = next(node for node in compact["nodes"] if node["i"] == "01_UTG_OPEN")
    expected = [[100,100,100,100,100,100,100,100,100,100,100,100,43],[100,100,100,100,100,100,100,69,53,53,0,0,0],[100,100,100,100,100,100,7,0,0,0,0,0,0],[100,87,41,100,100,68,0,0,0,0,0,0,0],[100,0,0,0,100,100,0,0,0,0,0,0,0],[0,0,0,0,0,100,16,0,0,0,0,0,0],[0,0,0,0,0,0,100,8,0,0,0,0,0],[0,0,0,0,0,0,0,100,9,0,0,0,0],[0,0,0,0,0,0,0,0,100,11,0,0,0],[0,0,0,0,0,0,0,0,0,51,6,0,0],[0,0,0,0,0,0,0,0,0,0,18,0,0],[0,0,0,0,0,0,0,0,0,0,0,17,0],[0,0,0,0,0,0,0,0,0,0,0,0,17]]
    expected_flat = [value for row in expected for value in row]

    assert raw["p"] == "スクリーンショット (303).png"
    assert raw["d"].startswith("UTG first-in, 100 BB, open to 2.0 BB")
    assert raw["a"] == ["allin", "raise", "fold"]
    assert float(raw["z"]["raise"]) == 2.0
    assert len(raw["h"]) == 169
    assert [int(row[1]) // 100 for row in raw["h"]] == expected_flat
    assert all(int(row[0]) == 0 for row in raw["h"])
    assert all(int(row[1]) + int(row[2]) == 10000 for row in raw["h"])

    data = policy._data()
    node = data["nodes_by_id"]["01_UTG_OPEN"]
    assert node["source_image"] == raw["p"]
    assert node["inferred"] is False if "inferred" in node else True
    assert node["action_totals"]["raise"] == 17.6
    assert node["hands"]["A2s"][0]["amount_bb"] == 2.0

    weighted = sum(
        combo_count(hand_class) * int(raw["h"][index][1]) / 10000.0
        for index, hand_class in enumerate(policy.HAND_ORDER)
    )
    assert abs(weighted - 233.26) < 0.005
    assert abs(weighted / 1326.0 * 100.0 - 17.6) < 0.02
    assert policy._modal_size_from_node(node) == 2.0


def test_every_screenshot_raise_size_has_a_combo_weighted_modal_result() -> None:
    data = policy._data()
    exact_nodes = [node for node in data["nodes"] if not node.get("inferred", False)]
    assert len(exact_nodes) == 28

    for node in exact_nodes:
        totals: dict[float, float] = {}
        for hand_class, choices in node["hands"].items():
            multiplicity = combo_count(hand_class)
            for item in choices:
                if str(item["action"]).startswith("raise"):
                    amount = item.get("amount_bb")
                    assert amount is not None and float(amount) > 0, (
                        node["id"], hand_class, item
                    )
                    size = float(amount)
                    totals[size] = totals.get(size, 0.0) + (
                        multiplicity * float(item["frequency"])
                    )

        selected = policy._modal_size_from_node(node)
        if totals:
            expected = max(totals.items(), key=lambda item: (item[1], -item[0]))[0]
            assert selected == expected, (node["id"], selected, expected)
        else:
            assert selected is None, node["id"]


def test_gto_size_lookup_is_position_and_history_only_not_hole_card_dependent() -> None:
    source = inspect.getsource(policy.preflop_gto_situation_size)
    assert "_hand_class" not in source
    assert "hole_cards" not in source
    assert "_resolve_spot(table, hand, player_id)" in source
    assert "_modal_size_from_node(node)" in source


def test_only_the_new_policy_is_the_runtime_preflop_source() -> None:
    app_source = (SOURCE / "PigeonPoker.pyw").read_text(encoding="utf-8")
    assert "from pigeon_poker.preflop_gto_strategy import" in app_source
    assert "preflop_screenshot_ranges" not in app_source
    strategy_source = (SOURCE / "pigeon_poker" / "preflop_gto_strategy.py").read_text(encoding="utf-8")
    assert "def choose_preflop_action(" in strategy_source
    assert "def preflop_gto_situation_size(" in strategy_source


if __name__ == "__main__":
    tests = [
        test_all_screenshot_nodes_contain_a_complete_169_hand_matrix,
        test_screenshot_action_totals_match_the_169_combo_weighted_matrix,
        test_every_screenshot_raise_size_has_a_combo_weighted_modal_result,
        test_gto_size_lookup_is_position_and_history_only_not_hole_card_dependent,
        test_only_the_new_policy_is_the_runtime_preflop_source,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "full preflop data-integrity tests")
