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


def test_pokercraft_has_sortable_session_and_hand_headers():
    build = source_of("_build_pokercraft_page")
    sessions = source_of("_sort_pokercraft_sessions")
    hands = source_of("_sort_pokercraft_hands")
    assert "TIME (JST)" in build
    assert "BLINDS" in build and "DURATION" in build and "WIN / LOSS" in build
    assert '"Hole Cards"' in build and '"Position"' in build and '"Opponents"' in build
    assert "_sort_pokercraft_sessions" in build
    assert "_sort_pokercraft_hands" in build
    for body in (sessions, hands):
        assert "self.poker_" in body and "sort_reverse" in body
        assert "not bool(" in body
        assert "False" in body  # first click is ascending


def test_hole_cards_tab_aggregates_suited_offsuit_and_pair_classes():
    build = source_of("_build_pokercraft_page")
    parser = source_of("_pokercraft_hand_class")
    refresh = source_of("_refresh_pokercraft")
    aggregate = source_of("_refresh_pokercraft_hole_cards")
    assert '"Hole Cards"' in build
    assert "poker_hole_cards_tree" in build
    assert "_refresh_pokercraft_hole_cards(filtered)" in refresh
    assert "re.findall" in parser and "rank_order" in parser
    assert '("s" if suit_a == suit_b else "o")' in parser
    assert "return rank_a * 2" in parser
    assert "winrate" in aggregate and "avgpot" in source_of("_render_pokercraft_hole_cards")


def test_all_pokercraft_timestamps_use_japan_time():
    formatter = source_of("_format_pokercraft_jst")
    parser = source_of("_pokercraft_parse_timestamp")
    assert "timedelta(hours=9)" in formatter + parser
    assert "astimezone" in formatter
    refresh = source_of("_refresh_pokercraft")
    assert "_format_pokercraft_jst" in refresh


def test_history_icon_draws_two_real_playing_cards_tilted_left():
    build = source_of("_create_table_window")
    draw = source_of("_draw_history_cards_icon")
    rotate = source_of("_rotate_card_points")
    assert "history_icon" in build and "_draw_history_cards_icon(history_icon)" in build
    assert "range_icon" in build and "_draw_range_grid_icon(range_icon" in build
    assert "canvas.create_polygon" in draw
    assert "♠" in draw
    assert '"#ffffff"' in draw.lower() or "'#ffffff'" in draw.lower()
    assert "-10.0" in draw
    assert "math.radians" in rotate
    assert "copy" not in draw.lower()


def test_live_hand_flow_shows_scrollable_table_history_with_cards_winner_and_pot():
    flow = source_of("_open_live_hand_flow")
    assert "self.history_store.list_recent(5000)" in flow
    assert 'row.get("table_id")' in flow
    assert "WINNER" in flow and "POT" in flow and "HOLE CARDS" in flow
    assert "self._draw_card(" in flow
    assert "rows_host" in flow and "scrollregion" in flow
    assert "win.after(1800, render)" in flow
    assert "pot_award" in flow and "hand_won_by_fold" in flow


def test_range_view_is_only_a_169_cell_proportional_matrix():
    view = source_of("_open_preflop_range_view")
    assert 'len(order) != 169' in view
    assert 'canvas.create_rectangle(' in view
    assert 'frequency / total' in view
    assert 'text=str(hand_class)' in view
    assert '"#e05252"' in view and '"#45a879"' in view and '"#438ac5"' in view
    assert "meta = tk.Frame" not in view
    assert "footer = tk.Frame" not in view


def test_range_icon_stays_clickable_and_explains_unavailable_nodes():
    updater = source_of("_update_range_icon_state")
    opener = source_of("_open_realtime_preflop_range")
    assert 'canvas.configure(state="normal", cursor="hand2")' in updater
    assert "この状況に一致する画像由来レンジはありません。" in opener
    assert "レンジ料金は発生していません。" in opener


def test_live_range_button_requires_exact_node_and_current_hero_turn():
    resolver = source_of("_range_chart_for_table")
    updater = source_of("_update_range_icon_state")
    opener = source_of("_open_realtime_preflop_range")
    assert "preflop_gto_range_for_situation" in resolver
    assert "finished" in resolver
    assert "next_to_act" in resolver and '"hero"' in resolver
    assert "chart is None" in opener and "return" in opener
    assert "state=" in updater and "enabled" in updater
    assert "_range_chart_for_table" in updater


def test_live_range_charges_shared_wallet_once_per_hand_not_stack():
    opener = source_of("_open_realtime_preflop_range")
    debit = source_of("_debit_live_range_review")
    assert "range_paid_hand_key" in opener
    assert "if not paid" in opener
    assert "_debit_live_range_review" in opener
    assert "big_blind" in opener
    assert "BEGIN IMMEDIATE" in debit
    assert "SELECT balance_cents FROM wallet_account" in debit
    assert "UPDATE wallet_account SET balance_cents" in debit
    assert "INSERT INTO cashier_transactions" in debit
    assert '"preflop-range-review"' in debit
    assert "hand.stack" not in debit and "player.stack" not in debit
    assert "range_paid_hand_key" in source_of("_cash_state_snapshot")


def test_historical_range_uses_only_events_before_hero_first_action():
    helper = source_of("_historical_preflop_range_chart")
    opener = source_of("_open_pokercraft_history_range")
    assert "hero_decision_index" in helper
    assert "normalized_events[:hero_decision_index]" in helper
    assert "preflop_gto_range_for_situation" in helper
    assert "return None" in helper
    assert "Historical review • FREE" in opener


def test_pokercraft_refreshes_live_without_blocking_table_play():
    timer = source_of("_tick_pokercraft_live_refresh")
    hand_end = TEXT[TEXT.find('self.history_store.save('):TEXT.find('self.history_store.save(')+1800]
    assert "list_recent(1)" in timer
    assert "self.after(1800, self._tick_pokercraft_live_refresh)" in timer
    assert 'self.after(80, self._refresh_pokercraft)' in hand_end


def run_tests():
    tests = [
        test_pokercraft_has_sortable_session_and_hand_headers,
        test_all_pokercraft_timestamps_use_japan_time,
        test_history_icon_draws_two_real_playing_cards_tilted_left,
        test_live_hand_flow_shows_scrollable_table_history_with_cards_winner_and_pot,
        test_range_view_is_only_a_169_cell_proportional_matrix,
        test_range_icon_stays_clickable_and_explains_unavailable_nodes,
        test_live_range_button_requires_exact_node_and_current_hero_turn,
        test_live_range_charges_shared_wallet_once_per_hand_not_stack,
        test_historical_range_uses_only_events_before_hero_first_action,
        test_pokercraft_refreshes_live_without_blocking_table_play,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "PokerCraft / live flow / range viewer tests")


if __name__ == "__main__":
    run_tests()


def test_live_preflop_range_is_an_overlay_and_pauses_the_action_clock():
    view = source_of("_open_preflop_range_view")
    assert "table_canvas.winfo_toplevel()" in view
    assert "win.overrideredirect(True)" not in view
    assert 'win.attributes("-topmost", True)' not in view
    assert "win.update_idletasks()" in view
    assert "win.after(80, draw)" in view
    assert "charge_label" in view
    assert "cash_squeeze_deadline_at" in view
    assert "paused_clock" in view
    assert "close_range_overlay" in view
    assert "resumed_deadline = time.monotonic() + paused_clock[\"remaining\"]" in view
