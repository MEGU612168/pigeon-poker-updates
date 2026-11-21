from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
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
    archetype: str = "balanced"
    removed_combos: tuple[tuple[tuple[str, str], float], ...] = ()
    learned_stats: tuple[tuple[str, float], ...] = ()


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
    # A short all-in call is still a call, not a raise/shove for range purposes.
    if raw in {"call", "called", "all_in_call", "allin_call", "call_all_in"}:
        return "call"
    if event.get("is_all_in") or event.get("all_in") or event.get("jam"):
        return "allin"
    if raw in {"allin", "all_in", "jam", "shove"}:
        return "allin"
    if raw in {"raise", "bet", "raise_to", "bet_to"}:
        return "raise"
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


def _position_for_player(table: Any, hand: Any, player_id: str) -> str | None:
    """Resolve a six-max seat position from the dealer and public seat order."""
    players = list(getattr(hand, "players", ()) or ())
    if len(players) != 6:
        return None
    dealer = getattr(table, "dealer_index", None)
    if dealer is None:
        dealer = getattr(hand, "dealer_index", None)
    if dealer is None:
        return None
    try:
        dealer = int(dealer) % 6
    except (TypeError, ValueError, OverflowError):
        return None
    seat_by_id = getattr(hand, "seat_by_id", {}) or {}
    target = str(player_id)
    for index, player in enumerate(players):
        if str(getattr(player, "player_id", "")) != target:
            continue
        try:
            seat = int(seat_by_id[target]) % 6 if isinstance(seat_by_id, dict) and target in seat_by_id else index
        except (TypeError, ValueError, OverflowError):
            return None
        return ("BTN", "SB", "BB", "UTG", "HJ", "CO")[(seat - dealer) % 6]
    return None


def _fallback_position_adjustment(
    position: str | None,
    action: str,
    prior_raises: int,
    raiser_position: str | None,
) -> float:
    """Position-specific adjustment to the fallback preflop range-strength cutoff.

    A higher cutoff means a tighter range. These are deliberately modest
    priors, used only when the exact 75-node action history is unavailable.
    """
    pos = str(position or "").upper()
    if action in {"raise", "allin"}:
        if int(prior_raises) <= 0:
            # First-in ranges: early seats are tighter; BTN/SB can open wider.
            adjustment = {
                "UTG": 0.105, "HJ": 0.065, "CO": 0.025,
                "BTN": -0.075, "SB": -0.025, "BB": 0.065,
            }.get(pos, 0.0)
        else:
            # 3-bet/4-bet ranges: blinds pay an out-of-position premium;
            # late-position reraises can retain more suited/connected hands.
            adjustment = {
                "UTG": 0.060, "HJ": 0.040, "CO": -0.015,
                "BTN": -0.045, "SB": 0.055, "BB": 0.025,
            }.get(pos, 0.0)
    elif action == "call":
        # BB receives the best price, SB is usually the most awkward defend.
        adjustment = {
            "UTG": 0.075, "HJ": 0.040, "CO": 0.005,
            "BTN": -0.045, "SB": 0.045, "BB": -0.105,
        }.get(pos, 0.0)
    elif action == "unacted":
        adjustment = {
            "UTG": 0.045, "HJ": 0.025, "CO": 0.000,
            "BTN": -0.045, "SB": 0.020, "BB": -0.070,
        }.get(pos, 0.0)
    else:
        adjustment = 0.0

    # Account for relative postflop position when facing an existing raise.
    # Blinds are always treated as out of position despite acting late preflop.
    order = {"UTG": 0, "HJ": 1, "CO": 2, "BTN": 3}
    raiser = str(raiser_position or "").upper()
    if int(prior_raises) > 0 and pos in order and raiser in order:
        if order[pos] > order[raiser]:
            adjustment -= 0.025
        elif order[pos] < order[raiser]:
            adjustment += 0.025
    return max(-0.16, min(0.18, adjustment))


def _fallback_preflop_range(hand: Any, player_id: str,
                            blockers: set[str],
                            table: Any = None) -> tuple[list[tuple[tuple[str, str], float]], str, float]:
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
    prior_history = all_preflop[:max(0, latest_pos)]
    prior_raises = sum(
        1 for event in prior_history
        if _event_action(event) in {"raise", "allin"}
    )
    position = _position_for_player(table, hand, player_id)
    previous_raise_event = next(
        (event for event in reversed(prior_history)
         if _event_action(event) in {"raise", "allin"}),
        None,
    )
    previous_raiser = None
    if previous_raise_event is not None:
        previous_raiser_id = str(
            previous_raise_event.get("player_id")
            or previous_raise_event.get("player") or ""
        )
        previous_raiser = next(
            (str(getattr(player, "player_id", ""))
             for player in list(getattr(hand, "players", ()) or ())
             if previous_raiser_id in {
                 str(getattr(player, "player_id", "")),
                 str(getattr(player, "name", "")),
             }),
            None,
        )
    raiser_position = (
        _position_for_player(table, hand, previous_raiser)
        if previous_raiser else None
    )
    position_adjustment = _fallback_position_adjustment(
        position, action, prior_raises, raiser_position
    )
    big_blind = max(1, int(getattr(hand, "big_blind", 1) or 1))
    raise_size_anchors = (2.3, 7.5, 17.0, 28.0)
    if action == "unacted":
        # Model an unacted seat's conditional continue-range rather than
        # pretending every unseen hand always calls. More raises and larger
        # sizing in front reduce both range width and entry probability.
        cutoff = {0: 0.34, 1: 0.55, 2: 0.73, 3: 0.84}.get(min(3, prior_raises), 0.88)
        unacted_source = True
        previous_raise = next(
            (event for event in reversed(all_preflop)
             if _event_action(event) in {"raise", "allin"}),
            None,
        )
        if previous_raise is not None:
            target_bb = max(0.0, float(previous_raise.get("target", previous_raise.get("paid", 0)) or 0) / big_blind)
            anchor = raise_size_anchors[min(3, max(0, prior_raises - 1))]
            if target_bb > anchor:
                cutoff += min(0.08, (target_bb / max(1.0, anchor) - 1.0) * 0.08)
    elif action in {"raise", "allin"}:
        cutoff = {0: 0.57, 1: 0.72, 2: 0.83, 3: 0.90}.get(min(3, prior_raises), 0.92)
        unacted_source = False
        target_bb = max(0.0, float(latest.get("target", latest.get("paid", 0)) or 0) / big_blind)
        anchor = raise_size_anchors[min(3, prior_raises)]
        size_ratio = target_bb / max(1.0, anchor)
        cutoff += max(-0.06, min(0.16, (size_ratio - 1.0) * 0.12))
    elif action == "call":
        cutoff = {0: 0.28, 1: 0.46, 2: 0.60, 3: 0.72}.get(min(3, prior_raises), 0.78)
        unacted_source = False
        call_cost = max(0.0, float(latest.get("to_call_before", 0) or 0))
        pot_before = max(1.0, float(latest.get("pot_before", 1) or 1))
        price_ratio = call_cost / pot_before
        cutoff += min(0.08, max(0.0, price_ratio - 0.20) * 0.10)
    else:
        return _uniform_combos(blockers), "unsupported-action-uniform", 0.10
    cutoff = max(0.05, min(0.97, cutoff + position_adjustment))

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


def _rank_strength(rank: tuple[Any, ...]) -> float:
    """Map the evaluator's lexicographic rank tuple to a monotonic 0..1 score."""
    category = max(0, min(8, int(rank[0])))
    category_base = (0.035, 0.175, 0.315, 0.455, 0.595,
                     0.735, 0.835, 0.915, 0.965)[category]
    components = [max(0, min(14, int(value))) for value in rank[1:6]]
    tie_code = sum(value / (15 ** (index + 1))
                   for index, value in enumerate(components))
    return max(0.0, min(0.999, category_base + 0.032 * tie_code))


def _board_metrics(cards: tuple[str, str], board: list[str]) -> tuple[float, float]:
    """Cached board metrics; repeated bet sizes reuse identical combo evaluations."""
    return _board_metrics_cached(tuple(cards), tuple(str(card) for card in board))


@lru_cache(maxsize=65536)
def _board_metrics_cached(
    cards: tuple[str, str], board: tuple[str, ...]
) -> tuple[float, float]:
    """Estimate made-hand class, kicker quality and live draw potential."""
    if len(board) < 3:
        return _preflop_strength(_cards_to_class(cards)), 0.0
    all_cards = list(cards) + list(board)
    rank = evaluate_seven(all_cards)
    made = _rank_strength(rank)

    suit_counts: dict[str, int] = {}
    rank_values: set[int] = set()
    for card in all_cards:
        suit_counts[card[1]] = suit_counts.get(card[1], 0) + 1
        rank_values.add(14 if card[0] == "A" else RANKS.index(card[0]) + 2)
    if 14 in rank_values:
        rank_values.add(1)

    highest_suit_count = max(suit_counts.values(), default=0)
    flush_draw = 0.0
    straight_draw = 0.0
    overcard_draw = 0.0
    # No future cards remain on the river: never classify a made river hand
    # as a live draw.
    if len(board) < 5:
        if highest_suit_count < 5:
            if highest_suit_count >= 4:
                flush_draw = 0.84
            elif highest_suit_count == 3 and len(board) == 3:
                flush_draw = 0.16

        completion_ranks: set[int] = set()
        backdoor_straight = False
        for high in range(5, 15):
            window = set(range(high - 4, high + 1))
            missing = window - rank_values
            if len(missing) == 1:
                completion_ranks.update(missing)
            elif len(missing) == 2 and len(board) == 3:
                backdoor_straight = True
        straight_draw = min(0.88, len(completion_ranks) * 0.40)
        if straight_draw <= 0 and backdoor_straight:
            straight_draw = 0.14

        board_ranks = {
            14 if card[0] == "A" else RANKS.index(card[0]) + 2
            for card in board
        }
        board_high = max(board_ranks, default=14)
        overcards = sum(
            1 for card in cards
            if (14 if card[0] == "A" else RANKS.index(card[0]) + 2) > board_high
        )
        overcard_draw = min(0.18, overcards * (0.075 if len(board) == 3 else 0.035))
    draw = min(1.0, flush_draw + straight_draw + overcard_draw)
    return made, draw


def _action_likelihood(action: str, made: float, draw: float,
                       size_fraction: float, street: str,
                       archetype: str = "balanced",
                       learned_stats: Any = None) -> float:
    """Posterior likelihood for an observed action, with a conservative player-style prior."""
    value = action.lower()
    style = str(archetype or "balanced").lower()
    made = max(0.0, min(1.0, float(made)))
    draw = 0.0 if street == "river" else max(0.0, min(1.0, float(draw)))
    size = max(0.0, float(size_fraction))
    if value == "check":
        likelihood = 0.90 - 0.58 * made + 0.10 * draw
    elif value in {"call", "allin_call", "all_in_call"}:
        support = max(0.025, min(1.0, 0.05 + 0.82 * made + 0.34 * draw))
        # An expensive call is more selective: marginal combos lose weight
        # faster than top-pair, set and draw-heavy combos.
        likelihood = support ** (1.0 + 0.30 * min(2.0, size))
        if style == "calling_station":
            likelihood *= 1.0 + 0.55 * (1.0 - made) + 0.18 * draw
        elif style == "overfolder":
            likelihood *= 0.76 + 0.34 * made + 0.10 * draw
        elif style == "aggressive":
            likelihood *= 1.0 + 0.16 * (1.0 - made)
    elif value in {"raise", "bet", "allin", "all_in", "jam", "shove"}:
        if size <= 0.33:
            likelihood = 0.16 + 0.48 * made + 0.26 * draw
        elif size <= 0.75:
            likelihood = 0.045 + 0.80 * made + 0.38 * draw
        else:
            likelihood = 0.012 + 0.96 * (made ** 1.35) + 0.48 * draw
        if street == "river":
            likelihood *= 0.94 + 0.08 * made
        if style == "aggressive":
            # Aggressive profiles arrive with more weak bets and semi-bluffs.
            likelihood *= 1.0 + 0.90 * (1.0 - made) + 0.35 * draw
        elif style == "calling_station":
            # The profile is less likely to turn weak hands into raises.
            likelihood *= 0.58 + 0.42 * made + 0.12 * draw
        elif style == "overfolder":
            # Tight profiles select stronger hands when choosing to bet/raise.
            likelihood *= 0.62 + 0.48 * made + 0.08 * draw
        elif style == "underbluffer":
            # Reduce weak no-showdown bets much more than value bets.
            likelihood *= 0.24 + 0.76 * made + 0.10 * draw
    else:
        return 0.5
    stats = learned_stats if isinstance(learned_stats, dict) else dict(learned_stats or ())
    sample_hands = max(0.0, float(stats.get("sample_hands", 0.0) or 0.0))
    confidence = min(0.80, sample_hands / (sample_hands + 24.0)) if sample_hands else 0.0
    if confidence > 0:
        if value in {"call", "allin_call", "all_in_call"}:
            observed = max(0.0, min(1.0, float(stats.get("postflop_call_rate", 0.30))))
            likelihood *= math.exp(max(-0.70, min(0.70, (observed - 0.30) * 1.55 * confidence)))
        elif value in {"raise", "bet", "allin", "all_in", "jam", "shove"}:
            observed = max(0.0, min(1.0, float(stats.get("postflop_aggression_rate", 0.22))))
            likelihood *= math.exp(max(-0.65, min(0.65, (observed - 0.22) * 1.35 * confidence)))
    return max(0.008, min(1.0, likelihood))


def _response_continue_probability(made: float, draw: float,
                                   size_fraction: float, street: str,
                                   archetype: str = "balanced",
                                   learned_stats: Any = None) -> float:
    """Estimate a player's continue frequency from hand strength, draws, size and style."""
    made = max(0.0, min(1.0, float(made)))
    draw = 0.0 if street == "river" else max(0.0, min(1.0, float(draw)))
    size = max(0.0, float(size_fraction))
    style = str(archetype or "balanced").lower()
    size_sensitivity = {
        "calling_station": 0.48,
        "aggressive": 0.78,
        "balanced": 1.0,
        "underbluffer": 1.08,
        "overfolder": 1.34,
    }.get(style, 1.0)
    logit = (
        -1.0 + 4.1 * made + 1.5 * draw
        - 0.72 * size_sensitivity * math.log1p(size)
    )
    if style == "calling_station":
        logit += 0.52 * (1.0 - made) + 0.10 * draw
    elif style == "overfolder":
        logit -= 0.46 * (1.0 - made)
    elif style == "aggressive":
        logit += 0.16 + 0.16 * draw
    elif style == "underbluffer":
        logit -= 0.28 * (1.0 - made)
    stats = learned_stats if isinstance(learned_stats, dict) else dict(learned_stats or ())
    sample_hands = max(0.0, float(stats.get("sample_hands", 0.0) or 0.0))
    confidence = min(0.80, sample_hands / (sample_hands + 24.0)) if sample_hands else 0.0
    if confidence > 0:
        observed_fold = max(0.0, min(1.0, float(stats.get("fold_to_bet_rate", 0.55))))
        cbet_opportunities = max(0.0, float(stats.get("fold_to_cbet_opportunities", 0.0) or 0.0))
        if street == "flop" and cbet_opportunities >= 4:
            cbet_fold = max(0.0, min(1.0, float(stats.get("fold_to_cbet_rate", observed_fold))))
            cbet_confidence = min(0.75, cbet_opportunities / (cbet_opportunities + 10.0))
            observed_fold = observed_fold * (1.0 - cbet_confidence) + cbet_fold * cbet_confidence
        observed_call = max(0.0, min(1.0, float(stats.get("postflop_call_rate", 0.30))))
        observed_continue = 0.55 * (1.0 - observed_fold) + 0.45 * observed_call
        logit += max(-1.0, min(1.0, (observed_continue - 0.35) * 2.0 * confidence))
    if street == "river":
        logit += 0.10 * made
    if logit >= 0:
        probability = 1.0 / (1.0 + math.exp(-min(30.0, logit)))
    else:
        exp_value = math.exp(max(-30.0, logit))
        probability = exp_value / (1.0 + exp_value)
    return max(0.015, min(0.985, probability))


def infer_opponent_ranges(table: Any, hand: Any, hero_id: str,
                          range_estimator: Callable[..., dict[str, Any]] | None = None
                          ) -> dict[str, OpponentRange]:
    """Build independent opponent ranges from preflop history and postflop actions."""
    hero = hand.player(hero_id)
    hero_cards = list(getattr(hero, "hole_cards", ()) or ())
    board_now = list(getattr(hand, "board", ()) or ())
    blockers = set(str(card) for card in hero_cards + board_now)
    hero_blockers = set(str(card) for card in hero_cards)
    public_blockers = set(str(card) for card in board_now)
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
        archetype = (
            str(row.get("archetype", "balanced")).lower()
            if isinstance(row, dict) else "balanced"
        )
        if archetype not in {"aggressive", "calling_station", "overfolder", "underbluffer"}:
            archetype = "balanced"
        raw_options: list[tuple[tuple[str, str], float]] = []
        source = "uniform-prior"
        confidence = 0.12
        if isinstance(row, dict) and row.get("supported") and isinstance(
            row.get("hand_class_probabilities"), dict
        ):
            unblocked_probabilities = row.get("unblocked_hand_class_probabilities")
            has_unblocked = isinstance(unblocked_probabilities, dict)
            class_probabilities = (
                unblocked_probabilities if has_unblocked
                else row["hand_class_probabilities"]
            )
            combo_blockers = public_blockers if has_unblocked else blockers
            for hand_class, raw_weight in class_probabilities.items():
                try:
                    class_weight = max(0.0, float(raw_weight))
                except (TypeError, ValueError):
                    continue
                combos = [combo for combo in _physical_combos(str(hand_class))
                          if not (set(combo) & combo_blockers)]
                if class_weight > 0 and combos:
                    raw_options.extend((combo, class_weight / len(combos)) for combo in combos)
            if raw_options:
                source = "fixed-chart-action-range"
                confidence = 0.90
        if not raw_options:
            # Keep hero cards out until after the action likelihood updates so
            # removed value/bluff combinations can be measured explicitly.
            raw_options, source, confidence = _fallback_preflop_range(
                hand, pid, public_blockers, table=table
            )

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
                learned_stats = row.get("learned_behavior", {}) if isinstance(row, dict) else {}
                likelihood = _action_likelihood(
                    action, made, draw, size_fraction, street, archetype, learned_stats
                )
                weighted = weight * likelihood
                if weighted > 0:
                    updated.append((combo, weighted))
            if updated:
                raw_options = updated
                source += "+postflop-action"
                confidence = min(0.96, confidence + 0.015)

        total = sum(weight for _, weight in raw_options)
        if total <= 0:
            raw_options = _uniform_combos(public_blockers)
            total = sum(weight for _, weight in raw_options)
            source = "recovered-uniform-prior"
            confidence = 0.08
        if total <= 0:
            continue
        removed_options = [
            (combo, weight) for combo, weight in raw_options
            if set(combo) & hero_blockers
        ]
        available_options = [
            (combo, weight) for combo, weight in raw_options
            if not (set(combo) & hero_blockers)
        ]
        available_total = sum(weight for _, weight in available_options)
        if available_total <= 0:
            available_options = _uniform_combos(blockers)
            available_total = sum(weight for _, weight in available_options)
            removed_options = []
            total = available_total
            source = "recovered-uniform-prior"
            confidence = 0.08
        normalised = tuple(
            (combo, weight / total) for combo, weight in available_options
        )
        removed_normalised = tuple(
            (combo, weight / total) for combo, weight in removed_options
        )
        participation = 1.0
        if source == "unacted-conditional-response" and current_street == "preflop":
            participation = {0: 0.42, 1: 0.29, 2: 0.17, 3: 0.10}.get(
                min(3, raises_seen), 0.07
            )
            previous_raise = next(
                (event for event in reversed(all_preflop_events)
                 if _event_action(event) in {"raise", "allin"}),
                None,
            )
            if previous_raise is not None:
                target_bb = max(
                    0.0,
                    float(previous_raise.get("target", previous_raise.get("paid", 0)) or 0)
                    / max(1, int(getattr(hand, "big_blind", 1) or 1)),
                )
                anchors = (2.3, 7.5, 17.0, 28.0)
                anchor = anchors[min(3, max(0, raises_seen - 1))]
                size_factor = max(0.55, min(1.0, anchor / max(1.0, target_bb)))
                participation *= size_factor
            # Conditional entry is seat-dependent too: BTN closes the action
            # more often, BB receives a discount, and SB is constrained OOP.
            position = (
                str(row.get("position", "")).upper()
                if isinstance(row, dict) and row.get("position")
                else _position_for_player(table, hand, pid)
            )
            participation *= {
                "UTG": 0.86, "HJ": 0.93, "CO": 1.00,
                "BTN": 1.10, "SB": 0.88, "BB": 1.16,
            }.get(position, 1.0)
        learned_stats = row.get("learned_behavior", {}) if isinstance(row, dict) else {}
        learned_stats_tuple = tuple(sorted(
            (str(key), float(value)) for key, value in learned_stats.items()
            if isinstance(value, (int, float)) and math.isfinite(float(value))
        )) if isinstance(learned_stats, dict) else ()
        ranges[pid] = OpponentRange(
            pid, normalised, source, confidence, participation,
            archetype, removed_normalised, learned_stats_tuple
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


def _sample_joint_opponent_hands(
    opponents: list[OpponentRange],
    blocked: set[str],
    deck: list[str],
    rng: Any,
    *,
    max_retries: int = 24,
) -> list[tuple[str, str]]:
    """Sample opponent combos jointly, conditioning on physical card uniqueness.

    Independent sequential weighted draws distort earlier seats whenever two
    ranges overlap. Rejection sampling preserves each range's relative weights
    conditional on a collision-free deal. A sequential recovery path keeps the
    game moving in degenerate / near-identical range cases.
    """
    active = [
        opponent for opponent in opponents
        if float(rng.random()) <= max(
            0.0, min(1.0, float(opponent.participation_probability))
        )
    ]
    if not active:
        return []

    for _ in range(max(1, int(max_retries))):
        picked_hands: list[tuple[str, str]] = []
        used_cards = set(blocked)
        collision = False
        for opponent in active:
            picked = _weighted_sample(opponent.combos, blocked, rng)
            if picked is None or set(picked) & used_cards:
                collision = True
                break
            picked_hands.append(picked)
            used_cards.update(picked)
        if not collision and len(picked_hands) == len(active):
            return picked_hands

    # Rare recovery: process the most constrained ranges first, preserving
    # every available conditioned combo and using random legal cards only if
    # a range has become physically impossible after blockers.
    picked_hands = []
    used_cards = set(blocked)
    ordered = sorted(
        active,
        key=lambda item: sum(
            1 for cards, weight in item.combos
            if weight > 0 and not (set(cards) & blocked)
        ),
    )
    for opponent in ordered:
        picked = _weighted_sample(opponent.combos, used_cards, rng)
        if picked is None:
            available = [card for card in deck if card not in used_cards]
            if len(available) < 2:
                break
            picked = tuple(rng.sample(available, 2))
        picked_hands.append(picked)
        used_cards.update(picked)
    return picked_hands


def _equity_vs_ranges(hand: Any, hero_id: str, ranges: dict[str, OpponentRange],
                      cpu: Any, *, simulation_multiplier: float = 1.0) -> tuple[float, int]:
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
    runs = int((220 + level * 130) * max(0.20, min(1.0, simulation_multiplier)))
    runs = max(100, min(950, runs))
    deck = [str(card) for card in make_deck()]
    remaining = 5 - len(board)
    wins = 0.0
    completed = 0
    for _ in range(runs):
        used = set(hero_cards + board)
        # Participation is sampled first; then card combinations are drawn
        # jointly to avoid order-biased blockers between independent ranges.
        hands = _sample_joint_opponent_hands(
            opponents, used, deck, rng
        )
        if not hands:
            wins += 1.0
            completed += 1
            continue
        for cards in hands:
            used.update(cards)
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
    """Estimate joint all-fold probability using each player's weighted range."""
    all_fold = 1.0
    street = {3: "flop", 4: "turn", 5: "river"}.get(len(board), "preflop")
    for opponent_range in ranges.values():
        total = sum(max(0.0, float(weight)) for _, weight in opponent_range.combos)
        if total <= 0:
            continue
        continue_mass = 0.0
        for combo, weight in opponent_range.combos:
            made, draw = _board_metrics(combo, board) if len(board) >= 3 else (
                _preflop_strength(_cards_to_class(combo)), 0.0
            )
            continue_mass += max(0.0, float(weight)) * _response_continue_probability(
                made, draw, bet_fraction, street, opponent_range.archetype,
                opponent_range.learned_stats,
            )
        conditional_continue = max(0.0, min(1.0, continue_mass / total))
        participation = max(0.0, min(1.0, float(opponent_range.participation_probability)))
        all_fold *= 1.0 - participation * conditional_continue
    return max(0.0, min(1.0, all_fold))


def _bet_response_metrics(
    hand: Any,
    hero_id: str,
    ranges: dict[str, OpponentRange],
    board: list[str],
    bet_fraction: float,
    cpu: Any,
    *,
    simulation_multiplier: float = 0.40,
) -> tuple[float, float, float, int]:
    """Condition ranges on calling; return all-fold, callers, called equity and samples."""
    street = {3: "flop", 4: "turn", 5: "river"}.get(len(board), "preflop")
    response_ranges: dict[str, OpponentRange] = {}
    expected_callers = 0.0
    all_fold = 1.0
    for pid, opponent_range in ranges.items():
        total = 0.0
        continue_mass = 0.0
        conditioned: list[tuple[tuple[str, str], float]] = []
        for combo, weight in opponent_range.combos:
            base_weight = max(0.0, float(weight))
            if base_weight <= 0:
                continue
            made, draw = _board_metrics(combo, board) if len(board) >= 3 else (
                _preflop_strength(_cards_to_class(combo)), 0.0
            )
            probability = _response_continue_probability(
                made, draw, bet_fraction, street, opponent_range.archetype,
                opponent_range.learned_stats,
            )
            weighted = base_weight * probability
            conditioned.append((combo, weighted))
            continue_mass += weighted
            total += base_weight
        if total <= 0:
            continue
        conditional_continue = max(0.0, min(1.0, continue_mass / total))
        participation = max(
            0.0, min(1.0, float(opponent_range.participation_probability))
        )
        actual_call_probability = participation * conditional_continue
        expected_callers += actual_call_probability
        all_fold *= 1.0 - actual_call_probability
        if continue_mass > 0:
            combo_weights = tuple(
                (combo, weight / continue_mass)
                for combo, weight in conditioned if weight > 0
            )
        else:
            combo_weights = opponent_range.combos
        response_ranges[pid] = OpponentRange(
            player_id=pid,
            combos=combo_weights,
            source=opponent_range.source + "+bet-response",
            confidence=opponent_range.confidence,
            participation_probability=actual_call_probability,
            archetype=opponent_range.archetype,
            learned_stats=opponent_range.learned_stats,
        )

    unconditional_equity, samples = _equity_vs_ranges(
        hand, hero_id, response_ranges, cpu,
        simulation_multiplier=simulation_multiplier,
    )
    if all_fold >= 0.999999:
        called_equity = 1.0
    else:
        called_equity = (
            unconditional_equity - all_fold
        ) / max(1e-9, 1.0 - all_fold)
        called_equity = max(0.0, min(1.0, called_equity))
    return (
        max(0.0, min(1.0, all_fold)),
        expected_callers,
        called_equity,
        samples,
    )


def _blocker_removal_metrics(
    hand: Any,
    hero_id: str,
    ranges: dict[str, OpponentRange],
    bet_fraction: float = 0.50,
) -> dict[str, float]:
    """Quantify whether hero's known cards remove likely value or bluff-catch combos.

    Only hypothetical combos made impossible by hero's own hole cards are
    inspected. Each removed combo is weighted by its prior/action likelihood,
    the opponent's probability of entering the pot, and its propensity to
    continue versus the supplied bet size.
    """
    board = [str(card) for card in list(getattr(hand, "board", ()) or ())]
    hero_cards = [str(card) for card in list(
        getattr(hand.player(hero_id), "hole_cards", ()) or ()
    )]
    if len(board) < 3 or len(hero_cards) != 2:
        return {
            "value_call_combos_blocked": 0.0,
            "bluff_call_combos_blocked": 0.0,
            "draw_call_combos_blocked": 0.0,
            "removed_combo_mass": 0.0,
        }
    hero_rank = evaluate_seven(hero_cards + board)
    street = {3: "flop", 4: "turn", 5: "river"}.get(len(board), "river")
    total_participation = sum(
        max(0.0, min(1.0, float(item.participation_probability)))
        for item in ranges.values()
    )
    if total_participation <= 0:
        return {
            "value_call_combos_blocked": 0.0,
            "bluff_call_combos_blocked": 0.0,
            "draw_call_combos_blocked": 0.0,
            "removed_combo_mass": 0.0,
        }

    value_blocked = 0.0
    bluff_blocked = 0.0
    draw_blocked = 0.0
    removed_mass = 0.0
    for opponent_range in ranges.values():
        participation = max(
            0.0, min(1.0, float(opponent_range.participation_probability))
        )
        if participation <= 0:
            continue
        for combo, raw_weight in opponent_range.removed_combos:
            weight = max(0.0, float(raw_weight)) * participation
            if weight <= 0 or set(combo) & set(board):
                continue
            made, draw = _board_metrics(combo, board)
            continue_probability = _response_continue_probability(
                made, draw, bet_fraction, street, opponent_range.archetype,
                opponent_range.learned_stats,
            )
            weighted_call = weight * continue_probability
            removed_mass += weight
            opponent_rank = evaluate_seven(list(combo) + board)
            if opponent_rank > hero_rank:
                value_blocked += weighted_call
            elif opponent_rank < hero_rank:
                bluff_blocked += weighted_call
            if draw >= 0.40:
                draw_blocked += weighted_call

    scale = 1.0 / max(1e-9, total_participation)
    return {
        "value_call_combos_blocked": value_blocked * scale,
        "bluff_call_combos_blocked": bluff_blocked * scale,
        "draw_call_combos_blocked": draw_blocked * scale,
        "removed_combo_mass": removed_mass * scale,
    }


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

def _thin_value_threshold(
    level: int,
    uncertainty: float,
    expected_callers: float,
    required_call: float,
    street: str,
) -> float:
    """Minimum equity when called for thin-value betting, stricter multiway."""
    cpu_level = min(5, max(1, int(level)))
    level_margin = {1: 0.105, 2: 0.075, 3: 0.050, 4: 0.025, 5: 0.010}[cpu_level]
    unknown = max(0.0, min(1.0, float(uncertainty)))
    callers = max(0.0, float(expected_callers))
    price_floor = float(required_call) + (
        0.035 if str(street).lower() == "preflop" else 0.015
    ) + unknown * 0.20
    multiway_floor = (
        0.50 + level_margin * 0.22 + unknown * 0.15
        + max(0.0, callers - 1.0) * 0.025
    )
    return max(0.50, min(0.78, max(price_floor, multiway_floor)))


def _best_passive_action(legal_actions: set[str]) -> str:
    for action in ("check", "fold", "call"):
        if action in legal_actions:
            return action
    return next(iter(legal_actions))


def _range_board_strength_profile(
    row: dict[str, Any],
    board: list[str],
    *,
    max_samples: int = 240,
) -> dict[str, float] | None:
    """Summarise a chart-derived preflop range's made-hand distribution on a board."""
    if not isinstance(row, dict) or not row.get("supported"):
        return None
    classes = row.get("unblocked_hand_class_probabilities")
    if not isinstance(classes, dict):
        classes = row.get("hand_class_probabilities")
    if not isinstance(classes, dict) or len(board) < 3:
        return None
    blockers = set(str(card) for card in board)
    options: list[tuple[tuple[str, str], float]] = []
    for hand_class, raw_weight in classes.items():
        try:
            class_weight = max(0.0, float(raw_weight))
        except (TypeError, ValueError, OverflowError):
            continue
        if class_weight <= 0:
            continue
        combos = [
            combo for combo in _physical_combos(str(hand_class))
            if not (set(combo) & blockers)
        ]
        if combos:
            options.extend((combo, class_weight / len(combos)) for combo in combos)
    total = sum(weight for _, weight in options)
    if total <= 0:
        return None

    # Systematic weighted sampling caps work while preserving the full weighted
    # class distribution. Cache sharing keeps repeated streets inexpensive.
    options.sort(key=lambda item: item[0])
    if len(options) > max(1, int(max_samples)):
        sample_count = max(1, int(max_samples))
        step = total / sample_count
        sampled: list[tuple[tuple[str, str], float]] = []
        index = 0
        cumulative = options[0][1]
        for sample_index in range(sample_count):
            target = (sample_index + 0.5) * step
            while index < len(options) - 1 and cumulative < target:
                index += 1
                cumulative += options[index][1]
            sampled.append((options[index][0], step))
        profile_options = sampled
    else:
        profile_options = options

    weighted_scores = [
        (_board_metrics(combo, board)[0], weight)
        for combo, weight in profile_options if weight > 0
    ]
    profile_total = sum(weight for _, weight in weighted_scores)
    if profile_total <= 0:
        return None
    mean = sum(score * weight for score, weight in weighted_scores) / profile_total
    nut_mass = sum(
        weight for score, weight in weighted_scores if score >= 0.315
    ) / profile_total
    # The upper decile is a compact proxy for nut advantage; integrate partial
    # weights rather than rounding a combo count at the percentile boundary.
    upper_mass = profile_total * 0.10
    upper_sum = 0.0
    remaining = upper_mass
    for score, weight in sorted(weighted_scores, key=lambda item: item[0], reverse=True):
        take = min(weight, remaining)
        upper_sum += score * take
        remaining -= take
        if remaining <= 1e-12:
            break
    upper_mean = upper_sum / max(1e-12, upper_mass)
    return {
        "mean_strength": mean,
        "top_decile_strength": upper_mean,
        "two_pair_plus_mass": nut_mass,
        "sampled_combos": float(len(weighted_scores)),
    }


def _preflop_range_advantage_profile(
    table: Any,
    hand: Any,
    hero_id: str,
    board: list[str],
    range_estimator: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    """Compare chart-derived preflop ranges on the current board, without hidden-card blockers."""
    neutral = {
        "supported": False,
        "range_disadvantage": False,
        "hero_mean_strength": 0.0,
        "opponent_mean_strength": 0.0,
        "mean_advantage": 0.0,
        "top_decile_advantage": 0.0,
        "two_pair_plus_advantage": 0.0,
    }
    if range_estimator is None or len(board) < 3:
        return neutral
    try:
        estimate = range_estimator(
            table=table, hand=hand, exclude_player_id=None
        ) or {}
    except Exception:
        return neutral
    rows = estimate.get("players", {}) if isinstance(estimate, dict) else {}
    if not isinstance(rows, dict):
        return neutral
    hero_row = rows.get(str(hero_id))
    hero_profile = _range_board_strength_profile(hero_row, board)
    if hero_profile is None:
        return neutral

    active_opponents = [
        player for player in list(getattr(hand, "players", ()) or ())
        if str(getattr(player, "player_id", ""))
        and str(getattr(player, "player_id", "")) != str(hero_id)
        and bool(getattr(player, "eligible", False))
    ]
    opponent_profiles = []
    for player in active_opponents:
        pid = str(getattr(player, "player_id", ""))
        profile = _range_board_strength_profile(rows.get(pid, {}), board)
        if profile is None:
            # A partial chart sample can misstate a multiway range edge.
            # Use the board-texture fallback unless every live opponent is covered.
            return neutral
        opponent_profiles.append(profile)
    if not opponent_profiles:
        return neutral

    opponent_mean = sum(row["mean_strength"] for row in opponent_profiles) / len(opponent_profiles)
    opponent_top = sum(row["top_decile_strength"] for row in opponent_profiles) / len(opponent_profiles)
    opponent_nut = sum(row["two_pair_plus_mass"] for row in opponent_profiles) / len(opponent_profiles)
    mean_advantage = hero_profile["mean_strength"] - opponent_mean
    top_advantage = hero_profile["top_decile_strength"] - opponent_top
    nut_advantage = hero_profile["two_pair_plus_mass"] - opponent_nut
    # Require a meaningful gap in the average/top end, or a clear nut-density
    # deficit, before labelling a line as range-disadvantaged.
    disadvantage = bool(
        (mean_advantage <= -0.025 and top_advantage <= -0.025)
        or top_advantage <= -0.065
        or (nut_advantage <= -0.12 and mean_advantage < 0.0)
    )
    return {
        "supported": True,
        "range_disadvantage": disadvantage,
        "hero_mean_strength": hero_profile["mean_strength"],
        "opponent_mean_strength": opponent_mean,
        "mean_advantage": mean_advantage,
        "top_decile_advantage": top_advantage,
        "two_pair_plus_advantage": nut_advantage,
    }


def _postflop_board_role_context(
    table: Any, hand: Any, player_id: str,
    range_estimator: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Estimate preflop-aggressor / board-texture fit and detect a true flop donk spot.

    This is a conservative board-role heuristic, not a solver range-frequency claim.
    It uses the actual preflop aggressor and public flop texture; unsupported or
    ambiguous histories return neutral flags rather than guessing.
    """
    players = list(getattr(hand, "players", ()) or ())
    ids = {
        str(getattr(player, "player_id", "")): str(getattr(player, "player_id", ""))
        for player in players
        if str(getattr(player, "player_id", ""))
    }
    names = {
        str(getattr(player, "name", "")): str(getattr(player, "player_id", ""))
        for player in players
        if str(getattr(player, "player_id", "")) and str(getattr(player, "name", ""))
    }

    def actor_id(event: dict[str, Any]) -> str | None:
        raw = str(event.get("player_id") or event.get("player") or "")
        return ids.get(raw) or names.get(raw)

    aggressor = None
    for event in list(getattr(hand, "events", ()) or ()):
        if not isinstance(event, dict) or event.get("type") != "action":
            continue
        event_street = str(event.get("street", "preflop")).lower().replace("-", "")
        if event_street != "preflop" or _event_action(event) not in {"raise", "allin"}:
            continue
        aggressor = actor_id(event)

    board = [str(card) for card in list(getattr(hand, "board", ()) or ())]
    ranks = []
    suits: dict[str, int] = {}
    for card in board:
        if len(card) < 2 or card[0] not in RANKS:
            continue
        ranks.append(RANKS.index(card[0]) + 2)
        suits[card[1]] = suits.get(card[1], 0) + 1
    unique = sorted(set(ranks))
    paired = len(unique) < len(ranks)
    span = unique[-1] - unique[0] if len(unique) >= 2 else 0
    gaps = sum(1 for left, right in zip(unique, unique[1:]) if right - left <= 3)
    low_connected = bool(
        len(unique) >= 3 and max(unique, default=14) <= 10
        and span <= 6 and gaps >= 2
    )
    max_suit = max(suits.values(), default=0)
    monotone = max_suit >= 3
    wet_low = bool(max_suit >= 2 and max(unique, default=14) <= 11 and span <= 7)
    caller_favored = bool(
        len(board) == 3 and (low_connected or (monotone and max(unique, default=14) <= 12) or wet_low)
    )
    aggressor_favored = bool(
        len(board) == 3 and max(unique, default=0) >= 12
        and not paired and not monotone and not low_connected
        and span >= 5
    )
    is_hero_aggressor = bool(aggressor and aggressor == str(player_id))
    texture_proxy_disadvantage = bool(
        aggressor and (
            (is_hero_aggressor and caller_favored)
            or (not is_hero_aggressor and aggressor_favored)
        )
    )
    range_profile = _preflop_range_advantage_profile(
        table, hand, str(player_id), board, range_estimator
    )
    # Prefer the actual chart-derived range comparison whenever both sides
    # have a supported preflop action. Only custom / unmatched histories use
    # the conservative board-texture proxy.
    range_disadvantage = (
        bool(range_profile["range_disadvantage"])
        if range_profile["supported"] else texture_proxy_disadvantage
    )

    # Postflop action begins left of the button. A non-aggressor acting before
    # an unacted preflop raiser on the flop is the classic donk-lead opportunity.
    dealer = getattr(table, "dealer_index", None)
    if dealer is None:
        dealer = getattr(hand, "dealer_index", None)
    seat_by_id = getattr(hand, "seat_by_id", {}) or {}
    try:
        dealer = int(dealer) % max(1, len(players)) if dealer is not None else None
    except (TypeError, ValueError):
        dealer = None

    def action_order(pid: str) -> int | None:
        if dealer is None or not players:
            return None
        seat = None
        if isinstance(seat_by_id, dict) and pid in seat_by_id:
            seat = seat_by_id[pid]
        else:
            seat = next(
                (index for index, player in enumerate(players)
                 if str(getattr(player, "player_id", "")) == pid),
                None,
            )
        try:
            distance = (int(seat) - dealer) % len(players)
        except (TypeError, ValueError):
            return None
        return distance if distance else len(players)

    current_street = str(getattr(hand, "street", "")).lower()
    acted_this_street = {
        actor for event in list(getattr(hand, "events", ()) or ())
        if isinstance(event, dict) and event.get("type") == "action"
        and str(event.get("street", "")).lower() == current_street
        for actor in [actor_id(event)] if actor
    }
    hero_order = action_order(str(player_id))
    aggressor_order = action_order(str(aggressor)) if aggressor else None
    donk_lead = bool(
        current_street == "flop" and len(board) == 3 and aggressor
        and aggressor != str(player_id) and aggressor not in acted_this_street
        and hero_order is not None and aggressor_order is not None
        and hero_order < aggressor_order
    )
    return {
        "preflop_aggressor": aggressor,
        "hero_is_preflop_aggressor": is_hero_aggressor,
        "caller_favored_board": caller_favored,
        "aggressor_favored_board": aggressor_favored,
        "preflop_range_disadvantage": range_disadvantage,
        "texture_proxy_range_disadvantage": texture_proxy_disadvantage,
        "preflop_range_profile": range_profile,
        "donk_lead": donk_lead,
    }


def _postflop_aggression_gates(
    value_gate: bool,
    bluff_gate: bool,
    *,
    street: str,
    to_call: int,
    donk_lead: bool,
    range_disadvantage: bool,
    made_category: int,
    draw_strength: float,
    expected_callers: float,
    called_equity: float,
    value_threshold: float,
    fold_probability: float,
    required_success: float,
    uncertainty_margin: float,
) -> tuple[bool, bool]:
    """Stop thin raises and unsupported donk leads without neutering normal value bets."""
    if str(street).lower() == "preflop":
        return bool(value_gate), bool(bluff_gate)

    draw = max(0.0, min(1.0, float(draw_strength)))
    callers = max(0.0, float(expected_callers))
    category = max(0, int(made_category))
    if int(to_call) > 0:
        # Raising is not just a larger call: require stronger equity when called.
        # Multiway pots and board textures that favor the opposing preflop range
        # demand an additional margin. Semi-bluff raises need a real high-equity draw.
        raise_floor = 0.60 + 0.045 * max(0.0, callers - 1.0)
        raise_floor += max(0.0, min(0.12, float(uncertainty_margin) * 0.10))
        if range_disadvantage:
            raise_floor += 0.07
        value_gate = bool(value_gate and float(called_equity) >= max(
            float(value_threshold), raise_floor
        ))
        draw_floor = 0.84 if range_disadvantage else 0.68
        bluff_gate = bool(
            bluff_gate and draw >= draw_floor
            and float(fold_probability) >= float(required_success) + 0.08
            + max(0.0, float(uncertainty_margin)) * 0.5
        )
    elif donk_lead:
        # A lead into the preflop aggressor is an exception, not a default
        # continuation bet. Keep it to two-pair+ HU, sets+ multiway, or a
        # genuinely strong combo draw.
        made_floor = 3 if callers >= 1.5 else 2
        draw_floor = 0.92 if callers >= 1.5 else 0.82
        strong_donk_hand = category >= made_floor or draw >= draw_floor
        value_gate = bool(value_gate and strong_donk_hand)
        bluff_gate = bool(
            bluff_gate and draw >= max(draw_floor, 0.90)
            and not range_disadvantage
        )
    elif range_disadvantage:
        # On a board that is a poor fit for our preflop line, avoid turning
        # medium-strength made hands into low-equity stabs.
        if category < 1:
            value_gate = False
            bluff_gate = bool(bluff_gate and draw >= 0.78)
        else:
            value_gate = bool(
                value_gate and float(called_equity) >= float(value_threshold) + 0.035
            )
    return bool(value_gate), bool(bluff_gate)


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
    ranges = infer_opponent_ranges(table, hand, player_id, range_estimator=range_estimator)
    equity, samples = _equity_vs_ranges(hand, player_id, ranges, cpu)
    blocker_metrics = _blocker_removal_metrics(hand, player_id, ranges)
    board_role = _postflop_board_role_context(
        table, hand, player_id, range_estimator=range_estimator
    ) if street != "preflop" else {
        "preflop_aggressor": None, "hero_is_preflop_aggressor": False,
        "caller_favored_board": False, "aggressor_favored_board": False,
        "preflop_range_disadvantage": False, "donk_lead": False,
    }
    hero_cards = tuple(str(card) for card in list(getattr(player, "hole_cards", ()) or ()))
    if street != "preflop" and len(hero_cards) == 2 and len(board) >= 3:
        try:
            hero_hand_category = int(evaluate_seven(list(hero_cards) + board)[0])
            _hero_made_strength, hero_draw_strength = _board_metrics(hero_cards, board)
        except (TypeError, ValueError, IndexError):
            hero_hand_category, hero_draw_strength = 0, 0.0
    else:
        hero_hand_category, hero_draw_strength = 0, 0.0

    level = min(5, max(1, int(getattr(cpu, "level", 3) or 3)))
    archetype = str(getattr(cpu, "archetype", "balanced") or "balanced")
    margin = {1: 0.105, 2: 0.075, 3: 0.050, 4: 0.025, 5: 0.010}[level]
    guardrail_penalty = min(
        1000, max(0, int(getattr(cpu, "_range_guardrail_penalty", 0) or 0))
    )
    expected_opponents = sum(
        max(0.0, min(1.0, float(opponent.participation_probability)))
        for opponent in ranges.values()
    )
    uncertainty = (
        sum(
            max(0.0, min(1.0, float(opponent.participation_probability)))
            * (1.0 - opponent.confidence)
            for opponent in ranges.values()
        ) / max(1e-9, expected_opponents)
        if expected_opponents > 0 else 0.0
    )
    uncertainty_margin = min(
        0.20, uncertainty * 0.11 + guardrail_penalty / 1000.0 * 0.12
    )
    rake_bps = max(0, int(getattr(hand, "rake_bps", 0) or 0))
    rake_cap = max(0, int(getattr(hand, "rake_cap", 0) or 0))
    call_pot = pot + to_call
    estimated_rake = min(rake_cap, int(call_pot * rake_bps / 10000)) if rake_bps else 0
    required_call = required_call_equity(pot, to_call, estimated_rake)
    required_bluff = required_bluff_success(pot, max(1, int(round(max(1, pot) * 0.50))))
    fold_probability = 0.0
    expected_callers = 0.0
    called_equity_estimate = equity
    response_samples = 0

    if street == "preflop":
        # Require stronger equity when multiple players still have cards and
        # when the opponent ranges are uncertain.
        # Unacted seats contribute according to their conditional entry
        # probability, not as certain extra opponents.
        required_call = min(
            0.99, required_call + margin + uncertainty_margin
            + max(0.0, expected_opponents - 1.0) * 0.018
        )
        decision_name = "multiway preflop range decision"
    else:
        blocker_call_delta = (
            blocker_metrics["bluff_call_combos_blocked"]
            - blocker_metrics["value_call_combos_blocked"]
        ) * 0.22
        blocker_call_delta = max(-0.035, min(0.035, blocker_call_delta))
        required_call = max(
            0.01,
            min(0.99, required_call + margin * 0.50 + uncertainty_margin + blocker_call_delta),
        )
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
            fractions = (0.25, 0.33, 0.50, 0.75, 1.00, 1.50)
            bases = [
                street_contribution + max(min_target - street_contribution,
                                          int(round(max(1, pot) * fraction)))
                for fraction in fractions
            ]
            if to_call:
                fractions = (0.50, 0.75, 1.00, 1.25, 1.50)
                bases = [
                    max(min_target, current_bet + max(last_full_raise, int(round(max(1, pot) * fraction))))
                    for fraction in fractions
                ]
            targets = {min(max_target, target) for target in bases
                       if min(max_target, target) >= min_target}
        for target in targets:
            if target <= current_bet:
                continue
            risk = target - street_contribution
            bet_fraction = risk / max(1, pot)
            candidate_blockers = _blocker_removal_metrics(
                hand, player_id, ranges, bet_fraction
            )
            (
                candidate_fold_probability,
                candidate_expected_callers,
                candidate_called_equity,
                candidate_response_samples,
            ) = _bet_response_metrics(
                hand, player_id, ranges, board, bet_fraction, cpu,
                simulation_multiplier=0.40,
            )
            required_success = required_bluff_success(pot, risk)
            candidate_required_bluff = required_success
            raise_increment = max(0, risk - to_call) if to_call else risk
            caller_payment = raise_increment if to_call else risk
            called_pot = (
                pot + risk + candidate_expected_callers * caller_payment
            )
            raise_ev = (
                candidate_fold_probability * pot
                + (1.0 - candidate_fold_probability)
                * (
                    candidate_called_equity * max(0, called_pot - estimated_rake)
                    - risk
                )
            )
            # Thin value is still value when the weighted calling range
            # loses often enough. More likely callers in multiway pots raise
            # the required threshold; level and uncertainty calibrate caution.
            value_threshold = _thin_value_threshold(
                level, uncertainty_margin, candidate_expected_callers,
                required_call, street,
            )
            value_gate = candidate_called_equity >= value_threshold
            blocker_bluff_pressure = max(
                0.0,
                min(
                    0.05,
                    candidate_blockers["value_call_combos_blocked"] * 0.30
                    - candidate_blockers["bluff_call_combos_blocked"] * 0.08,
                ),
            )
            bluff_gate = (
                candidate_fold_probability
                >= required_success + 0.04 + uncertainty_margin - blocker_bluff_pressure
                and candidate_called_equity < 0.48
            )
            value_gate, bluff_gate = _postflop_aggression_gates(
                value_gate,
                bluff_gate,
                street=street,
                to_call=to_call,
                donk_lead=bool(board_role.get("donk_lead", False)),
                range_disadvantage=bool(board_role.get("preflop_range_disadvantage", False)),
                made_category=hero_hand_category,
                draw_strength=hero_draw_strength,
                expected_callers=max(candidate_expected_callers, expected_opponents),
                called_equity=candidate_called_equity,
                value_threshold=value_threshold,
                fold_probability=candidate_fold_probability,
                required_success=required_success,
                uncertainty_margin=uncertainty_margin,
            )
            premium_preflop = False
            if street == "preflop":
                try:
                    premium_preflop = _cards_to_class(tuple(
                        str(card) for card in list(getattr(player, "hole_cards", ()) or ())
                    )) in {"AA", "KK", "AKs"}
                except Exception:
                    premium_preflop = False

            # Higher CPU levels compare candidate EV more tightly. Archetypes
            # shift the EV margin, but do not inject random raises unrelated to EV.
            ev_margin = max(1, int(round(
                max(1, pot) * {1: 0.085, 2: 0.060, 3: 0.038, 4: 0.018, 5: 0.006}[level]
            )))
            ev_margin = int(round(ev_margin * {
                "aggressive": 0.68,
                "calling_station": 1.45,
                "overfolder": 1.25,
                "underbluffer": 1.18,
            }.get(archetype, 1.0)))
            if premium_preflop:
                ev_margin = int(round(ev_margin * 0.60))
            ev_margin += int(round(max(1, pot) * guardrail_penalty / 1000.0 * 0.06))
            action_name = "raise" if to_call else "bet"
            if (
                (value_gate or bluff_gate)
                and action_name in actions
                and raise_ev > best_ev + max(1, ev_margin)
            ):
                best_action, best_amount, best_ev = action_name, target, raise_ev
                fold_probability = candidate_fold_probability
                expected_callers = candidate_expected_callers
                called_equity_estimate = candidate_called_equity
                response_samples = candidate_response_samples
                required_bluff = candidate_required_bluff

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
        f"expected callers {expected_callers:.2f}; equity when called {called_equity_estimate:.1%}; "
        f"blockers value/bluff/draw={blocker_metrics['value_call_combos_blocked']:.1%}/"
        f"{blocker_metrics['bluff_call_combos_blocked']:.1%}/"
        f"{blocker_metrics['draw_call_combos_blocked']:.1%}; "
        f"ranges {len(ranges)}; samples {samples + response_samples}; uncertainty {uncertainty:.2f}; "
        f"policy penalty {guardrail_penalty}; EV≈{best_ev:.1f}; "
        f"preflop aggressor={board_role.get('preflop_aggressor') or 'unknown'}; "
        f"range-disadvantage={bool(board_role.get('preflop_range_disadvantage', False))}; "
        f"chart-range-supported={bool(board_role.get('preflop_range_profile', {}).get('supported', False))}; "
        f"chart-range-mean-adv={float(board_role.get('preflop_range_profile', {}).get('mean_advantage', 0.0)):.3f}; "
        f"chart-range-top-adv={float(board_role.get('preflop_range_profile', {}).get('top_decile_advantage', 0.0)):.3f}; "
        f"donk-lead={bool(board_role.get('donk_lead', False))}; "
        f"hero-made-category={hero_hand_category}; draw={hero_draw_strength:.2f}; "
        "source=range-aware multiway response model with postflop aggression guardrails (not solver exact)"
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
