from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"
SOURCE_TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE_TEXT, filename=str(SOURCE))


def method(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing method: {name}")


def source_of(name: str) -> str:
    return ast.get_source_segment(SOURCE_TEXT, method(name)) or ""


def test_chart_never_gates_or_rewrites_hero_actions() -> None:
    action = source_of("_cash_human_action")
    assert "preflop_chart_options" not in action
    assert "_preflop_initial_raise_target" not in action
    assert "allowed = False" not in action
    assert "if not allowed:" not in action
    assert "self.cash_table.act(\"hero\", action, amount)" in action
    assert "amount = " not in action


def test_preflop_chart_only_sets_the_initial_editable_raise_size() -> None:
    helper = source_of("_preflop_initial_raise_target")
    refresh = source_of("_refresh_table_windows")
    assert "preflop_chart_options" in helper
    assert 'chart_controls.get("raise_amount")' in helper
    assert "return minimum" in helper
    assert "self._preflop_initial_raise_target(" in refresh
    assert 'record["bet_target_cents"].set(target)' in refresh
    assert 'record["bet_slider"].set(target)' in refresh
    assert 'record["bet_target"].set(' in refresh
    assert "ttk.Entry(sizes_frame" in refresh
    assert "self._on_table_bet_slider" in refresh


def test_user_can_change_initial_size_before_submitting() -> None:
    refresh = source_of("_refresh_table_windows")
    action = source_of("_floating_table_bet_action")
    assert "record[\"bet_target\"]" in refresh
    assert "self._on_table_bet_entry_change" in refresh
    assert "self._on_table_bet_slider" in refresh
    assert "int(target)" in action or "target =" in action
    assert "self._floating_table_action(table_id, verb, target)" in action


if __name__ == "__main__":
    tests = [
        test_chart_never_gates_or_rewrites_hero_actions,
        test_preflop_chart_only_sets_the_initial_editable_raise_size,
        test_user_can_change_initial_size_before_submitting,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "user choice freedom tests")
