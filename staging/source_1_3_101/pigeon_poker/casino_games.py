from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Any


RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUITS = ("♠", "♥", "♦", "♣")
RED_SUITS = frozenset(("♥", "♦"))


@dataclass(frozen=True, slots=True)
class Card:
    rank: str
    suit: str

    @property
    def label(self) -> str:
        return f"{self.rank}{self.suit}"


def card_label(card: Card) -> str:
    if not isinstance(card, Card):
        raise TypeError("card must be a Card")
    return card.label


def create_shoe(*, decks: int = 6, rng=None) -> list[Card]:
    """Create and shuffle a multi-deck casino shoe."""
    count = int(decks)
    if count < 1 or count > 8:
        raise ValueError("decks must be between 1 and 8")
    generator = rng or random.SystemRandom()
    cards = [Card(rank, suit) for _ in range(count) for suit in SUITS for rank in RANKS]
    generator.shuffle(cards)
    return cards


def _draw(shoe: list[Card]) -> Card:
    if not shoe:
        raise RuntimeError("The shoe is empty")
    return shoe.pop()


def _validate_bet(bet_cents: int) -> int:
    try:
        amount = int(bet_cents)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Bet must be an integer number of cents") from exc
    if amount < 100:
        raise ValueError("The minimum casino bet is $1.00")
    if amount > 100_000_000:
        raise ValueError("The maximum casino bet is $1,000,000.00")
    return amount


def _blackjack_card_value(card: Card) -> int:
    if card.rank == "A":
        return 11
    if card.rank in {"K", "Q", "J"}:
        return 10
    return int(card.rank)


def blackjack_total(cards: list[Card]) -> tuple[int, bool]:
    """Return best blackjack total and whether it is soft (an ace counts as 11)."""
    total = sum(_blackjack_card_value(card) for card in cards)
    aces = sum(card.rank == "A" for card in cards)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    soft = aces > 0 and total <= 21
    return total, soft


def baccarat_card_value(card: Card) -> int:
    if card.rank == "A":
        return 1
    if card.rank in {"10", "J", "Q", "K"}:
        return 0
    return int(card.rank)


def baccarat_total(cards: list[Card]) -> int:
    return sum(baccarat_card_value(card) for card in cards) % 10


def _blackjack_finish(state: dict[str, Any], result: str, payout_cents: int) -> dict[str, Any]:
    state["status"] = "settled"
    state["result"] = str(result)
    state["payout_cents"] = max(0, int(payout_cents))
    state["dealer_hole_revealed"] = True
    state["player_total"] = blackjack_total(state["player_cards"])[0]
    state["dealer_total"] = blackjack_total(state["dealer_cards"])[0]
    return state


def _blackjack_dealer_play(state: dict[str, Any]) -> None:
    dealer = state["dealer_cards"]
    shoe = state["shoe"]
    # The dealer stands on every 17, including soft 17.
    while blackjack_total(dealer)[0] < 17:
        dealer.append(_draw(shoe))


def blackjack_stand(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("game") != "blackjack" or state.get("status") != "playing":
        raise ValueError("There is no active blackjack hand")
    player_total = blackjack_total(state["player_cards"])[0]
    _blackjack_dealer_play(state)
    dealer_total = blackjack_total(state["dealer_cards"])[0]
    bet = int(state["bet_cents"])
    if dealer_total > 21 or player_total > dealer_total:
        result, payout = "PLAYER WIN", bet * 2
    elif player_total == dealer_total:
        result, payout = "PUSH", bet
    else:
        result, payout = "DEALER WIN", 0
    _blackjack_finish(state, result, payout)
    return state


def new_blackjack_round(
    bet_cents: int,
    *,
    rng=None,
    shoe: list[Card] | None = None,
) -> dict[str, Any]:
    """Deal one blackjack hand. Six decks, dealer stands on soft 17, natural pays 3:2."""
    bet = _validate_bet(bet_cents)
    cards = list(shoe) if shoe is not None else create_shoe(decks=6, rng=rng)
    if len(cards) < 4:
        raise ValueError("A blackjack shoe must contain at least 4 cards")
    state: dict[str, Any] = {
        "game": "blackjack",
        "status": "playing",
        "bet_cents": bet,
        "player_cards": [_draw(cards)],
        "dealer_cards": [_draw(cards)],
        "shoe": cards,
        "result": "",
        "payout_cents": 0,
        "dealer_hole_revealed": False,
        "doubled": False,
    }
    state["player_cards"].append(_draw(cards))
    state["dealer_cards"].append(_draw(cards))
    state["player_total"] = blackjack_total(state["player_cards"])[0]
    state["dealer_total"] = None
    player_natural = len(state["player_cards"]) == 2 and state["player_total"] == 21
    dealer_natural = len(state["dealer_cards"]) == 2 and blackjack_total(state["dealer_cards"])[0] == 21
    if player_natural and dealer_natural:
        _blackjack_finish(state, "PUSH • BOTH BLACKJACK", bet)
    elif dealer_natural:
        _blackjack_finish(state, "DEALER BLACKJACK", 0)
    elif player_natural:
        # Return the original stake plus 3:2 profit.
        _blackjack_finish(state, "BLACKJACK • 3:2", bet + (bet * 3 // 2))
    return state


def blackjack_hit(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("game") != "blackjack" or state.get("status") != "playing":
        raise ValueError("There is no active blackjack hand")
    state["player_cards"].append(_draw(state["shoe"]))
    total = blackjack_total(state["player_cards"])[0]
    if total > 21:
        return _blackjack_finish(state, "BUST", 0)
    if total == 21:
        return blackjack_stand(state)
    state["player_total"] = total
    return state


def blackjack_double(state: dict[str, Any]) -> dict[str, Any]:
    """Double the wager, take exactly one card, then stand."""
    if state.get("game") != "blackjack" or state.get("status") != "playing":
        raise ValueError("There is no active blackjack hand")
    if len(state["player_cards"]) != 2 or bool(state.get("doubled", False)):
        raise ValueError("Double down is available only before taking a hit")
    state["bet_cents"] = int(state["bet_cents"]) * 2
    state["doubled"] = True
    state["player_cards"].append(_draw(state["shoe"]))
    total = blackjack_total(state["player_cards"])[0]
    if total > 21:
        return _blackjack_finish(state, "BUST • DOUBLE DOWN", 0)
    return blackjack_stand(state)


def serialize_blackjack_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert an active hand and its remaining shoe into JSON-safe data."""
    if not state:
        return None
    result = {
        key: value for key, value in state.items()
        if key not in {"player_cards", "dealer_cards", "shoe"}
    }
    for key in ("player_cards", "dealer_cards", "shoe"):
        result[key] = [
            {"rank": card.rank, "suit": card.suit}
            for card in list(state.get(key, []))
        ]
    return result


def restore_blackjack_state(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Restore a JSON-safe hand, rejecting malformed or incompatible saved state."""
    if not raw:
        return None
    if not isinstance(raw, dict) or raw.get("game") != "blackjack":
        return None
    if raw.get("status") not in {"playing", "settled"}:
        return None

    def restore_cards(key: str) -> list[Card]:
        rows = raw.get(key, [])
        if not isinstance(rows, list):
            raise ValueError("Saved blackjack cards are invalid")
        cards = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Saved blackjack card is invalid")
            rank, suit = str(row.get("rank", "")), str(row.get("suit", ""))
            if rank not in RANKS or suit not in SUITS:
                raise ValueError("Saved blackjack card is not recognized")
            cards.append(Card(rank, suit))
        return cards

    restored = dict(raw)
    restored["player_cards"] = restore_cards("player_cards")
    restored["dealer_cards"] = restore_cards("dealer_cards")
    restored["shoe"] = restore_cards("shoe")
    restored["bet_cents"] = _validate_bet(restored.get("bet_cents", 0))
    if not restored["player_cards"] or len(restored["dealer_cards"]) != 2:
        raise ValueError("Saved blackjack hand is incomplete")
    return restored


def baccarat_banker_should_draw(banker_total: int, player_third_value: int | None) -> bool:
    """Punto Banco banker third-card rule, with None when Player stands."""
    total = int(banker_total)
    if not 0 <= total <= 9:
        raise ValueError("Banker total must be between 0 and 9")
    if player_third_value is None:
        return total <= 5
    third = int(player_third_value)
    if not 0 <= third <= 9:
        raise ValueError("Player third-card value must be between 0 and 9")
    if total <= 2:
        return True
    if total == 3:
        return third != 8
    if total == 4:
        return 2 <= third <= 7
    if total == 5:
        return 4 <= third <= 7
    if total == 6:
        return third in {6, 7}
    return False


def new_baccarat_round(
    bet_cents: int,
    side: str,
    *,
    rng=None,
    shoe: list[Card] | None = None,
) -> dict[str, Any]:
    """Play one Punto Banco round with standard third-card rules and 5% banker commission."""
    bet = _validate_bet(bet_cents)
    selected = str(side).strip().lower()
    if selected not in {"player", "banker", "tie"}:
        raise ValueError("Choose Player, Banker or Tie")
    cards = list(shoe) if shoe is not None else create_shoe(decks=8, rng=rng)
    if len(cards) < 4:
        raise ValueError("A baccarat shoe must contain at least 4 cards")
    player_cards = [_draw(cards)]
    banker_cards = [_draw(cards)]
    player_cards.append(_draw(cards))
    banker_cards.append(_draw(cards))
    player_start = baccarat_total(player_cards)
    banker_start = baccarat_total(banker_cards)
    natural = player_start in {8, 9} or banker_start in {8, 9}
    if not natural:
        if player_start <= 5:
            player_cards.append(_draw(cards))
            player_third = baccarat_card_value(player_cards[-1])
        else:
            player_third = None
        if baccarat_banker_should_draw(banker_start, player_third):
            banker_cards.append(_draw(cards))
    player_final = baccarat_total(player_cards)
    banker_final = baccarat_total(banker_cards)
    winner = "tie" if player_final == banker_final else ("player" if player_final > banker_final else "banker")

    if winner == "tie":
        payout = bet * 9 if selected == "tie" else (bet if selected in {"player", "banker"} else 0)
    elif selected == winner == "player":
        payout = bet * 2
    elif selected == winner == "banker":
        payout = bet + (bet * 95 // 100)
    else:
        payout = 0

    return {
        "game": "baccarat",
        "status": "settled",
        "bet_cents": bet,
        "bet_side": selected,
        "player_cards": player_cards,
        "banker_cards": banker_cards,
        "player_total": player_final,
        "banker_total": banker_final,
        "winner": winner,
        "result": f"{winner.upper()} WINS" if winner != "tie" else "TIE",
        "payout_cents": int(payout),
        "shoe": cards,
    }
