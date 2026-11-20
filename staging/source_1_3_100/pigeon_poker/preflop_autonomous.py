from __future__ import annotations

from dataclasses import dataclass
import itertools
import math
import random
from typing import Any, Callable

RANKS = "23456789TJQKA"
SUITS = ("s", "h", "d", "c")


@dataclass(frozen=True)
class AutonomousPreflopDecision:
    player_id: str
    action: str
    amount: int | None
    source: str
    equity_estimate: float
    required_call_equity: float
    required_bluff_success: float
    policy_penalty: int
    note: str = ""


def _physical_combos(hand_class: str) -> list[tuple[str, str]]:
    """Expand one 169-class hand into its physical two-card combinations."""
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
    high, low, kind = value
    if kind == "s":
        return [(high + suit, low + suit) for suit in SUITS]
    return [
        (high + first, low + second)
        for first in SUITS for second in SUITS if first != second
    ]


def _class_strength(hand_class: str) -> float:
    """Approximate preflop class ordering used only for uncovered-tree priors."""
    value = str(hand_class)
    if len(value) == 2 and value[0] == value[1] and value[0] in RANKS:
        return 0.58 + 0.40 * RANKS.index(value[0]) / 12.0
    if len(value) != 3 or value[0] not in RANKS or value[1] not in RANKS:
        return 0.0
    high, low, suited = value
    hi = RANKS.index(high)
    lo = RANKS.index(low)
    gap = hi - lo - 1
    score = 0.38 + 0.32 * hi / 12.0 + 0.18 * lo / 12.0
    score += 0.035 if suited == "s" else 0.0
    score += 0.035 if gap == 0 else 0.015 if gap == 1 else 0.0
    score -= 0.012 * max(0, gap - 2)
    # Wheel suited aces retain some blocker/bluff value in aggressive branches.
    if high == "A" and suited == "s" and low in "2345":
        score += 0.055
    return max(0.0, min(0.995, score))


def _action_range_cutoff(action: str, raises_before: int) -> float:
    """Uncovered-line prior: later raises are assigned progressively stronger ranges."""
    if action in {"allin", "all_in", "jam", "shove"}:
        return 0.90 if raises_before >= 2 else 0.82
    if action in {"raise", "bet", "raise_to", "bet_to"}:
        return {0: 0.62, 1: 0.73, 2: 0.86, 3: 0.92}.get(
            min(3, max(0, int(raises_before))), 0.94
        )
    if action in {"call", "called"}:
        return {0: 0.50, 1: 0.62, 2: 0.75, 3: 0.84}.get(
            min(3, max(0, int(raises_before))), 0.88
        )
    return 0.0


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


def _player_events(hand: Any, player_id: str) -> list[dict[str, Any]]:
    players = list(getattr(hand, "players", ()) or ())
    player = next((p for p in players if str(getattr(p, "player_id", "")) == str(player_id)), None)
    names = {str(player_id)}
    if player is not None:
        names.add(str(getattr(player, "name", "")))
    result = []
    for event in list(getattr(hand, "events", ()) or ()):
        if not isinstance(event, dict) or event.get("type") != "action":
            continue
        street = str(event.get("street", "preflop")).lower().replace("-", "")
        if street != "preflop":
            continue
        actor = str(event.get("player_id") or event.get("player") or "")
        if actor in names:
            result.append(event)
        elif player is not None and actor == str(getattr(player, "name", "")):
            result.append(event)
    return result


def _latest_unmodelled_range(hand: Any, player_id: str,
                             blockers: set[str]) -> list[tuple[tuple[str, str], float]]:
    events = _player_events(hand, player_id)
    if not events:
        return []
    latest = events[-1]
    action = _event_action(latest)
    if action not in {"raise", "allin", "call"}:
        return []
    all_actions = [
        event for event in list(getattr(hand, "events", ()) or ())
        if isinstance(event, dict) and event.get("type") == "action"
        and str(event.get("street", "preflop")).lower().replace("-", "") == "preflop"
    ]
    latest_index = next((i for i in range(len(all_actions) - 1, -1, -1)
                         if all_actions[i] is latest), -1)
    if latest_index < 0:
        # Event mappings are occasionally copied by the hand engine; use the last actor occurrence.
        actor_names = {str(player_id)}
        player = next((p for p in list(getattr(hand, "players", ()) or ())
                       if str(getattr(p, "player_id", "")) == str(player_id)), None)
        if player is not None:
            actor_names.add(str(getattr(player, "name", "")))
        latest_index = max(
            (i for i, event in enumerate(all_actions)
             if str(event.get("player_id") or event.get("player") or "") in actor_names),
            default=-1,
        )
    raises_before = sum(
        1 for event in all_actions[:max(0, latest_index)]
        if _event_action(event) in {"raise", "allin"}
    )
    cutoff = _action_range_cutoff(action, raises_before)
    weighted: list[tuple[tuple[str, str], float]] = []
    classes: list[str] = []
    for i, high in enumerate(reversed(RANKS)):
        for low in reversed(RANKS[:RANKS.index(high)]):
            classes.append(high + low + "s")
            classes.append(high + low + "o")
    classes.extend(rank + rank for rank in RANKS)
    for hand_class in classes:
        strength = _class_strength(hand_class)
        if strength <= cutoff:
            continue
        excess = (strength - cutoff) / max(0.001, 1.0 - cutoff)
        class_weight = excess ** 1.6
        if class_weight <= 0:
            continue
        combos = _physical_combos(hand_class)
        available = [combo for combo in combos if not (set(combo) & blockers)]
        if not available:
            continue
        each_weight = class_weight / len(available)
        weighted.extend((combo, each_weight) for combo in available)
    return weighted


def _weighted_class_range(probabilities: dict[str, Any],
                          blockers: set[str]) -> list[tuple[tuple[str, str], float]]:
    result: list[tuple[tuple[str, str], float]] = []
    for hand_class, probability in probabilities.items():
        try:
            class_weight = max(0.0, float(probability))
        except (TypeError, ValueError):
            continue
        if class_weight <= 0:
            continue
        combos = [
            combo for combo in _physical_combos(str(hand_class))
            if not (set(combo) & blockers)
        ]
        if not combos:
            continue
        each_weight = class_weight / len(combos)
        result.extend((combo, each_weight) for combo in combos)
    return result


def deck_for_uniform() -> list[str]:
    return [rank + suit for suit in SUITS for rank in RANKS]


def _weighted_pick(options: list[tuple[tuple[str, str], float]],
                   blocked: set[str], rng: Any) -> tuple[str, str] | None:
    available = [
        (cards, weight) for cards, weight in options
        if cards[0] not in blocked and cards[1] not in blocked and weight > 0
    ]
    if not available:
        return None
    total = sum(weight for _, weight in available)
    if total <= 0:
        return None
    target = float(rng.random()) * total
    for cards, weight in available:
        target -= weight
        if target <= 0:
            return cards
    return available[-1][0]


def _range_weighted_equity(table: Any, hand: Any, actor_id: str, cpu: Any,
                           range_estimator: Callable[..., dict[str, Any]],
                           evaluate_seven: Callable[[list[str]], Any],
                           make_deck: Callable[[], list[str]]) -> tuple[float, int, int]:
    actor = hand.player(actor_id)
    hero_cards = [str(card) for card in list(getattr(actor, "hole_cards", ()) or ())]
    board = [str(card) for card in list(getattr(hand, "board", ()) or ())]
    if len(hero_cards) != 2 or len(set(hero_cards + board)) != len(hero_cards + board):
        raise ValueError("Hero cards or board are unavailable for range equity")
    blockers = set(hero_cards + board)
    active_opponents = [
        player for player in list(getattr(hand, "players", ()) or ())
        if str(getattr(player, "player_id", "")) != str(actor_id)
        and bool(getattr(player, "eligible", False))
    ]
    if not active_opponents:
        return 1.0, 0, 0

    estimate = range_estimator(table=table, hand=hand, exclude_player_id=actor_id)
    rows = estimate.get("players", {}) if isinstance(estimate, dict) else {}
    active_with_history = [
        player for player in active_opponents
        if _player_events(hand, str(getattr(player, "player_id", "")))
    ]
    if not active_with_history:
        # No opponent has shown a voluntary action: use a full-deck prior.
        active_with_history = active_opponents

    opponent_options: list[list[tuple[tuple[str, str], float]]] = []
    for player in active_with_history:
        pid = str(getattr(player, "player_id", ""))
        row = rows.get(pid, {}) if isinstance(rows, dict) else {}
        options: list[tuple[tuple[str, str], float]] = []
        if isinstance(row, dict) and row.get("supported") and isinstance(
            row.get("hand_class_probabilities"), dict
        ):
            options = _weighted_class_range(row["hand_class_probabilities"], blockers)
        if not options:
            options = _latest_unmodelled_range(hand, pid, blockers)
        if not options:
            # A player with no usable action model receives a uniform physical-combo prior.
            options = [
                (tuple(cards), 1.0)
                for cards in itertools.combinations(
                    [card for card in deck_for_uniform() if card not in blockers], 2
                )
            ]
        if options:
            opponent_options.append(options)

    if not opponent_options:
        return 0.0, 0, 0

    rng = getattr(cpu, "rng", None)
    if rng is None or not hasattr(rng, "random"):
        rng = random.Random()
    base_runs = max(64, int(getattr(cpu, "simulations", 72) or 72))
    runs = max(256, min(1400, base_runs * 4))
    deck = [str(card) for card in make_deck()]
    remaining_board_cards = 5 - len(board)
    if remaining_board_cards < 0:
        raise ValueError("Board contains more than five cards")
    wins = 0.0
    completed = 0
    for _ in range(runs):
        used = set(blockers)
        opponent_hands: list[tuple[str, str]] = []
        for options in opponent_options:
            cards = _weighted_pick(options, used, rng)
            if cards is None:
                available = [card for card in deck if card not in used]
                if len(available) < 2:
                    break
                cards = tuple(rng.sample(available, 2))
            opponent_hands.append(cards)
            used.update(cards)
        if len(opponent_hands) != len(opponent_options):
            continue
        available_board = [card for card in deck if card not in used]
        if len(available_board) < remaining_board_cards:
            continue
        final_board = board + (rng.sample(available_board, remaining_board_cards)
                               if remaining_board_cards else [])
        hero_rank = evaluate_seven(hero_cards + final_board)
        ranks = [evaluate_seven(list(cards) + final_board) for cards in opponent_hands]
        best = max([hero_rank] + ranks)
        winners = 1 + sum(1 for rank in ranks if rank == best) if hero_rank == best else sum(
            1 for rank in ranks if rank == best
        )
        if hero_rank == best:
            wins += 1.0 / max(1, winners)
        completed += 1
    if completed <= 0:
        raise RuntimeError("No range-equity simulations completed")
    return wins / completed, completed, len(opponent_options)


def choose_uncovered_preflop_action(
    table: Any,
    hand: Any,
    actor_id: str,
    cpu: Any,
    range_estimator: Callable[..., dict[str, Any]],
    evaluate_seven: Callable[[list[str]], Any],
    make_deck: Callable[[], list[str]],
) -> AutonomousPreflopDecision:
    """Autonomous, range-aware policy for preflop branches absent from the fixed chart.

    This function never changes the screenshot chart. It is called only when no
    fixed 75-node decision is available (for example, a multiway 3-bet branch).
    """
    legal = hand.legal_actions(actor_id)
    legal_actions = {
        str(value).lower().replace("-", "_") for value in legal.get("actions", ())
    }
    if not legal_actions:
        raise ValueError("No legal preflop action is available")
    player = hand.player(actor_id)
    to_call = max(0, int(legal.get("to_call", 0) or 0))
    pot = max(0, int(getattr(hand, "pot", 0) or 0))
    pot_odds = to_call / max(1, pot + to_call)
    level = min(5, max(1, int(getattr(cpu, "level", 3) or 3)))
    level_margin = {1: 0.10, 2: 0.07, 3: 0.045, 4: 0.02, 5: 0.0}[level]
    archetype = str(getattr(cpu, "archetype", "balanced") or "balanced").lower()
    aggression = {1: 0.18, 2: 0.28, 3: 0.40, 4: 0.54, 5: 0.66}[level]
    aggression += {
        "aggressive": 0.18,
        "calling_station": -0.22,
        "overfolder": -0.12,
        "underbluffer": -0.10,
        "balanced": 0.0,
    }.get(archetype, 0.0)
    aggression = max(0.05, min(0.90, aggression))
    rng = getattr(cpu, "rng", None)
    if rng is None or not hasattr(rng, "random"):
        rng = random.Random()
    equity, runs, ranged_opponents = _range_weighted_equity(
        table, hand, actor_id, cpu, range_estimator, evaluate_seven, make_deck
    )

    # The chart intentionally has no multiway branch. The uncertainty score
    # increases the decision margin and reduces speculative aggression, but
    # never suspends the hand or changes any covered chart action.
    range_result = range_estimator(
        table=table, hand=hand, exclude_player_id=actor_id
    )
    rows = range_result.get("players", {}) if isinstance(range_result, dict) else {}
    unknown_rows = sum(
        1 for row in rows.values()
        if isinstance(row, dict) and row.get("supported") is False
    )
    penalty = min(85, 25 + 10 * unknown_rows + (15 if not range_result.get("supported", False) else 0))
    uncertainty_margin = penalty / 1000.0
    unacted_count = max(
        0,
        sum(1 for p in list(getattr(hand, "players", ()) or ())
            if bool(getattr(p, "eligible", False))
            and str(getattr(p, "player_id", "")) != str(actor_id))
        - ranged_opponents,
    )
    required_call = min(0.98, pot_odds + level_margin + uncertainty_margin
                        + min(0.06, 0.012 * unacted_count))

    max_target = int(legal.get("max_target", 0) or 0)
    min_target = int(legal.get("min_target", 0) or 0)
    current_bet = int(getattr(hand, "current_bet", 0) or 0)
    street_contribution = int(getattr(player, "street_contribution", 0) or 0)
    can_raise = bool(legal.get("raise_allowed")) and (
        "raise" in legal_actions or "bet" in legal_actions
    )

    chosen_action = "fold"
    chosen_amount: int | None = None
    if to_call > 0:
        if equity + 1e-9 < required_call and "fold" in legal_actions:
            chosen_action = "fold"
        else:
            raise_threshold = max(0.56, required_call + 0.16 + uncertainty_margin)
            value_edge = equity >= raise_threshold
            if can_raise and value_edge and rng.random() < aggression:
                try:
                    dealer = int(getattr(table, "dealer_index", getattr(hand, "dealer_index", 0)))
                    actor_index = int(getattr(hand, "seat_by_id", {}).get(actor_id, 0))
                    position_from_button = (actor_index - dealer) % max(
                        1, len(getattr(hand, "players", ()) or ())
                    )
                except (TypeError, ValueError, ZeroDivisionError):
                    position_from_button = 3
                multiplier = 2.20 if position_from_button <= 3 else 2.45
                desired = max(min_target, int(round(max(1, current_bet) * multiplier)))
                desired = min(desired, max_target)
                if desired >= max_target and "all_in" in legal_actions:
                    chosen_action = "all-in"
                elif desired > current_bet and (
                    "raise" in legal_actions or "bet" in legal_actions
                ):
                    chosen_action = "raise" if "raise" in legal_actions else "bet"
                    chosen_amount = desired
                else:
                    chosen_action = "call" if "call" in legal_actions else "fold"
            else:
                chosen_action = "call" if "call" in legal_actions else (
                    "check" if "check" in legal_actions else "fold"
                )
    else:
        if "check" in legal_actions:
            raise_threshold = max(0.84, 0.88 + uncertainty_margin)
            if can_raise and equity >= raise_threshold and rng.random() < aggression * 0.55:
                desired = max(min_target, int(round(max(1, pot) * 0.55)) + street_contribution)
                desired = min(desired, max_target)
                if desired >= max_target and "all_in" in legal_actions:
                    chosen_action = "all-in"
                elif desired > current_bet and "raise" in legal_actions:
                    chosen_action = "raise"
                    chosen_amount = desired
                else:
                    chosen_action = "check"
            else:
                chosen_action = "check"
        elif "call" in legal_actions:
            chosen_action = "call"
        elif "fold" in legal_actions:
            chosen_action = "fold"
        else:
            chosen_action = next(iter(legal_actions))

    # A pure bluff needs folds at least this often to break even. This is
    # reported for the chosen raise-size decision even when the raise is value-led.
    risk = (max(0, int(chosen_amount) - street_contribution)
            if chosen_amount is not None else
            max(0, max_target - street_contribution) if chosen_action == "all-in"
            else to_call)
    required_bluff = risk / max(1, pot + risk)
    note = (
        "range-weighted equity={:.1f}%; call threshold={:.1f}%; "
        "pure-bluff break-even fold rate={:.1f}%; samples={}; modeled opponents={}; "
        "uncertainty penalty={}"
    ).format(equity * 100.0, required_call * 100.0, required_bluff * 100.0,
             runs, ranged_opponents, penalty)
    return AutonomousPreflopDecision(
        player_id=str(actor_id),
        action=chosen_action,
        amount=chosen_amount,
        source="preflop-autonomous",
        equity_estimate=equity,
        required_call_equity=required_call,
        required_bluff_success=required_bluff,
        policy_penalty=penalty,
        note=note,
    )
