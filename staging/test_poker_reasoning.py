from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import importlib.util
import random
import sys
import types
from pathlib import Path
from types import SimpleNamespace


# The policy module uses the app's CPUAction and Hold'em evaluator. Provide
# compatible deterministic test doubles so this suite runs in GitHub Actions.
pkg = types.ModuleType("pigeon_poker")
SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
pkg.__path__ = [str(SOURCE_DIR / "pigeon_poker")]
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
    def __init__(self):
        self._rng = random.Random(23)

    def random(self):
        return self._rng.random()

    def sample(self, population, count):
        return self._rng.sample(list(population), count)


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



def _average_fallback_preflop_strength(rows):
    total = sum(weight for _, weight in rows)
    return sum(
        weight * module._preflop_strength(module._cards_to_class(combo))
        for combo, weight in rows
    ) / max(1e-9, total)


def test_uncovered_preflop_ranges_tighten_for_larger_raises_and_expensive_calls():
    players = [FakePlayer("hero", ("As", "Ah")), FakePlayer("villain")]

    def fallback(action, *, target=250, to_call=50, pot_before=1000):
        hand = FakeHand(players, pot=pot_before, street="preflop", to_call=to_call)
        hand.events = [{
            "type": "action", "street": "preflop", "player": "villain",
            "action": action, "target": target, "paid": to_call,
            "pot_before": pot_before, "to_call_before": to_call,
        }]
        return module._fallback_preflop_range(hand, "villain", {"As", "Ah"})[0]

    small_raise = fallback("raise", target=250)
    oversized_raise = fallback("raise", target=1000)
    cheap_call = fallback("call", to_call=50, pot_before=1000)
    expensive_call = fallback("call", to_call=1000, pot_before=1000)
    assert _average_fallback_preflop_strength(oversized_raise) > _average_fallback_preflop_strength(small_raise)
    assert _average_fallback_preflop_strength(expensive_call) > _average_fallback_preflop_strength(cheap_call)


def test_unacted_players_enter_less_often_after_a_large_open():
    def participation_for(target):
        players = [
            FakePlayer("hero", ("As", "Ah")),
            FakePlayer("UTG"),
            FakePlayer("BTN"),
        ]
        hand = FakeHand(players, pot=400, street="preflop", to_call=target)
        hand.events = [{
            "type": "action", "street": "preflop", "player": "UTG",
            "action": "raise", "target": target, "paid": target,
            "pot_before": 75, "to_call_before": 0,
        }]
        ranges = module.infer_opponent_ranges(
            FakeTable(), hand, "hero", sample_estimator
        )
        return ranges["BTN"].participation_probability

    standard_open = participation_for(250)
    large_open = participation_for(1000)
    assert large_open < standard_open



def _six_max_position_hand(actor_position: str, action: str = "raise"):
    # Clockwise seat indices relative to a BTN at table dealer index zero.
    position_ids = {
        "BTN": "BTN", "SB": "SB", "BB": "BB",
        "UTG": "UTG", "HJ": "HJ", "CO": "CO",
    }
    seat_order = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]
    players = [FakePlayer(position_ids[position]) for position in seat_order]
    hand = FakeHand(
        players, pot=400, street="preflop", to_call=250,
        actions=("fold", "call", "raise"), min_target=500, max_target=10000,
    )
    hand.seat_by_id = {player.player_id: index for index, player in enumerate(players)}
    hand.events = [{
        "type": "action", "street": "preflop", "player_id": actor_position,
        "action": action, "target": 250, "paid": 250,
        "pot_before": 75, "to_call_before": 0,
    }]
    return hand, FakeTable()


def _range_weighted_strength(rows):
    total = sum(weight for _, weight in rows)
    return sum(
        weight * module._preflop_strength(module._cards_to_class(combo))
        for combo, weight in rows
    ) / max(1e-9, total)


def test_fallback_open_ranges_are_position_aware() -> None:
    hand_utg, table_utg = _six_max_position_hand("UTG", "raise")
    hand_btn, table_btn = _six_max_position_hand("BTN", "raise")
    utg_rows = module._fallback_preflop_range(
        hand_utg, "UTG", set(), table=table_utg
    )[0]
    btn_rows = module._fallback_preflop_range(
        hand_btn, "BTN", set(), table=table_btn
    )[0]
    assert _range_weighted_strength(utg_rows) > _range_weighted_strength(btn_rows)
    assert len(utg_rows) < len(btn_rows)


def test_fallback_blind_defense_and_ip_response_use_seat_position() -> None:
    hand_bb, table_bb = _six_max_position_hand("BB", "call")
    hand_sb, table_sb = _six_max_position_hand("SB", "call")
    # Add an opener before the blind's action so this is a true defend node.
    for hand, actor in ((hand_bb, "BB"), (hand_sb, "SB")):
        hand.events.insert(0, {
            "type": "action", "street": "preflop", "player_id": "UTG",
            "action": "raise", "target": 250, "paid": 250,
            "pot_before": 75, "to_call_before": 0,
        })
        hand.events[1]["target"] = 800
        hand.events[1]["paid"] = 550
        hand.events[1]["to_call_before"] = 550
    bb_rows = module._fallback_preflop_range(
        hand_bb, "BB", set(), table=table_bb
    )[0]
    sb_rows = module._fallback_preflop_range(
        hand_sb, "SB", set(), table=table_sb
    )[0]
    assert _range_weighted_strength(bb_rows) < _range_weighted_strength(sb_rows)


def test_unacted_participation_uses_table_position_in_six_max() -> None:
    players = [FakePlayer(name) for name in ("BTN", "SB", "BB", "UTG", "HJ", "CO")]
    hand = FakeHand(players, pot=400, street="preflop", to_call=250)
    hand.seat_by_id = {player.player_id: index for index, player in enumerate(players)}
    hand.events = [{
        "type": "action", "street": "preflop", "player_id": "UTG",
        "action": "raise", "target": 250, "paid": 250,
        "pot_before": 75, "to_call_before": 0,
    }]
    no_chart = lambda **_kwargs: {"supported": False, "players": {}}
    ranges = module.infer_opponent_ranges(
        FakeTable(), hand, "UTG", range_estimator=no_chart
    )
    assert ranges["BTN"].participation_probability > ranges["SB"].participation_probability
    assert ranges["BB"].participation_probability > ranges["BTN"].participation_probability


def test_co_aces_continue_against_utg_open_and_hj_three_bet():
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
    decision = module.choose_range_aware_action(
        FakeTable(), hand, "CO", FakeCPU(5), range_estimator=sample_estimator
    )
    assert decision.source == "range-aware-policy"
    assert decision.action in {"call", "raise"}, decision.note


def test_all_cpu_levels_choose_a_legal_action_in_the_same_multiway_spot():
    for level in range(1, 6):
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
            {"type": "action", "street": "preflop", "player": "HJ", "action": "call",
             "target": 250, "paid": 250, "pot_before": 325, "to_call_before": 250},
            {"type": "street", "street": "flop", "board": ["Jh", "7d", "2c"]},
            {"type": "action", "street": "flop", "player": "UTG", "action": "check",
             "target": 0, "paid": 0, "pot_before": 800, "to_call_before": 0},
        ]
        decision = module.choose_range_aware_action(
            FakeTable(), hand, "hero", FakeCPU(level),
            range_estimator=sample_estimator,
        )
        assert decision.source == "range-aware-policy"
        assert decision.action in {"fold", "call", "raise"}




def test_archetypes_change_action_posteriors_and_calling_behavior():
    weak_call_station = module._action_likelihood(
        "call", 0.05, 0.0, 1.0, "flop", "calling_station"
    )
    weak_call_balanced = module._action_likelihood(
        "call", 0.05, 0.0, 1.0, "flop", "balanced"
    )
    weak_call_overfolder = module._action_likelihood(
        "call", 0.05, 0.0, 1.0, "flop", "overfolder"
    )
    weak_bet_aggressive = module._action_likelihood(
        "bet", 0.05, 0.0, 1.0, "flop", "aggressive"
    )
    weak_bet_balanced = module._action_likelihood(
        "bet", 0.05, 0.0, 1.0, "flop", "balanced"
    )
    weak_bet_underbluffer = module._action_likelihood(
        "bet", 0.05, 0.0, 1.0, "flop", "underbluffer"
    )
    assert weak_call_station > weak_call_balanced > weak_call_overfolder
    assert weak_bet_aggressive > weak_bet_balanced > weak_bet_underbluffer

    station_continue = module._response_continue_probability(
        0.05, 0.0, 1.0, "flop", "calling_station"
    )
    overfolder_continue = module._response_continue_probability(
        0.05, 0.0, 1.0, "flop", "overfolder"
    )
    assert station_continue > overfolder_continue


def test_blocker_metrics_distinguish_removed_value_and_bluff_combos():
    players = [
        FakePlayer("hero", ("As", "Kc")),
        FakePlayer("villain", ("2s", "3d")),
    ]
    hand = FakeHand(
        players, board=("Qh", "Jd", "2c"), pot=1000, street="river",
        to_call=0, actions=("check", "bet"), min_target=100, max_target=2000,
    )
    value_removed = module.OpponentRange(
        "villain", (), "test", 0.9, 1.0, "balanced",
        ((("As", "Ah"), 0.60), (("3s", "4d"), 0.40)),
    )
    value_metrics = module._blocker_removal_metrics(
        hand, "hero", {"villain": value_removed}, 0.75
    )
    bluff_removed = module.OpponentRange(
        "villain", (), "test", 0.9, 1.0, "balanced",
        ((("3s", "4d"), 0.90), (("As", "Ah"), 0.10)),
    )
    bluff_metrics = module._blocker_removal_metrics(
        hand, "hero", {"villain": bluff_removed}, 0.75
    )
    assert value_metrics["value_call_combos_blocked"] > value_metrics["bluff_call_combos_blocked"]
    assert bluff_metrics["bluff_call_combos_blocked"] > bluff_metrics["value_call_combos_blocked"]


def test_thin_value_threshold_is_lower_heads_up_and_rises_multiway():
    heads_up = module._thin_value_threshold(
        level=5, uncertainty=0.0, expected_callers=1.0,
        required_call=0.25, street="river",
    )
    three_way = module._thin_value_threshold(
        level=5, uncertainty=0.0, expected_callers=3.0,
        required_call=0.25, street="river",
    )
    uncertain = module._thin_value_threshold(
        level=5, uncertainty=0.8, expected_callers=1.0,
        required_call=0.25, street="river",
    )
    conservative = module._thin_value_threshold(
        level=1, uncertainty=0.0, expected_callers=1.0,
        required_call=0.25, street="river",
    )
    assert 0.50 <= heads_up < three_way
    assert uncertain > heads_up
    assert conservative > heads_up


def test_candidate_ev_simulation_budget_is_smaller_than_full_equity_budget():
    board = ["Jh", "7d", "2c"]
    players = [
        FakePlayer("hero", ("As", "Ah")),
        FakePlayer("UTG", ("3s", "4d")),
    ]
    hand = FakeHand(
        players, board=board, pot=1000, street="flop",
        to_call=0, actions=("check", "bet"), min_target=200,
    )
    ranges = {
        "UTG": module.OpponentRange(
            "UTG", ((("Kc", "Kd"), 0.6), (("Qc", "Qd"), 0.4)),
            "test", 0.9, 1.0,
        )
    }
    cpu = FakeCPU(3)
    _, full_samples = module._equity_vs_ranges(hand, "hero", ranges, cpu)
    _, _, _, candidate_samples = module._bet_response_metrics(
        hand, "hero", ranges, board, 0.75, cpu,
        simulation_multiplier=0.40,
    )
    assert 0 < candidate_samples < full_samples



def test_empirical_opponent_stats_change_postflop_action_and_response_models():
    observed_call = module._action_likelihood(
        "call", 0.08, 0.0, 0.75, "flop", "balanced",
        {"sample_hands": 120, "postflop_call_rate": 0.78},
    )
    baseline_call = module._action_likelihood(
        "call", 0.08, 0.0, 0.75, "flop", "balanced",
    )
    observed_aggression = module._action_likelihood(
        "bet", 0.08, 0.0, 0.75, "flop", "balanced",
        {"sample_hands": 120, "postflop_aggression_rate": 0.68},
    )
    baseline_aggression = module._action_likelihood(
        "bet", 0.08, 0.0, 0.75, "flop", "balanced",
    )
    sticky_response = module._response_continue_probability(
        0.12, 0.05, 0.75, "flop", "balanced",
        {"sample_hands": 120, "fold_to_bet_rate": 0.18, "postflop_call_rate": 0.72},
    )
    tight_response = module._response_continue_probability(
        0.12, 0.05, 0.75, "flop", "balanced",
        {"sample_hands": 120, "fold_to_bet_rate": 0.88, "postflop_call_rate": 0.10},
    )
    baseline_response = module._response_continue_probability(
        0.12, 0.05, 0.75, "flop", "balanced",
    )
    assert observed_call > baseline_call
    assert observed_aggression > baseline_aggression
    assert sticky_response > baseline_response > tight_response


def test_inferred_opponent_range_carries_persistent_behavioral_profile():
    players = [
        FakePlayer("UTG", ("2c", "3d")),
        FakePlayer("CO", ("As", "Ah")),
    ]
    hand = FakeHand(players, pot=400, street="preflop", to_call=250)
    hand.events = [{
        "type": "action", "street": "preflop", "player": "UTG",
        "action": "raise", "target": 250, "paid": 250,
        "pot_before": 75, "to_call_before": 0,
    }]

    def learned_estimator(**kwargs):
        result = sample_estimator(**kwargs)
        result["players"]["UTG"]["learned_behavior"] = {
            "sample_hands": 80.0,
            "vpip_rate": 0.32,
            "pfr_rate": 0.18,
            "fold_to_bet_rate": 0.24,
            "postflop_call_rate": 0.66,
            "postflop_aggression_rate": 0.38,
        }
        return result

    ranges = module.infer_opponent_ranges(
        FakeTable(), hand, "CO", learned_estimator
    )
    assert "UTG" in ranges
    learned = dict(ranges["UTG"].learned_stats)
    assert learned["sample_hands"] == 80.0
    assert learned["postflop_call_rate"] == 0.66



def test_flop_response_uses_opponent_fold_to_cbet_history():
    sticky_cbet = module._response_continue_probability(
        0.10, 0.08, 0.66, "flop", "balanced",
        {"sample_hands": 100, "fold_to_bet_rate": 0.55,
         "postflop_call_rate": 0.30, "fold_to_cbet_opportunities": 24,
         "fold_to_cbet_rate": 0.12},
    )
    baseline = module._response_continue_probability(
        0.10, 0.08, 0.66, "flop", "balanced",
    )
    overfold_cbet = module._response_continue_probability(
        0.10, 0.08, 0.66, "flop", "balanced",
        {"sample_hands": 100, "fold_to_bet_rate": 0.55,
         "postflop_call_rate": 0.30, "fold_to_cbet_opportunities": 24,
         "fold_to_cbet_rate": 0.90},
    )
    assert sticky_cbet > baseline > overfold_cbet




def test_preflop_board_role_detects_caller_favored_connected_flop() -> None:
    players = [
        FakePlayer("villain", ("2c", "3d")),
        FakePlayer("SB", ("4c", "5d")),
        FakePlayer("hero", ("As", "Kh")),
        FakePlayer("UTG", ("6c", "7d")),
        FakePlayer("HJ", ("8c", "9d")),
        FakePlayer("CO", ("Tc", "Jd")),
    ]
    hand = FakeHand(
        players, board=("8s", "7d", "6c"), pot=500,
        street="flop", to_call=0, actions=("check", "bet"),
    )
    hand.dealer_index = 0
    hand.seat_by_id = {"villain": 0, "SB": 1, "hero": 2, "UTG": 3, "HJ": 4, "CO": 5}
    hand.events = [
        {"type": "action", "street": "preflop", "player": "villain", "action": "raise",
         "target": 250, "paid": 250, "pot_before": 75, "to_call_before": 0},
        {"type": "action", "street": "preflop", "player": "hero", "action": "call",
         "target": 250, "paid": 250, "pot_before": 325, "to_call_before": 250},
        {"type": "street", "street": "flop", "board": ["8s", "7d", "6c"]},
    ]
    context = module._postflop_board_role_context(FakeTable(), hand, "hero")
    assert context["preflop_aggressor"] == "villain"
    assert context["caller_favored_board"] is True
    assert context["hero_is_preflop_aggressor"] is False
    assert context["preflop_range_disadvantage"] is False
    assert context["donk_lead"] is True


def test_preflop_aggressor_is_flagged_range_disadvantaged_on_low_connected_flop() -> None:
    players = [
        FakePlayer("hero", ("As", "Kh")),
        FakePlayer("SB", ("4c", "5d")),
        FakePlayer("villain", ("2c", "3d")),
        FakePlayer("UTG", ("6c", "7d")),
        FakePlayer("HJ", ("8c", "9d")),
        FakePlayer("CO", ("Tc", "Jd")),
    ]
    hand = FakeHand(
        players, board=("8s", "7d", "6c"), pot=500,
        street="flop", to_call=0, actions=("check", "bet"),
    )
    hand.dealer_index = 0
    hand.seat_by_id = {"hero": 0, "SB": 1, "villain": 2, "UTG": 3, "HJ": 4, "CO": 5}
    hand.events = [
        {"type": "action", "street": "preflop", "player": "hero", "action": "raise",
         "target": 250, "paid": 250, "pot_before": 75, "to_call_before": 0},
        {"type": "action", "street": "preflop", "player": "villain", "action": "call",
         "target": 250, "paid": 250, "pot_before": 325, "to_call_before": 250},
        {"type": "street", "street": "flop", "board": ["8s", "7d", "6c"]},
    ]
    context = module._postflop_board_role_context(FakeTable(), hand, "hero")
    assert context["hero_is_preflop_aggressor"] is True
    assert context["caller_favored_board"] is True
    assert context["preflop_range_disadvantage"] is True
    assert context["donk_lead"] is False


def test_ace_high_dry_flop_favors_preflop_aggressor_proxy() -> None:
    players = [
        FakePlayer("villain", ("As", "Ah")),
        FakePlayer("SB", ("4c", "5d")),
        FakePlayer("hero", ("2c", "3d")),
        FakePlayer("UTG", ("6c", "7d")),
        FakePlayer("HJ", ("8c", "9d")),
        FakePlayer("CO", ("Tc", "Jd")),
    ]
    hand = FakeHand(
        players, board=("As", "7d", "3c"), pot=500,
        street="flop", to_call=0, actions=("check", "bet"),
    )
    hand.dealer_index = 0
    hand.seat_by_id = {"villain": 0, "SB": 1, "hero": 2, "UTG": 3, "HJ": 4, "CO": 5}
    hand.events = [
        {"type": "action", "street": "preflop", "player": "villain", "action": "raise",
         "target": 250, "paid": 250, "pot_before": 75, "to_call_before": 0},
        {"type": "action", "street": "preflop", "player": "hero", "action": "call",
         "target": 250, "paid": 250, "pot_before": 325, "to_call_before": 250},
        {"type": "street", "street": "flop", "board": ["As", "7d", "3c"]},
    ]
    context = module._postflop_board_role_context(FakeTable(), hand, "hero")
    assert context["aggressor_favored_board"] is True
    assert context["preflop_range_disadvantage"] is True


def test_medium_strength_raise_is_blocked_on_range_disadvantage_board() -> None:
    value_gate, bluff_gate = module._postflop_aggression_gates(
        True, True,
        street="flop", to_call=200, donk_lead=False,
        range_disadvantage=True, made_category=1, draw_strength=0.14,
        expected_callers=1.0, called_equity=0.60, value_threshold=0.55,
        fold_probability=0.70, required_success=0.40, uncertainty_margin=0.05,
    )
    assert value_gate is False
    assert bluff_gate is False


def test_strong_value_raise_can_pass_the_stricter_postflop_gate() -> None:
    value_gate, bluff_gate = module._postflop_aggression_gates(
        True, False,
        street="flop", to_call=200, donk_lead=False,
        range_disadvantage=True, made_category=3, draw_strength=0.0,
        expected_callers=1.0, called_equity=0.78, value_threshold=0.55,
        fold_probability=0.25, required_success=0.40, uncertainty_margin=0.03,
    )
    assert value_gate is True
    assert bluff_gate is False


def test_weak_donk_lead_is_blocked_but_set_and_combo_draw_are_retained() -> None:
    weak_value, weak_bluff = module._postflop_aggression_gates(
        True, True,
        street="flop", to_call=0, donk_lead=True,
        range_disadvantage=False, made_category=1, draw_strength=0.14,
        expected_callers=1.0, called_equity=0.62, value_threshold=0.55,
        fold_probability=0.65, required_success=0.35, uncertainty_margin=0.02,
    )
    set_value, _ = module._postflop_aggression_gates(
        True, False,
        street="flop", to_call=0, donk_lead=True,
        range_disadvantage=False, made_category=3, draw_strength=0.0,
        expected_callers=1.0, called_equity=0.80, value_threshold=0.55,
        fold_probability=0.20, required_success=0.35, uncertainty_margin=0.02,
    )
    draw_value, draw_bluff = module._postflop_aggression_gates(
        False, True,
        street="flop", to_call=0, donk_lead=True,
        range_disadvantage=False, made_category=0, draw_strength=0.96,
        expected_callers=1.0, called_equity=0.38, value_threshold=0.55,
        fold_probability=0.75, required_success=0.35, uncertainty_margin=0.02,
    )
    assert weak_value is False and weak_bluff is False
    assert set_value is True
    assert draw_value is False and draw_bluff is True


def test_multiway_donk_gate_requires_set_or_exceptional_draw() -> None:
    two_pair, _ = module._postflop_aggression_gates(
        True, False,
        street="flop", to_call=0, donk_lead=True,
        range_disadvantage=False, made_category=2, draw_strength=0.0,
        expected_callers=2.0, called_equity=0.80, value_threshold=0.55,
        fold_probability=0.20, required_success=0.35, uncertainty_margin=0.02,
    )
    set_value, _ = module._postflop_aggression_gates(
        True, False,
        street="flop", to_call=0, donk_lead=True,
        range_disadvantage=False, made_category=3, draw_strength=0.0,
        expected_callers=2.0, called_equity=0.80, value_threshold=0.55,
        fold_probability=0.20, required_success=0.35, uncertainty_margin=0.02,
    )
    assert two_pair is False
    assert set_value is True




def test_screenshot_policy_derived_preflop_ranges_detect_opponent_nut_advantage() -> None:
    players = [
        FakePlayer("hero", ("As", "Kd")),
        FakePlayer("villain", ("2c", "3d")),
    ]
    hand = FakeHand(
        players, board=("8s", "7d", "6c"), pot=500,
        street="flop", to_call=0, actions=("check", "bet"),
    )
    calls = []

    def screenshot_policy_estimator(*, table, hand, exclude_player_id=None):
        calls.append(exclude_player_id)
        return {
            "supported": True,
            "players": {
                "hero": {
                    "supported": True,
                    "hand_class_probabilities": {"AA": 0.50, "KK": 0.50},
                },
                "villain": {
                    "supported": True,
                    "hand_class_probabilities": {
                        "88": 0.40, "77": 0.40, "87s": 0.20,
                    },
                },
            },
        }

    profile = module._preflop_range_advantage_profile(
        FakeTable(), hand, "hero", hand.board, screenshot_policy_estimator
    )
    assert calls == [None]
    assert profile["supported"] is True
    assert profile["mean_advantage"] < 0
    assert profile["top_decile_advantage"] < 0
    assert profile["range_disadvantage"] is True


def test_unmatched_preflop_line_falls_back_from_exact_range_profile() -> None:
    players = [
        FakePlayer("hero", ("As", "Kd")),
        FakePlayer("villain", ("2c", "3d")),
    ]
    hand = FakeHand(
        players, board=("8s", "7d", "6c"), pot=500,
        street="flop", to_call=0, actions=("check", "bet"),
    )

    def unsupported_estimator(*, table, hand, exclude_player_id=None):
        return {
            "supported": True,
            "players": {
                "hero": {"supported": False, "reason": "custom preflop size"},
                "villain": {"supported": True, "hand_class_probabilities": {"88": 1.0}},
            },
        }

    profile = module._preflop_range_advantage_profile(
        FakeTable(), hand, "hero", hand.board, unsupported_estimator
    )
    assert profile["supported"] is False
    assert profile["range_disadvantage"] is False


def test_facing_bet_response_splits_fold_call_and_raise_by_hand_strength():
    weak = module._response_action_probabilities(
        0.06, 0.04, 0.66, "turn", "balanced"
    )
    strong_value = module._response_action_probabilities(
        0.94, 0.02, 0.66, "turn", "balanced"
    )
    strong_draw = module._response_action_probabilities(
        0.08, 0.94, 0.66, "flop", "aggressive"
    )
    for probabilities in (weak, strong_value, strong_draw):
        assert len(probabilities) == 3
        assert all(0.0 <= value <= 1.0 for value in probabilities)
        assert abs(sum(probabilities) - 1.0) < 1e-9
    assert strong_value[2] > weak[2]
    assert strong_draw[2] > weak[2]
    assert weak[0] > 0.0
    assert weak[1] > weak[2]


def test_bet_response_branch_probabilities_sum_to_one_and_condition_on_calls():
    players = [
        FakePlayer("hero", ("Qh", "Qd")),
        FakePlayer("villain", ()),
    ]
    hand = FakeHand(
        players, board=("Js", "7d", "2c"), pot=1200,
        street="flop", to_call=0, actions=("check", "bet"),
        min_target=300, max_target=5000,
    )
    opponent = module.OpponentRange(
        player_id="villain",
        combos=(
            (("Jc", "Jh"), 0.35),
            (("3s", "4s"), 0.65),
        ),
        source="test-range",
        confidence=0.90,
        participation_probability=1.0,
        archetype="balanced",
    )
    metrics = module._bet_response_branch_metrics(
        hand, "hero", {"villain": opponent}, list(hand.board),
        0.66, FakeCPU(5), simulation_multiplier=0.25,
    )
    assert abs(
        metrics["all_fold_probability"]
        + metrics["call_only_probability"]
        + metrics["raise_probability"] - 1.0
    ) < 1e-8
    assert metrics["all_fold_probability"] > 0.0
    assert metrics["call_only_probability"] > 0.0
    assert metrics["raise_probability"] > 0.0
    # With one opponent, conditioning on a call-only branch means exactly one caller.
    assert abs(metrics["expected_callers"] - 1.0) < 1e-8
    assert 0.0 <= metrics["called_equity"] <= 1.0
    assert metrics["samples"] > 0
    assert 0.0 <= metrics["raise_conditioned_equity"] <= 1.0
    assert metrics["raise_samples"] > 0


def test_effective_all_in_cannot_receive_a_further_raise_response():
    players = [
        FakePlayer("hero", ("Qh", "Qd"), stack=500),
        FakePlayer("villain", (), stack=500),
    ]
    hand = FakeHand(
        players, board=("Js", "7d", "2c"), pot=1000,
        street="flop", to_call=0, actions=("check", "bet"),
    )
    opponent = module.OpponentRange(
        player_id="villain",
        combos=((("Jc", "Jh"), 0.5), (("3s", "4s"), 0.5)),
        source="test-range", confidence=0.9,
    )
    metrics = module._bet_response_branch_metrics(
        hand, "hero", {"villain": opponent}, list(hand.board),
        0.75, FakeCPU(5), simulation_multiplier=0.25,
    )
    assert metrics["raise_probability"] == 0.0
    assert abs(
        metrics["all_fold_probability"] + metrics["call_only_probability"] - 1.0
    ) < 1e-8


def test_size_specific_opponent_learning_changes_only_matching_street_and_size():
    baseline = module._response_action_probabilities(
        0.62, 0.18, 0.25, "flop", "balanced"
    )
    sticky = module._response_action_probabilities(
        0.62, 0.18, 0.25, "flop", "balanced",
        {
            "sample_hands": 0,
            "flop_small_response_opportunities": 80,
            "flop_small_fold_rate": 0.08,
            "flop_small_call_rate": 0.12,
            "flop_small_raise_rate": 0.80,
        },
    )
    overfolder = module._response_action_probabilities(
        0.62, 0.18, 0.25, "flop", "balanced",
        {
            "sample_hands": 0,
            "flop_small_response_opportunities": 80,
            "flop_small_fold_rate": 0.92,
            "flop_small_call_rate": 0.07,
            "flop_small_raise_rate": 0.01,
        },
    )
    other_size = module._response_action_probabilities(
        0.62, 0.18, 1.50, "flop", "balanced",
        {
            "sample_hands": 0,
            "flop_small_response_opportunities": 80,
            "flop_small_fold_rate": 0.08,
            "flop_small_call_rate": 0.12,
            "flop_small_raise_rate": 0.80,
        },
    )
    other_street = module._response_action_probabilities(
        0.62, 0.18, 0.25, "turn", "balanced",
        {
            "sample_hands": 0,
            "flop_small_response_opportunities": 80,
            "flop_small_fold_rate": 0.08,
            "flop_small_call_rate": 0.12,
            "flop_small_raise_rate": 0.80,
        },
    )
    assert sticky[2] > baseline[2]
    assert overfolder[0] > baseline[0]
    assert all(abs(a - b) < 1e-12 for a, b in zip(other_size, module._response_action_probabilities(
        0.62, 0.18, 1.50, "flop", "balanced"
    )))
    assert all(abs(a - b) < 1e-12 for a, b in zip(other_street, baseline))
    for probabilities in (baseline, sticky, overfolder, other_size, other_street):
        assert abs(sum(probabilities) - 1.0) < 1e-9



def test_sdv_check_value_beats_a_lower_ev_bet():
    players = [
        FakePlayer("hero", ("As", "Ah")),
        FakePlayer("villain", ()),
    ]
    hand = FakeHand(
        players, board=("Jc", "7d", "2s"), pot=1000, street="flop",
        to_call=0, actions=("check", "bet"), min_target=150, max_target=3000,
    )
    opponent = module.OpponentRange(
        player_id="villain",
        combos=((("Qc", "Qd"), 1.0),),
        source="test-range",
        confidence=1.0,
    )
    original = {
        "infer_opponent_ranges": module.infer_opponent_ranges,
        "_equity_vs_ranges": module._equity_vs_ranges,
        "_blocker_removal_metrics": module._blocker_removal_metrics,
        "_postflop_board_role_context": module._postflop_board_role_context,
        "_bet_response_branch_metrics": module._bet_response_branch_metrics,
    }
    module.infer_opponent_ranges = lambda *args, **kwargs: {"villain": opponent}
    module._equity_vs_ranges = lambda *args, **kwargs: (0.80, 500)
    module._blocker_removal_metrics = lambda *args, **kwargs: {
        "value_call_combos_blocked": 0.0,
        "bluff_call_combos_blocked": 0.0,
        "draw_call_combos_blocked": 0.0,
        "removed_combo_mass": 0.0,
    }
    module._postflop_board_role_context = lambda *args, **kwargs: {
        "preflop_aggressor": "villain",
        "hero_is_preflop_aggressor": False,
        "caller_favored_board": False,
        "aggressor_favored_board": False,
        "preflop_range_disadvantage": False,
        "preflop_range_advantage": False,
        "preflop_range_edge": 0.0,
        "preflop_range_profile": {"supported": False, "top_decile_advantage": 0.0},
        "donk_lead": False,
    }
    module._bet_response_branch_metrics = lambda *args, **kwargs: {
        "all_fold_probability": 0.30,
        "call_only_probability": 0.70,
        "raise_probability": 0.0,
        "expected_callers": 1.0,
        "called_equity": 0.10,
        "samples": 120,
    }
    try:
        decision = module.choose_range_aware_action(
            FakeTable(), hand, "hero", FakeCPU(5)
        )
    finally:
        for name, value in original.items():
            setattr(module, name, value)

    # The small bluff has positive absolute EV, but its 30% fold branch and
    # weak call-conditioned equity make it worth less than checking with 80%
    # range-weighted showdown equity after positional realization.
    assert decision.action == "check"
    assert "raw-equity=80.0%" in decision.note
    assert "realized-equity=77.3%" in decision.note
    assert "SDV-check-EV≈772.8" in decision.note


def test_showdown_value_profile_separates_current_hand_strength_from_draw_equity():
    heads_up = module._postflop_showdown_value_profile(
        0.64, 1, 1.0, "flop", supported=True,
        position_known=True, in_position=True,
    )
    multiway = module._postflop_showdown_value_profile(
        0.64, 1, 3.0, "flop", supported=True,
        position_known=True, in_position=True,
    )
    disadvantaged = module._postflop_showdown_value_profile(
        0.58, 1, 1.0, "flop", supported=True,
        range_disadvantage=True,
    )
    assert heads_up["has_sdv"] is True
    assert heads_up["classification"] in {"medium", "strong"}
    assert multiway["threshold"] > heads_up["threshold"]
    assert multiway["has_sdv"] is True
    assert disadvantaged["threshold"] > heads_up["threshold"]
    assert disadvantaged["has_sdv"] is False


def test_sdv_blocks_bluff_but_keeps_qualified_value_and_protection_bets():
    blocked_value, blocked_bluff = module._postflop_aggression_gates(
        False, True,
        street="river", to_call=0, donk_lead=False,
        range_disadvantage=False, made_category=1, draw_strength=0.0,
        expected_callers=1.0, called_equity=0.30, value_threshold=0.56,
        fold_probability=0.90, required_success=0.25, uncertainty_margin=0.01,
        has_sdv=True,
    )
    value_bet, value_bluff = module._postflop_aggression_gates(
        True, True,
        street="river", to_call=0, donk_lead=False,
        range_disadvantage=False, made_category=1, draw_strength=0.0,
        expected_callers=1.0, called_equity=0.72, value_threshold=0.56,
        fold_probability=0.70, required_success=0.25, uncertainty_margin=0.01,
        has_sdv=True,
    )
    protection_bet, protection_bluff = module._postflop_aggression_gates(
        False, True,
        street="flop", to_call=0, donk_lead=False,
        range_disadvantage=False, made_category=1, draw_strength=0.20,
        expected_callers=1.0, called_equity=0.50, value_threshold=0.56,
        fold_probability=0.55, required_success=0.30, uncertainty_margin=0.01,
        has_sdv=True, protection_gate=True,
    )
    assert blocked_value is False and blocked_bluff is False
    assert value_bet is True and value_bluff is False
    assert protection_bet is True and protection_bluff is False


def test_pure_bluff_requires_value_blockers_fold_equity_and_hu_conditions():
    good = module._postflop_pure_bluff_allowed(
        0.72, 0.30, 0.02, 1.0, 0.22, 0.02,
        in_position=True, range_advantage=False,
    )
    no_value_blocker = module._postflop_pure_bluff_allowed(
        0.92, 0.30, 0.02, 1.0, 0.02, 0.01,
        in_position=True, range_advantage=False,
    )
    multiway = module._postflop_pure_bluff_allowed(
        0.92, 0.30, 0.02, 2.0, 0.22, 0.02,
        in_position=True, range_advantage=True,
    )
    out_of_position_without_range_edge = module._postflop_pure_bluff_allowed(
        0.92, 0.30, 0.02, 1.0, 0.22, 0.02,
        in_position=False, range_advantage=False,
    )
    assert good is True
    assert no_value_blocker is False
    assert multiway is False
    assert out_of_position_without_range_edge is False


def test_thin_value_bets_are_size_capped():
    assert module._postflop_thin_value_size_allowed(True, 0.33, "river") is True
    assert module._postflop_thin_value_size_allowed(True, 0.50, "turn") is True
    assert module._postflop_thin_value_size_allowed(True, 0.51, "flop") is False
    assert module._postflop_thin_value_size_allowed(True, 0.34, "river") is False
    assert module._postflop_thin_value_size_allowed(False, 1.50, "river") is True


def test_high_fold_equity_does_not_turn_a_showdown_hand_into_a_bluff():
    players = [
        FakePlayer("hero", ("As", "Ah")),
        FakePlayer("villain", ()),
    ]
    hand = FakeHand(
        players, board=("Jc", "7d", "2s"), pot=1000, street="flop",
        to_call=0, actions=("check", "bet"), min_target=150, max_target=3000,
    )
    opponent = module.OpponentRange(
        player_id="villain",
        combos=((("Qc", "Qd"), 1.0),),
        source="test-range",
        confidence=1.0,
    )
    original = {
        "infer_opponent_ranges": module.infer_opponent_ranges,
        "_equity_vs_ranges": module._equity_vs_ranges,
        "_current_showdown_equity": module._current_showdown_equity,
        "_blocker_removal_metrics": module._blocker_removal_metrics,
        "_postflop_board_role_context": module._postflop_board_role_context,
        "_bet_response_branch_metrics": module._bet_response_branch_metrics,
    }
    module.infer_opponent_ranges = lambda *args, **kwargs: {"villain": opponent}
    module._equity_vs_ranges = lambda *args, **kwargs: (0.80, 500)
    module._current_showdown_equity = lambda *args, **kwargs: (0.80, 200)
    module._blocker_removal_metrics = lambda *args, **kwargs: {
        "value_call_combos_blocked": 0.0,
        "bluff_call_combos_blocked": 0.0,
        "draw_call_combos_blocked": 0.0,
        "removed_combo_mass": 0.0,
    }
    module._postflop_board_role_context = lambda *args, **kwargs: {
        "preflop_aggressor": "villain",
        "hero_is_preflop_aggressor": False,
        "caller_favored_board": False,
        "aggressor_favored_board": False,
        "preflop_range_disadvantage": False,
        "preflop_range_advantage": False,
        "preflop_range_edge": 0.0,
        "preflop_range_profile": {"supported": False, "top_decile_advantage": 0.0},
        "donk_lead": False,
    }
    module._bet_response_branch_metrics = lambda *args, **kwargs: {
        "all_fold_probability": 0.98,
        "call_only_probability": 0.02,
        "raise_probability": 0.0,
        "expected_callers": 0.02,
        "called_equity": 0.10,
        "called_current_equity": 0.10,
        "samples": 120,
    }
    try:
        decision = module.choose_range_aware_action(
            FakeTable(), hand, "hero", FakeCPU(5)
        )
    finally:
        for name, value in original.items():
            setattr(module, name, value)

    assert decision.action == "check"
    assert "SDV-profile=" in decision.note
    assert "SDV-supported=True" in decision.note


def test_chart_range_profile_recognizes_hero_positive_range_advantage():
    players = [
        FakePlayer("hero", ("9h", "Th")),
        FakePlayer("villain", ("2c", "3d")),
    ]
    hand = FakeHand(
        players, board=("8s", "7d", "6c"), pot=500,
        street="flop", to_call=0, actions=("check", "bet"),
    )

    def screenshot_policy_estimator(*, table, hand, exclude_player_id=None):
        return {
            "supported": True,
            "players": {
                "hero": {
                    "supported": True,
                    "hand_class_probabilities": {
                        "88": 0.40, "77": 0.40, "87s": 0.20,
                    },
                },
                "villain": {
                    "supported": True,
                    "hand_class_probabilities": {
                        "AA": 0.40, "KK": 0.30, "QQ": 0.30,
                    },
                },
            },
        }

    profile = module._preflop_range_advantage_profile(
        FakeTable(), hand, "hero", hand.board, screenshot_policy_estimator
    )
    assert profile["supported"] is True
    assert profile["mean_advantage"] > 0.0
    assert profile["top_decile_advantage"] > 0.0
    assert profile["range_advantage"] is True
    assert profile["range_edge"] > 0.0


def test_postflop_size_candidates_follow_range_edge_and_donk_context():
    polarized = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.12, expected_callers=1.0,
    )
    disadvantaged = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=False,
        range_disadvantage=True, nut_advantage=-0.08, expected_callers=1.0,
    )
    donk_hu = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=True, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.12, expected_callers=1.0,
    )
    donk_multiway = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=True, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.12, expected_callers=2.0,
    )
    assert 0.50 in polarized
    assert max(polarized) <= 0.75
    assert max(disadvantaged) <= 0.75
    assert max(donk_hu) <= 0.50
    assert max(donk_multiway) <= 0.33
    facing_bet_raise = module._postflop_bet_size_fractions(
        to_call=True, donk_lead=True, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.12, expected_callers=1.0,
    )
    # Raise candidates stay measured; the call amount is not part of the wager
    # passed to the opponent fold/call model.
    assert 1.00 in facing_bet_raise
    assert max(facing_bet_raise) <= 1.25
    assert max(facing_bet_raise) > max(donk_hu)


def test_postflop_raise_response_fraction_excludes_the_call_amount():
    # Pot before hero acts is 1,600; calling 500 and raising another 800
    # costs 1,300 total. Opponents face the extra 800 into the 2,100 pot
    # that exists after the call: 38.1%, not 81.25% or 1.0 pot.
    fraction = module._postflop_size_fraction(1600, risk=1300, to_call=500)
    assert abs(fraction - (800 / 2100)) < 1e-9
    assert module._postflop_size_fraction(1600, risk=400, to_call=0) == 0.25


def test_large_postflop_bets_polarize_to_strong_value_or_qualified_bluffs():
    # A middle-strength one-pair hand is allowed to use a merged small size,
    # but is kept out of the >=75% pot polarized betting range.
    middle_small = module._postflop_polarized_candidate_role(
        0.50, street="river", value_gate=True, bluff_gate=False,
        has_sdv=True, made_category=1, current_equity=0.62,
        nut_advantage=0.08, range_advantage=True, range_disadvantage=False,
        expected_callers=1.0, fold_probability=0.30, required_success=0.33,
        uncertainty_margin=0.02, value_combos_blocked=0.0,
        bluff_combos_blocked=0.0, draw_strength=0.0, in_position=True,
    )
    middle_large = module._postflop_polarized_candidate_role(
        0.75, street="river", value_gate=True, bluff_gate=False,
        has_sdv=True, made_category=1, current_equity=0.62,
        nut_advantage=0.08, range_advantage=True, range_disadvantage=False,
        expected_callers=1.0, fold_probability=0.30, required_success=0.33,
        uncertainty_margin=0.02, value_combos_blocked=0.0,
        bluff_combos_blocked=0.0, draw_strength=0.0, in_position=True,
    )
    strong_value = module._postflop_polarized_candidate_role(
        1.00, street="river", value_gate=True, bluff_gate=False,
        has_sdv=True, made_category=3, current_equity=0.84,
        nut_advantage=0.20, range_advantage=True, range_disadvantage=False,
        expected_callers=1.0, fold_probability=0.20, required_success=0.50,
        uncertainty_margin=0.01, value_combos_blocked=0.0,
        bluff_combos_blocked=0.0, draw_strength=0.0, in_position=True,
    )
    assert middle_small == "merged"
    assert middle_large is None
    assert strong_value == "value"


def test_polarized_bluffs_need_low_sdv_blockers_and_fold_equity():
    qualified = module._postflop_polarized_candidate_role(
        0.90, street="river", value_gate=False, bluff_gate=True,
        has_sdv=False, made_category=0, current_equity=0.12,
        nut_advantage=0.16, range_advantage=True, range_disadvantage=False,
        expected_callers=1.0, fold_probability=0.72, required_success=0.45,
        uncertainty_margin=0.01, value_combos_blocked=0.10,
        bluff_combos_blocked=0.01, draw_strength=0.0, in_position=True,
    )
    no_blocker = module._postflop_polarized_candidate_role(
        0.90, street="river", value_gate=False, bluff_gate=True,
        has_sdv=False, made_category=0, current_equity=0.12,
        nut_advantage=0.16, range_advantage=True, range_disadvantage=False,
        expected_callers=1.0, fold_probability=0.72, required_success=0.45,
        uncertainty_margin=0.01, value_combos_blocked=0.01,
        bluff_combos_blocked=0.02, draw_strength=0.0, in_position=True,
    )
    showdown_hand = module._postflop_polarized_candidate_role(
        0.90, street="river", value_gate=False, bluff_gate=True,
        has_sdv=True, made_category=1, current_equity=0.62,
        nut_advantage=0.16, range_advantage=True, range_disadvantage=False,
        expected_callers=1.0, fold_probability=0.72, required_success=0.45,
        uncertainty_margin=0.01, value_combos_blocked=0.10,
        bluff_combos_blocked=0.01, draw_strength=0.0, in_position=True,
    )
    assert qualified == "bluff"
    assert no_blocker is None
    assert showdown_hand is None


def test_multiway_polarization_blocks_bluffs_and_requires_near_nutted_value():
    multiway_bluff = module._postflop_polarized_candidate_role(
        0.90, street="turn", value_gate=False, bluff_gate=True,
        has_sdv=False, made_category=0, current_equity=0.10,
        nut_advantage=0.30, range_advantage=True, range_disadvantage=False,
        expected_callers=2.0, fold_probability=0.85, required_success=0.45,
        uncertainty_margin=0.01, value_combos_blocked=0.12,
        bluff_combos_blocked=0.01, draw_strength=0.60, in_position=True,
    )
    multiway_middle = module._postflop_polarized_candidate_role(
        0.90, street="turn", value_gate=True, bluff_gate=False,
        has_sdv=True, made_category=2, current_equity=0.75,
        nut_advantage=0.30, range_advantage=True, range_disadvantage=False,
        expected_callers=2.0, fold_probability=0.20, required_success=0.50,
        uncertainty_margin=0.01, value_combos_blocked=0.0,
        bluff_combos_blocked=0.0, draw_strength=0.0, in_position=False,
    )
    multiway_nuts = module._postflop_polarized_candidate_role(
        1.00, street="turn", value_gate=True, bluff_gate=False,
        has_sdv=True, made_category=4, current_equity=0.90,
        nut_advantage=0.40, range_advantage=True, range_disadvantage=False,
        expected_callers=2.0, fold_probability=0.20, required_success=0.50,
        uncertainty_margin=0.01, value_combos_blocked=0.0,
        bluff_combos_blocked=0.0, draw_strength=0.0, in_position=False,
    )
    assert multiway_bluff is None
    assert multiway_middle is None
    assert multiway_nuts == "value-multiway"


def test_preflop_174_policy_bypasses_postflop_polarization_gate():
    assert module._postflop_polarized_candidate_role(
        2.50, street="preflop", value_gate=False, bluff_gate=False,
        has_sdv=False, made_category=0, current_equity=0.0,
        nut_advantage=0.0, range_advantage=False, range_disadvantage=False,
        expected_callers=3.0, fold_probability=0.0, required_success=0.0,
        uncertainty_margin=0.0, value_combos_blocked=0.0,
        bluff_combos_blocked=0.0, draw_strength=0.0, in_position=False,
    ) == "preflop-chart"


def test_postflop_overbets_require_a_polar_nut_edge_or_low_spr_stackoff():
    assert module._postflop_overbet_size_allowed(
        1.25, street="turn", range_advantage=True, range_disadvantage=False,
        nut_advantage=0.18, expected_callers=1.0, made_category=3,
        current_equity=0.78, spr=3.0,
    ) is True
    assert module._postflop_overbet_size_allowed(
        1.50, street="river", range_advantage=True, range_disadvantage=False,
        nut_advantage=0.24, expected_callers=1.0, made_category=3,
        current_equity=0.82, spr=2.0,
    ) is True
    assert module._postflop_overbet_size_allowed(
        1.50, street="flop", range_advantage=True, range_disadvantage=False,
        nut_advantage=0.20, expected_callers=1.0, made_category=3,
        current_equity=0.90, spr=1.5,
    ) is True
    assert module._postflop_overbet_size_allowed(
        1.50, street="flop", range_advantage=True, range_disadvantage=False,
        nut_advantage=0.20, expected_callers=1.0, made_category=1,
        current_equity=0.75, spr=8.0,
    ) is False
    assert module._postflop_overbet_size_allowed(
        1.50, street="turn", range_advantage=False, range_disadvantage=False,
        nut_advantage=0.25, expected_callers=1.0, made_category=3,
        current_equity=0.90, spr=4.0,
    ) is False
    assert module._postflop_overbet_size_allowed(
        1.50, street="river", range_advantage=True, range_disadvantage=False,
        nut_advantage=0.20, expected_callers=2.0, made_category=2,
        current_equity=0.80, spr=2.0,
    ) is False


def test_multiway_postflop_sizes_are_capped_unless_nut_advantage_is_extreme():
    normal_multiway = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.12, expected_callers=2.0,
        street="flop", made_category=3,
    )
    rare_nutted_multiway = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.35, expected_callers=2.0,
        street="turn", made_category=4,
    )
    assert max(normal_multiway) <= 0.50
    assert 1.25 in rare_nutted_multiway


def test_verified_caller_range_edge_allows_strong_top_pair_donk():
    value_gate, bluff_gate = module._postflop_aggression_gates(
        True, False,
        street="flop", to_call=0, donk_lead=True,
        range_disadvantage=False, range_advantage=True, range_edge=0.10,
        made_category=1, draw_strength=0.14, expected_callers=1.0,
        called_equity=0.68, value_threshold=0.55,
        fold_probability=0.25, required_success=0.35, uncertainty_margin=0.02,
    )
    assert value_gate is True
    assert bluff_gate is False



def test_current_showdown_equity_excludes_future_draw_equity():
    players = [
        FakePlayer("hero", ("As", "Kd")),
        FakePlayer("villain", ()),
    ]
    hand = FakeHand(
        players, board=("Jc", "7d", "2s"), pot=1000, street="flop",
        to_call=0, actions=("check", "bet"),
    )
    opponent = module.OpponentRange(
        player_id="villain",
        combos=((("Qc", "Qd"), 1.0),),
        source="exact-test-combo",
        confidence=1.0,
    )
    current, samples = module._current_showdown_equity(
        hand, "hero", {"villain": opponent}, FakeCPU(5)
    )
    # A-high is behind QQ on the current flop; turn/river improvement outs
    # belong to runout equity and must not be mislabelled as current SDV.
    assert current == 0.0
    assert samples >= 100


def test_current_showdown_equity_respects_joint_blockers_and_participation():
    players = [
        FakePlayer("hero", ("As", "Ah")),
        FakePlayer("villain1", ()),
        FakePlayer("villain2", ()),
    ]
    hand = FakeHand(
        players, board=("Jc", "7d", "2s"), pot=1000, street="flop",
        to_call=0, actions=("check", "bet"),
    )
    strong = module.OpponentRange(
        player_id="villain1", combos=((("Qc", "Qd"), 1.0),),
        source="test", confidence=1.0, participation_probability=1.0,
    )
    folded = module.OpponentRange(
        player_id="villain2", combos=((("Kc", "Kd"), 1.0),),
        source="test", confidence=1.0, participation_probability=0.0,
    )
    current, _ = module._current_showdown_equity(
        hand, "hero", {"villain1": strong, "villain2": folded}, FakeCPU(5)
    )
    assert current == 1.0


def test_equity_realization_respects_position_street_and_multiway_pressure():
    ip = module._equity_realization_factor(
        "flop", in_position=True, position_known=True,
        expected_opponents=1.0, made_category=1, draw_strength=0.2,
    )
    oop = module._equity_realization_factor(
        "flop", in_position=False, position_known=True,
        expected_opponents=1.0, made_category=1, draw_strength=0.2,
    )
    multiway = module._equity_realization_factor(
        "flop", in_position=False, position_known=True,
        expected_opponents=3.0, made_category=1, draw_strength=0.2,
    )
    river = module._equity_realization_factor(
        "river", in_position=False, position_known=True,
        expected_opponents=4.0, made_category=0, draw_strength=0.0,
    )
    assert ip > oop
    assert multiway < oop
    assert river == 1.0


def test_postflop_position_profile_identifies_last_to_act():
    players = [
        FakePlayer("hero", ("As", "Kd")),
        FakePlayer("villain", ()),
        FakePlayer("other", ()),
    ]
    hand = FakeHand(
        players, board=("Jc", "7d", "2s"), pot=1000, street="flop",
        to_call=0, actions=("check", "bet"),
    )
    # Seat 0 is the dealer/button and acts last postflop.
    profile = module._postflop_position_profile(FakeTable(), hand, "hero")
    assert profile["known"] is True
    assert profile["in_position"] is True
    assert profile["opponents_after"] == 0

    hand.seat_by_id = {"hero": 1, "villain": 0, "other": 2}
    profile_oop = module._postflop_position_profile(FakeTable(), hand, "hero")
    assert profile_oop["known"] is True
    assert profile_oop["in_position"] is False
    assert profile_oop["opponents_after"] == 2


def test_postflop_action_posterior_shifts_range_toward_stronger_made_hands():
    players = [
        FakePlayer("hero", ("As", "Kd")),
        FakePlayer("villain", ()),
    ]
    hand = FakeHand(
        players, board=("Jc", "7d", "2s"), pot=1000, street="flop",
        to_call=0, actions=("check", "bet"),
    )
    row = {
        "supported": True,
        "hand_class_probabilities": {"JJ": 0.50, "A4o": 0.50},
        "archetype": "balanced",
    }
    before = module._action_updated_range_board_profile(
        row, hand, "villain", list(hand.board)
    )
    hand.events = [
        {"type": "street", "street": "flop", "board": ["Jc", "7d", "2s"]},
        {"type": "action", "street": "flop", "player": "villain", "action": "bet",
         "target": 2000, "paid": 2000, "pot_before": 1000, "to_call_before": 0},
    ]
    after = module._action_updated_range_board_profile(
        row, hand, "villain", list(hand.board)
    )
    assert before is not None and after is not None
    assert after["mean_strength"] > before["mean_strength"]
    assert after["two_pair_plus_mass"] >= before["two_pair_plus_mass"]


def test_near_indifferent_actions_use_a_controlled_mix_at_high_cpu_level():
    candidates = [
        ("check", None, 100.0),
        ("bet", 300, 99.5),
        ("bet", 600, 80.0),
    ]
    action, amount, mixed, count = module._sample_near_optimal_action(
        candidates, best_ev=100.0, pot=1000, level=5, rng=FixedRandom()
    )
    assert action in {"check", "bet"}
    assert amount in {None, 300}
    assert mixed is True
    assert count == 2


def test_low_cpu_level_keeps_near_optimal_policy_deterministic():
    candidates = [
        ("check", None, 100.0),
        ("bet", 300, 99.9),
    ]
    action, amount, mixed, count = module._sample_near_optimal_action(
        candidates, best_ev=100.0, pot=1000, level=3, rng=FixedRandom()
    )
    assert (action, amount) == ("check", None)
    assert mixed is False
    assert count == 1


def test_draw_equity_does_not_automatically_qualify_as_thin_value():
    value, bluff = module._postflop_aggression_gates(
        True, True,
        street="flop", to_call=0, donk_lead=False,
        range_disadvantage=False, made_category=0, draw_strength=0.90,
        expected_callers=1.0, called_equity=0.62,
        value_threshold=0.56, fold_probability=0.65,
        required_success=0.35, uncertainty_margin=0.02,
        called_current_equity=0.18,
    )
    assert value is False
    # A strong draw can still be used as a semi-bluff, subject to fold equity.
    assert bluff is True



def test_board_texture_changes_size_plan_for_dry_wet_and_paired_boards():
    dry = module._postflop_board_texture(["As", "7d", "2c"])
    wet = module._postflop_board_texture(["9s", "8s", "7d"])
    paired = module._postflop_board_texture(["8s", "8d", "2c"])
    monotone = module._postflop_board_texture(["As", "Ks", "4s"])
    assert dry["wetness"] < wet["wetness"]
    assert paired["paired"] is True
    assert monotone["monotone"] is True

    dry_plan = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.10, expected_callers=1.0,
        board_texture=dry,
    )
    wet_plan = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.10, expected_callers=1.0,
        board_texture=wet,
    )
    disadvantage_plan = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=False,
        range_disadvantage=True, nut_advantage=-0.10, expected_callers=1.0,
        board_texture=wet,
    )
    assert min(dry_plan) < min(wet_plan)
    assert max(wet_plan) <= 0.75
    assert max(disadvantage_plan) <= 0.75


def test_completed_draws_are_identified_from_public_board_only():
    turn_flush = module._postflop_board_texture(["As", "Ks", "4s", "2d"])
    river_straight = module._postflop_board_texture(["9c", "8d", "7h", "6s", "5c"])
    flop_monotone = module._postflop_board_texture(["As", "Ks", "4s"])
    assert turn_flush["completed_flush"] is True
    assert river_straight["completed_straight"] is True
    assert flop_monotone["completed_flush"] is False
    assert flop_monotone["monotone"] is True



def test_spr_changes_opponent_continue_and_raise_response():
    shallow = module._response_action_probabilities(
        0.58, 0.16, 0.66, "flop", "balanced", spr=1.2
    )
    deep = module._response_action_probabilities(
        0.58, 0.16, 0.66, "flop", "balanced", spr=12.0
    )
    assert shallow[1] + shallow[2] > deep[1] + deep[2]
    assert shallow[2] > deep[2]


def test_spr_calibrates_equity_realization_and_thin_value_threshold():
    shallow_realization = module._equity_realization_factor(
        "flop", in_position=True, position_known=True,
        expected_opponents=1.0, made_category=3, draw_strength=0.1, spr=1.5,
    )
    deep_realization = module._equity_realization_factor(
        "flop", in_position=True, position_known=True,
        expected_opponents=1.0, made_category=3, draw_strength=0.1, spr=12.0,
    )
    shallow_threshold = module._thin_value_threshold(
        5, 0.01, 1.0, 0.30, "flop", spr=1.5, made_category=3,
    )
    deep_threshold = module._thin_value_threshold(
        5, 0.01, 1.0, 0.30, "flop", spr=12.0, made_category=3,
    )
    assert shallow_realization > deep_realization
    assert shallow_threshold < deep_threshold


def test_spr_expands_stackoff_sizes_only_for_strong_nut_hands():
    texture = module._postflop_board_texture(["As", "7d", "2c"])
    shallow = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.16, expected_callers=1.0,
        board_texture=texture, spr=1.5, street="flop", made_category=3,
    )
    shallow_one_pair = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.16, expected_callers=1.0,
        board_texture=texture, spr=1.5, street="flop", made_category=1,
    )
    deep = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.12, expected_callers=1.0,
        board_texture=texture, spr=12.0, street="flop", made_category=3,
    )
    assert 1.50 in shallow
    assert max(shallow_one_pair) <= 0.75
    assert max(deep) <= 0.75
    assert 0.25 in deep



def test_opponent_board_profile_removes_hero_known_card_blockers():
    players = [
        FakePlayer("hero", ("As", "Kd")),
        FakePlayer("villain", ()),
    ]
    hand = FakeHand(
        players, board=("Jc", "7d", "2s"), pot=1000, street="flop",
        to_call=0, actions=("check", "bet"),
    )
    row = {
        "supported": True,
        "hand_class_probabilities": {"AA": 0.50, "KK": 0.50},
    }
    unblocked_only_by_board = module._action_updated_range_board_profile(
        row, hand, "villain", list(hand.board)
    )
    conditioned_on_hero = module._action_updated_range_board_profile(
        row, hand, "villain", list(hand.board),
        extra_blockers=tuple(hand.player("hero").hole_cards),
    )
    assert unblocked_only_by_board is not None and conditioned_on_hero is not None
    assert conditioned_on_hero["sampled_combos"] < unblocked_only_by_board["sampled_combos"]




def test_one_pair_plus_draw_needs_made_hand_equity_to_be_thin_value():
    value, bluff = module._postflop_aggression_gates(
        True, True,
        street="flop", to_call=0, donk_lead=False,
        range_disadvantage=False, made_category=1, draw_strength=0.92,
        expected_callers=1.0, called_equity=0.64,
        value_threshold=0.56, fold_probability=0.68,
        required_success=0.35, uncertainty_margin=0.02,
        called_current_equity=0.30,
    )
    assert value is False
    assert bluff is True




def test_semi_bluff_draw_strength_uses_call_range_improvement_equity():
    clean_draw = module._range_conditioned_draw_strength(
        0.24, 0.56, 0.18, "flop"
    )
    no_improvement = module._range_conditioned_draw_strength(
        0.50, 0.48, 0.22, "turn"
    )
    river = module._range_conditioned_draw_strength(
        0.30, 0.30, 0.99, "river"
    )
    assert clean_draw > 0.50
    assert no_improvement == 0.22
    assert river == 0.0


def test_174_chart_bayesian_ranges_update_from_recorded_action_and_learned_stats():
    players = [
        FakePlayer("btn"), FakePlayer("sb"), FakePlayer("bb"),
        FakePlayer("utg"), FakePlayer("hj"), FakePlayer("co"),
    ]
    hand = FakeHand(
        players, board=(), pot=150, street="preflop",
        to_call=0, actions=("check", "raise", "fold"),
    )
    hand.big_blind = 100
    hand.events = [
        {"type": "action", "street": "preflop", "player_id": "utg", "action": "fold"},
        {"type": "action", "street": "preflop", "player_id": "hj", "action": "fold"},
        {"type": "action", "street": "preflop", "player_id": "co", "action": "fold"},
        {"type": "action", "street": "preflop", "player_id": "btn",
         "action": "raise", "target": 250, "paid": 250},
        {"type": "action", "street": "preflop", "player_id": "sb", "action": "fold"},
        # Scenario 146: BB responds to BTN's 2.5 BB open with a 13 BB 3-bet.
        {"type": "action", "street": "preflop", "player_id": "bb",
         "action": "raise", "target": 1300, "paid": 1300},
    ]
    learned = {
        "bb": {"sample_hands": 40.0, "postflop_call_rate": 0.52,
               "postflop_aggression_rate": 0.34, "fold_to_bet_rate": 0.41},
    }
    profiles = {"bb": SimpleNamespace(archetype="aggressive")}
    estimate = module.build_174_preflop_range_estimate(
        FakeTable(), hand, learned_profiles=learned, player_profiles=profiles
    )
    assert estimate["supported"] is True
    row = estimate["players"]["bb"]
    assert row["supported"] is True
    assert row["observed_preflop_actions"] == 1
    # Multiple 174 source images can carry the same fully matched history;
    # the range posterior should keep the matched node rather than force one ID.
    assert row["exact_preflop_nodes"] == 1
    assert row["inferred_preflop_nodes"] == 0
    assert len(row["scenario_ids"]) == 1
    assert row["confidence"] > 0.16
    assert row["source"] == "174-preflop-sequential-bayesian-range"
    assert abs(sum(row["hand_class_probabilities"].values()) - 1.0) < 1e-8
    assert abs(sum(row["unblocked_hand_class_probabilities"].values()) - 1.0) < 1e-8
    # A chart-observed BTN open is more compatible with premium hands than 72o.
    assert row["hand_class_probabilities"]["AA"] > row["hand_class_probabilities"]["72o"]
    assert row["archetype"] == "aggressive"
    assert row["learned_behavior"]["sample_hands"] == 40.0


def test_174_chart_does_not_invent_a_first_in_limp_range():
    players = [
        FakePlayer("btn"), FakePlayer("sb"), FakePlayer("bb"),
        FakePlayer("utg"), FakePlayer("hj"), FakePlayer("co"),
    ]
    hand = FakeHand(players, board=(), street="preflop", actions=("call", "raise", "fold"))
    hand.events = [
        {"type": "action", "street": "preflop", "player_id": "utg", "action": "fold"},
        {"type": "action", "street": "preflop", "player_id": "hj", "action": "fold"},
        {"type": "action", "street": "preflop", "player_id": "co", "action": "fold"},
        {"type": "action", "street": "preflop", "player_id": "btn", "action": "call", "paid": 100},
    ]
    estimate = module.build_174_preflop_range_estimate(FakeTable(), hand)
    # An unsupported chart action is not silently converted into a fake range.
    assert "btn" not in estimate["players"]


def test_all_in_call_realizes_raw_equity_but_non_all_in_call_does_not():
    raw = 0.48
    realized = 0.86
    assert module._call_realized_equity(
        raw, realized, call_is_all_in=True
    ) == raw
    assert module._call_realized_equity(
        raw, realized, call_is_all_in=False
    ) == raw * realized


def test_geometric_bet_size_tracks_spr_and_streets_remaining():
    flop = module._geometric_bet_fraction(4.0, 3)
    turn = module._geometric_bet_fraction(4.0, 2)
    river = module._geometric_bet_fraction(4.0, 1)
    assert flop is not None and turn is not None and river is not None
    assert 0.50 < flop < turn < river
    texture = module._postflop_board_texture(["As", "7d", "2c"])
    sizes = module._postflop_bet_size_fractions(
        to_call=False, donk_lead=False, range_advantage=True,
        range_disadvantage=False, nut_advantage=0.12,
        expected_callers=1.0, board_texture=texture,
        spr=4.0, remaining_streets=3,
    )
    assert round(flop, 2) in sizes




def test_cash_cpu_connects_174_chart_ranges_and_learned_profiles_to_postflop():
    app_path = SOURCE_DIR / "PigeonPoker.pyw"
    app_source = app_path.read_text(encoding="utf-8")
    assert "build_174_preflop_range_estimate" in app_source
    assert "learned_profiles=opponent_learning" in app_source
    assert "player_profiles=profiles" in app_source
    assert "def postflop_range_estimator(" in app_source
    assert app_source.count("range_estimator=postflop_range_estimator") == 2
    # The 174 preflop policy remains a separate, immutable CPU decision path.
    assert "choose_preflop_174_action(table, hand, pid, cpu)" in app_source
    reasoning_source = MODULE_PATH.read_text(encoding="utf-8")
    assert "def _postflop_polarized_candidate_role(" in reasoning_source
    assert "polar-role={selected_polar_role}" in reasoning_source
    assert "def _postflop_sdv_aggression_allowed(" in reasoning_source
    assert "SDV-bet-candidates-blocked={sdv_candidates_blocked}" in reasoning_source
    assert "sdv_passive_baseline_ev" in reasoning_source



def test_flush_and_straight_draws_require_private_hand_contribution():
    # Four flush cards on the board alone must not be treated as every
    # opponent holding a private flush draw.
    board_only_flush = module._board_metrics(
        ("Qc", "As"), ["2h", "7h", "Kh", "3h"]
    )[1]
    # Four consecutive ranks on the board alone likewise do not create a
    # private straight draw for unrelated low hole cards.
    board_only_straight = module._board_metrics(
        ("2c", "3d"), ["6s", "7h", "8c", "9d"]
    )[1]
    assert board_only_flush < 0.30
    assert board_only_straight == 0.0


def test_flush_draw_quality_recognizes_nut_and_backdoor_contribution():
    nut_flush_draw = module._board_metrics(
        ("Ah", "Qs"), ["2h", "7h", "Kh"]
    )[1]
    dominated_flush_draw = module._board_metrics(
        ("3h", "Qs"), ["2h", "7h", "Kh"]
    )[1]
    private_backdoor_flush = module._board_metrics(
        ("Qh", "As"), ["2h", "7h", "Kd"]
    )[1]
    no_private_backdoor_flush = module._board_metrics(
        ("Qc", "As"), ["2h", "7h", "Kd"]
    )[1]
    assert nut_flush_draw > dominated_flush_draw
    assert private_backdoor_flush > no_private_backdoor_flush


def test_postflop_raise_size_fraction_uses_the_post_call_pot_consistently():
    increment = module._postflop_raise_increment(1600, 500, 0.50)
    assert increment == 1050
    actual_fraction = module._postflop_size_fraction(
        1600, 500 + increment, 500
    )
    assert actual_fraction == 0.50
    # A lead bet continues to use the uncalled current pot as its denominator.
    assert module._postflop_raise_increment(1600, 0, 0.50) == 800




def test_sdv_thin_and_medium_value_bets_need_equity_edge_and_size_discipline():
    common = dict(
        has_sdv=True, street="flop", to_call=0, made_category=1,
        called_current_equity=0.70, value_threshold=0.56,
        expected_callers=1.0, value_gate=True, protection_gate=False,
        candidate_ev=1060, passive_ev=1000, pot=1000,
    )
    thin_small = module._postflop_sdv_aggression_allowed(
        classification="thin", bet_fraction=0.33, **common
    )
    thin_large = module._postflop_sdv_aggression_allowed(
        classification="thin", bet_fraction=0.50, **common
    )
    thin_low_ev = module._postflop_sdv_aggression_allowed(
        classification="thin", bet_fraction=0.25,
        **{**common, "candidate_ev": 1020},
    )
    medium_half_pot = module._postflop_sdv_aggression_allowed(
        classification="medium", bet_fraction=0.50, **common
    )
    medium_over_size = module._postflop_sdv_aggression_allowed(
        classification="medium", bet_fraction=0.75, **common
    )
    assert thin_small is True
    assert thin_large is False
    assert thin_low_ev is False
    assert medium_half_pot is True
    assert medium_over_size is False


def test_sdv_river_thin_value_is_smaller_and_multiway_is_stricter():
    river = dict(
        has_sdv=True, classification="thin", street="river", to_call=0,
        made_category=1, called_current_equity=0.74,
        value_threshold=0.52, expected_callers=1.0, value_gate=True,
        protection_gate=False, candidate_ev=1100, passive_ev=1000, pot=1000,
    )
    small_river = module._postflop_sdv_aggression_allowed(
        bet_fraction=0.25, **river
    )
    third_pot_river = module._postflop_sdv_aggression_allowed(
        bet_fraction=0.33, **river
    )
    multiway = module._postflop_sdv_aggression_allowed(
        bet_fraction=0.25, **{**river, "expected_callers": 2.0}
    )
    assert small_river is True
    assert third_pot_river is False
    assert multiway is False


def test_sdv_one_pair_raises_require_exceptional_calling_range_equity():
    base = dict(
        has_sdv=True, classification="medium", street="turn", to_call=500,
        bet_fraction=0.50, made_category=1, value_threshold=0.56,
        expected_callers=1.0, value_gate=True, protection_gate=False,
        candidate_ev=1200, passive_ev=1000, pot=1000,
    )
    ordinary_top_pair = module._postflop_sdv_aggression_allowed(
        called_current_equity=0.74, **base
    )
    near_exceptional_top_pair = module._postflop_sdv_aggression_allowed(
        called_current_equity=0.87, **{**base, "classification": "strong"},
    )
    assert ordinary_top_pair is False
    assert near_exceptional_top_pair is True


def test_sdv_protection_bets_are_small_and_must_not_sacrifice_check_ev():
    base = dict(
        has_sdv=True, classification="thin", street="flop", to_call=0,
        made_category=1, called_current_equity=0.50, value_threshold=0.56,
        expected_callers=1.0, value_gate=True, protection_gate=True,
        candidate_ev=1020, passive_ev=1000, pot=1000,
    )
    small_protection = module._postflop_sdv_aggression_allowed(
        bet_fraction=0.25, **base
    )
    half_pot_protection = module._postflop_sdv_aggression_allowed(
        bet_fraction=0.50, **base
    )
    ev_losing_protection = module._postflop_sdv_aggression_allowed(
        bet_fraction=0.20, **{**base, "candidate_ev": 990}
    )
    assert small_protection is True
    assert half_pot_protection is False
    assert ev_losing_protection is False



if __name__ == "__main__":
    tests = [value for name, value in globals().items()
             if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests))
