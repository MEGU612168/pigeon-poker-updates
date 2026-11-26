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


def test_casino_pages_use_real_graphical_canvases() -> None:
    page = source_of("_build_casino_page")
    assert page.count("tk.Canvas(") == 2
    assert "self.blackjack_table_canvas" in page
    assert "self.baccarat_table_canvas" in page
    assert '"<Configure>"' in page
    assert "self._casino_draw_blackjack_table()" in page
    assert "self._casino_draw_baccarat_table()" in page


def test_playing_cards_have_front_and_back_artwork() -> None:
    draw = source_of("_casino_draw_card")
    assert "canvas.create_rectangle" in draw
    assert "canvas.create_polygon" in draw
    assert "canvas.create_text" in draw
    assert "face_up" in draw
    assert "Segoe UI Symbol" in draw
    assert "♥" in draw and "♦" in draw


def test_card_row_reveals_multiple_cards_in_position() -> None:
    draw = source_of("_casino_draw_card_row")
    assert "visible_count" in draw
    assert "face_down_indices" in draw
    assert "self._casino_draw_card(" in draw


def test_chips_are_rendered_as_visual_tokens() -> None:
    draw = source_of("_casino_draw_chip")
    assert draw.count("canvas.create_oval") >= 3
    assert "canvas.create_line" in draw
    assert "canvas.create_text" in draw


def test_blackjack_table_shows_dealer_player_wager_and_shoe() -> None:
    draw = source_of("_casino_draw_blackjack_table")
    for token in ("DEALER", "PLAYER", "SHOE", "blackjack_total", "_casino_draw_card_row", "_casino_draw_chip"):
        assert token in draw


def test_baccarat_table_has_separate_player_and_banker_zones() -> None:
    draw = source_of("_casino_draw_baccarat_table")
    assert "player_center" in draw and "banker_center" in draw
    assert "PLAYER" in draw and "BANKER" in draw
    assert "PLAYER" in draw and "BANKER" in draw and "TIE" in draw
    assert "self._casino_draw_card_row(" in draw
    assert "state['bet_side']" in draw


def test_blackjack_cards_are_revealed_in_stages() -> None:
    animate = source_of("_casino_animate_blackjack_to_state")
    assert "steps.append" in animate
    assert "self.after(" in animate
    assert "self.blackjack_visible_player_cards" in animate
    assert "self.blackjack_visible_dealer_cards" in animate


def test_baccarat_cards_are_revealed_in_stages() -> None:
    animate = source_of("_casino_animate_baccarat_to_state")
    assert "steps.append" in animate
    assert "self.after(" in animate
    assert "self.baccarat_visible_player_cards" in animate
    assert "self.baccarat_visible_banker_cards" in animate


def test_blackjack_input_is_locked_during_the_deal_animation() -> None:
    start = source_of("_casino_start_blackjack")
    action = source_of("_casino_blackjack_action")
    refresh = source_of("_refresh_casino_display")
    assert "self._casino_animate_blackjack_to_state(" in start
    assert "self.blackjack_dealing" in action
    assert 'state=("disabled" if active or self.blackjack_dealing else "normal")' in refresh


def test_baccarat_betting_is_locked_during_the_deal_animation() -> None:
    play = source_of("_casino_play_baccarat")
    refresh = source_of("_refresh_casino_display")
    assert "if self.baccarat_dealing:" in play
    assert "self._casino_animate_baccarat_to_state()" in play
    assert '("disabled" if self.baccarat_dealing else "normal")' in refresh


def test_270_dollar_refund_is_atomic_and_audited_once() -> None:
    refund = source_of("_apply_one_time_270_dollar_casino_test_refund")
    assert "amount_cents = 27_000" in refund
    assert "pigeon_poker_v1_5_16_casino_test_refund_270_usd" in refund
    assert "pigeon-poker-v1.5.16-casino-test-refund-270-usd" in refund
    assert 'con.execute("BEGIN IMMEDIATE")' in refund
    assert "wallet_meta" in refund
    assert '"casino-test-refund"' in refund
    assert 'con.execute("COMMIT")' in refund
    assert "reset_for_test_stage" not in refund


def test_refund_is_applied_once_during_startup_without_changing_poker_pnl() -> None:
    init = source_of("__init__")
    assert init.count("self._apply_one_time_270_dollar_casino_test_refund()") == 1
    poker_pnl = source_of("_cashier_poker_pnl_cents")
    assert '"casino-test-refund"' not in poker_pnl


TESTS = [
    test_casino_pages_use_real_graphical_canvases,
    test_playing_cards_have_front_and_back_artwork,
    test_card_row_reveals_multiple_cards_in_position,
    test_chips_are_rendered_as_visual_tokens,
    test_blackjack_table_shows_dealer_player_wager_and_shoe,
    test_baccarat_table_has_separate_player_and_banker_zones,
    test_blackjack_cards_are_revealed_in_stages,
    test_baccarat_cards_are_revealed_in_stages,
    test_blackjack_input_is_locked_during_the_deal_animation,
    test_baccarat_betting_is_locked_during_the_deal_animation,
    test_270_dollar_refund_is_atomic_and_audited_once,
    test_refund_is_applied_once_during_startup_without_changing_poker_pnl,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(TESTS), "casino visual UI tests")
