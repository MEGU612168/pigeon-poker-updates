from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_1_3_101"
APP = SOURCE / "PigeonPoker.pyw"
LEGACY_POLICY = SOURCE / "pigeon_poker" / "preflop_gto_strategy.py"
NEW_POLICY = SOURCE / "pigeon_poker" / "preflop_174_policy.py"
NEW_DATA = SOURCE / "pigeon_poker" / "preflop_174_policy_data.py"


def test_legacy_preflop_strategy_is_not_shipped() -> None:
    assert not LEGACY_POLICY.exists()


def test_application_routes_preflop_cpu_actions_to_the_174_policy() -> None:
    source = APP.read_text(encoding="utf-8")
    ast.parse(source, filename=str(APP))
    assert "from pigeon_poker.preflop_174_policy import choose_preflop_174_action" in source
    assert source.count("choose_preflop_174_action(") >= 2
    assert "range_estimator=postflop_range_estimator" in source
    assert "_choose_preflop_legal_fallback" not in source
    assert "174_POLICY_PENDING" not in source
    assert "TEMPORARY SAFE FALLBACK" not in source
    for retired in (
        "preflop_gto_strategy",
        "choose_preflop_action",
        "preflop_gto_situation_size",
        "estimate_preflop_opponent_ranges",
        "build_live_hu_solver_setup",
    ):
        assert retired not in source, retired
    assert "cleanup_retired_preflop_modules()" in source


def test_174_policy_is_packaged_and_is_cpu_level_independent() -> None:
    assert NEW_POLICY.is_file()
    assert NEW_DATA.is_file()
    policy = NEW_POLICY.read_text(encoding="utf-8")
    ast.parse(policy, filename=str(NEW_POLICY))
    assert "cpu.level" not in policy
    assert "cpu.archetype" not in policy
    assert "preflop-174-scenario-policy" in policy
    assert "out-of-range-at-node" in policy
    assert "preflop-174-out-of-range-guardrail" in policy
    assert "No exact 174-scenario action history" in policy
    assert "ranked = [(_history_distance" not in policy


def test_old_hero_sizing_controls_are_removed_but_manual_bet_controls_remain() -> None:
    source = APP.read_text(encoding="utf-8")
    assert "_preflop_gto_initial_raise_target" not in source
    assert "_apply_preflop_gto_size" not in source
    assert "GTO SIZE" not in source
    assert "self._on_table_bet_slider" in source
    assert "self._on_table_bet_entry_change" in source


if __name__ == "__main__":
    tests = [
        test_legacy_preflop_strategy_is_not_shipped,
        test_application_routes_preflop_cpu_actions_to_the_174_policy,
        test_174_policy_is_packaged_and_is_cpu_level_independent,
        test_old_hero_sizing_controls_are_removed_but_manual_bet_controls_remain,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174-scenario integration source tests")
