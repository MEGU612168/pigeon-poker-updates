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
    assert 'size_actions.configure(height=34)' in create
    assert 'situation_actions.configure(height=24)' in create
    assert '("size_actions", "situation_actions", 34)' in refresh
    assert '("situation_actions", "utility_actions", 24)' in refresh
    assert "dock_row.winfo_children()" in refresh
    assert "dock_row.pack_forget()" in refresh
    assert 'before=before_row' in refresh


def test_vip_roles_assign_all_five_opponents_to_pro_only() -> None:
    namespace: dict[str, object] = {}
    exec(compile(VIP_SOURCE.read_text(encoding="utf-8"), str(VIP_SOURCE), "exec"), namespace)
    cpu_ids = [f"cpu-{index}" for index in range(5)]
    roles = namespace["assign_vip_cpu_roles"](cpu_ids)
    assert namespace["VIP_PRO_ROLE"] == "pro_only"
    assert namespace["VIP_PURE_GTO_COUNT"] == 5
    assert namespace["VIP_NEAR_GTO_COUNT"] == 0
    assert set(roles.values()) == {"pro_only"}
    assert all(namespace["vip_cpu_role_label"](role) == "PRO ONLY" for role in roles.values())
    assert namespace["validate_vip_cpu_roles"](cpu_ids, roles) is True
    weaker = dict(roles)
    weaker["cpu-0"] = "near_gto"
    assert namespace["validate_vip_cpu_roles"](cpu_ids, weaker) is False


def test_vip_runtime_uses_maximum_cpu_level_and_increased_postflop_samples() -> None:
    join = source_of("_join_table")
    assert "VIP_PRO_SIMULATIONS = 256" in TEXT
    assert "level=(5 if is_vip_mode(table_mode) else profile.level)" in join
    assert "simulations=(VIP_PRO_SIMULATIONS if is_vip_mode(table_mode) else 48)" in join
    assert "assign_vip_cpu_roles(" in join
    assert "VIP_NEAR_GTO_COUNT" in join
    assert "fixed 174-scenario preflop chart" in join
    assert "Local strategy, not solver-exact GTO" in join


def test_vip_has_distinct_private_club_window_and_table_surface() -> None:
    create = source_of("_create_table_window")
    draw = source_of("_draw_table")
    lobby = source_of("_build_lobby")
    buyin = source_of("_open_vip_buyin_dialog")
    assert "VIP PRIVATE CLUB" in create
    assert 'bg="#caa45f"' in create
    assert 'header_bg = "#090b10" if vip_mode' in create
    assert "VIP PRIVATE CLUB" in draw
    assert "vip_rail_double_line" in draw
    assert "vip_felt_gold_pinstripe" in draw
    assert 'text="PRO ONLY"' in draw
    assert "PRO ONLY  •  FIVE LEVEL-5 OPPONENTS" in lobby
    assert "VIP PRIVATE CLUB" in buyin


def test_normal_rush_cpu_settings_remain_unchanged() -> None:
    join = source_of("_join_table")
    assert "profile.level" in join
    assert "profile.archetype" in join
    assert "else 48" in join
    assert 'self.cash_cpu_profiles = {profile.cpu_id: profile for profile in profiles}' in join


def run_tests() -> None:
    tests = [
        test_empty_bet_and_174_range_rows_are_removed_from_action_dock,
        test_vip_roles_assign_all_five_opponents_to_pro_only,
        test_vip_runtime_uses_maximum_cpu_level_and_increased_postflop_samples,
        test_vip_has_distinct_private_club_window_and_table_surface,
        test_normal_rush_cpu_settings_remain_unchanged,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "VIP pro lineup and action dock tests")


if __name__ == "__main__":
    run_tests()
