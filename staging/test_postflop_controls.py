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


def text_of(name: str) -> str:
    return ast.get_source_segment(SOURCE_TEXT, method(name)) or ""


def test_every_street_reaches_one_shared_hero_action_renderer() -> None:
    source = text_of("_refresh_table_windows")
    assert 'legal = hand.legal_actions("hero")' in source
    assert 'if hand.next_to_act != "hero":' in source
    assert "PREFLOP GTO ACTIONS ONLY" not in source
    assert "YOUR TURN • PREFLOP RAISE SIZE FIXED" not in source
    assert 'if hand.street == "preflop"' not in source[
        source.index('if hand.next_to_act != "hero":') + 1:
        source.index('legal = hand.legal_actions("hero")')
    ]


def test_postflop_fold_check_call_bet_raise_controls_are_rebuilt() -> None:
    source = text_of("_refresh_table_windows")
    assert 'fold_button.configure(text="FOLD"' in source
    assert '"check" in action_names' in source
    assert '"call" in action_names' in source
    assert '"bet" in action_names or "raise" in action_names' in source
    assert "tk.Scale(" in source
    assert 'self._floating_table_bet_action(tid, var)' in source
    assert "self._set_table_pot_preset" in source


def test_legacy_preflop_size_helper_is_removed_and_manual_bet_entry_remains() -> None:
    refresh = text_of("_refresh_table_windows")
    assert "_preflop_gto_initial_raise_target" not in SOURCE_TEXT
    assert "_apply_preflop_gto_size" not in SOURCE_TEXT
    assert "preflop_gto_situation_size" not in SOURCE_TEXT
    assert "GTO SIZE" not in SOURCE_TEXT
    assert 'target = minimum' in refresh
    assert 'record["bet_target"].set(' in refresh
    assert 'record["bet_slider"].set(target)' in refresh
    assert 'record["bet_target_cents"].set(target)' in refresh
    assert "ttk.Entry(sizes_frame" in refresh
    assert "command=lambda value, tid=slot.table_id: self._on_table_bet_slider" in refresh


def test_submitted_hero_action_and_amount_are_not_rewritten() -> None:
    action = text_of("_cash_human_action")
    assert "preflop_gto_action_options" not in action
    assert "_preflop_gto_initial_raise_target" not in action
    assert "self.cash_table.act(\"hero\", action, amount)" in action
    assert "amount = " not in action


if __name__ == "__main__":
    tests = [
        test_every_street_reaches_one_shared_hero_action_renderer,
        test_postflop_fold_check_call_bet_raise_controls_are_rebuilt,
        test_legacy_preflop_size_helper_is_removed_and_manual_bet_entry_remains,
        test_submitted_hero_action_and_amount_are_not_rewritten,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "shared action UI tests")
