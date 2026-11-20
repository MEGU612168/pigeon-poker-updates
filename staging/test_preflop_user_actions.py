from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"
SOURCE_TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE_TEXT, filename=str(SOURCE))


def method(name: str) -> ast.FunctionDef:
    matches = [
        node for node in ast.walk(TREE)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if not matches:
        raise AssertionError(f"Missing method: {name}")
    return matches[0]


def source_of(name: str) -> str:
    return ast.get_source_segment(SOURCE_TEXT, method(name)) or ""


def test_hero_preflop_actions_are_never_gated_by_chart_frequencies() -> None:
    action = source_of("_cash_human_action")
    assert "PREFLOP CHART LINE NOT COVERED" not in action
    assert "USE THE CHART ACTIONS AND BB SIZE ONLY" not in action
    assert "_fixed_preflop_raise_target" in action
    assert 'if key in {"raise", "bet"}:' in action
    # Fold/call/check/all-in reach the ordinary legal action path unchanged.
    assert "allowed = False" not in action
    assert "if not allowed:" not in action


def test_preflop_ui_shows_every_legal_fold_call_raise_and_allin_action() -> None:
    refresh = SOURCE_TEXT
    marker = 'record["status"].set(\n                        "YOUR TURN • PREFLOP RAISE SIZE FIXED"'
    at = refresh.find(marker)
    assert at >= 0, "The unrestricted preflop action UI branch is missing."
    start = refresh.rfind('if hand.street == "preflop"', 0, at)
    branch = refresh[start:at]
    assert 'or "fold" in action_names' in branch
    assert 'if "check" in action_names:' in branch
    assert 'elif "call" in action_names:' in branch
    assert 'if "raise" in action_names or "bet" in action_names:' in branch
    assert 'if "all-in" in action_names:' in branch
    assert 'state="normal"' in branch
    assert 'chart_controls.get("fold")' not in branch
    assert 'chart_controls.get("call_action")' not in branch
    assert 'chart_controls.get("raise_action")' not in branch


def test_only_preflop_raise_amount_uses_fixed_chart_size_with_legal_fallback() -> None:
    sizing = source_of("_fixed_preflop_raise_target")
    assert "preflop_chart_options" in sizing
    assert 'chart_controls.get("raise_amount")' in sizing
    assert 'legal.get("min_target"' in sizing
    assert "return minimum" in sizing
    action = source_of("_cash_human_action")
    assert "amount = self._fixed_preflop_raise_target(" in action
    assert 'if key in {"raise", "bet"}:' in action
    assert 'if key == "fold"' not in action
    assert 'if key in {"call", "check"}' not in action


def test_postflop_controls_still_use_the_unrestricted_normal_legal_action_ui() -> None:
    refresh = SOURCE_TEXT
    assert 'legal = hand.legal_actions("hero")' in refresh
    assert "self._floating_table_bet_action(tid, var)" in refresh


if __name__ == "__main__":
    cases = [
        test_hero_preflop_actions_are_never_gated_by_chart_frequencies,
        test_preflop_ui_shows_every_legal_fold_call_raise_and_allin_action,
        test_only_preflop_raise_amount_uses_fixed_chart_size_with_legal_fallback,
        test_postflop_controls_still_use_the_unrestricted_normal_legal_action_ui,
    ]
    for case in cases:
        case()
        print("PASS", case.__name__)
    print("ALL PASS", len(cases), "preflop user action freedom tests")
