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
    assert len(raw_nodes) == 27
    assert summary["exact_screenshot_nodes"] == 27
    assert summary["node_count"] == 28
    assert summary["inferred_nodes"] == 1

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


def test_every_screenshot_raise_size_has_a_combo_weighted_modal_result() -> None:
    data = policy._data()
    exact_nodes = [node for node in data["nodes"] if not node.get("inferred", False)]
    assert len(exact_nodes) == 27

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
        test_every_screenshot_raise_size_has_a_combo_weighted_modal_result,
        test_gto_size_lookup_is_position_and_history_only_not_hole_card_dependent,
        test_only_the_new_policy_is_the_runtime_preflop_source,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "full preflop data-integrity tests")
