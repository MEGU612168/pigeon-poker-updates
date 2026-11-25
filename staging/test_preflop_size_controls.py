from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "source_1_3_101" / "PigeonPoker.pyw"


def test_174_raise_size_button_is_present_in_the_dedicated_action_row():
    source = APP.read_text(encoding="utf-8")
    assert "preflop_174_raise_size_options" in source
    assert "def _show_preflop_174_sizing_menu(self, table_id: str):" in source
    assert 'record["situation_actions"]' in source
    assert 'record["gto_size_button"] = sizing_button' in source
    assert "174 RAISE SIZE" in source
    assert 'hand.street == "preflop" and "raise" in action_names' in source


def test_174_raise_size_menu_only_sets_the_amount_and_does_not_submit():
    source = APP.read_text(encoding="utf-8")
    start = source.index("    def _show_preflop_174_sizing_menu(self, table_id: str):")
    end = source.index("    def _set_table_pot_preset(", start)
    method = source[start:end]
    assert "_set_table_bet_target(tid, target)" in method
    assert "_floating_table_action(" not in method
    assert "tk_popup(" in method
    assert "chart frequency" in method


def test_postflop_pot_presets_remain_available_and_unchanged():
    source = APP.read_text(encoding="utf-8")
    assert 'for pct in self.bet_pot_percentages:' in source
    assert 'lambda tid=slot.table_id, p=pct: self._set_table_pot_preset(tid, p)' in source


if __name__ == "__main__":
    tests = [
        test_174_raise_size_button_is_present_in_the_dedicated_action_row,
        test_174_raise_size_menu_only_sets_the_amount_and_does_not_submit,
        test_postflop_pot_presets_remain_available_and_unchanged,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174 raise-size UI regression tests")
