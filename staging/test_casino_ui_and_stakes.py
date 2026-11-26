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


def test_nl500_and_nl1000_are_added_with_correct_blinds_and_buyins() -> None:
    assert '"NL500": (250, 500)' in TEXT
    assert '"NL1000": (500, 1000)' in TEXT
    lobby = source_of("_build_lobby")
    picker = source_of("_open_rush_stake_dialog")
    assert '("NL500", "$2.50 / $5.00")' in lobby
    assert '("NL1000", "$5.00 / $10.00")' in lobby
    assert '("NL500", "$2.50 / $5.00")' in picker
    assert '("NL1000", "$5.00 / $10.00")' in picker


def test_cpu_pool_has_independent_levels_for_the_two_new_stakes() -> None:
    assert '"NL500", "NL1000", VIP_STAKE_KEY' in TEXT
    settings = source_of("_build_settings_page")
    assert "values=list(self.cpu_pool_store.stakes)" in settings


def test_pokercraft_filter_labels_and_bb100_maps_include_new_stakes() -> None:
    assert TEXT.count('"NL500", "NL1000", "VIP25/50"') == 2
    labels = source_of("_pokercraft_blinds_label")
    assert '"NL500": "$2.50 / $5"' in labels
    assert '"NL1000": "$5 / $10"' in labels
    breakdown = source_of("_refresh_pokercraft_breakdowns")
    historical = source_of("_historical_preflop_range_chart")
    assert '"NL500": 500' in breakdown and '"NL1000": 1000' in breakdown
    assert '"NL500": 500' in historical and '"NL1000": 1000' in historical


def test_casino_page_is_navigable_and_built_at_startup() -> None:
    assert '("CASINO", "casino")' in TEXT
    init = TEXT[TEXT.index("self._build_shell()"):TEXT.index("self.protocol(")]
    assert "self._build_casino_page()" in init
    page = source_of("_build_casino_page")
    assert "BLACKJACK" in page and "BACCARAT" in page
    assert "self._make_scrollable_tab" in page
    assert "self.casino_history_tree" in page


def test_blackjack_uses_full_hand_actions_and_saves_unfinished_round() -> None:
    start = source_of("_casino_start_blackjack")
    action = source_of("_casino_blackjack_action")
    save = source_of("_casino_save_blackjack_state")
    assert "new_blackjack_round" in start
    assert "blackjack_hit(state)" in action
    assert "blackjack_stand(state)" in action
    assert "blackjack_double(state)" in action
    assert "serialize_blackjack_state" in save
    assert "restore_blackjack_state" in TEXT


def test_baccarat_uses_standard_punto_banco_engine_and_three_bets() -> None:
    page = source_of("_build_casino_page")
    play = source_of("_casino_play_baccarat")
    assert "BET PLAYER" in page and "BET BANKER" in page and "BET TIE" in page
    assert "new_baccarat_round" in play
    assert "0.95:1 after 5% commission" in page
    assert "Tie pays 8:1" in page


def test_casino_wagers_and_payouts_use_shared_wallet_but_not_poker_pnl() -> None:
    debit = source_of("_casino_debit_wager")
    credit = source_of("_casino_credit_payout")
    poker_pnl = source_of("_cashier_poker_pnl_cents")
    casino_pnl = source_of("_refresh_casino_display")
    assert '"casino-wager"' in debit
    assert '"casino-payout"' in credit
    assert '"buy-in", "manual-rebuy", "auto-rebuy", "cash-out"' in poker_pnl
    assert '"casino-wager", "casino-payout"' in casino_pnl


def test_casino_rejects_sub_minimum_or_fractional_cent_wagers() -> None:
    parser = source_of("_parse_casino_bet")
    assert "Decimal(raw)" in parser
    assert "result < 100" in parser
    assert "cents != cents.to_integral_value()" in parser


def run_tests() -> None:
    tests = [
        test_nl500_and_nl1000_are_added_with_correct_blinds_and_buyins,
        test_cpu_pool_has_independent_levels_for_the_two_new_stakes,
        test_pokercraft_filter_labels_and_bb100_maps_include_new_stakes,
        test_casino_page_is_navigable_and_built_at_startup,
        test_blackjack_uses_full_hand_actions_and_saves_unfinished_round,
        test_baccarat_uses_standard_punto_banco_engine_and_three_bets,
        test_casino_wagers_and_payouts_use_shared_wallet_but_not_poker_pnl,
        test_casino_rejects_sub_minimum_or_fractional_cent_wagers,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "casino integration tests")


if __name__ == "__main__":
    run_tests()
