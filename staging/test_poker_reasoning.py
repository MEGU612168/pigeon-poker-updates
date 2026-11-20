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

MODULE_PATH = Path(__file__).with_name("source_1_3_101") / "pigeon_poker" / "poker_reasoning.py"
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



def test_board_strength_preserves_exact_showdown_rank_order_over_random_samples():
    rng = random.Random(20261121)
    deck = make_deck()
    for _ in range(1000):
        sample = rng.sample(deck, 9)
        board = sample[:5]
        hand_a = (sample[5], sample[6])
        hand_b = (sample[7], sample[8])
        rank_a = evaluate_seven(list(hand_a) + board)
        rank_b = evaluate_seven(list(hand_b) + board)
        strength_a, _ = module._board_metrics(hand_a, board)
        strength_b, _ = module._board_metrics(hand_b, board)
        if rank_a == rank_b:
            assert abs(strength_a - strength_b) < 1e-9
        else:
            assert (strength_a > strength_b) == (rank_a > rank_b)


def test_flush_and_straight_draw_detection_distinguishes_real_outs():
    flush_draw = module._board_metrics(
        ("Jh", "Tc"), ["6h", "7h", "2h"]
    )[1]
    backdoor_only = module._board_metrics(
        ("Js", "Tc"), ["6h", "7h", "2h"]
    )[1]
    open_ended = module._board_metrics(
        ("5h", "Kc"), ["6s", "7d", "8c"]
    )[1]
    gutshot = module._board_metrics(
        ("5h", "Kc"), ["6s", "7d", "9c"]
    )[1]
    assert flush_draw > backdoor_only
    assert open_ended > gutshot
    assert gutshot > 0


def test_bet_response_probabilities_react_to_strength_draws_and_size():
    weak = module._response_continue_probability(0.04, 0.0, 0.75, "flop")
    top_pair = module._response_continue_probability(0.22, 0.0, 0.75, "flop")
    strong_draw = module._response_continue_probability(0.20, 0.80, 0.75, "flop")
    large_bet = module._response_continue_probability(0.22, 0.0, 1.50, "flop")
    assert top_pair > weak
    assert strong_draw > top_pair
    assert large_bet < top_pair


def test_multiway_response_model_counts_callers_and_tightens_all_fold_probability():
    board = ["Jh", "7d", "2c"]
    players = [
        FakePlayer("hero", ("As", "Ah")),
        FakePlayer("UTG", ("3s", "4d")),
        FakePlayer("HJ", ("5s", "6d")),
        FakePlayer("BTN", ("8s", "9d")),
    ]
    hand = FakeHand(
        players, board=board, pot=1600, street="flop",
        to_call=500, actions=("fold", "call", "raise"), min_target=1000,
    )
    ranges = {
        "UTG": module.OpponentRange(
            "UTG", ((("Kc", "Kd"), 0.55), (("Qc", "Qd"), 0.45)),
            "test-range", 0.8, 1.0),
        "HJ": module.OpponentRange(
            "HJ", ((("8c", "8d"), 0.50), (("9c", "9d"), 0.50)),
            "test-range", 0.8, 1.0),
        "BTN": module.OpponentRange(
            "BTN", ((("6c", "6d"), 0.50), (("5c", "5d"), 0.50)),
            "test-range", 0.8, 1.0),
    }
    cpu = FakeCPU(1)
    one_fold, one_callers, one_equity, one_samples = module._bet_response_metrics(
        hand, "hero", {"UTG": ranges["UTG"]}, board, 0.75, cpu
    )
    three_fold, three_callers, three_equity, three_samples = module._bet_response_metrics(
        hand, "hero", ranges, board, 0.75, cpu
    )
    assert 0.0 <= three_fold <= one_fold <= 1.0
    assert 0.0 <= one_callers < three_callers <= 3.0
    assert 0.0 <= one_equity <= 1.0
    assert 0.0 <= three_equity <= 1.0
    assert one_samples > 0 and three_samples > 0


def test_range_aware_policy_reports_caller_conditioned_ev_inputs():
    players = [
        FakePlayer("hero", ("As", "Ah")),
        FakePlayer("UTG", ("2c", "3d")),
        FakePlayer("HJ", ("4c", "5d")),
        FakePlayer("BTN", ("8c", "9d")),
    ]
    hand = FakeHand(
        players, board=("Jh", "7d", "2c"), pot=1600, street="flop",
        to_call=500, actions=("fold", "call", "raise"), min_target=1000,
    )
    hand.events = [
        {"type": "action", "street": "preflop", "player": "UTG", "action": "raise",
         "target": 250, "paid": 250, "pot_before": 75, "to_call_before": 0},
        {"type": "action", "street": "preflop", "player": "HJ", "action": "raise",
         "target": 800, "paid": 550, "pot_before": 325, "to_call_before": 250},
        {"type": "action", "street": "preflop", "player": "BTN", "action": "call",
         "target": 800, "paid": 800, "pot_before": 1125, "to_call_before": 800},
        {"type": "street", "street": "flop", "board": ["Jh", "7d", "2c"]},
        {"type": "action", "street": "flop", "player": "UTG", "action": "check",
         "target": 0, "paid": 0, "pot_before": 2400, "to_call_before": 0},
    ]
    decision = module.choose_range_aware_action(
        FakeTable(), hand, "hero", FakeCPU(3), range_estimator=sample_estimator
    )
    assert decision.source == "range-aware-policy"
    assert decision.action in {"fold", "call", "raise"}
    assert "expected callers" in decision.note
    assert "equity when called" in decision.note
    assert "multiway response model" in decision.note


if __name__ == "__main__":
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests))
