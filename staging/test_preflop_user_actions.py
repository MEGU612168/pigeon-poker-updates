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


def test_gto_policy_never_gates_or_rewrites_hero_actions() -> None:
    action = source_of("_cash_human_action")
    assert "preflop_gto_action_options" not in action
    assert "_preflop_gto_initial_raise_target" not in action
    assert "allowed = False" not in action
    assert "if not allowed:" not in action
    assert "self.cash_table.act(\"hero\", action, amount)" in action
    assert "amount = " not in action


def test_preflop_gto_only_sets_the_initial_editable_raise_size() -> None:
    helper = source_of("_preflop_gto_initial_raise_target")
    refresh = source_of("_refresh_table_windows")
    assert "preflop_gto_situation_size(table, hand, actor_id)" in helper
    assert "preflop_gto_action_options" not in helper
    assert "return minimum" in helper
    assert "self._preflop_gto_initial_raise_target(" in refresh
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


def test_gto_size_button_is_preflop_only_and_user_editable() -> None:
    refresh = source_of("_refresh_table_windows")
    initial_size = source_of("_preflop_gto_initial_raise_target")
    apply_size = source_of("_apply_preflop_gto_size")
    action = source_of("_cash_human_action")

    assert 'if hand.street == "preflop" and not bool(state.get("cash_gto_spot_mode", False)):' in refresh
    assert 'situation_frame, "GTO SIZE"' in refresh
    assert 'record["gto_size_button"] = gto_size_button' in refresh
    assert "situation_actions = tk.Frame(action_outer" in SOURCE_TEXT
    assert "situation_actions" in refresh
    assert "self._apply_preflop_gto_size(tid)" in refresh
    assert "preflop_gto_situation_size(table, hand, actor_id)" in initial_size
    assert "preflop_gto_situation_size(table, hand, \"hero\")" in apply_size
    assert "preflop_gto_action_options" not in apply_size
    assert 'hand.next_to_act != "hero"' in apply_size
    assert "self._set_table_bet_target(table_id, target)" in apply_size
    assert "self.cash_table.act(\"hero\", action, amount)" in action
    assert "_apply_preflop_gto_size" not in action
    assert "preflop_gto_action_options" not in action



def test_gto_size_helper_is_only_for_hero_ui_and_bot_keeps_hand_range_policy() -> None:
    helper = source_of("_apply_preflop_gto_size")
    worker = source_of("_start_cash_cpu_chain_if_needed")
    strategy_source = (Path(__file__).with_name("source_1_3_101") / "pigeon_poker" / "preflop_gto_strategy.py").read_text(encoding="utf-8")
    choose_start = strategy_source.index("def choose_preflop_action(")
    choose_end = strategy_source.index("def _modal_size_from_node(", choose_start)
    bot_policy = strategy_source[choose_start:choose_end]

    # Human GTO sizing is only an editable UI suggestion; CPU decisions use
    # their own two-card class, history resolver, frequency matrix and RNG.
    assert "preflop_gto_situation_size(table, hand, \"hero\")" in helper
    assert "preflop_gto_situation_size" not in worker
    assert "hand_class = _hand_class(" in bot_policy
    assert "spot = _resolve_spot(table, hand, player_id)" in bot_policy
    assert "raw, inferred = _actions_for_hand(spot, hand_class)" in bot_policy
    assert "choices = _legal_choices(hand, player_id, raw" in bot_policy
    assert "rng.random()" in bot_policy
    assert 'source="new-screenshot-gto" if exact else "gto-rule-inference"' in bot_policy
    assert 'source="gto-inferred-legal-fallback"' in bot_policy
    assert 'decision_source == "new-screenshot-gto"' in worker
    assert 'decision_source == "gto-rule-inference"' in worker
    assert 'decision_source == "gto-inferred-legal-fallback"' in worker
    assert "preflop_guardrail_used" not in worker
    assert "preflop_screenshot_range" not in SOURCE_TEXT
    assert "from pigeon_poker.preflop_gto_strategy import (" in SOURCE_TEXT
    assert "choose_preflop_action(table, hand, pid, cpu, None)" in worker


def test_new_hand_reloads_gto_initial_amount_after_postflop() -> None:
    refresh = source_of("_refresh_table_windows")
    assert "current_hand_key = id(hand) if hand is not None else None" in refresh
    assert "current_hand_key," in refresh
    assert 'record["bet_target_cents"].set(target)' in refresh
    assert "self._preflop_gto_initial_raise_target(" in refresh



def test_gto_size_button_reports_applied_unmatched_and_error_states() -> None:
    apply_size = source_of("_apply_preflop_gto_size")
    assert 'record["status"].set' in apply_size
    assert "GTO SIZE APPLIED" in apply_size
    assert "preflop_gto_situation_size(table, hand, \"hero\")" in apply_size
    assert "NO MATCHING GTO SIZE" in apply_size
    assert "except Exception as exc:" in apply_size
    assert "GTO SIZE ERROR" in apply_size

if __name__ == "__main__":
    tests = [
        test_gto_policy_never_gates_or_rewrites_hero_actions,
        test_preflop_gto_only_sets_the_initial_editable_raise_size,
        test_user_can_change_initial_size_before_submitting,
        test_uncovered_preflop_history_never_uses_generic_range_policy,
        test_gto_size_button_is_preflop_only_and_user_editable,
        test_gto_size_helper_is_only_for_hero_ui_and_bot_keeps_hand_range_policy,
        test_new_hand_reloads_gto_initial_amount_after_postflop,
        test_gto_size_button_reports_applied_unmatched_and_error_states,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "user choice freedom tests")
