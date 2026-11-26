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


def run_tests() -> None:
    tests = [
        test_runout_street_order_is_flop_turn_river,
        test_run_it_twice_is_animated_in_two_complete_street_sequences,
        test_runout_renderer_keeps_future_cards_hidden_until_each_street,
        test_live_opponent_hole_cards_are_revealed_for_an_allin_showdown_only,
        test_each_new_hand_clears_previous_runout_presentation_state,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "all-in runout presentation tests")


if __name__ == "__main__":
    run_tests()
