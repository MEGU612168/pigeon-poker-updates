from __future__ import annotations

from pathlib import Path
import importlib.util
import sys

MODULE = Path(__file__).with_name("source_1_3_101") / "pigeon_poker" / "casino_games.py"
SPEC = importlib.util.spec_from_file_location("pigeon_casino_games_test", MODULE)
assert SPEC is not None and SPEC.loader is not None
casino = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = casino
SPEC.loader.exec_module(casino)

Card = casino.Card


def shoe_in_draw_order(*cards: Card) -> list[Card]:
    # Engine draws with pop(); the final supplied card is dealt first.
    return list(reversed(cards))


def test_six_deck_shoe_has_312_cards_and_valid_cards() -> None:
    shoe = casino.create_shoe(decks=6)
    assert len(shoe) == 312
    assert all(card.rank in casino.RANKS and card.suit in casino.SUITS for card in shoe)


def test_blackjack_natural_pays_three_to_two() -> None:
    state = casino.new_blackjack_round(
        1000,
        shoe=shoe_in_draw_order(
            Card("A", "♠"), Card("9", "♣"), Card("K", "♥"), Card("7", "♦")
        ),
    )
    assert state["status"] == "settled"
    assert state["result"] == "BLACKJACK • 3:2"
    assert state["payout_cents"] == 2500
    assert state["dealer_hole_revealed"] is True


def test_blackjack_both_naturals_push() -> None:
    state = casino.new_blackjack_round(
        1000,
        shoe=shoe_in_draw_order(
            Card("A", "♠"), Card("A", "♣"), Card("K", "♥"), Card("Q", "♦")
        ),
    )
    assert state["result"] == "PUSH • BOTH BLACKJACK"
    assert state["payout_cents"] == 1000


def test_blackjack_soft_ace_can_convert_to_hard_ace() -> None:
    assert casino.blackjack_total([Card("A", "♠"), Card("6", "♥")]) == (17, True)
    assert casino.blackjack_total([Card("A", "♠"), Card("6", "♥"), Card("10", "♦")]) == (17, False)


def test_blackjack_hit_busts_and_returns_no_payout() -> None:
    state = casino.new_blackjack_round(
        1000,
        shoe=shoe_in_draw_order(
            Card("10", "♠"), Card("6", "♣"), Card("8", "♥"), Card("10", "♦"),
            Card("5", "♠"),
        ),
    )
    casino.blackjack_hit(state)
    assert state["status"] == "settled"
    assert state["result"] == "BUST"
    assert state["payout_cents"] == 0


def test_blackjack_double_down_doubles_wager_and_takes_one_card() -> None:
    state = casino.new_blackjack_round(
        1000,
        shoe=shoe_in_draw_order(
            Card("5", "♠"), Card("6", "♣"), Card("6", "♥"), Card("10", "♦"),
            Card("10", "♠"), Card("2", "♣"),
        ),
    )
    casino.blackjack_double(state)
    assert state["doubled"] is True
    assert state["bet_cents"] == 2000
    assert state["result"] == "PLAYER WIN"
    assert state["payout_cents"] == 4000


def test_double_down_is_not_available_after_a_hit() -> None:
    state = casino.new_blackjack_round(
        1000,
        shoe=shoe_in_draw_order(
            Card("5", "♠"), Card("6", "♣"), Card("6", "♥"), Card("10", "♦"),
            Card("2", "♠"), Card("3", "♣"), Card("4", "♥"),
        ),
    )
    casino.blackjack_hit(state)
    try:
        casino.blackjack_double(state)
    except ValueError:
        pass
    else:
        raise AssertionError("Double down after a hit must be rejected")


def test_baccarat_natural_nine_wins_and_banker_gets_commission() -> None:
    state = casino.new_baccarat_round(
        1000, "banker",
        shoe=shoe_in_draw_order(
            Card("8", "♠"), Card("8", "♣"), Card("K", "♥"), Card("A", "♦")
        ),
    )
    assert state["winner"] == "banker"
    assert state["banker_total"] == 8
    assert state["payout_cents"] == 1950


def test_baccarat_tie_bet_pays_eight_to_one_profit() -> None:
    state = casino.new_baccarat_round(
        1000, "tie",
        shoe=shoe_in_draw_order(
            Card("9", "♠"), Card("9", "♣"), Card("K", "♥"), Card("Q", "♦")
        ),
    )
    assert state["winner"] == "tie"
    assert state["payout_cents"] == 9000


def test_baccarat_player_or_banker_bet_pushes_on_tie() -> None:
    state = casino.new_baccarat_round(
        1000, "player",
        shoe=shoe_in_draw_order(
            Card("9", "♠"), Card("9", "♣"), Card("K", "♥"), Card("Q", "♦")
        ),
    )
    assert state["winner"] == "tie"
    assert state["payout_cents"] == 1000


def test_baccarat_player_third_card_causes_correct_banker_draw() -> None:
    state = casino.new_baccarat_round(
        1000, "player",
        shoe=shoe_in_draw_order(
            Card("2", "♠"), Card("2", "♣"), Card("3", "♥"), Card("2", "♦"),
            Card("4", "♠"), Card("6", "♣"),
        ),
    )
    assert len(state["player_cards"]) == 3
    assert len(state["banker_cards"]) == 3
    assert state["player_total"] == 9
    assert state["banker_total"] == 0
    assert state["winner"] == "player"
    assert state["payout_cents"] == 2000


def test_baccarat_banker_draw_table_edges() -> None:
    assert casino.baccarat_banker_should_draw(0, 9)
    assert casino.baccarat_banker_should_draw(2, 8)
    assert not casino.baccarat_banker_should_draw(3, 8)
    assert casino.baccarat_banker_should_draw(3, 7)
    assert not casino.baccarat_banker_should_draw(4, 1)
    assert casino.baccarat_banker_should_draw(4, 2)
    assert not casino.baccarat_banker_should_draw(5, 3)
    assert casino.baccarat_banker_should_draw(5, 4)
    assert casino.baccarat_banker_should_draw(6, 6)
    assert not casino.baccarat_banker_should_draw(6, 5)
    assert not casino.baccarat_banker_should_draw(7, None)
    assert casino.baccarat_banker_should_draw(5, None)


def test_invalid_bets_and_baccarat_selection_are_rejected() -> None:
    for amount in (0, 99, -100):
        try:
            casino.new_blackjack_round(amount)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid bet was accepted: {amount}")
    try:
        casino.new_baccarat_round(100, "dragon")
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid baccarat side was accepted")



def test_blackjack_round_can_be_saved_and_resumed() -> None:
    state = casino.new_blackjack_round(
        1200,
        shoe=shoe_in_draw_order(
            Card("10", "♠"), Card("6", "♣"), Card("7", "♥"), Card("10", "♦"),
            Card("2", "♠"), Card("3", "♣"),
        ),
    )
    saved = casino.serialize_blackjack_state(state)
    restored = casino.restore_blackjack_state(saved)
    assert restored is not None
    assert restored["bet_cents"] == 1200
    assert restored["status"] == "playing"
    assert restored["player_cards"] == state["player_cards"]
    assert restored["dealer_cards"] == state["dealer_cards"]
    assert restored["shoe"] == state["shoe"]
    casino.blackjack_hit(restored)
    assert len(restored["player_cards"]) == 3

def run_tests() -> None:
    tests = [
        test_six_deck_shoe_has_312_cards_and_valid_cards,
        test_blackjack_natural_pays_three_to_two,
        test_blackjack_both_naturals_push,
        test_blackjack_soft_ace_can_convert_to_hard_ace,
        test_blackjack_hit_busts_and_returns_no_payout,
        test_blackjack_double_down_doubles_wager_and_takes_one_card,
        test_double_down_is_not_available_after_a_hit,
        test_baccarat_natural_nine_wins_and_banker_gets_commission,
        test_baccarat_tie_bet_pays_eight_to_one_profit,
        test_baccarat_player_or_banker_bet_pushes_on_tie,
        test_baccarat_player_third_card_causes_correct_banker_draw,
        test_baccarat_banker_draw_table_edges,
        test_invalid_bets_and_baccarat_selection_are_rejected,
        test_blackjack_round_can_be_saved_and_resumed,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "casino rules tests")


if __name__ == "__main__":
    run_tests()
