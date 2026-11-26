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

VIP_PRO_BASE_SAMPLES = 1024
VIP_TOP_PRO_BASE_SAMPLES = 4096


def _vip_base_sample_budget(cpu: Any) -> int | None:
    """Return the actual base Monte Carlo budget used by VIP equity passes."""
    if bool(getattr(cpu, "_vip_top_pro_mode", False)):
        return VIP_TOP_PRO_BASE_SAMPLES
    if bool(getattr(cpu, "_vip_pro_mode", False)):
        return VIP_PRO_BASE_SAMPLES
    return None


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



def build_174_preflop_range_estimate(
    table: Any,
    hand: Any,
    *,
    learned_profiles: dict[str, dict[str, Any]] | None = None,
    player_profiles: dict[str, Any] | None = None,
    exclude_player_id: str | None = None,
) -> dict[str, Any]:
    """Build Bayesian preflop ranges from the immutable 174-scenario chart.

    Each recorded preflop decision updates that player's 169 hand-class prior
    using the action and (for raises) the recorded raise-to size in the matching
    action-history node. Exact nodes are preferred; nearest-node evidence is
    down-weighted. Missing/unsupported chart actions are ignored rather than
    treated as folds. Opponent behavior statistics are attached separately.
    """
    try:
        from . import preflop_174_policy as chart
    except Exception:
        return {"supported": False, "players": {}}

    players = list(getattr(hand, "players", ()) or ())
    positions = chart._position_map(table, hand)
    if not positions:
        return {"supported": False, "players": {}}
    id_by_name = {
        str(getattr(player, "name", "")): str(getattr(player, "player_id", ""))
        for player in players if str(getattr(player, "name", ""))
    }
    classes = tuple(chart._HAND_ORDER)
    class_counts = {
        hand_class: max(1, len(_physical_combos(hand_class)))
        for hand_class in classes
    }
    combo_total = float(sum(class_counts.values()))
    base_prior = {
        hand_class: count / combo_total
        for hand_class, count in class_counts.items()
    }
    posterior = {
        pid: dict(base_prior)
        for pid in positions
    }
    evidence: dict[str, dict[str, Any]] = {
        pid: {
            "observations": 0,
            "quality": 0.0,
            "exact_nodes": 0,
            "inferred_nodes": 0,
            "inferred_cells": 0,
            "scenario_ids": [],
        }
        for pid in positions
    }
    history: list[dict[str, Any]] = []
    big_blind = chart._big_blind(hand, table)
    events = list(getattr(hand, "events", ()) or ())

    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") not in {None, "action"} and not event.get("action"):
            continue
        event_street = str(event.get("street", "preflop")).lower().replace("-", "")
        if event_street not in {"preflop", "pre"}:
            continue
        raw_pid = str(event.get("player_id") or event.get("player") or "")
        pid = raw_pid if raw_pid in positions else id_by_name.get(raw_pid, raw_pid)
        actor_position = positions.get(pid) or str(event.get("position", "")).upper()
        action = (
            chart._event_action(event) if event.get("action")
            else chart._normalise_action(event.get("decision"))
        )
        has_prior_raise = any(
            item.get("action") in {"raise", "allin"} for item in history
        )
        # First-in calls/limps are not present in the 174-node source charts.
        # Never infer one from a merely-nearby node; preserve an unsupported
        # prior rather than manufacturing a preflop limp range.
        unsupported_first_in_limp = action == "call" and not has_prior_raise
        if (actor_position in chart.POSITIONS and pid in posterior
                and action in {"fold", "call", "check", "raise", "allin"}
                and not unsupported_first_in_limp):
            try:
                scenario, inferred_node, distance = chart._choose_scenario(
                    actor_position, history, random.Random(0)
                )
            except Exception:
                scenario, inferred_node, distance = None, True, 9.0
            if scenario is not None:
                actual_size_bb = (
                    chart._event_target_bb(event, big_blind)
                    if action in {"raise", "allin"} else None
                )
                likelihoods: dict[str, float] = {}
                cell_inference_mass = 0.0
                prior_predictive = 0.0
                for hand_class in classes:
                    try:
                        distribution, cell_inferred, _method = chart._scenario_distribution(
                            scenario, hand_class
                        )
                    except Exception:
                        distribution, cell_inferred = {}, True
                    action_mass = 0.0
                    for (candidate_action, candidate_size), frequency in distribution.items():
                        normalized = chart._normalise_action(candidate_action)
                        if action == "raise":
                            if normalized != "raise":
                                continue
                            if (actual_size_bb is not None and candidate_size is not None
                                    and not chart._size_matches(candidate_size, actual_size_bb)):
                                continue
                            if actual_size_bb is not None and candidate_size is None:
                                continue
                        elif action == "allin":
                            if normalized != "allin":
                                continue
                            if (actual_size_bb is not None and candidate_size is not None
                                    and not chart._size_matches(candidate_size, actual_size_bb)):
                                continue
                        elif normalized != action:
                            continue
                        action_mass += max(0.0, float(frequency))
                    action_mass = max(0.0, min(1.0, action_mass))
                    likelihoods[hand_class] = action_mass
                    prior_predictive += posterior[pid][hand_class] * action_mass
                    if cell_inferred:
                        cell_inference_mass += posterior[pid][hand_class]

                # The action was outside the represented chart node. Preserve
                # the existing Bayesian prior; do not hallucinate a fold/raise.
                if prior_predictive >= 1e-6:
                    updated = {}
                    for hand_class in classes:
                        # Small likelihood smoothing avoids deleting a hand
                        # class solely because a finite source chart has no row.
                        likelihood = 0.012 + 0.988 * likelihoods[hand_class]
                        updated[hand_class] = posterior[pid][hand_class] * likelihood
                    total = sum(updated.values())
                    if total > 0:
                        posterior[pid] = {
                            hand_class: value / total
                            for hand_class, value in updated.items()
                        }
                        meta = evidence[pid]
                        meta["observations"] += 1
                        if inferred_node:
                            meta["inferred_nodes"] += 1
                            node_quality = math.exp(-min(3.0, max(0.0, float(distance))) * 1.15)
                        else:
                            meta["exact_nodes"] += 1
                            node_quality = 1.0
                        inferred_share = cell_inference_mass
                        meta["inferred_cells"] += 1 if inferred_share >= 0.50 else 0
                        meta["quality"] += node_quality * (1.0 - 0.30 * inferred_share)
                        meta["scenario_ids"].append(int(scenario.get("id", -1)))
        if actor_position in chart.POSITIONS and action in {
            "fold", "call", "check", "raise", "allin"
        }:
            history.append({
                "position": actor_position,
                "action": action,
                "size_bb": (
                    chart._event_target_bb(event, big_blind)
                    if action in {"raise", "allin"} else None
                ),
            })

    learned_profiles = learned_profiles or {}
    player_profiles = player_profiles or {}
    board_blockers = set(str(card) for card in list(getattr(hand, "board", ()) or ()))
    rows: dict[str, dict[str, Any]] = {}
    for pid, weights in posterior.items():
        meta = evidence[pid]
        if int(meta["observations"]) <= 0:
            continue
        total = sum(max(0.0, float(value)) for value in weights.values())
        if total <= 0:
            continue
        probabilities = {
            hand_class: max(0.0, float(value)) / total
            for hand_class, value in weights.items()
        }
        unblocked: dict[str, float] = {}
        for hand_class, probability in probabilities.items():
            combos = _physical_combos(hand_class)
            if not combos:
                continue
            available = sum(
                1 for combo in combos if not (set(combo) & board_blockers)
            )
            if available:
                unblocked[hand_class] = probability * available / len(combos)
        unblocked_total = sum(unblocked.values())
        if unblocked_total > 0:
            unblocked = {
                hand_class: value / unblocked_total
                for hand_class, value in unblocked.items()
            }
        quality = max(0.0, float(meta["quality"]))
        confidence = 0.16 + 0.72 * (1.0 - math.exp(-0.62 * quality))
        confidence = max(0.16, min(0.88, confidence))

        learned = learned_profiles.get(pid, {})
        if not isinstance(learned, dict):
            learned = {}
        player_profile = player_profiles.get(pid)
        archetype = str(getattr(player_profile, "archetype", "balanced") or "balanced")
        if archetype not in {"aggressive", "calling_station", "overfolder", "underbluffer"}:
            archetype = "balanced"
        rows[pid] = {
            "supported": True,
            "position": positions.get(pid),
            "hand_class_probabilities": probabilities,
            "unblocked_hand_class_probabilities": unblocked or probabilities,
            "confidence": confidence,
            "source": "174-preflop-sequential-bayesian-range",
            "archetype": archetype,
            "learned_behavior": dict(learned),
            "observed_preflop_actions": int(meta["observations"]),
            "exact_preflop_nodes": int(meta["exact_nodes"]),
            "inferred_preflop_nodes": int(meta["inferred_nodes"]),
            "inferred_hand_cells": int(meta["inferred_cells"]),
            "scenario_ids": tuple(meta["scenario_ids"]),
        }
    return {
        "supported": bool(rows),
        "players": rows,
        "source": "174-preflop-sequential-bayesian-range",
    }


def _call_realized_equity(
    raw_equity: float,
    realization_factor: float,
    *,
    call_is_all_in: bool,
) -> float:
    """All-in calls realize raw equity; non-all-in calls retain less than full equity."""
    equity = max(0.0, min(1.0, float(raw_equity)))
    if call_is_all_in:
        return equity
    factor = max(0.0, min(1.0, float(realization_factor)))
    return max(0.0, min(1.0, equity * factor))


def _geometric_bet_fraction(spr: float, remaining_streets: int) -> float | None:
    """Pot fraction that geometrically commits the effective stack over remaining streets."""
    effective_spr = max(0.0, float(spr))
    streets = max(1, int(remaining_streets))
    if effective_spr <= 0:
        return None
    fraction = (math.pow(1.0 + 2.0 * effective_spr, 1.0 / streets) - 1.0) / 2.0
    if not math.isfinite(fraction) or fraction <= 0:
        return None
    return max(0.05, min(4.0, fraction))


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
    hole_suit_counts: dict[str, int] = {}
    rank_values: set[int] = set()
    board_rank_values: set[int] = set()
    hole_rank_values: set[int] = set()
    for card in all_cards:
        suit_counts[card[1]] = suit_counts.get(card[1], 0) + 1
        rank = 14 if card[0] == "A" else RANKS.index(card[0]) + 2
        rank_values.add(rank)
    for card in board:
        rank = 14 if card[0] == "A" else RANKS.index(card[0]) + 2
        board_rank_values.add(rank)
    for card in cards:
        hole_suit_counts[card[1]] = hole_suit_counts.get(card[1], 0) + 1
        hole_rank_values.add(14 if card[0] == "A" else RANKS.index(card[0]) + 2)
    hole_contribution_ranks = hole_rank_values - board_rank_values
    # Ace can contribute as the low end of a wheel as well as the high end.
    if 14 in hole_contribution_ranks:
        hole_contribution_ranks.add(1)
    if 14 in rank_values:
        rank_values.add(1)

    flush_draw = 0.0
    straight_draw = 0.0
    overcard_draw = 0.0
    # Attribute draws to the private hand, not merely to a draw-looking board.
    # A four-flush on the board does not give every player a private flush draw;
    # similarly, a four-card straight texture shared by the board is not an
    # individual straight draw unless a hole-card rank contributes to it.
    if len(board) < 5:
        for suit, suit_count in suit_counts.items():
            hole_count = hole_suit_counts.get(suit, 0)
            if hole_count <= 0:
                continue
            if 4 <= suit_count < 5:
                suited_hole_ranks = [
                    14 if card[0] == "A" else RANKS.index(card[0]) + 2
                    for card in cards if card[1] == suit
                ]
                top_held = max(suited_hole_ranks, default=0)
                higher_available = sum(
                    1 for rank in range(top_held + 1, 15)
                    if RANKS[rank - 2] + suit not in all_cards
                )
                # A nut draw is more robust than a dominated low flush draw.
                flush_quality = (
                    0.94 if higher_available == 0 else
                    0.86 if higher_available == 1 else
                    0.79 if higher_available == 2 else 0.72
                )
                flush_draw = max(flush_draw, flush_quality)
            elif suit_count == 3 and len(board) == 3:
                # Backdoor flushes require at least one matching hole card.
                flush_draw = max(flush_draw, 0.16 + 0.02 * min(1, hole_count - 1))

        completion_ranks: set[int] = set()
        backdoor_straight = False
        for high in range(5, 15):
            window = set(range(high - 4, high + 1))
            missing = window - rank_values
            hole_contributes = bool(window & hole_contribution_ranks)
            if len(missing) == 1 and hole_contributes:
                completion_ranks.update(missing)
            elif len(missing) == 2 and len(board) == 3 and hole_contributes:
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
                                   learned_stats: Any = None,
                                   spr: float | None = None) -> float:
    """Estimate continuation frequency from strength, sizing, style and SPR."""
    made = max(0.0, min(1.0, float(made)))
    draw = 0.0 if street == "river" else max(0.0, min(1.0, float(draw)))
    size = max(0.0, float(size_fraction))
    style = str(archetype or "balanced").lower()
    size_sensitivity = {
        "calling_station": 0.48, "aggressive": 0.78, "balanced": 1.0,
        "underbluffer": 1.08, "overfolder": 1.34,
    }.get(style, 1.0)
    logit = -1.0 + 4.1 * made + 1.5 * draw - 0.72 * size_sensitivity * math.log1p(size)
    if style == "calling_station":
        logit += 0.52 * (1.0 - made) + 0.10 * draw
    elif style == "overfolder":
        logit -= 0.46 * (1.0 - made)
    elif style == "aggressive":
        logit += 0.16 + 0.16 * draw
    elif style == "underbluffer":
        logit -= 0.28 * (1.0 - made)
    if spr is not None:
        effective_spr = max(0.0, float(spr))
        if effective_spr <= 2.0:
            logit += 0.20 * (2.0 - effective_spr) / 2.0
        elif effective_spr >= 8.0:
            logit -= min(0.24, (effective_spr - 8.0) * 0.015)
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


def _response_action_probabilities(
    made: float,
    draw: float,
    size_fraction: float,
    street: str,
    archetype: str = "balanced",
    learned_stats: Any = None,
    spr: float | None = None,
) -> tuple[float, float, float]:
    """Return (fold, call, raise) probabilities with style, size and SPR."""
    made = max(0.0, min(1.0, float(made)))
    draw = 0.0 if street == "river" else max(0.0, min(1.0, float(draw)))
    size = max(0.0, float(size_fraction))
    style = str(archetype or "balanced").lower()
    stats = learned_stats if isinstance(learned_stats, dict) else dict(learned_stats or ())
    continue_probability = _response_continue_probability(
        made, draw, size, street, style, learned_stats, spr=spr
    )
    raise_logit = -3.40 + 2.50 * made + 1.60 * draw - 0.12 * math.log1p(size)
    if style == "aggressive":
        raise_logit += 0.55
    elif style == "calling_station":
        raise_logit -= 0.50
    elif style == "overfolder":
        raise_logit -= 0.25
    elif style == "underbluffer":
        raise_logit -= 0.85
    if spr is not None and float(spr) <= 2.0:
        raise_logit += 0.18 * (2.0 - max(0.0, float(spr))) / 2.0
    sample_hands = max(0.0, float(stats.get("sample_hands", 0.0) or 0.0))
    confidence = min(0.65, sample_hands / (sample_hands + 36.0)) if sample_hands else 0.0
    observed_aggression = max(0.0, min(1.0, float(stats.get("postflop_aggression_rate", 0.22))))
    raise_logit += (observed_aggression - 0.22) * 1.30 * confidence
    raise_logit = max(-8.0, min(4.0, raise_logit))
    raise_share = max(0.015, min(0.72, 1.0 / (1.0 + math.exp(-raise_logit))))
    raise_probability = continue_probability * raise_share
    call_probability = continue_probability - raise_probability
    fold_probability = 1.0 - continue_probability
    street_key = str(street or "").lower()
    if street_key in {"flop", "turn", "river"}:
        size_bucket = "small" if size <= 0.33 else "medium" if size <= 0.75 else "large" if size <= 1.25 else "overbet"
        profile_prefix = f"{street_key}_{size_bucket}"
        opportunities = max(0.0, float(stats.get(f"{profile_prefix}_response_opportunities", 0.0) or 0.0))
        if opportunities >= 3.0:
            observed = [
                max(0.0, float(stats.get(f"{profile_prefix}_fold_rate", 0.55))),
                max(0.0, float(stats.get(f"{profile_prefix}_call_rate", 0.35))),
                max(0.0, float(stats.get(f"{profile_prefix}_raise_rate", 0.10))),
            ]
            observed_total = sum(observed)
            if observed_total > 0:
                observed = [value / observed_total for value in observed]
                sample_weight = min(0.78, opportunities / (opportunities + 12.0))
                model = [fold_probability, call_probability, raise_probability]
                fold_probability, call_probability, raise_probability = [
                    (1.0 - sample_weight) * model_value + sample_weight * observed_value
                    for model_value, observed_value in zip(model, observed)
                ]
    total = fold_probability + call_probability + raise_probability
    if total <= 0:
        return 1.0, 0.0, 0.0
    return tuple(
        max(0.0, min(1.0, value / total))
        for value in (fold_probability, call_probability, raise_probability)
    )

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
                source = str(row.get("source", "fixed-chart-action-range"))
                try:
                    confidence = max(0.12, min(0.92, float(row.get("confidence", 0.82))))
                except (TypeError, ValueError, OverflowError):
                    confidence = 0.72
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
    vip_budget = _vip_base_sample_budget(cpu)
    if vip_budget is not None:
        # A full-strength pass uses exactly the advertised tier budget.
        # Smaller candidate/response passes use a documented fraction of it.
        fraction = max(0.20, min(1.0, float(simulation_multiplier)))
        runs = int(round(vip_budget * fraction))
        sample_cap = vip_budget
    else:
        runs = int(
            (220 + level * 130)
            * max(0.20, min(1.0, simulation_multiplier))
        )
        sample_cap = 950
    runs = max(100, min(sample_cap, runs))
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



def _current_showdown_equity(
    hand: Any,
    hero_id: str,
    ranges: dict[str, OpponentRange],
    cpu: Any,
    *,
    simulation_multiplier: float = 0.55,
) -> tuple[float, int]:
    """Estimate made-hand equity on the current board, without future runouts.

    This separates present showdown value from draw/improvement equity. Opponent
    participation and combo collisions are sampled jointly, so multiway ranges
    do not reuse physical cards.
    """
    hero = hand.player(hero_id)
    hero_cards = [str(card) for card in list(getattr(hero, "hole_cards", ()) or ())]
    board = [str(card) for card in list(getattr(hand, "board", ()) or ())]
    if len(hero_cards) != 2 or len(board) < 3:
        return 0.0, 0
    if len(set(hero_cards + board)) != len(hero_cards) + len(board):
        raise ValueError("Duplicate cards in current showdown-equity state")
    if not ranges:
        return 1.0, 0
    rng = getattr(cpu, "rng", None) or random.Random()
    level = min(5, max(1, int(getattr(cpu, "level", 3) or 3)))
    vip_budget = _vip_base_sample_budget(cpu)
    if vip_budget is not None:
        fraction = max(0.25, min(1.0, float(simulation_multiplier)))
        runs = int(round(vip_budget * fraction))
        sample_cap = vip_budget
    else:
        sample_cap = 420
        runs = int((120 + level * 60) * max(
            0.25, min(1.0, float(simulation_multiplier))
        ))
    runs = max(100, min(sample_cap, runs))
    deck = [str(card) for card in make_deck()]
    hero_rank = evaluate_seven(hero_cards + board)
    wins = 0.0
    completed = 0
    for _ in range(runs):
        hands = _sample_joint_opponent_hands(
            list(ranges.values()), set(hero_cards + board), deck, rng
        )
        if not hands:
            wins += 1.0
            completed += 1
            continue
        ranks = [evaluate_seven(list(cards) + board) for cards in hands]
        best = max([hero_rank] + ranks)
        winners = (1 if hero_rank == best else 0) + sum(
            1 for rank in ranks if rank == best
        )
        if hero_rank == best:
            wins += 1.0 / max(1, winners)
        completed += 1
    if completed <= 0:
        raise RuntimeError("No current-board showdown simulations completed")
    return wins / completed, completed


def _postflop_position_profile(
    table: Any, hand: Any, hero_id: str
) -> dict[str, Any]:
    """Resolve whether hero acts last against the remaining live opponents."""
    players = list(getattr(hand, "players", ()) or ())
    dealer = getattr(table, "dealer_index", None)
    if dealer is None:
        dealer = getattr(hand, "dealer_index", None)
    try:
        dealer_index = int(dealer) % max(1, len(players))
    except (TypeError, ValueError, OverflowError):
        return {"known": False, "in_position": False, "opponents_after": 0}
    seat_by_id = getattr(hand, "seat_by_id", {}) or {}

    def distance(player: Any) -> int | None:
        pid = str(getattr(player, "player_id", ""))
        try:
            seat = (
                int(seat_by_id[pid]) % len(players)
                if isinstance(seat_by_id, dict) and pid in seat_by_id
                else next(i for i, item in enumerate(players)
                          if str(getattr(item, "player_id", "")) == pid)
            )
        except (StopIteration, TypeError, ValueError, OverflowError):
            return None
        delta = (seat - dealer_index) % len(players)
        return len(players) if delta == 0 else delta

    hero = next(
        (p for p in players if str(getattr(p, "player_id", "")) == str(hero_id)),
        None,
    )
    hero_distance = distance(hero) if hero is not None else None
    if hero_distance is None:
        return {"known": False, "in_position": False, "opponents_after": 0}
    live = [
        p for p in players
        if str(getattr(p, "player_id", ""))
        and str(getattr(p, "player_id", "")) != str(hero_id)
        and bool(getattr(p, "eligible", False))
    ]
    opponent_distances = [
        value for p in live if (value := distance(p)) is not None
    ]
    if not opponent_distances:
        return {"known": True, "in_position": True, "opponents_after": 0}
    after = sum(1 for value in opponent_distances if value > hero_distance)
    return {
        "known": True,
        "in_position": after == 0,
        "opponents_after": after,
        "hero_action_order": hero_distance,
        "live_opponents": len(opponent_distances),
    }



def _equity_realization_factor(
    street: str,
    *,
    in_position: bool,
    position_known: bool,
    expected_opponents: float,
    made_category: int,
    draw_strength: float,
    spr: float | None = None,
) -> float:
    """Approximate equity realization when future betting remains possible."""
    current = str(street or "").lower()
    if current == "river":
        return 1.0
    base = {"flop": 0.935, "turn": 0.965}.get(current, 0.94)
    if spr is not None:
        effective_spr = max(0.0, float(spr))
        if effective_spr <= 2.0:
            base += 0.020
        elif effective_spr >= 8.0:
            base -= min(0.025, (effective_spr - 8.0) * 0.002)
    if position_known:
        base += 0.035 if in_position else -0.035
    else:
        base -= 0.015
    category = max(0, int(made_category))
    draw = max(0.0, min(1.0, float(draw_strength)))
    if category >= 2:
        base += 0.015
    elif category == 0 and draw < 0.25:
        base -= 0.025
    elif draw >= 0.70:
        base += 0.010
    base -= max(0.0, float(expected_opponents) - 1.0) * 0.025
    return max(0.78, min(0.995, base))

def _action_updated_range_board_profile(
    row: dict[str, Any],
    hand: Any,
    player_id: str,
    board: list[str],
    *,
    extra_blockers: tuple[str, ...] | list[str] | set[str] = (),
    max_samples: int = 320,
) -> dict[str, float] | None:
    """Build board strength from a player's range after every observed street action."""
    if not isinstance(row, dict) or not row.get("supported") or len(board) < 3:
        return None
    classes = row.get("unblocked_hand_class_probabilities")
    if not isinstance(classes, dict):
        classes = row.get("hand_class_probabilities")
    if not isinstance(classes, dict):
        return None
    board_blockers = set(str(card) for card in board)
    known_blockers = board_blockers | {
        str(card) for card in extra_blockers if str(card)
    }
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
            if not (set(combo) & known_blockers)
        ]
        if combos:
            options.extend((combo, class_weight / len(combos)) for combo in combos)
    if not options:
        return None

    players = list(getattr(hand, "players", ()) or ())
    actor_ids = {str(getattr(p, "player_id", "")) for p in players}
    actor_names = {
        str(getattr(p, "name", "")): str(getattr(p, "player_id", ""))
        for p in players if str(getattr(p, "name", ""))
    }
    target = str(player_id)
    running_board: list[str] = []
    learned = row.get("learned_behavior", row.get("learned_stats", {}))
    archetype = str(row.get("archetype", "balanced") or "balanced")
    for event in list(getattr(hand, "events", ()) or ()):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "street":
            running_board = [
                str(card) for card in event.get("board", running_board)
            ]
            continue
        if event.get("type") != "action":
            continue
        raw_actor = str(event.get("player_id") or event.get("player") or "")
        actor = raw_actor if raw_actor in actor_ids else actor_names.get(raw_actor)
        if actor != target:
            continue
        event_street = str(event.get("street", "preflop")).lower().replace("-", "")
        if event_street not in {"flop", "turn", "river"} or len(running_board) < 3:
            continue
        action = _event_action(event)
        if action == "fold":
            continue
        pot_before = max(1, int(event.get("pot_before", 1) or 1))
        paid = max(0, int(event.get("paid", event.get("amount", 0)) or 0))
        to_call = max(0, int(event.get("to_call_before", 0) or 0))
        if action in {"raise", "bet", "allin"}:
            size_fraction = paid / pot_before
        elif action in {"call", "allin_call"}:
            size_fraction = to_call / pot_before
        else:
            size_fraction = 0.0
        updated: list[tuple[tuple[str, str], float]] = []
        for combo, weight in options:
            if set(combo) & set(running_board):
                continue
            made, draw = _board_metrics(combo, running_board)
            likelihood = _action_likelihood(
                action, made, draw, size_fraction, event_street,
                archetype, learned,
            )
            posterior_weight = weight * likelihood
            if posterior_weight > 0:
                updated.append((combo, posterior_weight))
        if updated:
            options = updated

    total = sum(weight for _, weight in options)
    if total <= 0:
        return None
    options = [(combo, weight / total) for combo, weight in options]
    options.sort(key=lambda item: item[0])
    if len(options) > max(1, int(max_samples)):
        sample_count = max(1, int(max_samples))
        step = 1.0 / sample_count
        cumulative = options[0][1]
        index = 0
        sampled: list[tuple[tuple[str, str], float]] = []
        for sample_index in range(sample_count):
            target_weight = (sample_index + 0.5) * step
            while index < len(options) - 1 and cumulative < target_weight:
                index += 1
                cumulative += options[index][1]
            sampled.append((options[index][0], step))
        profile_options = sampled
    else:
        profile_options = options

    scores = [
        (_board_metrics(combo, board)[0], weight)
        for combo, weight in profile_options if weight > 0
    ]
    profile_total = sum(weight for _, weight in scores)
    if profile_total <= 0:
        return None
    mean = sum(score * weight for score, weight in scores) / profile_total
    nut_mass = sum(weight for score, weight in scores if score >= 0.315) / profile_total
    upper_mass = profile_total * 0.10
    remaining = upper_mass
    upper_sum = 0.0
    for score, weight in sorted(scores, key=lambda item: item[0], reverse=True):
        take = min(weight, remaining)
        upper_sum += score * take
        remaining -= take
        if remaining <= 1e-12:
            break
    return {
        "mean_strength": mean,
        "top_decile_strength": upper_sum / max(1e-12, upper_mass),
        "two_pair_plus_mass": nut_mass,
        "sampled_combos": float(len(scores)),
    }


def _sample_near_optimal_action(
    candidates: list[tuple[str, int | None, float]],
    *,
    best_ev: float,
    pot: int,
    level: int,
    rng: Any,
) -> tuple[str, int | None, bool, int]:
    """Mix among near-indifferent postflop actions instead of always pure-maxing EV.

    This is an EV-neighborhood approximation to mixed strategy, not a claimed
    solver frequency. Lower CPU levels remain deterministic and exploitative.
    """
    if int(level) < 4 or len(candidates) < 2:
        if candidates:
            chosen = max(candidates, key=lambda item: item[2])
            return chosen[0], chosen[1], False, 1
        return "", None, False, 0
    budget = max(1.0, float(max(1, int(pot))) * (0.010 if int(level) >= 5 else 0.018))
    near = [
        item for item in candidates
        if float(item[2]) >= float(best_ev) - budget
    ]
    # Collapse duplicate action/amount entries while preserving the best EV.
    collapsed: dict[tuple[str, int | None], float] = {}
    for action, amount, ev in near:
        key = (str(action), None if amount is None else int(amount))
        collapsed[key] = max(float(ev), collapsed.get(key, -float("inf")))
    near = [(a, amount, ev) for (a, amount), ev in collapsed.items()]
    if len(near) < 2:
        chosen = max(candidates, key=lambda item: item[2])
        return chosen[0], chosen[1], False, 1
    temperature = max(1.0, float(max(1, int(pot))) * (
        0.003 if int(level) >= 5 else 0.006
    ))
    weights = [
        math.exp(max(-20.0, min(0.0, (float(ev) - float(best_ev)) / temperature)))
        for _, _, ev in near
    ]
    total = sum(weights)
    threshold = (float(rng.random()) if rng is not None else random.random()) * total
    for item, weight in zip(near, weights):
        threshold -= weight
        if threshold <= 0:
            return item[0], item[1], True, len(near)
    chosen = near[-1]
    return chosen[0], chosen[1], True, len(near)

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



def _bet_response_branch_metrics(
    hand: Any,
    hero_id: str,
    ranges: dict[str, OpponentRange],
    board: list[str],
    bet_fraction: float,
    cpu: Any,
    *,
    simulation_multiplier: float = 0.40,
) -> dict[str, float | int]:
    """Model all-fold, call-only and raise branches with raise-conditioned ranges.

    A raise branch is no longer automatically valued as an immediate fold.
    It estimates the opponent's raise-conditioned range so the caller can
    compare continuing against that range with folding the initial bet.
    This remains a one-response approximation, not a full solver game tree.
    """
    street = {3: "flop", 4: "turn", 5: "river"}.get(len(board), "preflop")
    hero_stack = max(0, int(getattr(hand.player(hero_id), "stack", 0) or 0))
    effective_stack = hero_stack
    for opponent_id in ranges:
        try:
            opponent_stack = max(
                0, int(getattr(hand.player(opponent_id), "stack", 0) or 0)
            )
            effective_stack = min(effective_stack, opponent_stack)
        except Exception:
            continue
    effective_spr = effective_stack / max(1, int(getattr(hand, "pot", 0) or 0))
    call_ranges: dict[str, OpponentRange] = {}
    raise_conditioned_options: list[tuple[tuple[str, str], float]] = []
    raise_weighted_archetypes: list[tuple[str, float]] = []
    all_fold_probability = 1.0
    no_raise_probability = 1.0
    conditional_call_probabilities: list[float] = []

    for pid, opponent_range in ranges.items():
        total_mass = 0.0
        call_mass = 0.0
        raise_mass = 0.0
        call_conditioned: list[tuple[tuple[str, str], float]] = []
        raise_conditioned: list[tuple[tuple[str, str], float]] = []
        for combo, weight in opponent_range.combos:
            base_weight = max(0.0, float(weight))
            if base_weight <= 0:
                continue
            made, draw = _board_metrics(combo, board) if len(board) >= 3 else (
                _preflop_strength(_cards_to_class(combo)), 0.0
            )
            _fold_p, call_p, raise_p = _response_action_probabilities(
                made, draw, bet_fraction, street, opponent_range.archetype,
                opponent_range.learned_stats, spr=effective_spr,
            )
            if bet_fraction >= effective_spr and effective_spr > 0:
                # An effective all-in cannot be raised over; merge raise mass into calls.
                call_p += raise_p
                raise_p = 0.0
            total_mass += base_weight
            call_weight = base_weight * call_p
            raise_weight = base_weight * raise_p
            call_mass += call_weight
            raise_mass += raise_weight
            if call_weight > 0:
                call_conditioned.append((combo, call_weight))
            if raise_weight > 0:
                raise_conditioned.append((combo, raise_weight))

        if total_mass <= 0:
            continue
        participation = max(
            0.0, min(1.0, float(opponent_range.participation_probability))
        )
        average_call = max(0.0, min(1.0, call_mass / total_mass))
        average_raise = max(0.0, min(1.0, raise_mass / total_mass))
        actual_raise_probability = participation * average_raise
        actual_call_probability = participation * average_call
        no_raise_for_player = max(0.0, 1.0 - actual_raise_probability)
        all_fold_for_player = max(
            0.0, 1.0 - actual_call_probability - actual_raise_probability
        )
        no_raise_probability *= no_raise_for_player
        all_fold_probability *= all_fold_for_player

        conditional_call_probability = (
            actual_call_probability / no_raise_for_player
            if no_raise_for_player > 1e-12 else 0.0
        )
        conditional_call_probability = max(
            0.0, min(1.0, conditional_call_probability)
        )
        conditional_call_probabilities.append(conditional_call_probability)
        if call_mass > 0:
            combo_weights = tuple(
                (combo, weight / call_mass)
                for combo, weight in call_conditioned
            )
        else:
            combo_weights = opponent_range.combos
        call_ranges[pid] = OpponentRange(
            player_id=pid,
            combos=combo_weights,
            source=opponent_range.source + "+call-response",
            confidence=opponent_range.confidence,
            participation_probability=conditional_call_probability,
            archetype=opponent_range.archetype,
            learned_stats=opponent_range.learned_stats,
        )
        if actual_raise_probability > 0 and raise_mass > 0:
            raise_conditioned_options.extend(
                (combo, (weight / raise_mass) * actual_raise_probability)
                for combo, weight in raise_conditioned
            )
            raise_weighted_archetypes.append(
                (opponent_range.archetype, actual_raise_probability)
            )

    all_fold_probability = max(0.0, min(1.0, all_fold_probability))
    no_raise_probability = max(0.0, min(1.0, no_raise_probability))
    call_only_probability = max(
        0.0, min(1.0, no_raise_probability - all_fold_probability)
    )
    raise_probability = max(0.0, min(1.0, 1.0 - no_raise_probability))
    conditional_all_fold = (
        all_fold_probability / no_raise_probability
        if no_raise_probability > 1e-12 else 1.0
    )
    conditional_all_fold = max(0.0, min(1.0, conditional_all_fold))
    expected_callers_no_raise = sum(conditional_call_probabilities)
    probability_any_call_no_raise = 1.0 - conditional_all_fold
    expected_callers = (
        expected_callers_no_raise / probability_any_call_no_raise
        if probability_any_call_no_raise > 1e-12 else 0.0
    )

    no_raise_equity, samples = _equity_vs_ranges(
        hand, hero_id, call_ranges, cpu,
        simulation_multiplier=simulation_multiplier,
    )
    current_made_equity, made_samples = _current_showdown_equity(
        hand, hero_id, call_ranges, cpu,
        simulation_multiplier=0.45,
    )
    if conditional_all_fold >= 0.999999:
        called_equity = 1.0
        called_current_equity = 1.0
    else:
        called_equity = (
            no_raise_equity - conditional_all_fold
        ) / max(1e-9, 1.0 - conditional_all_fold)
        called_equity = max(0.0, min(1.0, called_equity))
        called_current_equity = (
            current_made_equity - conditional_all_fold
        ) / max(1e-9, 1.0 - conditional_all_fold)
        called_current_equity = max(0.0, min(1.0, called_current_equity))

    raise_conditioned_equity = 0.0
    raise_samples = 0
    raise_mass_total = sum(weight for _, weight in raise_conditioned_options)
    if raise_probability > 1e-6 and raise_mass_total > 1e-12:
        combined: dict[tuple[str, str], float] = {}
        for combo, weight in raise_conditioned_options:
            combined[combo] = combined.get(combo, 0.0) + max(0.0, float(weight))
        total = sum(combined.values())
        archetype_weight: dict[str, float] = {}
        for archetype, weight in raise_weighted_archetypes:
            archetype_weight[archetype] = archetype_weight.get(archetype, 0.0) + weight
        selected_archetype = (
            max(archetype_weight.items(), key=lambda item: item[1])[0]
            if archetype_weight else "balanced"
        )
        raiser_range = OpponentRange(
            player_id="raise-response",
            combos=tuple(
                (combo, weight / total)
                for combo, weight in combined.items() if weight > 0
            ),
            source="raise-conditioned-response-range",
            confidence=0.65,
            participation_probability=1.0,
            archetype=selected_archetype,
        )
        raise_conditioned_equity, raise_samples = _equity_vs_ranges(
            hand, hero_id, {"raise-response": raiser_range}, cpu,
            simulation_multiplier=0.25,
        )

    total_probability = all_fold_probability + call_only_probability + raise_probability
    if total_probability > 0 and abs(total_probability - 1.0) > 1e-9:
        all_fold_probability /= total_probability
        call_only_probability /= total_probability
        raise_probability /= total_probability
    return {
        "all_fold_probability": all_fold_probability,
        "call_only_probability": call_only_probability,
        "raise_probability": raise_probability,
        "expected_callers": max(0.0, expected_callers),
        "called_equity": max(0.0, min(1.0, called_equity)),
        "called_current_equity": max(0.0, min(1.0, called_current_equity)),
        "raise_conditioned_equity": max(0.0, min(1.0, raise_conditioned_equity)),
        "made_samples": made_samples,
        "raise_samples": raise_samples,
        "samples": samples + made_samples + raise_samples,
    }

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
    """Compatibility wrapper returning all-fold and call-conditioned metrics."""
    metrics = _bet_response_branch_metrics(
        hand, hero_id, ranges, board, bet_fraction, cpu,
        simulation_multiplier=simulation_multiplier,
    )
    return (
        float(metrics["all_fold_probability"]),
        float(metrics["expected_callers"]),
        float(metrics["called_equity"]),
        int(metrics["samples"]),
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
    spr: float | None = None,
    made_category: int = 0,
) -> float:
    """Minimum realized equity when called, calibrated for table state and SPR."""
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
    threshold = max(price_floor, multiway_floor)
    if spr is not None:
        effective_spr = max(0.0, float(spr))
        if effective_spr >= 8.0:
            threshold += min(0.035, (effective_spr - 8.0) * 0.0035)
        elif effective_spr <= 2.0 and int(made_category) >= 2:
            threshold -= 0.015
    return max(0.48, min(0.82, threshold))

def _best_passive_action(legal_actions: set[str]) -> str:
    for action in ("check", "fold", "call"):
        if action in legal_actions:
            return action
    return next(iter(legal_actions))


def _showdown_value_ev(equity: float, pot: int, estimated_rake: int = 0) -> float:
    """Approximate the value retained by checking through to showdown.

    Equity is weighted by action-updated opponent ranges and physical blockers.
    This one-street checkdown proxy is not a full future-street game tree; it
    prevents the policy from comparing a bet against an artificial zero-value check.
    """
    share = max(0.0, min(1.0, float(equity)))
    distributable = max(0, int(pot) - max(0, int(estimated_rake)))
    return share * distributable




def _range_conditioned_draw_strength(
    made_equity: float,
    runout_equity: float,
    board_draw_strength: float,
    street: str,
) -> float:
    """Blend visible draw texture with improvement equity against the call range."""
    if str(street or "").lower() == "river":
        return 0.0
    made = max(0.0, min(1.0, float(made_equity)))
    runout = max(0.0, min(1.0, float(runout_equity)))
    structural = max(0.0, min(1.0, float(board_draw_strength)))
    range_improvement = max(0.0, runout - made)
    conditioned = min(0.98, range_improvement * 1.75)
    return max(structural, conditioned)


def _postflop_board_texture(board: list[str]) -> dict[str, Any]:
    """Describe board dynamism for sizing and street-transition decisions."""
    cards = [str(card) for card in board if len(str(card)) >= 2]
    ranks = sorted({
        14 if card[0] == "A" else RANKS.index(card[0]) + 2
        for card in cards if card[0] in RANKS
    })
    suits: dict[str, int] = {}
    for card in cards:
        suits[card[1]] = suits.get(card[1], 0) + 1
    rank_counts: dict[int, int] = {}
    for card in cards:
        if card[0] not in RANKS:
            continue
        rank = 14 if card[0] == "A" else RANKS.index(card[0]) + 2
        rank_counts[rank] = rank_counts.get(rank, 0) + 1
    pair_count = sum(max(0, count - 1) for count in rank_counts.values())
    max_suit = max(suits.values(), default=0)
    connected_links = sum(
        1 for left, right in zip(ranks, ranks[1:]) if right - left <= 2
    )
    near_links = sum(
        1 for left, right in zip(ranks, ranks[1:]) if right - left <= 4
    )
    high_cards = sum(1 for rank in ranks if rank >= 10)
    span = ranks[-1] - ranks[0] if len(ranks) >= 2 else 0
    wetness = 0.0
    if max_suit == 2:
        wetness += 0.16
    elif max_suit >= 3:
        wetness += 0.42
    wetness += min(0.36, connected_links * 0.18)
    wetness += min(0.16, max(0, near_links - connected_links) * 0.08)
    if pair_count:
        wetness -= min(0.16, pair_count * 0.08)
    if high_cards >= 2:
        wetness -= 0.04
    if len(ranks) >= 3 and span <= 4:
        wetness += 0.08
    wetness = max(0.0, min(1.0, wetness))

    completed_flush = bool(len(cards) >= 4 and max_suit >= 3)
    unique = set(ranks)
    if 14 in unique:
        unique.add(1)
    completed_straight = any(
        len(set(range(high - 4, high + 1)) & unique) >= 5
        for high in range(5, 15)
    )
    return {
        "wetness": wetness,
        "paired": pair_count > 0,
        "pair_count": pair_count,
        "monotone": max_suit >= 3 and len(cards) >= 3,
        "two_tone": max_suit == 2,
        "connected_links": connected_links,
        "high_card_density": high_cards / max(1, len(ranks)),
        "completed_flush": completed_flush,
        "completed_straight": completed_straight,
    }




def _postflop_size_fraction(pot: int, risk: int, to_call: int = 0) -> float:
    """Measure the wager opponents face, excluding money already required to call.

    For a raise, the wager is the extra raise increment divided by the pot after
    the hero's call. Counting the call itself as part of the raise makes a
    normal raise look much larger to the response model, distorting fold
    probabilities and candidate EV.
    """
    current_pot = max(1, int(pot))
    total_risk = max(0, int(risk))
    call_cost = max(0, int(to_call))
    if call_cost > 0:
        wager = max(0, total_risk - call_cost)
        denominator = current_pot + call_cost
    else:
        wager = total_risk
        denominator = current_pot
    if wager <= 0:
        return 0.0
    return max(0.0, min(4.0, float(wager) / max(1, denominator)))

def _postflop_raise_increment(pot: int, to_call: int, fraction: float) -> int:
    """Convert a raise-size fraction into chips using the pot after hero calls.

    This is the same denominator used by _postflop_size_fraction. Keeping
    candidate generation and response sizing on one pot basis prevents the
    BOT from labelling a smaller raise as (for example) a 50% pot raise.
    """
    post_call_pot = max(1, int(pot)) + max(0, int(to_call))
    size = max(0.0, min(4.0, float(fraction)))
    return max(0, int(round(post_call_pot * size)))


def _postflop_bet_size_fractions(
    *,
    to_call: bool,
    donk_lead: bool,
    range_advantage: bool,
    range_disadvantage: bool,
    nut_advantage: float,
    expected_callers: float,
    board_texture: dict[str, Any] | None = None,
    spr: float | None = None,
    remaining_streets: int = 2,
    street: str = "flop",
    made_category: int = 0,
) -> tuple[float, ...]:
    """Generate a compact GTO-style size menu from range, nuts, texture and SPR.

    Range advantage primarily supports betting frequency. Nut advantage and
    board/runout interaction justify larger sizes. Flop sizes start smaller;
    turn/river overbets are reserved for genuinely polar, heads-up value ranges.
    Multiway defaults are deliberately reduced because combined calling ranges
    retain much more equity than a single opponent's range.
    """
    callers = max(0.0, float(expected_callers))
    nut_edge = max(0.0, min(1.0, float(nut_advantage)))
    texture = board_texture if isinstance(board_texture, dict) else {}
    wetness = max(0.0, min(1.0, float(texture.get("wetness", 0.30) or 0.0)))
    paired = bool(texture.get("paired", False))
    monotone = bool(texture.get("monotone", False))
    current_street = str(street or "flop").lower()
    category = max(0, min(8, int(made_category)))
    effective_spr = max(0.0, float(spr)) if spr is not None else 5.0
    hu = callers <= 1.25

    if to_call:
        # A raise menu is expressed in increments over the current pot. It is
        # intentionally narrower than a lead-bet menu; the call component is
        # excluded later when the response model measures the actual raise.
        if callers >= 1.5 or range_disadvantage:
            return (0.50, 0.75)
        if range_advantage and nut_edge >= 0.12:
            return (0.50, 0.75, 1.00, 1.25)
        return (0.33, 0.50, 0.75, 1.00)

    if donk_lead:
        if callers >= 1.5:
            return (0.20, 0.25, 0.33)
        return (0.20, 0.25, 0.33, 0.50) if wetness >= 0.48 else (0.20, 0.25, 0.33)

    if callers >= 1.5:
        # Rare multiway exceptions need both a substantial nut edge and a
        # near-nutted made hand; a generic range edge is not enough.
        if (
            range_advantage and not range_disadvantage
            and nut_edge >= 0.30 and category >= 4
            and current_street in {"turn", "river"}
        ):
            return (0.25, 0.33, 0.50, 0.75, 1.00, 1.25)
        return (0.15, 0.25, 0.33, 0.50)

    if range_disadvantage:
        return (0.20, 0.33, 0.50, 0.75) if wetness >= 0.50 else (0.15, 0.25, 0.33, 0.50)

    if range_advantage and nut_edge >= 0.05:
        if current_street == "flop":
            if paired or wetness < 0.25:
                base_sizes = (0.15, 0.25, 0.33, 0.50)
            elif wetness >= 0.50 or monotone:
                base_sizes = (0.25, 0.33, 0.50, 0.75, 1.00) if nut_edge >= 0.12 and category >= 2 else (0.25, 0.33, 0.50, 0.75)
            else:
                base_sizes = (0.20, 0.25, 0.33, 0.50, 0.75)
        elif current_street == "turn":
            base_sizes = (0.25, 0.33, 0.50, 0.75, 1.00)
            if nut_edge >= 0.15 and category >= 2:
                base_sizes += (1.25,)
        elif current_street == "river":
            base_sizes = (0.25, 0.33, 0.50, 0.75, 1.00)
            if nut_edge >= 0.15 and category >= 2:
                base_sizes += (1.25,)
            if nut_edge >= 0.22 and category >= 3:
                base_sizes += (1.50,)
        else:
            base_sizes = (0.25, 0.33, 0.50, 0.75)

        # A shallow-SPR flop jam is retained only for a strong made hand with a
        # verified nut edge. It is not a blanket permission to bet 2.5x pot.
        if (
            current_street == "flop" and hu
            and 0.0 < effective_spr <= 1.75
            and category >= 3 and nut_edge >= 0.12
        ):
            base_sizes += (round(effective_spr, 2),)

        # Geometric sizing is a planning tool, not an instruction to overbet
        # every street. Add it only when it is small enough for the current
        # street or when the turn/river hand meets the polar-value conditions.
        geometric = _geometric_bet_fraction(effective_spr, remaining_streets)
        if geometric is not None:
            if geometric <= 1.00:
                base_sizes += (round(geometric, 2),)
            elif (
                current_street in {"turn", "river"}
                and hu and nut_edge >= 0.15 and category >= 2
                and geometric <= (1.25 if current_street == "turn" else 1.50)
            ):
                base_sizes += (round(geometric, 2),)
        return tuple(sorted(set(base_sizes)))

    # Without a meaningful range/nut edge, use merged, small-to-medium bets.
    if paired or wetness < 0.20:
        return (0.10, 0.15, 0.25, 0.33, 0.50)
    if wetness >= 0.60 or monotone:
        return (0.25, 0.33, 0.50, 0.75)
    return (0.15, 0.25, 0.33, 0.50, 0.75)


def _postflop_overbet_size_allowed(
    bet_fraction: float,
    *,
    street: str,
    range_advantage: bool,
    range_disadvantage: bool,
    nut_advantage: float,
    expected_callers: float,
    made_category: int,
    current_equity: float,
    spr: float,
) -> bool:
    """Permit overbets only where GTO-style polar/nut conditions support them."""
    size = max(0.0, float(bet_fraction))
    if size <= 1.0 + 1e-9:
        return True
    current_street = str(street or "").lower()
    nut_edge = max(0.0, min(1.0, float(nut_advantage)))
    callers = max(0.0, float(expected_callers))
    category = max(0, min(8, int(made_category)))
    equity = max(0.0, min(1.0, float(current_equity)))
    effective_spr = max(0.0, float(spr))

    if not range_advantage or range_disadvantage or nut_edge < 0.12:
        return False

    if current_street == "flop":
        # Early-street overbets are unusual. Keep only genuine low-SPR,
        # near-stack-off value situations, not generic range bets.
        return bool(
            callers <= 1.15 and effective_spr <= 1.75
            and size <= effective_spr + 0.02
            and category >= 3 and equity >= 0.78
            and nut_edge >= 0.15
        )
    if current_street == "turn":
        if callers >= 1.5:
            return bool(
                size <= 1.25 and nut_edge >= 0.30
                and category >= 4 and equity >= 0.85
            )
        return bool(
            size <= 1.25 and callers <= 1.25
            and nut_edge >= 0.15 and category >= 2
            and equity >= 0.72
        )
    if current_street == "river":
        if callers >= 1.5:
            return bool(
                size <= 1.25 and nut_edge >= 0.30
                and category >= 4 and equity >= 0.85
            )
        return bool(
            size <= 1.50 and callers <= 1.25
            and nut_edge >= 0.15 and category >= 2
            and equity >= 0.70
        )
    return False



def _postflop_polarized_candidate_role(
    bet_fraction: float,
    *,
    street: str,
    value_gate: bool,
    bluff_gate: bool,
    has_sdv: bool,
    made_category: int,
    current_equity: float,
    nut_advantage: float,
    range_advantage: bool,
    range_disadvantage: bool,
    expected_callers: float,
    fold_probability: float,
    required_success: float,
    uncertainty_margin: float,
    value_combos_blocked: float,
    bluff_combos_blocked: float,
    draw_strength: float,
    in_position: bool,
) -> str | None:
    """Classify large-bet candidates as polar value, polar bluff, or middle.

    Below 75% pot, merged betting remains available. At 75% pot and above,
    the betting range is deliberately polarized: strong value hands or
    carefully selected low-showdown-value bluffs. Medium-strength SDV hands
    are routed to the check/call region instead of being inflated into a
    large bet. This is a deterministic GTO-inspired heuristic, not a solver
    frequency table.
    """
    size = max(0.0, float(bet_fraction))
    if size < 0.75 - 1e-9:
        return "merged"

    current_street = str(street or "").lower()
    # Preflop is governed by the immutable 174-situation chart. Never apply
    # postflop range-polarity gates to its sizing/action frequencies.
    if current_street == "preflop":
        return "preflop-chart"
    callers = max(0.0, float(expected_callers))
    category = max(0, min(8, int(made_category)))
    equity = max(0.0, min(1.0, float(current_equity)))
    nut_edge = max(0.0, min(1.0, float(nut_advantage)))
    value_blocked = max(0.0, float(value_combos_blocked))
    bluff_blocked = max(0.0, float(bluff_combos_blocked))
    blocker_edge = value_blocked - 0.75 * bluff_blocked

    # In multiway pots a polar bluff has to get through several ranges. Keep
    # large bets almost exclusively for near-nutted value; rare strong
    # multiway overbets are independently capped by the overbet guard.
    if callers > 1.25:
        if (
            value_gate and has_sdv and category >= 4
            and equity >= 0.86 and nut_edge >= 0.30
            and range_advantage and not range_disadvantage
            and size <= 1.25 + 1e-9
        ):
            return "value-multiway"
        return None

    value_equity_floor = {
        "flop": 0.72,
        "turn": 0.75,
        "river": 0.78,
    }.get(current_street, 0.75)
    value_category_ok = category >= 2 or (
        current_street == "river" and category >= 1 and equity >= 0.85
    )
    polar_value = bool(
        value_gate and has_sdv and value_category_ok
        and equity >= value_equity_floor
        and nut_edge >= 0.12
        and (range_advantage or nut_edge >= 0.24)
        and not range_disadvantage
    )
    if polar_value:
        return "value"

    # A large bluff needs a low-SDV hand, positive removal of value calls,
    # and a fold rate with a meaningful margin over break-even. Draw equity
    # can qualify a semi-bluff, but it cannot turn a medium SDV hand into a
    # bluff. The helper also requires heads-up conditions and IP/range edge.
    polar_bluff = bool(
        bluff_gate and not has_sdv
        and equity <= 0.52
        and value_blocked >= 0.035
        and blocker_edge >= 0.035
        and _postflop_pure_bluff_allowed(
            fold_probability,
            required_success,
            uncertainty_margin,
            callers,
            value_blocked,
            bluff_blocked,
            in_position=bool(in_position),
            range_advantage=bool(range_advantage and not range_disadvantage),
        )
    )
    if polar_bluff:
        return "bluff"
    return None


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
        "range_advantage": False,
        "range_edge": 0.0,
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
    hero_profile = _action_updated_range_board_profile(
        hero_row, hand, str(hero_id), board
    )
    if hero_profile is None:
        return neutral
    hero_player = next(
        (p for p in list(getattr(hand, "players", ()) or ())
         if str(getattr(p, "player_id", "")) == str(hero_id)),
        None,
    )
    hero_known_cards = tuple(
        str(card) for card in list(getattr(hero_player, "hole_cards", ()) or ())
    )

    active_opponents = [
        player for player in list(getattr(hand, "players", ()) or ())
        if str(getattr(player, "player_id", ""))
        and str(getattr(player, "player_id", "")) != str(hero_id)
        and bool(getattr(player, "eligible", False))
    ]
    opponent_profiles = []
    for player in active_opponents:
        pid = str(getattr(player, "player_id", ""))
        profile = _action_updated_range_board_profile(
            rows.get(pid, {}), hand, pid, board,
            extra_blockers=hero_known_cards,
        )
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
    advantage = bool(
        (mean_advantage >= 0.025 and top_advantage >= 0.025)
        or top_advantage >= 0.065
        or (nut_advantage >= 0.12 and mean_advantage > 0.0)
    )
    range_edge = (
        0.30 * mean_advantage
        + 0.50 * top_advantage
        + 0.20 * nut_advantage
    )
    return {
        "supported": True,
        "range_disadvantage": disadvantage,
        "range_advantage": advantage,
        "range_edge": range_edge,
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
    texture_proxy_advantage = bool(
        aggressor and (
            (is_hero_aggressor and aggressor_favored)
            or (not is_hero_aggressor and caller_favored)
        )
    )
    range_disadvantage = (
        bool(range_profile["range_disadvantage"])
        if range_profile["supported"] else texture_proxy_disadvantage
    )
    range_advantage = (
        bool(range_profile.get("range_advantage", False))
        if range_profile["supported"] else texture_proxy_advantage
    )
    range_edge = (
        float(range_profile.get("range_edge", 0.0))
        if range_profile["supported"] else (
            0.045 if texture_proxy_advantage else
            -0.045 if texture_proxy_disadvantage else 0.0
        )
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
        "preflop_range_advantage": range_advantage,
        "preflop_range_edge": range_edge,
        "texture_proxy_range_disadvantage": texture_proxy_disadvantage,
        "texture_proxy_range_advantage": texture_proxy_advantage,
        "preflop_range_profile": range_profile,
        "donk_lead": donk_lead,
    }



def _postflop_showdown_value_profile(
    current_equity: float,
    made_category: int,
    expected_opponents: float,
    street: str,
    *,
    supported: bool,
    position_known: bool = False,
    in_position: bool = False,
    range_advantage: bool = False,
    range_disadvantage: bool = False,
) -> dict[str, Any]:
    """Classify current-board showdown value separately from future draw equity.

    The thresholds are heuristic policy cutoffs, not solver frequencies. They
    become tighter multiway and when the 174-chart range profile favours the
    opponent. A hand with meaningful SDV is protected from being repurposed as
    a low-equity bluff.
    """
    value = max(0.0, min(1.0, float(current_equity)))
    category = max(0, min(8, int(made_category)))
    opponents = max(0.0, float(expected_opponents))
    current_street = str(street or "").lower()
    if category <= 0:
        base = {"flop": 0.66, "turn": 0.63, "river": 0.59}.get(current_street, 0.63)
    elif category == 1:
        base = {"flop": 0.56, "turn": 0.54, "river": 0.51}.get(current_street, 0.54)
    elif category == 2:
        base = {"flop": 0.48, "turn": 0.47, "river": 0.46}.get(current_street, 0.47)
    else:
        base = {"flop": 0.42, "turn": 0.42, "river": 0.43}.get(current_street, 0.42)

    multiway_adjustment = min(0.12, max(0.0, opponents - 1.0) * 0.045)
    position_adjustment = -0.015 if position_known and in_position else 0.0
    range_adjustment = (
        0.025 if range_disadvantage else
        -0.020 if range_advantage else 0.0
    )
    threshold = max(
        0.34,
        min(0.84, base + multiway_adjustment + position_adjustment + range_adjustment),
    )
    has_sdv = bool(supported and len(current_street) > 0 and value >= threshold)
    margin = value - threshold
    classification = (
        "unsupported" if not supported else
        "none" if not has_sdv else
        "strong" if margin >= 0.14 else
        "medium" if margin >= 0.06 else
        "thin"
    )
    return {
        "supported": bool(supported),
        "has_sdv": has_sdv,
        "classification": classification,
        "current_equity": value,
        "threshold": threshold,
        "margin": margin,
        "multiway_adjustment": multiway_adjustment,
        "range_adjustment": range_adjustment,
    }


def _postflop_pure_bluff_allowed(
    fold_probability: float,
    required_success: float,
    uncertainty_margin: float,
    expected_callers: float,
    value_combos_blocked: float,
    bluff_combos_blocked: float,
    *,
    in_position: bool,
    range_advantage: bool,
) -> bool:
    """Pure bluffs need both sufficient fold equity and useful value blockers."""
    blocker_edge = (
        max(0.0, float(value_combos_blocked))
        - 0.75 * max(0.0, float(bluff_combos_blocked))
    )
    fold_floor = min(
        0.98,
        max(0.0, float(required_success))
        + 0.14
        + max(0.0, float(uncertainty_margin)) * 0.75,
    )
    return bool(
        float(fold_probability) >= fold_floor
        and float(expected_callers) <= 1.25
        and blocker_edge >= 0.035
        and (bool(in_position) or bool(range_advantage))
    )


def _postflop_thin_value_size_allowed(
    is_thin_value: bool,
    bet_fraction: float,
    street: str,
) -> bool:
    """Thin one-pair value uses a capped size to avoid isolating against better."""
    if not is_thin_value:
        return True
    cap = 0.33 if str(street or "").lower() == "river" else 0.50
    return float(bet_fraction) <= cap + 1e-9


def _postflop_sdv_aggression_allowed(
    has_sdv: bool,
    classification: str,
    *,
    street: str,
    to_call: int,
    bet_fraction: float,
    made_category: int,
    called_current_equity: float,
    value_threshold: float,
    expected_callers: float,
    value_gate: bool,
    protection_gate: bool,
    candidate_ev: float,
    passive_ev: float,
    pot: int,
    range_disadvantage: bool = False,
) -> bool:
    """Require a clear reason to turn a showdown hand into an aggressive bet.

    Thin and medium SDV hands should usually realise their value by checking
    or calling. They may bet only when worse hands continue often enough to
    support value, the size is controlled, and the candidate clears the
    passive check/call EV by a meaningful margin. Protection bets are handled
    separately and kept small. Raises with one-pair SDV are strongly restricted.
    """
    if not bool(has_sdv):
        return True

    current_street = str(street or "").lower()
    if current_street not in {"flop", "turn", "river"}:
        return True
    category = max(0, min(8, int(made_category)))
    callers = max(0.0, float(expected_callers))
    size = max(0.0, float(bet_fraction))
    current_equity = max(0.0, min(1.0, float(called_current_equity)))
    threshold = max(0.0, min(1.0, float(value_threshold)))
    pot_size = max(1, int(pot))
    ev_edge = float(candidate_ev) - float(passive_ev)

    # A protection bet is not a licence to turn a marginal SDV hand into a
    # large value bet. It is only a small, heads-up denial bet on early streets.
    if bool(protection_gate):
        return bool(
            int(to_call) <= 0
            and current_street in {"flop", "turn"}
            and size <= 0.25 + 1e-9
            and callers <= 1.25
            and current_equity >= max(0.40, threshold - 0.10)
            and ev_edge >= 0.005 * pot_size
        )

    if not bool(value_gate):
        return False

    role = str(classification or "none").lower()
    multiway = callers >= 1.5
    disadvantage = bool(range_disadvantage)
    equity_floor_extra = (0.045 if multiway else 0.0) + (0.025 if disadvantage else 0.0)
    ev_floor_extra = (0.015 if multiway else 0.0) + (0.010 if disadvantage else 0.0)

    if int(to_call) > 0:
        # When facing a bet, an SDV hand should not turn into a thin raise.
        # One-pair raises need exceptional equity against the calling range.
        if category < 2 and current_equity < 0.82:
            return False
        if role != "strong" and current_equity < 0.86:
            return False
        size_cap = 0.75 if category < 3 else 1.00
        return bool(
            size <= size_cap + 1e-9
            and current_equity >= max(threshold + 0.08, 0.78 + equity_floor_extra)
            and ev_edge >= (0.025 + ev_floor_extra) * pot_size
        )

    if role == "thin":
        size_cap = 0.25 if current_street == "river" else 0.33
        equity_floor = max(threshold + 0.06, 0.66 + equity_floor_extra)
        ev_floor = 0.030 + ev_floor_extra
    elif role == "medium":
        size_cap = 0.33 if current_street == "river" else 0.50
        equity_floor = max(threshold + 0.04, 0.62 + equity_floor_extra)
        ev_floor = 0.020 + ev_floor_extra
    elif role == "strong":
        if category >= 2:
            size_cap = 0.75 if current_street != "river" else 1.00
        else:
            size_cap = 0.50 if current_street != "river" else 0.33
        equity_floor = max(threshold + 0.02, 0.60 + equity_floor_extra)
        ev_floor = 0.010 + ev_floor_extra
    else:
        return False

    if multiway:
        size_cap = min(size_cap, 0.33 if role != "strong" else 0.50)
    return bool(
        size <= size_cap + 1e-9
        and current_equity >= equity_floor
        and ev_edge >= ev_floor * pot_size
    )


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
    range_advantage: bool = False,
    range_edge: float = 0.0,
    called_current_equity: float | None = None,
    has_sdv: bool = False,
    protection_gate: bool = False,
) -> tuple[bool, bool]:
    """Gate aggression using made-hand quality, SDV, range edge and opponent count."""
    if str(street).lower() == "preflop":
        return bool(value_gate), bool(bluff_gate)

    draw = max(0.0, min(1.0, float(draw_strength)))
    callers = max(0.0, float(expected_callers))
    category = max(0, int(made_category))
    edge = max(-0.25, min(0.25, float(range_edge)))
    current_equity = (
        float(called_current_equity)
        if called_current_equity is not None else float(called_equity)
    )
    # A hand that can win at showdown is not a candidate for a pure bluff.
    # The only non-value exception is the tightly constrained small protection
    # bet computed by the caller; it is never allowed to become a raise bluff.
    if has_sdv:
        bluff_gate = False
    if protection_gate and int(to_call) <= 0 and not donk_lead:
        value_gate = True
    effective_value_threshold = float(value_threshold)
    if range_advantage and not range_disadvantage:
        effective_value_threshold = max(
            0.48, effective_value_threshold - min(0.02, max(0.0, edge) * 0.20)
        )
    # A draw may have substantial all-in equity, but it is not automatically
    # a value hand. Require current made-hand equity to support thin value.
    if category < 1 and current_equity < effective_value_threshold:
        value_gate = False
    elif category == 1 and current_equity < 0.42:
        # A pair plus a strong draw is still primarily a draw if its made hand
        # loses too often to the opponent's call-conditioned range.
        value_gate = False

    if int(to_call) > 0:
        raise_floor = 0.60 + 0.045 * max(0.0, callers - 1.0)
        raise_floor += max(0.0, min(0.12, float(uncertainty_margin) * 0.10))
        if range_disadvantage:
            raise_floor += 0.07
        elif range_advantage:
            raise_floor -= min(0.02, max(0.0, edge) * 0.20)
        value_gate = bool(
            value_gate
            and float(called_equity) >= max(effective_value_threshold, raise_floor)
            and (category >= 1 or current_equity >= max(0.52, effective_value_threshold))
        )
        draw_floor = 0.84 if range_disadvantage else (
            0.64 if range_advantage else 0.68
        )
        bluff_gate = bool(
            bluff_gate and draw >= draw_floor
            and float(fold_probability) >= float(required_success) + 0.08
            + max(0.0, float(uncertainty_margin)) * 0.5
        )
    elif donk_lead:
        # HU donks can include top pair when a verified caller-side range edge
        # supports it. Multiway leads remain restricted to sets or exceptional draws.
        if callers >= 1.5:
            strong_donk_hand = category >= 3 or draw >= 0.92
            draw_floor = 0.92
        else:
            range_supported_top_pair = bool(
                range_advantage and not range_disadvantage and category >= 1
                and float(called_equity) >= effective_value_threshold + 0.035
            )
            strong_donk_hand = (
                category >= 2 or range_supported_top_pair or draw >= 0.82
            )
            draw_floor = 0.82
        value_gate = bool(
            value_gate and strong_donk_hand
            and (category >= 1 or current_equity >= effective_value_threshold)
        )
        bluff_gate = bool(
            bluff_gate and draw >= max(draw_floor, 0.90)
            and not range_disadvantage
        )
    elif range_disadvantage:
        if category < 1:
            value_gate = False
            bluff_gate = bool(bluff_gate and draw >= 0.78)
        else:
            value_gate = bool(
                value_gate and float(called_equity) >= effective_value_threshold + 0.035
                and (category >= 1 or current_equity >= effective_value_threshold)
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
    current_made_equity, made_samples = (
        _current_showdown_equity(hand, player_id, ranges, cpu)
        if street != "preflop" else (equity, 0)
    )
    blocker_metrics = _blocker_removal_metrics(hand, player_id, ranges)
    board_role = _postflop_board_role_context(
        table, hand, player_id, range_estimator=range_estimator
    ) if street != "preflop" else {
        "preflop_aggressor": None, "hero_is_preflop_aggressor": False,
        "caller_favored_board": False, "aggressor_favored_board": False,
        "preflop_range_disadvantage": False, "preflop_range_advantage": False,
        "preflop_range_edge": 0.0, "donk_lead": False,
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

    position_profile = (
        _postflop_position_profile(table, hand, player_id)
        if street != "preflop" else {
            "known": False, "in_position": False, "opponents_after": 0
        }
    )
    level = min(5, max(1, int(getattr(cpu, "level", 3) or 3)))
    archetype = str(getattr(cpu, "archetype", "balanced") or "balanced")
    margin = {1: 0.105, 2: 0.075, 3: 0.050, 4: 0.025, 5: 0.010}[level]
    if bool(getattr(cpu, "_vip_top_pro_mode", False)):
        margin = min(margin, 0.001)
    elif bool(getattr(cpu, "_vip_pro_mode", False)):
        margin = min(margin, 0.005)
    guardrail_penalty = min(
        1000, max(0, int(getattr(cpu, "_range_guardrail_penalty", 0) or 0))
    )
    expected_opponents = sum(
        max(0.0, min(1.0, float(opponent.participation_probability)))
        for opponent in ranges.values()
    )
    effective_stack = stack
    for opponent_id in ranges:
        try:
            effective_stack = min(
                effective_stack,
                max(0, int(getattr(hand.player(opponent_id), "stack", 0) or 0)),
            )
        except Exception:
            continue
    spr = effective_stack / max(1, pot)
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
    equity_realization = (
        _equity_realization_factor(
            street,
            in_position=bool(position_profile.get("in_position", False)),
            position_known=bool(position_profile.get("known", False)),
            expected_opponents=expected_opponents,
            made_category=hero_hand_category,
            draw_strength=hero_draw_strength,
            spr=spr,
        ) if street != "preflop" else 1.0
    )
    realized_equity = max(0.0, min(1.0, equity * equity_realization))
    showdown_profile = _postflop_showdown_value_profile(
        current_made_equity,
        hero_hand_category,
        expected_opponents,
        street,
        supported=bool(ranges) and len(board) >= 3,
        position_known=bool(position_profile.get("known", False)),
        in_position=bool(position_profile.get("in_position", False)),
        range_advantage=bool(board_role.get("preflop_range_advantage", False)),
        range_disadvantage=bool(board_role.get("preflop_range_disadvantage", False)),
    ) if street != "preflop" else {
        "supported": False, "has_sdv": False, "classification": "not-postflop",
        "current_equity": 0.0, "threshold": 0.0, "margin": 0.0,
    }
    rake_bps = max(0, int(getattr(hand, "rake_bps", 0) or 0))
    rake_cap = max(0, int(getattr(hand, "rake_cap", 0) or 0))
    call_pot = pot + to_call
    estimated_rake = min(rake_cap, int(call_pot * rake_bps / 10000)) if rake_bps else 0
    call_is_all_in = stack > 0 and to_call >= stack
    call_equity = _call_realized_equity(
        equity, equity_realization, call_is_all_in=call_is_all_in
    )
    required_call = required_call_equity(pot, to_call, estimated_rake)
    required_bluff = required_bluff_success(pot, max(1, int(round(max(1, pot) * 0.50))))
    fold_probability = 0.0
    expected_callers = 0.0
    called_equity_estimate = equity
    response_samples = 0
    raise_response_probability = 0.0
    raise_equity_estimate = 0.0
    candidate_draw_strength = hero_draw_strength

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

    # SDV is the range-weighted value of checking through to showdown.
    # A zero-valued check baseline systematically over-bets medium-strength hands.
    showdown_value_ev = (
        _showdown_value_ev(realized_equity, pot, estimated_rake)
        if street != "preflop" else 0.0
    )
    best_action = _best_passive_action(actions)
    best_amount: int | None = None
    best_ev = -float("inf")
    selected_polar_role = "check/call or middle-strength"
    if best_action == "fold":
        best_ev = 0.0
    elif best_action == "check":
        best_ev = showdown_value_ev if "check" in actions else 0.0
    elif best_action == "call":
        best_ev = call_equity * max(0, call_pot - estimated_rake) - to_call
    elif best_action in {"all_in", "allin"}:
        best_ev = equity * max(0, call_pot - estimated_rake) - to_call

    if to_call > 0 and call_equity < required_call and "fold" in actions:
        best_action, best_amount, best_ev = "fold", None, 0.0
    elif to_call > 0 and "call" in actions:
        best_action, best_amount = "call", None
        best_ev = call_equity * max(0, call_pot - estimated_rake) - to_call

    # Preserve the original passive check/call EV as the reference point.
    # Candidate bets must beat this baseline before they can enter the high-level
    # near-indifference mixer; otherwise the mixer can leak thin-SDV bets into
    # a strategy that should simply check and realise showdown value.
    sdv_passive_baseline_ev = best_ev
    sdv_candidates_blocked = 0
    selected_sdv_policy = (
        "check/call-preserve" if bool(showdown_profile.get("has_sdv", False))
        else "not-applicable"
    )

    # Candidate actions are retained for a controlled near-indifference mix
    # at high CPU levels; lower levels continue to choose the pure best EV.
    strategy_candidates: list[tuple[str, int | None, float]] = []
    if street != "preflop" and to_call > 0:
        if "fold" in actions:
            strategy_candidates.append(("fold", None, 0.0))
        if "call" in actions:
            strategy_candidates.append((
                "call", None,
                call_equity * max(0, call_pot - estimated_rake) - to_call,
            ))
    elif street != "preflop" and "check" in actions:
        strategy_candidates.append(("check", None, showdown_value_ev))
    else:
        strategy_candidates.append((best_action, best_amount, best_ev))

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
        # Only postflop sizing consumes a range/nut profile. Preflop remains
        # fully controlled by the immutable 174-situation chart.
        nut_advantage = 0.0
        if street == "preflop":
            multipliers = (2.15, 2.40, 2.70) if to_call else (2.0, 2.3)
            targets = {
                min(max_target, max(min_target, int(round(max(current_bet, last_full_raise) * factor))))
                for factor in multipliers
            }
        else:
            range_profile = board_role.get("preflop_range_profile", {})
            nut_advantage = float(
                range_profile.get("top_decile_advantage", 0.0)
            ) if isinstance(range_profile, dict) else 0.0
            board_texture = _postflop_board_texture(board)
            fractions = _postflop_bet_size_fractions(
                to_call=bool(to_call),
                donk_lead=bool(board_role.get("donk_lead", False)),
                range_advantage=bool(board_role.get("preflop_range_advantage", False)),
                range_disadvantage=bool(board_role.get("preflop_range_disadvantage", False)),
                nut_advantage=nut_advantage,
                expected_callers=expected_opponents,
                board_texture=board_texture,
                spr=spr,
                remaining_streets=max(1, 6 - len(board)),
                street=street,
                made_category=hero_hand_category,
            )
            bases = [
                street_contribution + max(min_target - street_contribution,
                                          int(round(max(1, pot) * fraction)))
                for fraction in fractions
            ]
            if to_call:
                bases = [
                    max(
                        min_target,
                        current_bet + max(
                            last_full_raise,
                            _postflop_raise_increment(pot, to_call, fraction),
                        ),
                    )
                    for fraction in fractions
                ]
            targets = {min(max_target, target) for target in bases
                       if min(max_target, target) >= min_target}
        for target in targets:
            if target <= current_bet:
                continue
            risk = target - street_contribution
            # Opponents respond to the incremental wager, not to the call
            # amount already included in the current pot.
            bet_fraction = _postflop_size_fraction(pot, risk, to_call)
            candidate_blockers = _blocker_removal_metrics(
                hand, player_id, ranges, bet_fraction
            )
            response_metrics = _bet_response_branch_metrics(
                hand, player_id, ranges, board, bet_fraction, cpu,
                simulation_multiplier=0.40,
            )
            candidate_fold_probability = float(response_metrics["all_fold_probability"])
            candidate_call_probability = float(response_metrics["call_only_probability"])
            candidate_raise_probability = float(response_metrics["raise_probability"])
            candidate_raise_equity = float(
                response_metrics.get("raise_conditioned_equity", 0.0)
            )
            candidate_expected_callers = float(response_metrics["expected_callers"])
            candidate_called_equity = float(response_metrics["called_equity"])
            candidate_called_current_equity = float(
                response_metrics.get("called_current_equity", candidate_called_equity)
            )
            candidate_draw_strength = _range_conditioned_draw_strength(
                candidate_called_current_equity,
                candidate_called_equity,
                hero_draw_strength,
                street,
            )
            candidate_response_samples = int(response_metrics["samples"])
            required_success = required_bluff_success(pot, risk)
            candidate_required_bluff = required_success
            raise_increment = max(0, risk - to_call) if to_call else risk
            caller_payment = raise_increment if to_call else risk
            candidate_called_realized_equity = _call_realized_equity(
                candidate_called_equity,
                equity_realization,
                call_is_all_in=(stack > 0 and risk >= stack),
            )
            called_pot = (
                pot + risk + candidate_expected_callers * caller_payment
            )
            candidate_rake = (
                min(rake_cap, int(called_pot * rake_bps / 10000))
                if rake_bps else 0
            )
            # The raise branch is evaluated against a separate raise-conditioned
            # range. Hero either folds and loses the initial investment, or calls
            # the modeled re-raise when its price and equity make continuation +EV.
            raise_branch_ev = -float(risk)
            if candidate_raise_probability > 0.0 and candidate_raise_equity > 0.0:
                opponent_commitment = min(
                    max(0, int(round(2.5 * risk))), effective_stack
                )
                extra_to_call = max(0, opponent_commitment - risk)
                hero_extra = min(extra_to_call, max(0, stack - risk))
                raise_branch_pot = (
                    pot + risk + opponent_commitment + hero_extra
                )
                raise_branch_rake = (
                    min(rake_cap, int(raise_branch_pot * rake_bps / 10000))
                    if rake_bps else 0
                )
                continue_ev = (
                    candidate_raise_equity
                    * max(0, raise_branch_pot - raise_branch_rake)
                    - (risk + hero_extra)
                )
                raise_branch_ev = max(-float(risk), continue_ev)
            raise_ev = (
                candidate_fold_probability * pot
                + candidate_call_probability
                * (
                    candidate_called_realized_equity * max(0, called_pot - candidate_rake)
                    - risk
                )
                + candidate_raise_probability * raise_branch_ev
            )
            # Thin value is still value when the weighted calling range
            # loses often enough. More likely callers in multiway pots raise
            # the required threshold; level and uncertainty calibrate caution.
            value_threshold = _thin_value_threshold(
                level, uncertainty_margin, candidate_expected_callers,
                required_call, street, spr=spr,
                made_category=hero_hand_category,
            )
            minimum_made_equity = (
                value_threshold if hero_hand_category == 0
                else 0.42 if hero_hand_category == 1
                else 0.30
            )
            value_gate = (
                candidate_called_realized_equity >= value_threshold
                and candidate_called_current_equity >= minimum_made_equity
            )
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
            has_sdv = bool(showdown_profile.get("has_sdv", False))
            range_advantage = bool(board_role.get("preflop_range_advantage", False))
            range_disadvantage = bool(board_role.get("preflop_range_disadvantage", False))
            in_position = bool(position_profile.get("in_position", False))
            # A draw is a semi-bluff only when it has meaningful improvement
            # equity against the range that actually continues. Backdoor-only
            # texture cannot justify an otherwise unsupported pure bluff.
            if bluff_gate and candidate_draw_strength < 0.35:
                bluff_gate = _postflop_pure_bluff_allowed(
                    candidate_fold_probability,
                    required_success,
                    uncertainty_margin,
                    max(candidate_expected_callers, expected_opponents),
                    candidate_blockers["value_call_combos_blocked"],
                    candidate_blockers["bluff_call_combos_blocked"],
                    in_position=in_position,
                    range_advantage=range_advantage,
                )
            candidate_thin_value = bool(
                value_gate and has_sdv and hero_hand_category == 1
                and (
                    candidate_called_realized_equity < value_threshold + 0.085
                    or float(showdown_profile.get("margin", 0.0)) < 0.12
                )
            )
            overbet_allowed = (
                True if street == "preflop" else
                _postflop_overbet_size_allowed(
                    bet_fraction,
                    street=street,
                    range_advantage=range_advantage,
                    range_disadvantage=range_disadvantage,
                    nut_advantage=nut_advantage,
                    expected_callers=max(candidate_expected_callers, expected_opponents),
                    made_category=hero_hand_category,
                    current_equity=candidate_called_current_equity,
                    spr=spr,
                )
            )
            if not overbet_allowed:
                continue
            protection_gate = bool(
                has_sdv and not value_gate
                and to_call == 0
                and street in {"flop", "turn"}
                and hero_hand_category == 1
                and board_texture.get("wetness", 0.0) >= 0.48
                and bet_fraction <= 0.33
                and max(candidate_expected_callers, expected_opponents) <= 1.25
                and not range_disadvantage
                and candidate_called_realized_equity >= max(0.45, value_threshold - 0.09)
                and candidate_called_current_equity >= max(
                    0.39, float(showdown_profile.get("threshold", 0.55)) - 0.13
                )
                and candidate_fold_probability >= max(0.10, required_success - 0.05)
            )
            value_gate, bluff_gate = _postflop_aggression_gates(
                value_gate,
                bluff_gate,
                street=street,
                to_call=to_call,
                donk_lead=bool(board_role.get("donk_lead", False)),
                range_disadvantage=range_disadvantage,
                made_category=hero_hand_category,
                draw_strength=candidate_draw_strength,
                expected_callers=max(candidate_expected_callers, expected_opponents),
                called_equity=candidate_called_realized_equity,
                value_threshold=value_threshold,
                fold_probability=candidate_fold_probability,
                required_success=required_success,
                uncertainty_margin=uncertainty_margin,
                range_advantage=range_advantage,
                range_edge=float(board_role.get("preflop_range_edge", 0.0)),
                called_current_equity=candidate_called_current_equity,
                has_sdv=has_sdv,
                protection_gate=protection_gate,
            )
            if not _postflop_thin_value_size_allowed(
                candidate_thin_value, bet_fraction, street
            ):
                continue
            sdv_allowed = _postflop_sdv_aggression_allowed(
                has_sdv,
                str(showdown_profile.get("classification", "none")),
                street=street,
                to_call=to_call,
                bet_fraction=bet_fraction,
                made_category=hero_hand_category,
                called_current_equity=candidate_called_current_equity,
                value_threshold=value_threshold,
                expected_callers=max(candidate_expected_callers, expected_opponents),
                value_gate=value_gate,
                protection_gate=protection_gate,
                candidate_ev=raise_ev,
                passive_ev=sdv_passive_baseline_ev,
                pot=pot,
                range_disadvantage=range_disadvantage,
            )
            if not sdv_allowed:
                sdv_candidates_blocked += 1
                continue
            polar_role = _postflop_polarized_candidate_role(
                bet_fraction,
                street=street,
                value_gate=value_gate,
                bluff_gate=bluff_gate,
                has_sdv=has_sdv,
                made_category=hero_hand_category,
                current_equity=candidate_called_current_equity,
                nut_advantage=nut_advantage,
                range_advantage=range_advantage,
                range_disadvantage=range_disadvantage,
                expected_callers=max(candidate_expected_callers, expected_opponents),
                fold_probability=candidate_fold_probability,
                required_success=required_success,
                uncertainty_margin=uncertainty_margin,
                value_combos_blocked=candidate_blockers["value_call_combos_blocked"],
                bluff_combos_blocked=candidate_blockers["bluff_call_combos_blocked"],
                draw_strength=candidate_draw_strength,
                in_position=in_position,
            )
            if polar_role is None:
                continue
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
            if bool(getattr(cpu, "_vip_top_pro_mode", False)):
                # TOP PRO applies especially fine EV comparisons and a more
                # aggressive, range-aware pressure strategy.
                ev_margin = min(ev_margin, max(1, int(round(max(1, pot) * 0.001))))
            elif bool(getattr(cpu, "_vip_pro_mode", False)):
                # The standard VIP PRO tier also compares EV more tightly.
                ev_margin = min(ev_margin, max(1, int(round(max(1, pot) * 0.003))))
            action_name = "raise" if to_call else "bet"
            if (value_gate or bluff_gate) and action_name in actions:
                strategy_candidates.append((action_name, target, raise_ev))
            if (
                (value_gate or bluff_gate)
                and action_name in actions
                and raise_ev > best_ev + max(1, ev_margin)
            ):
                best_action, best_amount, best_ev = action_name, target, raise_ev
                selected_polar_role = polar_role
                selected_sdv_policy = (
                    "protection-small" if protection_gate else
                    "thin-value" if showdown_profile.get("classification") == "thin" else
                    "medium-value" if showdown_profile.get("classification") == "medium" else
                    "strong-value"
                ) if has_sdv else "not-applicable"
                fold_probability = candidate_fold_probability
                expected_callers = candidate_expected_callers
                called_equity_estimate = candidate_called_equity
                response_samples = candidate_response_samples
                raise_response_probability = candidate_raise_probability
                raise_equity_estimate = candidate_raise_equity
                required_bluff = candidate_required_bluff

    # If no call is faced, a low-EV bluff is not forced: checking remains the baseline.
    if to_call == 0 and "check" in actions and best_ev <= 0:
        best_action, best_amount, best_ev = "check", None, 0.0
    if best_action not in actions:
        best_action = _best_passive_action(actions)
        best_amount = None

    if best_action in {"bet", "raise"} and best_amount is None:
        best_action = "check" if "check" in actions else _best_passive_action(actions)

    mixed_action = False
    mixed_candidate_count = 1
    if street != "preflop" and level >= 4 and strategy_candidates:
        strategy_best_ev = max(float(item[2]) for item in strategy_candidates)
        rng = getattr(cpu, "rng", None) or random.Random()
        mixed_name, mixed_amount, mixed_action, mixed_candidate_count = (
            _sample_near_optimal_action(
                strategy_candidates,
                best_ev=strategy_best_ev,
                pot=pot,
                level=level,
                rng=rng,
            )
        )
        if mixed_name in actions:
            best_action, best_amount = mixed_name, mixed_amount
            selected_polar_role = "mixed-near-indifference"
            chosen = next((
                item for item in strategy_candidates
                if item[0] == mixed_name and item[1] == mixed_amount
            ), None)
            if chosen is not None:
                best_ev = float(chosen[2])
    if best_amount is not None:
        best_amount = max(min_target, min(max_target, int(best_amount)))
    if best_action == "allin":
        best_amount = None

    selected_size_note = (
        f"selected-size={_postflop_size_fraction(pot, best_amount - street_contribution, to_call):.0%}"
        f"{' of post-call pot' if to_call else ' of pot'}; "
        if best_amount is not None and best_action in {"bet", "raise"}
        else "selected-size=none; "
    )
    note = (
        f"{decision_name}; equity {equity:.1%}; required call {required_call:.1%}; "
        f"pure-bluff required folds {required_bluff:.1%}; estimated all-fold {fold_probability:.1%}; "
        f"expected callers {expected_callers:.2f}; equity when called {called_equity_estimate:.1%}; "
        f"estimated raise response {raise_response_probability:.1%}; "
        f"equity vs raise range {raise_equity_estimate:.1%}; "
        f"blockers value/bluff/draw={blocker_metrics['value_call_combos_blocked']:.1%}/"
        f"{blocker_metrics['bluff_call_combos_blocked']:.1%}/"
        f"{blocker_metrics['draw_call_combos_blocked']:.1%}; "
        f"ranges {len(ranges)}; total samples {samples + made_samples + response_samples}; uncertainty {uncertainty:.2f}; "
        f"policy penalty {guardrail_penalty}; EV≈{best_ev:.1f}; "
        f"current-made-equity={current_made_equity:.1%}; "
        f"equity-realization={equity_realization:.3f}; "
        f"position-known={bool(position_profile.get('known', False))}; "
        f"in-position={bool(position_profile.get('in_position', False))}; "
        f"mixed-action={mixed_action}; mixed-candidates={mixed_candidate_count}; "
        f"board-wetness={float(_postflop_board_texture(board).get('wetness', 0.0)):.2f}; "
        f"board-paired={bool(_postflop_board_texture(board).get('paired', False))}; "
        f"board-monotone={bool(_postflop_board_texture(board).get('monotone', False))}; "
        f"preflop aggressor={board_role.get('preflop_aggressor') or 'unknown'}; "
        f"range-disadvantage={bool(board_role.get('preflop_range_disadvantage', False))}; "
        f"chart-range-supported={bool(board_role.get('preflop_range_profile', {}).get('supported', False))}; "
        f"chart-range-mean-adv={float(board_role.get('preflop_range_profile', {}).get('mean_advantage', 0.0)):.3f}; "
        f"chart-range-top-adv={float(board_role.get('preflop_range_profile', {}).get('top_decile_advantage', 0.0)):.3f}; "
        f"range-advantage={bool(board_role.get('preflop_range_advantage', False))}; "
        f"range-edge={float(board_role.get('preflop_range_edge', 0.0)):.3f}; "
        f"raw-equity={equity:.1%}; realized-equity={realized_equity:.1%}; "
        f"call-realized-equity={call_equity:.1%}; call-is-all-in={call_is_all_in}; SPR={spr:.2f}; "
        f"SDV-check-EV≈{showdown_value_ev:.1f}; "
        f"SDV-profile={showdown_profile.get('classification', 'unknown')}; "
        f"SDV-current-equity={float(showdown_profile.get('current_equity', 0.0)):.1%}; "
        f"SDV-threshold={float(showdown_profile.get('threshold', 0.0)):.1%}; "
        f"SDV-supported={bool(showdown_profile.get('supported', False))}; "
        f"SDV-aggression-policy={selected_sdv_policy}; "
        f"SDV-bet-candidates-blocked={sdv_candidates_blocked}; "
        f"donk-lead={bool(board_role.get('donk_lead', False))}; "
        f"hero-made-category={hero_hand_category}; "
        f"structural-draw={hero_draw_strength:.2f}; "
        f"range-conditioned-draw={candidate_draw_strength:.2f}; "
        f"{selected_size_note}"
        f"polar-role={selected_polar_role}; "
        "source=range-aware multiway response model with GTO-style sizing and polarized-range constraints (not solver exact)"
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
