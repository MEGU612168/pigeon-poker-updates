from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"
TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(TEXT, filename=str(SOURCE))


def method(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing method: {name}")


def source_of(name: str) -> str:
    return ast.get_source_segment(TEXT, method(name)) or ""


def test_runout_street_order_is_flop_turn_river() -> None:
    assignment = next(
        node for node in TREE.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "RUNOUT_REVEAL_STAGES"
                for target in node.targets)
    )
    assert ast.literal_eval(assignment.value) == (
        ("FLOP", 0, 3), ("TURN", 3, 4), ("RIVER", 4, 5)
    )


def test_run_it_twice_is_animated_in_two_complete_street_sequences() -> None:
    resolve = source_of("_resolve_allin_decision")
    start = source_of("_animate_multi_runout_reveal")
    step = source_of("_multi_runout_reveal_step")
    frame = source_of("_multi_runout_reveal_frame")
    assert "self._animate_multi_runout_reveal(table_id, runout_boards)" in resolve
    assert "self.cash_visible_board = list(hand.board)" not in resolve
    assert "cash_runout_reveal_counts" in start
    assert "cash_runout_boards_for_reveal" in start
    assert "OPPONENT CARDS REVEALED" in start
    assert "RUNOUT_REVEAL_STAGES" in step
    assert "BOARD {board_index + 1} • {stage_name}" in step
    assert "FLOP_REVEAL_FRAMES" in frame
    assert "STREET_REVEAL_FRAMES" in frame
    assert "cash_runout_reveal_counts" in frame
    assert "_finish_allin_runout_reveal" in step
    assert "self._update_cash_after_action()" in source_of("_finish_allin_runout_reveal")


def test_runout_renderer_keeps_future_cards_hidden_until_each_street() -> None:
    draw = source_of("_draw_table")
    assert "cash_runout_reveal_counts" in draw
    assert "cash_runout_reveal_anim" in draw
    assert "self._draw_card_3d(" in draw
    assert "self._draw_card_back(canvas, card_x, row_y, run_card_w, run_card_h)" in draw
    assert "RUN IT {len(runout_boards_for_display)}×  •  {runout_phase" in draw


def test_live_opponent_hole_cards_are_revealed_for_an_allin_showdown_only() -> None:
    draw = source_of("_draw_table")
    assert "cash_runout_show_hole_cards" in draw
    assert "len(player.hole_cards) == 2 and not player.folded" in draw
    assert "hand.winner_reason == \"showdown\" and player.eligible" in draw
    assert "self._draw_card(canvas, x-50, y+38, player.hole_cards[0], 42, 58)" in draw


def test_each_new_hand_clears_previous_runout_presentation_state() -> None:
    start = source_of("_start_cash_hand")
    assert 'active_state["cash_runout_show_hole_cards"] = False' in start
    assert 'active_state["cash_runout_reveal_counts"] = []' in start
    assert 'active_state["cash_runout_reveal_anim"] = None' in start
    assert 'active_state["cash_runout_phase"] = ""' in start



def test_runout_progress_survives_table_switch_snapshot() -> None:
    snapshot = source_of("_cash_state_snapshot")
    for field in (
        "cash_runout_show_hole_cards",
        "cash_runout_reveal_counts",
        "cash_runout_reveal_anim",
        "cash_runout_boards_for_reveal",
        "cash_runout_phase",
        "cash_runout_reveal_pending",
    ):
        assert f'"{field}"' in snapshot


def test_pot_award_waits_until_runout_animation_finishes() -> None:
    refresh = source_of("_refresh_table_windows")
    finish = source_of("_finish_allin_runout_reveal")
    assert 'not bool(state.get("cash_runout_reveal_pending", False))' in refresh
    assert 'slot.state["cash_runout_reveal_pending"] = False' in finish
    assert "self._update_cash_after_action()" in finish


def test_live_hole_cards_are_rendered_before_the_run_it_choice_dialog() -> None:
    show = source_of("_show_allin_decision")
    assert show.index('state["cash_runout_show_hole_cards"] = True') < show.index('dialog = tk.Toplevel(parent)')
    assert 'state["cash_runout_phase"] = "HANDS REVEALED • CHOOSE RUNOUT"' in show
    assert "ALLIN_RUNOUT_HOLE_REVEAL_PAUSE_MS" in show
    assert "Both hands are open. Choose how many times" in show
    assert "cash_runout_pre_settlement_stacks" in show


def test_every_allin_requires_an_explicit_runout_choice_without_timeout() -> None:
    show = source_of("_show_allin_decision")
    assert "RUN IT ONCE" in show
    assert "RUN IT TWICE" in show
    assert "RUN IT THREE TIMES" in show
    assert "cash_run_it_preference" not in show
    assert "18000" not in show
    assert "_auto_resolve_runout" not in show
    assert "No automatic runout" in show


def test_single_and_multiple_runouts_use_the_same_staged_reveal_path() -> None:
    resolve = source_of("_resolve_allin_decision")
    start = source_of("_animate_multi_runout_reveal")
    assert "self._animate_multi_runout_reveal(table_id, runout_boards)" in resolve
    assert "self._animate_board_reveal(" not in resolve
    assert "if len(boards) < 1:" in start
    assert "cash_runout_boards_for_reveal" in start


def test_allin_runout_has_deliberate_hole_flop_turn_river_and_board_pauses() -> None:
    constants = {}
    for node in TREE.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    if target.id.startswith("ALLIN_RUNOUT_"):
                        constants[target.id] = ast.literal_eval(node.value)
    assert constants["ALLIN_RUNOUT_HOLE_REVEAL_PAUSE_MS"] >= 900
    assert constants["ALLIN_RUNOUT_FLOP_TO_TURN_PAUSE_MS"] >= 1200
    assert constants["ALLIN_RUNOUT_TURN_TO_RIVER_PAUSE_MS"] >= 1600
    assert constants["ALLIN_RUNOUT_BETWEEN_BOARDS_PAUSE_MS"] >= 1300
    assert constants["ALLIN_RUNOUT_FLOP_FRAMES"] >= 16
    assert constants["ALLIN_RUNOUT_STREET_FRAMES"] >= 16
    assert constants["ALLIN_RUNOUT_FLOP_FRAME_MS"] >= 40
    assert constants["ALLIN_RUNOUT_STREET_FRAME_MS"] >= 45
    frame = source_of("_multi_runout_reveal_frame")
    assert "ALLIN_RUNOUT_FLOP_FRAMES" in frame
    assert "ALLIN_RUNOUT_STREET_FRAMES" in frame
    assert "next_card_index == 3" in frame
    assert "next_card_index == 4" in frame
    assert "ALLIN_RUNOUT_FLOP_TO_TURN_PAUSE_MS" in frame
    assert "ALLIN_RUNOUT_TURN_TO_RIVER_PAUSE_MS" in frame


def test_result_banner_pot_paid_and_made_hand_rank_wait_until_runout_finishes() -> None:
    draw = source_of("_draw_table")
    assert 'and not runout_reveal_pending' in draw
    assert 'if hand.finished and hand.winner_reason == "showdown" and not runout_reveal_pending:' in draw
    assert '"POT PAID" if hand.finished' in draw
    assert "cash_runout_reveal_pending" in draw
    finish = source_of("_finish_allin_runout_reveal")
    assert 'slot.state["cash_runout_reveal_pending"] = False' in finish
    assert "self._update_cash_after_action()" in finish


def test_stacks_and_pot_remain_at_pre_showdown_values_while_cards_are_hidden() -> None:
    draw = source_of("_draw_table")
    assert "pre_settlement_stacks = special_state.get" in draw
    assert "display_stack = (int(pre_settlement_stacks.get" in draw
    assert "if runout_reveal_pending else int(player.stack)" in draw
    assert "pre_settlement_pot = special_state.get" in draw
    assert "display_pot = int(pre_settlement_pot)" in draw
    assert "self._format_table_chips(display_pot, table.big_blind)" in draw


def test_suspense_state_survives_table_switch_and_resets_on_the_next_hand() -> None:
    snapshot = source_of("_cash_state_snapshot")
    start = source_of("_start_cash_hand")
    for field in (
        "cash_runout_pre_settlement_stacks",
        "cash_runout_pre_settlement_pot",
        "cash_runout_prompt_token",
    ):
        assert f'"{field}"' in snapshot
        assert f'active_state["{field}"]' in start


def run_tests() -> None:
    tests = [
        test_runout_street_order_is_flop_turn_river,
        test_run_it_twice_is_animated_in_two_complete_street_sequences,
        test_runout_renderer_keeps_future_cards_hidden_until_each_street,
        test_live_opponent_hole_cards_are_revealed_for_an_allin_showdown_only,
        test_each_new_hand_clears_previous_runout_presentation_state,
        test_runout_progress_survives_table_switch_snapshot,
        test_pot_award_waits_until_runout_animation_finishes,
        test_live_hole_cards_are_rendered_before_the_run_it_choice_dialog,
        test_every_allin_requires_an_explicit_runout_choice_without_timeout,
        test_single_and_multiple_runouts_use_the_same_staged_reveal_path,
        test_allin_runout_has_deliberate_hole_flop_turn_river_and_board_pauses,
        test_result_banner_pot_paid_and_made_hand_rank_wait_until_runout_finishes,
        test_stacks_and_pot_remain_at_pre_showdown_values_while_cards_are_hidden,
        test_suspense_state_survives_table_switch_and_resets_on_the_next_hand,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "all-in runout presentation tests")


if __name__ == "__main__":
    run_tests()
