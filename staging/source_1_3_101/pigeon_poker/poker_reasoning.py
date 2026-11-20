from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
import random
from typing import Any, Callable

from .cpu import CPUAction
from .engine import evaluate_seven, make_deck

RANKS = "23456789TJQKA"
SUITS = "cdhs"


@dataclass(frozen=True)
class OpponentRange:
    player_id: str
    combos: tuple[tuple[tuple[str, str], float], ...]
    source: str
    confidence: float
    participation_probability: float = 1.0


@dataclass(frozen=True)
class PokerDecisionMetrics:
    equity: float
    required_call_equity: float
    required_bluff_success: float
    fold_probability: float
    modeled_opponents: int
    samples: int
    uncertainty: float


def _event_action(event: dict[str, Any]) -> str:
    raw = str(event.get("action", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if event.get("is_all_in") or event.get("all_in") or event.get("jam"):
        return "allin"
    if raw in {"allin", "all_in", "jam", "shove"}:
        return "allin"
    if raw in {"raise", "bet", "raise_to", "bet_to"}:
        return "raise"
    if raw in {"call", "called", "all_in_call"}:
        return "call"
    if raw in {"fold", "folded"}:
        return "fold"
    return raw


def _player_events(hand: Any, player_id: str, *, street: str | None = None) -> list[dict[str, Any]]:
    player = next(
        (p for p in list(getattr(hand, "players", ()) or ())
         if str(getattr(p, "player_id", "")) == str(player_id)),
        None,
    )
    names = {str(player_id)}
    if player is not None:
        names.add(str(getattr(player, "name", "")))
    result = []
    for event in list(getattr(hand, "events", ()) or ()):
        if not isinstance(event, dict) or event.get("type") != "action":
            continue
        actor = str(event.get("player_id") or event.get("player") or "")
        if actor not in names:
            continue
        event_street = str(event.get("street", "preflop")).lower().replace("-", "")
        if street is None or event_street == street:
            result.append(event)
    return result


def _physical_combos(hand_class: str) -> list[tuple[str, str]]:
    value = str(hand_class)
    if len(value) == 2 and value[0] == value[1] and value[0] in RANKS:
        return [
            (value[0] + first, value[1] + second)
            for first, second in itertools.combinations(SUITS, 2)
        ]
    if (len(value) != 3 or value[0] not in RANKS or value[1] not in RANKS
            or value[0] == value[1] or value[2] not in {"s", "o"}
            or RANKS.index(value[0]) <= RANKS.index(value[1])):
        return []
    high, low, suited = value
    if suited == "s":
        return [(high + suit, low + suit) for suit in SUITS]
    return [
        (high + first, low + second)
        for first in SUITS for second in SUITS if first != second
    ]


def _preflop_strength(hand_class: str) -> float:
    value = str(hand_class)
    if len(value) == 2 and value[0] == value[1] and value[0] in RANKS:
        return 0.50 + 0.49 * RANKS.index(value[0]) / 12.0
    if len(value) != 3 or value[0] not in RANKS or value[1] not in RANKS:
        return 0.0
    high, low, suited = value
    hi, lo = RANKS.index(high), RANKS.index(low)
    gap = hi - lo - 1
    score = 0.18 + 0.34 * hi / 12.0 + 0.20 * lo / 12.0
    score += 0.065 if suited == "s" else 0.0
    score += 0.075 if gap == 0 else 0.035 if gap == 1 else 0.0
    score -= 0.018 * max(0, gap - 2)
    if high == "A" and suited == "s" and low in "2345":
        score += 0.045
    return max(0.0, min(0.96, score))


def _fallback_preflop_range(hand: Any, player_id: str,
                            blockers: set[str]) -> tuple[list[tuple[tuple[str, str], float]], str, float]:
    events = _player_events(hand, player_id, street="preflop")
    voluntary = [event for event in events if _event_action(event) != "fold"]
    all_preflop = [
        event for event in list(getattr(hand, "events", ()) or ())
        if isinstance(event, dict) and event.get("type") == "action"
        and str(event.get("street", "preflop")).lower().replace("-", "") == "preflop"
    ]
    latest = voluntary[-1] if voluntary else None
    action = _event_action(latest) if latest is not None else "unacted"
    latest_pos = max(
        (index for index, event in enumerate(all_preflop) if event is latest),
        default=-1,
    ) if latest is not None else len(all_preflop)
    if latest is not None and latest_pos < 0:
        actor_names = {str(player_id)}
        player = next((p for p in list(getattr(hand, "players", ()) or ())
                       if str(getattr(p, "player_id", "")) == str(player_id)), None)
        if player is not None:
            actor_names.add(str(getattr(player, "name", "")))
        latest_pos = max(
            (index for index, event in enumerate(all_preflop)
             if str(event.get("player_id") or event.get("player") or "") in actor_names),
            default=len(all_preflop),
        )
    prior_raises = sum(
        1 for event in all_preflop[:max(0, latest_pos)]
        if _event_action(event) in {"raise", "allin"}
    )
    if action == "unacted":
        # Model an unacted seat's conditional continue-range rather than
        # pretending every unseen hand always calls. More raises in front
        # tighten that hypothetical continue-range substantially.
        cutoff = {0: 0.34, 1: 0.55, 2: 0.73, 3: 0.84}.get(min(3, prior_raises), 0.88)
        unacted_source = True
    elif action in {"raise", "allin"}:
        cutoff = {0: 0.57, 1: 0.72, 2: 0.83, 3: 0.90}.get(min(3, prior_raises), 0.92)
        unacted_source = False
    elif action == "call":
        cutoff = {0: 0.28, 1: 0.46, 2: 0.60, 3: 0.72}.get(min(3, prior_raises), 0.78)
        unacted_source = False
    else:
        return _uniform_combos(blockers), "unsupported-action-uniform", 0.10

    classes: list[str] = []
    for high_index in range(len(RANKS) - 1, 0, -1):
        high = RANKS[high_index]
        for low_index in range(high_index - 1, -1, -1):
            low = RANKS[low_index]
            classes.extend((high + low + "s", high + low + "o"))
    classes.extend(rank + rank for rank in RANKS)

    weighted: list[tuple[tuple[str, str], float]] = []
    for hand_class in classes:
        strength = _preflop_strength(hand_class)
        if strength <= cutoff:
            continue
        weight = ((strength - cutoff) / max(0.001, 1.0 - cutoff)) ** 1.5
        combos = [combo for combo in _physical_combos(hand_class)
                  if not (set(combo) & blockers)]
        if weight > 0 and combos:
            weighted.extend((combo, weight / len(combos)) for combo in combos)

    if not weighted:
        weighted = _uniform_combos(blockers)
        return weighted, "fallback-wide", 0.10
    confidence = 0.22 if unacted_source else max(0.20, 0.56 - 0.08 * prior_raises)
    source = "unacted-conditional-response" if unacted_source else "action-inferred-prior"
    return weighted, source, confidence


def _uniform_combos(blockers: set[str]) -> list[tuple[tuple[str, str], float]]:
    cards = [rank + suit for suit in SUITS for rank in RANKS if rank + suit not in blockers]
    return [(combo, 1.0) for combo in itertools.combinations(cards, 2)]


def _board_metrics(cards: tuple[str, str], board: list[str]) -> tuple[float, float]:
    """Approximate made-hand and draw strength using only currently visible cards."""
    if len(board) < 3:
        return 0.0, 0.0
    all_cards = list(cards) + list(board)
    rank = evaluate_seven(all_cards)
    category = int(rank[0])
    tie = sum(int(value) for value in rank[1:])
    made = min(1.0, category / 8.0 + tie / 25000.0)

    suit_counts: dict[str, int] = {}
    rank_values = set()
    for card in all_cards:
        suit_counts[card[1]] = suit_counts.get(card[1], 0) + 1
        rank_values.add(14 if card[0] == "A" else RANKS.index(card[0]) + 2)
    if 14 in rank_values:
        rank_values.add(1)

    flush_draw = max(suit_counts.values(), default=0) >= 4
    straight_draw = False
    for high in range(14, 4, -1):
        window = set(range(high - 4, high + 1))
        if len(window & rank_values) >= 4:
            straight_draw = True
            break
    draw = (0.62 if flush_draw else 0.0) + (0.45 if straight_draw else 0.0)
    return made, min(1.0, draw)


def _action_likelihood(action: str, made: float, draw: float,
                       size_fraction: float, street: str) -> float:
    value = action.lower()
    if value in {"check"}:
        likelihood = 0.88 - 0.48 * made + 0.12 * draw
        return max(0.18, min(1.0, likelihood))
    if value in {"call", "allin_call"}:
        likelihood = 0.12 + 0.82 * made + 0.30 * draw
        return max(0.04, min(1.0, likelihood))
    if value in {"raise", "bet", "allin", "all_in", "jam", "shove"}:
        if size_fraction <= 0.33:
            likelihood = 0.30 + 0.30 * made + 0.18 * draw
        elif size_fraction <= 0.75:
            likelihood = 0.08 + 0.78 * made + 0.34 * draw
        else:
            likelihood = 0.025 + 0.92 * (made ** 1.5) + 0.42 * draw
        if street == "river":
            likelihood *= 0.92 + 0.12 * made
        return max(0.015, min(1.0, likelihood))
    return 0.5


def infer_opponent_ranges(table: Any, hand: Any, hero_id: str,
                          range_estimator: Callable[..., dict[str, Any]] | None = None
                          ) -> dict[str, OpponentRange]:
    """Build independent opponent ranges from preflop history and postflop actions."""
    hero = hand.player(hero_id)
    hero_cards = list(getattr(hero, "hole_cards", ()) or ())
    board_now = list(getattr(hand, "board", ()) or ())
    blockers = set(str(card) for card in hero_cards + board_now)
    estimate: dict[str, Any] = {}
    if range_estimator is not None:
        try:
            estimate = range_estimator(table=table, hand=hand, exclude_player_id=hero_id) or {}
        except Exception:
            estimate = {}
    estimated_rows = estimate.get("players", {}) if isinstance(estimate, dict) else {}

    ranges: dict[str, OpponentRange] = {}
    current_street = str(getattr(hand, "street", "preflop")).lower()
    all_preflop_events = [
        event for event in list(getattr(hand, "events", ()) or ())
        if isinstance(event, dict) and event.get("type") == "action"
        and str(event.get("street", "preflop")).lower().replace("-", "") == "preflop"
    ]
    raises_seen = sum(
        1 for event in all_preflop_events
        if _event_action(event) in {"raise", "allin"}
    )
    for opponent in list(getattr(hand, "players", ()) or ()):
        pid = str(getattr(opponent, "player_id", ""))
        if not pid or pid == str(hero_id) or not bool(getattr(opponent, "eligible", False)):
            continue
        row = estimated_rows.get(pid, {}) if isinstance(estimated_rows, dict) else {}
        raw_options: list[tuple[tuple[str, str], float]] = []
        source = "uniform-prior"
        confidence = 0.12
        if isinstance(row, dict) and row.get("supported") and isinstance(
            row.get("hand_class_probabilities"), dict
        ):
            for hand_class, raw_weight in row["hand_class_probabilities"].items():
                try:
                    class_weight = max(0.0, float(raw_weight))
                except (TypeError, ValueError):
                    continue
                combos = [combo for combo in _physical_combos(str(hand_class))
                          if not (set(combo) & blockers)]
                if class_weight > 0 and combos:
                    raw_options.extend((combo, class_weight / len(combos)) for combo in combos)
            if raw_options:
                source = "fixed-chart-action-range"
                confidence = 0.90
        if not raw_options:
            raw_options, source, confidence = _fallback_preflop_range(hand, pid, blockers)

        # Rebuild the board as it existed at each action. This prevents later
        # turn/river cards from leaking into an earlier flop decision.
        running_board: list[str] = []
        for event in list(getattr(hand, "events", ()) or ()):
            if not isinstance(event, dict):
                continue
            if event.get("type") == "street":
                running_board = [str(card) for card in event.get("board", running_board)]
                continue
            if event.get("type") != "action":
                continue
            event_actor = str(event.get("player_id") or event.get("player") or "")
            if event_actor != pid and event_actor != str(getattr(opponent, "name", "")):
                continue
            street = str(event.get("street", "preflop")).lower().replace("-", "")
            if street == "preflop" or len(running_board) < 3:
                continue
            action = _event_action(event)
            if action == "fold":
                continue
            pot_before = max(1, int(event.get("pot_before", 1) or 1))
            paid = max(0, int(event.get("paid", event.get("amount", 0)) or 0))
            to_call = max(0, int(event.get("to_call_before", 0) or 0))
            size_fraction = (paid / pot_before) if action in {"raise", "bet", "allin"} else (
                to_call / pot_before if action in {"call", "allin_call"} else 0.0
            )
            updated: list[tuple[tuple[str, str], float]] = []
            for combo, weight in raw_options:
                if set(combo) & set(running_board):
                    continue
                made, draw = _board_metrics(combo, running_board)
                likelihood = _action_likelihood(action, made, draw, size_fraction, street)
                weighted = weight * likelihood
                if weighted > 0:
                    updated.append((combo, weighted))
            if updated:
                raw_options = updated
                source += "+postflop-action"
                confidence = min(0.96, confidence + 0.015)

        total = sum(weight for _, weight in raw_options)
        if total <= 0:
            raw_options = _uniform_combos(blockers)
            total = sum(weight for _, weight in raw_options)
            source = "recovered-uniform-prior"
            confidence = 0.08
        normalised = tuple((combo, weight / total) for combo, weight in raw_options)
        participation = 1.0
        if source == "unacted-conditional-response" and current_street == "preflop":
            participation = {0: 0.42, 1: 0.29, 2: 0.17, 3: 0.10}.get(
                min(3, raises_seen), 0.07
            )
        ranges[pid] = OpponentRange(
            pid, normalised, source, confidence, participation
        )
    return ranges


def _weighted_sample(options: tuple[tuple[tuple[str, str], float], ...],
                     blocked: set[str], rng: Any) -> tuple[str, str] | None:
    available = [(cards, weight) for cards, weight in options
                 if cards[0] not in blocked and cards[1] not in blocked and weight > 0]
    if not available:
        return None
    total = sum(weight for _, weight in available)
    pick = float(rng.random()) * total
    for cards, weight in available:
        pick -= weight
        if pick <= 0:
            return cards
    return available[-1][0]


def _equity_vs_ranges(hand: Any, hero_id: str, ranges: dict[str, OpponentRange],
                      cpu: Any) -> tuple[float, int]:
    hero = hand.player(hero_id)
    hero_cards = [str(card) for card in list(getattr(hero, "hole_cards", ()) or ())]
    board = [str(card) for card in list(getattr(hand, "board", ()) or ())]
    if len(hero_cards) != 2 or len(set(hero_cards + board)) != len(hero_cards + board):
        raise ValueError("Hero's hole cards or current board are unavailable")
    opponents = list(ranges.values())
    if not opponents:
        return 1.0, 0
    rng = getattr(cpu, "rng", None) or random.Random()
    level = min(5, max(1, int(getattr(cpu, "level", 3) or 3)))
    runs = 220 + level * 130
    runs = min(950, runs)
    deck = [str(card) for card in make_deck()]
    remaining = 5 - len(board)
    wins = 0.0
    completed = 0
    for _ in range(runs):
        used = set(hero_cards + board)
        hands: list[tuple[str, str]] = []
        for opponent_range in opponents:
            # A player who has not acted yet is not forced to continue.
            # Sample their entry into the pot separately from their conditional range.
            if float(rng.random()) > float(opponent_range.participation_probability):
                continue
            picked = _weighted_sample(opponent_range.combos, used, rng)
            if picked is None:
                available = [card for card in deck if card not in used]
                if len(available) < 2:
                    hands = []
                    break
                picked = tuple(rng.sample(available, 2))
            hands.append(picked)
            used.update(picked)
        if not hands:
            wins += 1.0
            completed += 1
            continue
        available_board = [card for card in deck if card not in used]
        if len(available_board) < remaining:
            continue
        runout = board + (rng.sample(available_board, remaining) if remaining else [])
        hero_rank = evaluate_seven(hero_cards + runout)
        ranks = [evaluate_seven(list(cards) + runout) for cards in hands]
        best = max([hero_rank] + ranks)
        winner_count = (1 if hero_rank == best else 0) + sum(rank == best for rank in ranks)
        if hero_rank == best:
            wins += 1.0 / max(1, winner_count)
        completed += 1
    if completed <= 0:
        raise RuntimeError("No range-weighted equity simulations completed")
    return wins / completed, completed


def _fold_probability(ranges: dict[str, OpponentRange], board: list[str],
                      bet_fraction: float) -> float:
    """Estimate probability that every active opponent folds to this bet size."""
    all_fold = 1.0
    for opponent_range in ranges.values():
        total = 0.0
        folds = 0.0
        for combo, weight in opponent_range.combos:
            made, draw = _board_metrics(combo, board) if len(board) >= 3 else (
                _preflop_strength(_cards_to_class(combo)), 0.0
            )
            # Small bets fold fewer hands; large bets apply more pressure.
            pressure = max(0.55, min(1.65, 0.78 + bet_fraction * 0.78))
            continue_strength = max(0.03, min(0.98, 0.12 + 0.88 * made + 0.28 * draw))
            fold_rate = max(0.015, min(0.95, (1.0 - continue_strength) * pressure))
            folds += weight * fold_rate
            total += weight
        if total > 0:
            conditional_fold = max(0.0, min(1.0, folds / total))
            actual_fold = 1.0 - (
                float(opponent_range.participation_probability) * (1.0 - conditional_fold)
            )
            all_fold *= max(0.0, min(1.0, actual_fold))
    return all_fold


def _cards_to_class(cards: tuple[str, str]) -> str:
    first, second = cards
    r1, r2 = RANKS.index(first[0]), RANKS.index(second[0])
    if r1 == r2:
        return first[0] + second[0]
    high, low = (first, second) if r1 > r2 else (second, first)
    return high[0] + low[0] + ("s" if first[1] == second[1] else "o")


def required_call_equity(pot_before_call: int, call_amount: int, rake_amount: int = 0) -> float:
    """Minimum equity to call, after estimated rake, as a fraction of the final pot."""
    pot = max(0, int(pot_before_call))
    call = max(0, int(call_amount))
    rake = max(0, int(rake_amount))
    return min(1.0, call / max(1, pot + call - rake))


def required_bluff_success(pot_before_bet: int, risk_amount: int) -> float:
    """Pure-bluff break-even fold frequency: risk / (pot + risk)."""
    pot = max(0, int(pot_before_bet))
    risk = max(0, int(risk_amount))
    return min(1.0, risk / max(1, pot + risk))

def _best_passive_action(legal_actions: set[str]) -> str:
    for action in ("check", "fold", "call"):
        if action in legal_actions:
            return action
    return next(iter(legal_actions))


def _choose_range_aware_action_impl(
    table: Any,
    hand: Any,
    player_id: str,
    cpu: Any,
    range_estimator: Callable[..., dict[str, Any]] | None = None,
) -> CPUAction:
    """Choose actions from independent opponent ranges, multiway equity and EV.

    Covered 75-node preflop decisions are handled by the immutable chart before
    this function is called. This policy handles uncovered branches and all
    postflop spots; it never changes the chart data.
    """
    legal = hand.legal_actions(player_id)
    actions = {str(value).lower().replace("-", "_") for value in legal.get("actions", ())}
    if not actions:
        raise ValueError("No legal action is available")
    player = hand.player(player_id)
    pot = max(0, int(getattr(hand, "pot", 0) or 0))
    to_call = max(0, int(legal.get("to_call", 0) or 0))
    stack = max(0, int(getattr(player, "stack", 0) or 0))
    street = str(getattr(hand, "street", "preflop")).lower()
    board = [str(card) for card in list(getattr(hand, "board", ()) or ())]
    ranges = infer_opponent_ranges(table, hand, player_id, range_estimator)
    equity, samples = _equity_vs_ranges(hand, player_id, ranges, cpu)

    level = min(5, max(1, int(getattr(cpu, "level", 3) or 3)))
    archetype = str(getattr(cpu, "archetype", "balanced") or "balanced")
    margin = {1: 0.105, 2: 0.075, 3: 0.050, 4: 0.025, 5: 0.010}[level]
    aggression = {1: 0.16, 2: 0.25, 3: 0.36, 4: 0.50, 5: 0.64}[level]
    aggression += {"aggressive": 0.16, "calling_station": -0.18,
                   "overfolder": -0.10, "underbluffer": -0.08}.get(archetype, 0.0)
    aggression = max(0.04, min(0.85, aggression))
    uncertainty = (
        sum(1.0 - opponent.confidence for opponent in ranges.values()) / max(1, len(ranges))
        if ranges else 0.0
    )
    uncertainty_margin = min(0.10, uncertainty * 0.11)
    rake_bps = max(0, int(getattr(hand, "rake_bps", 0) or 0))
    rake_cap = max(0, int(getattr(hand, "rake_cap", 0) or 0))
    call_pot = pot + to_call
    estimated_rake = min(rake_cap, int(call_pot * rake_bps / 10000)) if rake_bps else 0
    required_call = required_call_equity(pot, to_call, estimated_rake)
    required_bluff = required_bluff_success(pot, max(1, int(round(max(1, pot) * 0.50))))
    fold_probability = 0.0

    if street == "preflop":
        # Require stronger equity when multiple players still have cards and
        # when the opponent ranges are uncertain.
        active_count = len(ranges)
        required_call = min(
            0.99, required_call + margin + uncertainty_margin
            + max(0, active_count - 1) * 0.018
        )
        decision_name = "multiway preflop range decision"
    else:
        required_call = min(0.99, required_call + margin * 0.50 + uncertainty_margin)
        decision_name = "postflop action-updated range decision"

    best_action = _best_passive_action(actions)
    best_amount: int | None = None
    best_ev = -float("inf")
    if best_action == "fold":
        best_ev = 0.0
    elif best_action == "check":
        best_ev = 0.0
    elif best_action == "call":
        best_ev = equity * max(0, call_pot - estimated_rake) - to_call
    elif best_action in {"all_in", "allin"}:
        best_ev = equity * max(0, call_pot - estimated_rake) - to_call

    if to_call > 0 and equity < required_call and "fold" in actions:
        best_action, best_amount, best_ev = "fold", None, 0.0
    elif to_call > 0 and "call" in actions:
        best_action, best_amount = "call", None
        best_ev = equity * max(0, call_pot - estimated_rake) - to_call

    # A range-aware raise can be a value raise or a fold-equity play.
    can_raise = bool(legal.get("raise_allowed")) and (
        "raise" in actions or "bet" in actions
    )
    min_target = max(0, int(legal.get("min_target", 0) or 0))
    max_target = max(0, int(legal.get("max_target", 0) or 0))
    street_contribution = max(0, int(getattr(player, "street_contribution", 0) or 0))
    current_bet = max(0, int(getattr(hand, "current_bet", 0) or 0))
    last_full_raise = max(1, int(getattr(hand, "last_full_raise", 1) or 1))

    if can_raise and max_target >= min_target > street_contribution:
        if street == "preflop":
            multipliers = (2.15, 2.40, 2.70) if to_call else (2.0, 2.3)
            targets = {
                min(max_target, max(min_target, int(round(max(current_bet, last_full_raise) * factor))))
                for factor in multipliers
            }
        else:
            fractions = (0.33, 0.50, 0.75, 1.00)
            bases = [
                street_contribution + max(min_target - street_contribution,
                                          int(round(max(1, pot) * fraction)))
                for fraction in fractions
            ]
            if to_call:
                bases = [
                    max(min_target, current_bet + max(last_full_raise, int(round(max(1, pot) * fraction))))
                    for fraction in (0.50, 0.75, 1.00)
                ]
            targets = {min(max_target, target) for target in bases
                       if min(max_target, target) >= min_target}
        for target in targets:
            if target <= current_bet:
                continue
            risk = target - street_contribution
            bet_fraction = risk / max(1, pot)
            fold_probability = _fold_probability(ranges, board, bet_fraction)
            required_success = required_bluff_success(pot, risk)
            required_bluff = required_success
            # When called, an additional raise receives a larger pot; this is
            # an approximation, not a solver-exact future-game EV.
            raise_increment = max(0, risk - to_call) if to_call else risk
            called_pot = pot + risk + raise_increment
            raise_ev = (
                fold_probability * pot
                + (1.0 - fold_probability) * (equity * max(0, called_pot - estimated_rake) - risk)
            )
            value_gate = equity >= max(
                0.56 if street == "preflop" else 0.57,
                required_call + (0.105 if street == "preflop" else 0.13) + uncertainty_margin,
            )
            bluff_gate = (
                fold_probability >= required_success + 0.04 + uncertainty_margin
                and equity < 0.48
            )
            premium_preflop = False
            if street == "preflop":
                try:
                    premium_preflop = _cards_to_class(tuple(
                        str(card) for card in list(getattr(player, "hole_cards", ()) or ())
                    )) in {"AA", "KK", "AKs"}
                except Exception:
                    premium_preflop = False
            raise_probability = aggression * (0.60 + 0.40 * max(0.0, min(1.0, equity)))
            if premium_preflop:
                raise_probability = min(0.95, raise_probability + 0.24)
            if bluff_gate:
                raise_probability *= 0.72
            if (value_gate or bluff_gate) and float(getattr(getattr(cpu, "rng", None), "random", lambda: 0.0)()) < raise_probability:
                action_name = "raise" if to_call else "bet"
                action_key = action_name
                if action_key in actions and raise_ev > best_ev + 0.01:
                    best_action, best_amount, best_ev = action_key, target, raise_ev

    # If no call is faced, a low-EV bluff is not forced: checking remains the baseline.
    if to_call == 0 and "check" in actions and best_ev <= 0:
        best_action, best_amount, best_ev = "check", None, 0.0
    if best_action not in actions:
        best_action = _best_passive_action(actions)
        best_amount = None

    if best_action in {"bet", "raise"} and best_amount is None:
        best_action = "check" if "check" in actions else _best_passive_action(actions)

    if best_amount is not None:
        best_amount = max(min_target, min(max_target, int(best_amount)))
    if best_action == "allin":
        best_amount = None

    note = (
        f"{decision_name}; equity {equity:.1%}; required call {required_call:.1%}; "
        f"pure-bluff required folds {required_bluff:.1%}; estimated all-fold {fold_probability:.1%}; "
        f"ranges {len(ranges)}; samples {samples}; uncertainty {uncertainty:.2f}; "
        f"EV≈{best_ev:.1f}; source=range-aware estimate (not solver exact)"
    )
    return CPUAction(
        player_id=str(player_id),
        action=best_action,
        amount=best_amount,
        source="range-aware-policy",
        equity_estimate=equity,
        note=note,
    )


def choose_range_aware_action(
    table: Any,
    hand: Any,
    player_id: str,
    cpu: Any,
    range_estimator: Callable[..., dict[str, Any]] | None = None,
) -> CPUAction:
    """Non-stopping wrapper: policy errors become a conservative legal action.

    A normal chart gap is not an error and is handled by the range-aware
    policy. This guardrail activates only when card/state/range evaluation
    itself fails; it records a cumulative per-CPU penalty and never invents
    a raise, bet, or shove.
    """
    try:
        return _choose_range_aware_action_impl(
            table, hand, player_id, cpu, range_estimator=range_estimator
        )
    except Exception as exc:
        legal = hand.legal_actions(player_id)
        actions = {
            str(value).lower().replace("-", "_")
            for value in legal.get("actions", ())
        }
        to_call = max(0, int(legal.get("to_call", 0) or 0))
        if to_call <= 0 and "check" in actions:
            action = "check"
        elif "fold" in actions:
            action = "fold"
        elif "check" in actions:
            action = "check"
        elif "call" in actions:
            action = "call"
        else:
            action = next(iter(actions))
        previous = max(0, int(getattr(cpu, "_range_guardrail_penalty", 0) or 0))
        penalty = min(1000, previous + 100)
        try:
            setattr(cpu, "_range_guardrail_penalty", penalty)
        except Exception:
            pass
        return CPUAction(
            player_id=str(player_id),
            action=action,
            amount=None,
            source="range-aware-guardrail",
            equity_estimate=0.0,
            note=(
                "Range estimate failed; conservative legal action selected; "
                f"error={type(exc).__name__}; cumulative policy penalty={penalty}"
            ),
        )
