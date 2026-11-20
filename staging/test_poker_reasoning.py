from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import importlib.util
import random
import sys
import types
from pathlib import Path


# The policy module uses the app's CPUAction and Hold'em evaluator. Provide
# compatible deterministic test doubles so this suite runs in GitHub Actions.
pkg = types.ModuleType("pigeon_poker")
pkg.__path__ = []
sys.modules["pigeon_poker"] = pkg

cpu_mod = types.ModuleType("pigeon_poker.cpu")

@dataclass(frozen=True)
class CPUAction:
    player_id: str
    action: str
    amount: int | None
    source: str
    equity_estimate: float | None = None
    note: str = ""

cpu_mod.CPUAction = CPUAction
sys.modules["pigeon_poker.cpu"] = cpu_mod

engine_mod = types.ModuleType("pigeon_poker.engine")
RANKS = "23456789TJQKA"
SUITS = "cdhs"

def make_deck():
    return [rank + suit for suit in SUITS for rank in RANKS]

def evaluate_five(cards):
    ranks = sorted((RANKS.index(card[0]) + 2 for card in cards), reverse=True)
    suits = [card[1] for card in cards]
    counts = {}
    for rank in ranks:
        counts[rank] = counts.get(rank, 0) + 1
    groups = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    values = set(ranks)
    if 14 in values:
        values.add(1)
    straight = next((high for high in range(14, 4, -1)
                     if all(rank in values for rank in range(high - 4, high + 1))), None)
    flush = len(set(suits)) == 1
    if flush and straight:
        return (8, straight)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if groups[0][0] == 3 and groups[1][0] == 2:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *ranks)
    if straight:
        return (4, straight)
    if groups[0][0] == 3:
        kickers = sorted((r for r, c in counts.items() if c == 1), reverse=True)
        return (3, groups[0][1], *kickers)
    pairs = sorted((r for r, c in counts.items() if c == 2), reverse=True)
    if len(pairs) == 2:
        kicker = next(r for r, c in counts.items() if c == 1)
        return (2, pairs[0], pairs[1], kicker)
    if len(pairs) == 1:
        kickers = sorted((r for r, c in counts.items() if c == 1), reverse=True)
        return (1, pairs[0], *kickers)
    return (0, *ranks)

def evaluate_seven(cards):
    if len(cards) not in (5, 6, 7):
        raise ValueError("test evaluator expects five to seven cards")
    return max(evaluate_five(combo) for combo in combinations(cards, 5))

engine_mod.make_deck = make_deck
engine_mod.evaluate_seven = evaluate_seven
sys.modules["pigeon_poker.engine"] = engine_mod

MODULE_PATH = Path(__file__).with_name("source_1_3_100") / "pigeon_poker" / "poker_reasoning.py"
if not MODULE_PATH.is_file():
    MODULE_PATH = Path(__file__).with_name("poker_reasoning_test_target.py")
spec = importlib.util.spec_from_file_location("pigeon_poker.poker_reasoning", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class FixedRandom:
    def random(self):
        return 0.5
    def sample(self, population, count):
        return random.Random(23).sample(list(population), count)


class FakeCPU:
    def __init__(self, level=5):
        self.level = level
        self.archetype = "balanced"
        self.rng = FixedRandom()


class FakePlayer:
    def __init__(self, player_id, cards=(), *, eligible=True, contribution=0, stack=10000):
        self.player_id = player_id
        self.name = player_id
        self.hole_cards = list(cards)
        self.eligible = eligible
        self.street_contribution = contribution
        self.total_contribution = contribution
        self.stack = stack


class FakeHand:
    def __init__(self, players, *, board=(), pot=1200, street="preflop",
                 to_call=800, actions=("fold", "call", "raise"),
                 min_target=1000, max_target=10000):
        self.players = players
        self.board = list(board)
        self.pot = pot
        self.street = street
        self.current_bet = to_call
        self.last_full_raise = 200
        self.big_blind = 100
        self.rake_bps = 0
        self.rake_cap = 0
        self.events = []
        self._legal = {
            "actions": list(actions), "to_call": to_call,
            "min_target": min_target, "max_target": max_target,
            "raise_allowed": "raise" in actions or "bet" in actions,
        }
    def player(self, player_id):
        return next(p for p in self.players if p.player_id == player_id)
    def legal_actions(self, player_id):
        return dict(self._legal)


class FakeTable:
    dealer_index = 0


def sample_estimator(*, table, hand, exclude_player_id):
    rows = {
        "UTG": {
            "supported": True,
            "hand_class_probabilities": {
                "QQ": 0.24, "JJ": 0.20, "TT": 0.16,
                "AKs": 0.16, "AQs": 0.12, "KQs": 0.12,
            },
        },
        "HJ": {
            "supported": True,
            "hand_class_probabilities": {
                "KK": 0.24, "QQ": 0.20, "JJ": 0.16,
                "AKs": 0.16, "AQs": 0.12, "KQs": 0.12,
            },
        },
        "BTN": {
            "supported": True,
            "hand_class_probabilities": {
                "AA": 0.08, "KK": 0.12, "QQ": 0.12,
                "AKs": 0.20, "AQs": 0.18, "KQs": 0.15, "JTs": 0.15,
            },
        },
    }
    observed = {
        str(event.get("player") or event.get("player_id") or "")
        for event in list(getattr(hand, "events", ()) or ())
        if isinstance(event, dict) and event.get("type") == "action"
        and str(event.get("street", "preflop")).lower().replace("-", "") == "preflop"
    }
    return {
        "supported": True,
        "players": {
            pid: value for pid, value in rows.items()
            if pid != exclude_player_id and pid in observed
        },
    }


def test_call_equity_formula():
    assert abs(module.required_call_equity(1000, 500) - (1 / 3)) < 1e-9
    assert abs(module.required_call_equity(1000, 500, 50) - (500 / 1450)) < 1e-9


def test_pure_bluff_break_even_formula():
    assert abs(module.required_bluff_success(1000, 500) - (1 / 3)) < 1e-9
    assert abs(module.required_bluff_success(1000, 1000) - 0.5) < 1e-9


def test_three_way_utg_open_hj_three_bet_co_aces_is_not_stopped():
    players = [
        FakePlayer("UTG", ("2c", "3d")),
        FakePlayer("HJ", ("4c", "5d")),
        FakePlayer("CO", ("As", "Ah")),
        FakePlayer("BTN", ("6c", "7d")),
        FakePlayer("SB", ("8c", "9d")),
        FakePlayer("BB", ("Tc", "Jd")),
    ]
    hand = FakeHand(players, pot=1200, to_call=800,
                    actions=("fold", "call", "raise"), min_target=1000)
    hand.events = [
        {"type": "action", "street": "preflop", "player": "UTG", "action": "raise",
         "target": 250, "paid": 250, "pot_before": 75, "to_call_before": 0},
        {"type": "action", "street": "preflop", "player": "HJ", "action": "raise",
         "target": 800, "paid": 550, "pot_before": 325, "to_call_before": 250},
    ]
    ranges = module.infer_opponent_ranges(FakeTable(), hand, "CO", sample_estimator)
    assert "UTG" in ranges and "HJ" in ranges
    assert ranges["UTG"].source == "fixed-chart-action-range"
    assert ranges["HJ"].source == "fixed-chart-action-range"

    decision = module.choose_range_aware_action(
        FakeTable(), hand, "CO", FakeCPU(), range_estimator=sample_estimator
    )
    assert decision.source == "range-aware-policy"
    assert decision.action in {"call", "raise", "fold"}
    assert decision.action != "limp"
    assert "required call" in decision.note
    assert "pure-bluff required folds" in decision.note
    assert "samples" in decision.note


def test_postflop_action_updates_each_opponents_range_without_hidden_cards():
    players = [
        FakePlayer("hero", ("As", "Ah")),
        FakePlayer("UTG", ("2c", "3d")),
        FakePlayer("HJ", ("4c", "5d")),
        FakePlayer("BB", ("8c", "9d")),
    ]
    hand = FakeHand(
        players, board=("Jh", "7d", "2c"), pot=1600, street="flop",
        to_call=500, actions=("fold", "call", "raise"), min_target=1000,
    )
    hand.events = [
        {"type": "action", "street": "preflop", "player": "UTG", "action": "raise",
         "target": 250, "paid": 250, "pot_before": 75, "to_call_before": 0},
        {"type": "street", "street": "flop", "board": ["Jh", "7d", "2c"]},
        {"type": "action", "street": "flop", "player": "UTG", "action": "bet",
         "target": 500, "paid": 500, "pot_before": 1000, "to_call_before": 0},
    ]
    ranges = module.infer_opponent_ranges(FakeTable(), hand, "hero", sample_estimator)
    assert "postflop-action" in ranges["UTG"].source
    assert "fixed-chart-action-range" in ranges["UTG"].source
    total = sum(weight for _, weight in ranges["UTG"].combos)
    assert abs(total - 1.0) < 1e-9
    assert all("2c" not in combo and "Jh" not in combo and "7d" not in combo
               for combo, _ in ranges["UTG"].combos)

    decision = module.choose_range_aware_action(
        FakeTable(), hand, "hero", FakeCPU(4), range_estimator=sample_estimator
    )
    assert decision.source == "range-aware-policy"
    assert decision.action in {"fold", "call", "raise"}
    assert decision.equity_estimate is not None


def test_range_policy_guardrail_keeps_hand_moving_and_penalizes_repeat_failures():
    players = [
        FakePlayer("hero", ()),
        FakePlayer("UTG", ("2c", "3d")),
    ]
    hand = FakeHand(players, pot=500, street="flop", to_call=200,
                    actions=("fold", "call"), min_target=200)
    hand.board = ["Jh", "7d", "2c"]
    cpu = FakeCPU(4)
    first = module.choose_range_aware_action(
        FakeTable(), hand, "hero", cpu, range_estimator=sample_estimator
    )
    assert first.source == "range-aware-guardrail"
    assert first.action == "fold"
    assert "policy penalty=100" in first.note
    assert cpu._range_guardrail_penalty == 100
    second = module.choose_range_aware_action(
        FakeTable(), hand, "hero", cpu, range_estimator=sample_estimator
    )
    assert second.source == "range-aware-guardrail"
    assert cpu._range_guardrail_penalty == 200

def test_unacted_opponent_remains_in_multiway_equity():
    players = [
        FakePlayer("hero", ("As", "Ah")),
        FakePlayer("UTG", ("2c", "3d")),
        FakePlayer("HJ", ("4c", "5d")),
        FakePlayer("BTN", ("8c", "9d")),
    ]
    hand = FakeHand(players, pot=300, street="preflop", to_call=100,
                    actions=("fold", "call", "raise"), min_target=200)
    hand.events = [
        {"type": "action", "street": "preflop", "player": "UTG", "action": "raise",
         "target": 200, "paid": 200, "pot_before": 75, "to_call_before": 0},
    ]
    ranges = module.infer_opponent_ranges(FakeTable(), hand, "hero", sample_estimator)
    assert len(ranges) == 3
    assert ranges["BTN"].source in {
        "unacted-conditional-response", "fixed-chart-action-range"
    }
    decision = module.choose_range_aware_action(
        FakeTable(), hand, "hero", FakeCPU(3), range_estimator=sample_estimator
    )
    assert decision.action in {"fold", "call", "raise"}
    assert "ranges 3" in decision.note


if __name__ == "__main__":
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests))
