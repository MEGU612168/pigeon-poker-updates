from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parent
SOURCE = ROOT / "source_1_3_101" / "PigeonPoker.pyw"
VIP_SOURCE = ROOT / "source_1_3_101" / "pigeon_poker" / "vip_ai.py"
TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(TEXT, filename=str(SOURCE))


def method(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing method: {name}")


def source_of(name: str) -> str:
    return ast.get_source_segment(TEXT, method(name)) or ""


def test_empty_bet_and_174_range_rows_are_removed_from_action_dock() -> None:
    create = source_of("_create_table_window")
    refresh = source_of("_refresh_table_windows")
    assert 'size_actions.configure(height=28 if vip_mode else 30)' in create
    assert 'situation_actions.configure(height=18 if vip_mode else 20)' in create
    assert 'vip_dock = is_vip_mode(state.get("cash_game_mode", RUSH_MODE))' in refresh
    assert '("size_actions", "situation_actions", 28 if vip_dock else 30)' in refresh
    assert '("situation_actions", "utility_actions", 18 if vip_dock else 20)' in refresh
    assert '0 if vip_dock else 1' in refresh
    assert "dock_row.winfo_children()" in refresh
    assert "dock_row.pack_forget()" in refresh
    assert 'before=before_row' in refresh


def test_vip_roles_assign_exactly_three_pro_and_two_top_pro() -> None:
    namespace: dict[str, object] = {}
    exec(compile(VIP_SOURCE.read_text(encoding="utf-8"), str(VIP_SOURCE), "exec"), namespace)
    cpu_ids = [f"cpu-{index}" for index in range(5)]
    roles = namespace["assign_vip_cpu_roles"](cpu_ids)
    assert namespace["VIP_PRO_COUNT"] == 3
    assert namespace["VIP_TOP_PRO_COUNT"] == 2
    assert list(roles.values()).count("pro") == 3
    assert list(roles.values()).count("top_pro") == 2
    assert [namespace["vip_cpu_role_label"](r) for r in roles.values()].count("PRO") == 3
    assert [namespace["vip_cpu_role_label"](r) for r in roles.values()].count("TOP PRO") == 2
    assert all(namespace["vip_cpu_role_label"](r) in {"PRO", "TOP PRO"} for r in roles.values())
    assert namespace["validate_vip_cpu_roles"](cpu_ids, roles) is True
    invalid = dict(roles)
    invalid[cpu_ids[0]] = "top_pro" if roles[cpu_ids[0]] == "pro" else "pro"
    assert namespace["validate_vip_cpu_roles"](cpu_ids, invalid) is False


def test_vip_pro_and_top_pro_use_separate_simulation_budgets() -> None:
    join = source_of("_join_table")
    assert "VIP_PRO_SIMULATIONS = 1024" in TEXT
    assert "VIP_TOP_PRO_SIMULATIONS = 4096" in TEXT
    assert "VIP_TOP_PRO_SIMULATIONS" in join
    assert "VIP_PRO_SIMULATIONS" in join
    assert 'self.vip_cpu_roles.get(profile.cpu_id) == VIP_TOP_PRO_ROLE' in join
    assert "vip_cpu._vip_top_pro_mode" in join
    assert "vip_cpu._vip_pro_mode = True" in join
    assert '"aggressive"' in join
    assert "fixed 174-scenario preflop chart" in join
    assert "Local strategy, not solver-exact GTO" in join


def test_vip_has_distinct_private_club_window_and_table_surface() -> None:
    create = source_of("_create_table_window")
    draw = source_of("_draw_table")
    lobby = source_of("_build_lobby")
    buyin = source_of("_open_vip_buyin_dialog")
    assert "VIP PRIVATE CLUB" in create
    assert 'bg="#d9b96d"' in create
    assert 'header_bg = "#19070d" if vip_mode else "#080e19"' in create
    assert "P I G E O N   P R I V A T E   C L U B" in draw
    assert "vip_rail_double_line" in draw
    assert "vip_felt_gold_pinstripe" in draw
    assert 'text=vip_role_text' in draw
    assert '"TOP PRO"' in draw
    assert "THREE PRO  •  TWO TOP PRO" in lobby
    assert "PRO 1,024 SAMPLES" in lobby
    assert "TOP PRO 4,096 SAMPLES" in lobby
    assert "#71172c" in draw
    assert "#e2bd69" in draw
    assert "window._pigeon_vip_theme = vip_mode" in create
    assert "dock_bg = \"#19070d\" if vip_mode else COLORS[\"panel\"]" in create
    assert "VIP PRIVATE CLUB" in buyin
    assert "THREE PRO  •  TWO TOP PRO" in buyin
    assert "AUTO-REBUY BELOW 80 BB" in buyin


def test_normal_rush_cpu_settings_remain_unchanged() -> None:
    join = source_of("_join_table")
    assert "profile.level" in join
    assert "profile.archetype" in join
    assert "else 48" in join
    assert 'self.cash_cpu_profiles = {profile.cpu_id: profile for profile in profiles}' in join





def test_vip_auto_rebuy_below_80bb_targets_100bb_and_respects_wallet() -> None:
    namespace: dict[str, object] = {}
    exec(compile(VIP_SOURCE.read_text(encoding="utf-8"), str(VIP_SOURCE), "exec"), namespace)
    bb = 5000
    plan = namespace["make_vip_auto_rebuy_plan"](
        {"hero": 79 * bb, "cpu-low": 65 * bb, "cpu-zero": 0, "cpu-boundary": 80 * bb},
        bb, wallet_available_cents=21 * bb,
    )
    assert plan["threshold_cents"] == 80 * bb
    assert plan["target_cents"] == 100 * bb
    assert plan["targets"] == {
        "hero": 100 * bb, "cpu-low": 100 * bb, "cpu-zero": 100 * bb,
    }
    assert plan["cpu_rebuys"] == {"cpu-low": 35 * bb, "cpu-zero": 100 * bb}
    assert plan["hero_debit_cents"] == 21 * bb
    assert plan["hero_skipped_cents"] == 0
    short = namespace["make_vip_auto_rebuy_plan"](
        {"hero": 79 * bb, "cpu-low": 79 * bb}, bb, wallet_available_cents=0,
    )
    assert "hero" not in short["targets"]
    assert short["hero_skipped_cents"] == 21 * bb
    assert short["targets"]["cpu-low"] == 100 * bb


def test_vip_auto_rebuy_is_wired_before_new_hand() -> None:
    start = source_of("_start_cash_hand")
    assert "make_vip_auto_rebuy_plan(" in start
    assert "wallet_available_cents=self.cash_balance_cents" in start
    assert 'self.cash_table.next_hand(' in start
    assert 'rebuy_stacks=(vip_rebuy_plan or {}).get("targets", {})' in start
    assert '"auto-rebuy"' in start
    assert "HERO top-ups require sufficient wallet funds" in start

def run_tests() -> None:
    tests = [
        test_empty_bet_and_174_range_rows_are_removed_from_action_dock,
        test_vip_roles_assign_exactly_three_pro_and_two_top_pro,
        test_vip_pro_and_top_pro_use_separate_simulation_budgets,
        test_vip_auto_rebuy_below_80bb_targets_100bb_and_respects_wallet,
        test_vip_auto_rebuy_is_wired_before_new_hand,
        test_vip_has_distinct_private_club_window_and_table_surface,
        test_normal_rush_cpu_settings_remain_unchanged,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "VIP lineup, auto-rebuy, CPU tier, and action dock tests")


if __name__ == "__main__":
    run_tests()
