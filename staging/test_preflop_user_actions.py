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




def test_uncovered_preflop_history_never_uses_generic_range_policy() -> None:
    worker = source_of("_start_cash_cpu_chain_if_needed")
    start = worker.index(
        'if hand.street == "preflop":\n                        # Every preflop turn'
    )
    end = worker.index(
        'elif not (session is not None and session.hand_token == id(hand)',
        start,
    )
    preflop_branch = worker[start:end]
    assert "fallback_decision = choose_preflop_action(table, hand, pid, cpu, None)" in preflop_branch
    assert "choose_range_aware_action" not in preflop_branch

    recovery = worker.index(
        'if decision is None:\n                            # If a preflop helper unexpectedly'
    )
    recovery_end = worker.index("if cancel_event.is_set():", recovery)
    recovery_branch = worker[recovery:recovery_end]
    assert 'if hand.street == "preflop":' in recovery_branch
    assert "decision = choose_preflop_action(table, hand, pid, cpu, None)" in recovery_branch
    assert "else:" in recovery_branch
    assert "decision = choose_range_aware_action(" in recovery_branch


def test_chart_size_button_is_preflop_only_and_user_editable() -> None:
    refresh = source_of("_refresh_table_windows")
    apply_size = source_of("_apply_preflop_chart_size")
    action = source_of("_cash_human_action")

    assert 'if hand.street == "preflop" and not bool(state.get("cash_gto_spot_mode", False)):' in refresh
    assert 'sizes_frame, "CHART SIZE"' in refresh
    assert 'record["chart_size_button"] = chart_button' in refresh
    assert "self._apply_preflop_chart_size(tid)" in refresh
    assert "preflop_chart_options(table, hand, \"hero\")" in apply_size
    assert 'hand.next_to_act != "hero"' in apply_size
    assert "self._set_table_bet_target(table_id, target)" in apply_size
    assert "self.cash_table.act(\"hero\", action, amount)" in action
    assert "_apply_preflop_chart_size" not in action
    assert "preflop_chart_options" not in action


def test_new_hand_reloads_chart_initial_amount_after_postflop() -> None:
    refresh = source_of("_refresh_table_windows")
    assert "current_hand_key = id(hand) if hand is not None else None" in refresh
    assert "current_hand_key," in refresh
    assert 'record["bet_target_cents"].set(target)' in refresh
    assert "self._preflop_initial_raise_target(" in refresh


if __name__ == "__main__":
    tests = [
        test_chart_never_gates_or_rewrites_hero_actions,
        test_preflop_chart_only_sets_the_initial_editable_raise_size,
        test_user_can_change_initial_size_before_submitting,
        test_uncovered_preflop_history_never_uses_generic_range_policy,
        test_chart_size_button_is_preflop_only_and_user_editable,
        test_new_hand_reloads_chart_initial_amount_after_postflop,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "user choice freedom tests")
