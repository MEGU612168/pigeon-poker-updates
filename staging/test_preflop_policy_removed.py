from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_1_3_101"
APP = SOURCE / "PigeonPoker.pyw"
OLD_POLICY = SOURCE / "pigeon_poker" / "preflop_gto_strategy.py"


def test_old_preflop_strategy_module_is_not_shipped() -> None:
    assert not OLD_POLICY.exists()


def test_application_has_no_runtime_dependency_on_the_legacy_policy() -> None:
    source = APP.read_text(encoding="utf-8")
    ast.parse(source, filename=str(APP))
    for retired in (
        "preflop_gto_strategy",
        "choose_preflop_action",
        "preflop_gto_situation_size",
        "estimate_preflop_opponent_ranges",
        "preflop_range_image_for_situation",
        "build_live_hu_solver_setup",
    ):
        assert retired not in source, retired
    assert "cleanup_retired_preflop_modules()" in source
    assert "_choose_preflop_legal_fallback(table, hand, pid, cpu)" in source


def test_all_cpus_use_the_same_temporary_preflop_safety_net() -> None:
    source = APP.read_text(encoding="utf-8")
    start = source.index("def _choose_preflop_legal_fallback(")
    end = source.index("\ndef load_config(", start)
    helper = source[start:end]
    assert "cpu.level" not in helper
    assert "cpu.archetype" not in helper
    assert "cpu.rng" not in helper
    assert 'source="preflop-legacy-removed-safe-fallback"' in helper
    assert "174_POLICY_PENDING" in helper


def test_old_hero_sizing_controls_are_removed_but_manual_bet_controls_remain() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "_preflop_gto_initial_raise_target" not in source
    assert "_apply_preflop_gto_size" not in source
    assert "GTO SIZE" not in source
    assert "self._on_table_bet_slider" in source
    assert "self._on_table_bet_entry_change" in source


if __name__ == "__main__":
    tests = [
        test_old_preflop_strategy_module_is_not_shipped,
        test_application_has_no_runtime_dependency_on_the_legacy_policy,
        test_all_cpus_use_the_same_temporary_preflop_safety_net,
        test_old_hero_sizing_controls_are_removed_but_manual_bet_controls_remain,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "legacy preflop retirement tests")
