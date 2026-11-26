from __future__ import annotations

import math
import random
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from .preflop_174_policy_data import load_preflop_174_data

POSITIONS = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
POSITION_BY_SEAT_FROM_BUTTON = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
RANKS = "AKQJT98765432"
_HAND_ORDER = tuple(load_preflop_174_data()["hand_order"])
_HAND_INDEX = {value: index for index, value in enumerate(_HAND_ORDER)}


@lru_cache(maxsize=1)
def _scenarios() -> tuple[dict[str, Any], ...]:
    return tuple(load_preflop_174_data()["scenarios"])


def _normalise_action(value: Any) -> str:
    action = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if action in {"call", "called", "all_in_call", "allin_call", "call_all_in", "limp", "complete"}:
        return "call"
    if action in {"allin", "all_in", "shove", "jam"}:
        return "allin"
    if action in {"fold", "folded", "muck"}:
        return "fold"
    if action in {"raise", "bet", "raise_to", "bet_to", "open", "3bet", "4bet", "squeeze"}:
        return "raise"
    if action == "check":
        return "check"
    return action


def _event_action(event: dict[str, Any]) -> str:
    raw = str(event.get("action", "")).strip().lower().replace("-", "_").replace(" ", "_")
    # A short all-in call remains a call for the action-history match.
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
    return _normalise_action(raw)


def _position_map(table: Any, hand: Any) -> dict[str, str]:
    players = list(getattr(hand, "players", ()) or ())
    if len(players) == 6:
        dealer = getattr(table, "dealer_index", None)
        if dealer is None:
            dealer = getattr(hand, "dealer_index", None)
        try:
            dealer = int(dealer) % 6
        except (TypeError, ValueError, OverflowError):
            dealer = None
        if dealer is not None:
            seat_by_id = getattr(hand, "seat_by_id", {}) or {}
            result: dict[str, str] = {}
            for index, player in enumerate(players):
                pid = str(getattr(player, "player_id", ""))
                if not pid:
                    continue
                try:
                    seat = int(seat_by_id[pid]) % 6 if isinstance(seat_by_id, dict) and pid in seat_by_id else index
                except (TypeError, ValueError, OverflowError):
                    continue
                result[pid] = POSITION_BY_SEAT_FROM_BUTTON[(seat - dealer) % 6]
            if len(result) == 6:
                return result
    result = {}
    for player in players:
        pid = str(getattr(player, "player_id", ""))
        position = str(getattr(player, "position", "")).upper()
        if pid and position in POSITIONS:
            result[pid] = position
    return result


def _big_blind(hand: Any, table: Any = None) -> int:
    for obj in (hand, table):
        if obj is None:
            continue
        for name in ("big_blind", "big_blind_amount", "bb_amount"):
            try:
                value = int(getattr(obj, name, 0) or 0)
            except (TypeError, ValueError, OverflowError):
                continue
            if value > 0:
                return value
    return 100


def _event_target_bb(event: dict[str, Any], bb: int) -> float | None:
    for key in ("target", "raise_to", "to_amount", "total_contribution", "target_amount"):
        value = event.get(key)
        if value is None:
            continue
        try:
            amount = float(value) / max(1, bb)
            if math.isfinite(amount):
                return max(0.0, amount)
        except (TypeError, ValueError, OverflowError):
            pass
    for key in ("amount", "paid"):
        value = event.get(key)
        if value is None:
            continue
        try:
            amount = float(value) / max(1, bb)
            if math.isfinite(amount):
                return max(0.0, amount)
        except (TypeError, ValueError, OverflowError):
            pass
    return None


def _actual_history(table: Any, hand: Any, player_id: str, positions: dict[str, str]) -> list[dict[str, Any]]:
    players = list(getattr(hand, "players", ()) or ())
    id_by_name = {
        str(getattr(player, "name", "")): str(getattr(player, "player_id", ""))
        for player in players if str(getattr(player, "name", ""))
    }
    bb = _big_blind(hand, table)
    output: list[dict[str, Any]] = []
    for event in list(getattr(hand, "events", ()) or ()):
        if not isinstance(event, dict):
            continue
        street = str(event.get("street", "preflop")).lower().replace("-", "")
        if street not in {"preflop", "pre"}:
            continue
        if event.get("type") not in {None, "action"} and not event.get("action"):
            continue
        action = _event_action(event) if event.get("action") else _normalise_action(event.get("decision"))
        if action not in {"fold", "call", "check", "raise", "allin"}:
            continue
        raw_pid = str(event.get("player_id") or event.get("player") or "")
        pid = raw_pid if raw_pid in positions else id_by_name.get(raw_pid, raw_pid)
        position = positions.get(pid) or str(event.get("position", "")).upper()
        if position not in POSITIONS:
            continue
        amount_bb = _event_target_bb(event, bb) if action in {"raise", "allin"} else None
        output.append({"position": position, "action": action, "size_bb": amount_bb})

    # The 174 first-in charts (UTG/HJ/CO/BTN/SB) encode the folded-to-me
    # prefix implicitly as an empty history. A live hand records those folds
    # as events. Treat a prefix made exclusively of folds as the same source
    # state; otherwise the lookup falls through to an unrelated nearest node.
    if output and all(item["action"] == "fold" for item in output):
        return []
    return output


def _size_matches(expected: Any, actual: Any) -> bool:
    if expected is None:
        return True
    if actual is None:
        return False
    try:
        e, a = float(expected), float(actual)
    except (TypeError, ValueError, OverflowError):
        return False
    if not math.isfinite(e) or not math.isfinite(a):
        return False
    return abs(e - a) <= max(0.12, abs(e) * 0.04)


def _event_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if str(expected.get("position", "")).upper() != actual["position"]:
        return False
    action = _normalise_action(expected.get("action"))
    if action != actual["action"]:
        return False
    if action in {"raise", "allin"}:
        return _size_matches(expected.get("size_bb"), actual.get("size_bb"))
    return True


def _event_cost(expected: dict[str, Any], actual: dict[str, Any]) -> float:
    ep, ap = str(expected.get("position", "")).upper(), actual["position"]
    ea, aa = _normalise_action(expected.get("action")), actual["action"]
    if ep == ap and ea == aa:
        if ea in {"raise", "allin"}:
            es, ass = expected.get("size_bb"), actual.get("size_bb")
            if es is None or ass is None:
                return 0.25
            try:
                return min(2.5, abs(float(es) - float(ass)) / max(1.0, abs(float(es)) * 0.12))
            except (TypeError, ValueError, OverflowError):
                return 0.8
        return 0.0
    if ea == aa:
        return 1.5 if ep != ap else 1.2
    return 2.2 if ep == ap else 2.8


def _history_distance(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> float:
    # Ordered edit distance: folds, calls, re-raises and repeated decisions all matter.
    prev = [float(i) for i in range(len(actual) + 1)]
    for i, want in enumerate(expected, 1):
        cur = [float(i)]
        for j, got in enumerate(actual, 1):
            cur.append(min(
                prev[j] + 1.15,
                cur[j - 1] + 1.15,
                prev[j - 1] + _event_cost(want, got),
            ))
        prev = cur
    return prev[-1] / max(1, len(expected), len(actual))


def _hand_class(cards: Any) -> str | None:
    try:
        items = [str(card).strip() for card in list(cards or ())]
    except Exception:
        return None
    if len(items) != 2:
        return None
    suits = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}
    parsed = []
    for card in items:
        rank = card[:-1].upper() if len(card) >= 2 else ""
        suit = card[-1:] if card else ""
        if rank == "10":
            rank = "T"
        if rank not in RANKS:
            return None
        parsed.append((rank, suits.get(suit, suit.lower())))
    r1, s1 = parsed[0]
    r2, s2 = parsed[1]
    if r1 == r2:
        result = r1 + r2
    else:
        i1, i2 = RANKS.index(r1), RANKS.index(r2)
        high, low = (r1, r2) if i1 < i2 else (r2, r1)
        result = high + low + ("s" if s1 == s2 else "o")
    return result if result in _HAND_INDEX else None


def _hand_distance(a: str, b: str) -> float:
    def feats(value: str) -> tuple[int, int, int, int]:
        if len(value) == 2:
            idx = RANKS.index(value[0])
            return idx, idx, 1, 0
        high, low = value[:2]
        return RANKS.index(high), RANKS.index(low), 0, int(value.endswith("s"))
    ah, al, ap, ass = feats(a)
    bh, bl, bp, bss = feats(b)
    return abs(ah - bh) * 0.9 + abs(al - bl) * 1.1 + (1.15 if ap != bp else 0.0) + (0.65 if not ap and not bp and ass != bss else 0.0)


def _decode_hand_actions(scenario: dict[str, Any], hand_index: int) -> dict[tuple[str, float | None], float]:
    row = scenario["hands"][hand_index]
    options = scenario["action_options"]
    output: dict[tuple[str, float | None], float] = {}
    for option_index, frequency in row:
        action, size = options[int(option_index)]
        key = (str(action), None if size is None else float(size))
        output[key] = output.get(key, 0.0) + float(frequency)
    return output


def _normalise_distribution(values: dict[tuple[str, float | None], float]) -> dict[tuple[str, float | None], float]:
    total = sum(max(0.0, float(x)) for x in values.values())
    if total <= 0:
        return {}
    return {k: max(0.0, float(v)) / total for k, v in values.items() if v > 0}


def _infer_hand_distribution(scenario: dict[str, Any], hand_class: str) -> tuple[dict[tuple[str, float | None], float], str]:
    # Missing/grey cells in the source screenshots are never silently treated as folds.
    # Extrapolate only from measured hand classes in the same scenario, by rank/suitedness.
    candidates = []
    for index, row in enumerate(scenario["hands"]):
        if not row:
            continue
        other = _HAND_ORDER[index]
        distance = _hand_distance(hand_class, other)
        candidates.append((distance, index))
    if not candidates:
        return {}, "no-measured-hand-neighbour"
    candidates.sort(key=lambda item: item[0])
    nearest = candidates[:12]
    aggregate: dict[tuple[str, float | None], float] = {}
    for distance, index in nearest:
        weight = 1.0 / ((0.45 + distance) ** 2)
        for key, frequency in _decode_hand_actions(scenario, index).items():
            aggregate[key] = aggregate.get(key, 0.0) + weight * frequency
    return _normalise_distribution(aggregate), "same-scenario-hand-neighbours"


def _scenario_distribution(scenario: dict[str, Any], hand_class: str) -> tuple[dict[tuple[str, float | None], float], bool, str]:
    index = _HAND_INDEX[hand_class]
    if scenario["hands"][index]:
        return _normalise_distribution(_decode_hand_actions(scenario, index)), False, "measured-image-cell"
    # A blank/grey source cell is not a measured frequency distribution.
    # Never fabricate a hand strategy from neighbouring cells or scenario totals.
    return {}, True, "unmeasured-image-cell"


def _scenario_strategy_signature(scenario: dict[str, Any]) -> tuple[Any, ...]:
    """Canonicalise the full 169-cell action matrix, independent of option ordering."""
    rows = []
    for index, row in enumerate(scenario.get("hands", ())):
        decoded = _decode_hand_actions(scenario, index) if row else {}
        entries = [
            (
                str(action),
                None if size is None else round(float(size), 6),
                round(float(frequency), 8),
            )
            for (action, size), frequency in decoded.items()
        ]
        rows.append(tuple(sorted(entries, key=repr)))
    return tuple(rows)


def _choose_scenario(
    actor_position: str,
    actual_history: list[dict[str, Any]],
    rng: Any = None,
) -> tuple[dict[str, Any] | None, bool, float]:
    """Select only an exact ordered action-history match; never borrow a nearby node."""
    exact = [
        scenario for scenario in _scenarios()
        if scenario["position"] == actor_position
        and len(scenario["history"]) == len(actual_history)
        and all(
            _event_matches(want, got)
            for want, got in zip(scenario["history"], actual_history)
        )
    ]
    if not exact:
        return None, True, math.inf
    if len(exact) == 1:
        return exact[0], False, 0.0

    signatures = {_scenario_strategy_signature(item) for item in exact}
    if len(signatures) != 1:
        # Same action history with different strategy data is ambiguous.
        return None, True, math.inf
    canonical = min(exact, key=lambda item: int(item["id"]))
    return canonical, False, 0.0



def _strict_range_history_matches(
    expected_history: list[dict[str, Any]],
    actual_history: list[dict[str, Any]],
) -> bool:
    """Match a paid range image only when every action and raise size is known."""
    if len(expected_history) != len(actual_history):
        return False
    for expected, actual in zip(expected_history, actual_history):
        if str(expected.get("position", "")).upper() != str(actual.get("position", "")).upper():
            return False
        action = _normalise_action(expected.get("action"))
        if action != _normalise_action(actual.get("action")):
            return False
        if action == "raise":
            # A missing raise size could select a different paid source chart.
            if expected.get("size_bb") is None or actual.get("size_bb") is None:
                return False
            if not _size_matches(expected.get("size_bb"), actual.get("size_bb")):
                return False
        # All-in is an action class here. Some source histories do not record
        # a target size for the shove, so never reject them only for that.
    return True


def find_exact_preflop_174_scenario_candidates(
    actor_position: str,
    actual_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return every strictly exact source node for later live-state disambiguation."""
    actor = str(actor_position or "").upper()
    if actor not in POSITIONS:
        return []
    return [
        scenario for scenario in _scenarios()
        if str(scenario.get("position", "")).upper() == actor
        and _strict_range_history_matches(list(scenario.get("history", []) or []), actual_history)
    ]


def find_exact_preflop_174_scenario(
    actor_position: str,
    actual_history: list[dict[str, Any]],
) -> int | None:
    """Return a unique exact source-image ID; never use nearest-node inference."""
    matches = find_exact_preflop_174_scenario_candidates(actor_position, actual_history)
    if len(matches) != 1:
        return None
    try:
        return int(matches[0]["id"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


# Two source nodes explicitly distinguish whether BTN was already all-in.
# Their visible action histories and available decision labels are otherwise
# identical, so the live all-in state is required for safe paid-image lookup.
PAID_RANGE_ALL_IN_POSITION_REQUIREMENTS = {
    252: frozenset({"CO"}),
    253: frozenset({"CO", "BTN"}),
}


def exact_preflop_174_source_candidates(
    table: Any,
    hand: Any,
    player_id: str,
) -> tuple[str | None, dict[str, str], list[dict[str, Any]]]:
    """Return exact history candidates plus live seat-position mapping."""
    if str(getattr(hand, "next_to_act", "") or "") != str(player_id):
        return None, {}, []
    positions = _position_map(table, hand)
    actor_position = positions.get(str(player_id))
    if actor_position not in POSITIONS:
        return None, positions, []
    actual_history = _actual_history(table, hand, str(player_id), positions)
    return (
        actor_position,
        positions,
        find_exact_preflop_174_scenario_candidates(actor_position, actual_history),
    )


def exact_preflop_174_source_image(
    table: Any,
    hand: Any,
    player_id: str,
) -> int | None:
    """Resolve the actor's exact 174-node image for a live decision."""
    if str(getattr(hand, "next_to_act", "") or "") != str(player_id):
        return None
    positions = _position_map(table, hand)
    actor_position = positions.get(str(player_id))
    if actor_position not in POSITIONS:
        return None
    actual_history = _actual_history(table, hand, str(player_id), positions)
    return find_exact_preflop_174_scenario(actor_position, actual_history)

def exact_preflop_174_source_image_for_hero(table: Any, hand: Any) -> int | None:
    """Convenience wrapper for the live cash-table hero."""
    return exact_preflop_174_source_image(table, hand, "hero")

def _legal_actions(legal: dict[str, Any]) -> set[str]:
    return {_normalise_action(value) for value in legal.get("actions", ())}


def _legal_choices(hand: Any, player_id: str, distribution: dict[tuple[str, float | None], float], bb: int) -> list[dict[str, Any]]:
    legal = hand.legal_actions(player_id)
    legal_actions = _legal_actions(legal)
    to_call = max(0, int(legal.get("to_call", 0) or 0))
    can_raise = bool(legal.get("raise_allowed", True)) and "raise" in legal_actions
    min_target = int(legal.get("min_target", 0) or 0)
    max_target = int(legal.get("max_target", 0) or 0)
    output = []
    for (action, size_bb), frequency in distribution.items():
        if frequency <= 0:
            continue
        if action == "raise":
            if not can_raise or size_bb is None:
                continue
            target = int(round(float(size_bb) * bb))
            if target < max(1, min_target) or (max_target > 0 and target > max_target):
                continue
            output.append({"action": "raise", "amount": target, "frequency": frequency, "size_bb": float(size_bb)})
        elif action == "allin":
            if "allin" in legal_actions:
                output.append({"action": "all_in", "amount": None, "frequency": frequency, "size_bb": size_bb})
            elif can_raise and max_target > 0:
                output.append({"action": "raise", "amount": max_target, "frequency": frequency, "size_bb": max_target / max(1, bb)})
        elif action == "call":
            if to_call > 0 and "call" in legal_actions:
                output.append({"action": "call", "amount": None, "frequency": frequency, "size_bb": None})
            elif to_call == 0 and "check" in legal_actions:
                output.append({"action": "check", "amount": None, "frequency": frequency, "size_bb": None})
        elif action == "check" and to_call == 0 and "check" in legal_actions:
            output.append({"action": "check", "amount": None, "frequency": frequency, "size_bb": None})
        elif action == "fold" and "fold" in legal_actions:
            output.append({"action": "fold", "amount": None, "frequency": frequency, "size_bb": None})
    return output


def _filter_first_in_distribution(
    actor_position: str,
    actual_history: list[dict[str, Any]],
    distribution: dict[tuple[str, float | None], float],
) -> dict[tuple[str, float | None], float]:
    """Enforce the source-backed first-in invariants on inferred nodes too.

    UTG/HJ/CO/BTN have no open-limp branch in the 174 source charts. First-in
    opens are small raises, not oversized 20+ BB raises. SB completion remains
    available because the SB source node explicitly contains CALL.
    """
    if actual_history:
        return distribution
    actor = str(actor_position or "").upper()
    output = {}
    for (action, size_bb), frequency in distribution.items():
        if action == "call" and actor in {"UTG", "HJ", "CO", "BTN"}:
            continue
        if action == "raise" and (
            size_bb is None or float(size_bb) > 5.0
        ):
            continue
        output[(action, size_bb)] = float(frequency)
    return output


def _select_live_scenario(
    table: Any,
    hand: Any,
    player_id: str,
    actor_position: str,
    actual_history: list[dict[str, Any]],
    rng: Any,
) -> tuple[dict[str, Any], bool, float]:
    """Use the exact same source node as the paid range viewer when possible."""
    try:
        if str(getattr(hand, "next_to_act", "") or "") == str(player_id):
            # Runtime import avoids a module cycle: range_scenario_resolver
            # itself imports this policy module's exact-history helpers.
            from .range_scenario_resolver import resolve_range_image_for_hand

            chart = resolve_range_image_for_hand(table, hand, player_id)
            if chart is not None:
                source_id = int(chart["source_id"])
                selected = next(
                    (item for item in _scenarios() if int(item["id"]) == source_id),
                    None,
                )
                if selected is not None:
                    if chart.get("raise_size_verified") is False:
                        # The ordered actor/action history is exact, but the
                        # runtime event omitted a raise-to amount. Keep this
                        # distinct from nearest-node inference in the decision
                        # metadata so neither BOT nor UI claims a fully exact
                        # size match.
                        return selected, True, -1.0
                    return selected, False, 0.0
    except (KeyError, TypeError, ValueError, AttributeError, RuntimeError):
        # A failed exact resolver must not be replaced by a fuzzy nearest node.
        pass
    return None, True, math.inf


def _safe_legal_fallback(
    player_id: str,
    legal: dict[str, Any],
    hand_class: str,
    scenario_id: int | None,
    *,
    scenario_inferred: bool = False,
    distance: float = 0.0,
) -> SimpleNamespace:
    """Take a legal safety action without losing the selected 174 source ID."""
    available = _legal_actions(legal)
    to_call = max(0, int(legal.get("to_call", 0) or 0))
    if "check" in available and to_call == 0:
        action, amount = "check", None
    elif "fold" in available and to_call > 0:
        action, amount = "fold", None
    elif "call" in available:
        action, amount = "call", None
    elif "fold" in available:
        action, amount = "fold", None
    elif "check" in available:
        action, amount = "check", None
    elif "raise" in available and int(legal.get("min_target", 0) or 0) > 0:
        action, amount = "raise", int(legal["min_target"])
    else:
        raise RuntimeError("No legal preflop action is available")
    return SimpleNamespace(
        player_id=str(player_id), action=action, amount=amount,
        source=(
            "preflop-174-legal-guardrail" if scenario_id is not None
            else "preflop-uncovered-legal-guardrail"
        ),
        node_id=(
            f"174_IMAGE_{int(scenario_id)}" if scenario_id is not None
            else "UNMAPPED_PREFLOP_HISTORY"
        ),
        source_image_no=None if scenario_id is None else int(scenario_id),
        hand_class=hand_class, action_frequency=1.0,
        inferred=bool(scenario_inferred), scenario_match_mode=(
            "exact" if not scenario_inferred
            else "actions-size-unverified" if distance < 0
            else "nearest-inferred"
        ),
        action_size_bb=None, size_source="legal-guardrail",
        note=(
            (
                f"174-scenario #{int(scenario_id)}; no measured action was available "
                "for this hand in the matched source cell; legal guardrail used."
            ) if scenario_id is not None else
            "No exact 174-scenario action history matched; no unrelated range was borrowed. "
            "A conservative legal-action guardrail was used."
        ),
    )


def choose_preflop_174_action(
    table: Any,
    hand: Any,
    player_id: str,
    cpu: Any,
    *,
    range_estimator: Any = None,
) -> SimpleNamespace:
    """Select a legal preflop action from exact 174 source scenarios.

    Every CPU uses this same chart-derived preflop policy. CPU level/archetype is not
    consulted. Postflop behaviour remains in poker_reasoning.py and is not changed here.
    """
    legal = hand.legal_actions(player_id)
    if not legal.get("actions"):
        raise ValueError("No legal preflop action is available")
    positions = _position_map(table, hand)
    actor_position = positions.get(str(player_id))
    if actor_position not in POSITIONS:
        raise RuntimeError(f"Cannot resolve six-max actor position for {player_id}")
    actual_history = _actual_history(table, hand, player_id, positions)
    rng = getattr(cpu, "rng", None) or random.Random()
    scenario, scenario_inferred, distance = _select_live_scenario(
        table, hand, player_id, actor_position, actual_history, rng
    )
    player = hand.player(player_id)
    hand_class = _hand_class(getattr(player, "hole_cards", ()))
    if hand_class is None:
        raise RuntimeError("CPU hole cards could not be mapped to a 169-class hand")

    def uncovered_fallback(reason: str) -> SimpleNamespace:
        if callable(range_estimator):
            try:
                # Uncovered histories/cells use the independent range-aware
                # policy, never a guessed 174 node or a neighbouring hand cell.
                from .poker_reasoning import choose_range_aware_action

                fallback = choose_range_aware_action(
                    table, hand, player_id, cpu, range_estimator=range_estimator
                )
                return SimpleNamespace(
                    player_id=str(player_id),
                    action=str(fallback.action),
                    amount=fallback.amount,
                    source="preflop-uncovered-range-aware-fallback",
                    node_id="UNMAPPED_PREFLOP_HISTORY",
                    source_image_no=None,
                    hand_class=hand_class,
                    action_frequency=0.0,
                    inferred=True,
                    scenario_match_mode="unsupported",
                    size_source="range-aware-fallback",
                    note=(
                        f"{reason}; no 174 chart was borrowed. "
                        f"Independent range policy: {getattr(fallback, 'note', '')}"
                    ),
                    equity_estimate=getattr(fallback, "equity_estimate", None),
                )
            except Exception:
                pass
        return _safe_legal_fallback(
            player_id, legal, hand_class,
            None if scenario is None else int(scenario["id"]),
            scenario_inferred=scenario_inferred, distance=distance,
        )

    if scenario is None:
        return uncovered_fallback(
            "No exact 174-scenario action history (including known raise sizes) matched"
        )

    distribution, hand_inferred, hand_method = _scenario_distribution(scenario, hand_class)
    if not distribution:
        return uncovered_fallback(
            f"174-scenario #{int(scenario['id'])} has no measured cell for {hand_class}"
        )
    distribution = _filter_first_in_distribution(actor_position, actual_history, distribution)
    bb = _big_blind(hand, table)
    choices = _legal_choices(hand, player_id, distribution, bb)
    if not choices:
        return _safe_legal_fallback(
            player_id, legal, hand_class, int(scenario["id"]),
            scenario_inferred=scenario_inferred, distance=distance,
        )
    total = sum(item["frequency"] for item in choices)
    if total <= 0:
        return _safe_legal_fallback(
            player_id, legal, hand_class, int(scenario["id"]),
            scenario_inferred=scenario_inferred, distance=distance,
        )
    pick = float(rng.random()) * total
    chosen = choices[-1]
    for item in choices:
        pick -= item["frequency"]
        if pick <= 0:
            chosen = item
            break
    exact = not scenario_inferred
    inferred = bool(scenario_inferred or hand_inferred)
    source_image = int(scenario["id"])
    if exact:
        match_label = "exact"
    elif scenario_inferred and distance < 0:
        match_label = "exact-action-history; live raise size unavailable"
    else:
        match_label = f"nearest-inferred distance={distance:.3f}"
    note = (f"174-scenario #{source_image} ({match_label}); {hand_method}; "
            "hand frequencies estimated from source-image colour proportions.")
    return SimpleNamespace(
        player_id=str(player_id), action=chosen["action"], amount=chosen["amount"],
        source="preflop-174-scenario-policy", node_id=f"174_IMAGE_{source_image}",
        hand_class=hand_class, action_frequency=float(chosen["frequency"]) / total,
        inferred=inferred,
        size_source="174-image-exact" if not inferred else "174-image-inference",
        note=note, source_image_no=source_image,
        scenario_match_mode=(
            "exact" if exact
            else "actions-size-unverified" if scenario_inferred and distance < 0
            else "nearest-inferred"
        ),
        action_size_bb=chosen.get("size_bb"),
        hand_inference_method=hand_method,
    )



def preflop_174_raise_size_options(
    table: Any,
    hand: Any,
    player_id: str = "hero",
) -> dict[str, Any] | None:
    """Return legal chart-derived preflop raise sizes for the acting player.

    Exact 174 histories are preferred. Other histories use the same nearest
    source-scenario inference as the CPU policy, clearly marked as inferred.
    This helper only selects sizing targets; it never submits an action.
    """
    if hand is None or bool(getattr(hand, "finished", False)):
        return None
    if str(getattr(hand, "street", "")).lower() != "preflop":
        return None
    if str(getattr(hand, "next_to_act", "") or "") != str(player_id):
        return None
    try:
        legal = hand.legal_actions(player_id)
        if "raise" not in _legal_actions(legal) or not bool(legal.get("raise_allowed", True)):
            return None
        positions = _position_map(table, hand)
        actor_position = positions.get(str(player_id))
        if actor_position not in POSITIONS:
            return None
        actual_history = _actual_history(table, hand, player_id, positions)
        # A fixed seed makes the displayed source scenario stable while the user
        # opens/closes the sizing menu; CPU action sampling keeps its own RNG.
        scenario, scenario_inferred, distance = _select_live_scenario(
            table, hand, player_id, actor_position, actual_history, random.Random(0)
        )
        if scenario is None:
            return None
        player = hand.player(player_id)
        hand_class = _hand_class(getattr(player, "hole_cards", ()))
        if hand_class is None:
            return None
        distribution, hand_inferred, hand_method = _scenario_distribution(scenario, hand_class)
        distribution = _filter_first_in_distribution(actor_position, actual_history, distribution)
        bb = _big_blind(hand, table)
        min_target = int(legal.get("min_target", 0) or 0)
        max_target = int(legal.get("max_target", 0) or 0)

        # Build the size menu from the SAME scenario as the displayed chart,
        # not from a separate fuzzy lookup of the hero's current hand.
        # All active source sizes are visible; sizes with 0% for this hand are
        # shown disabled rather than causing the whole selector to disappear.
        active_sizes: set[float] = set()
        options = list(scenario.get("action_options", []) or [])
        for source_scenario in (scenario,):
            for row in source_scenario.get("hands", []):
                for option_index, frequency in row or []:
                    if float(frequency) <= 0:
                        continue
                    action, size = options[int(option_index)]
                    if str(action).lower() == "raise" and size is not None:
                        active_sizes.add(float(size))

        choices = []
        first_in = not actual_history
        for size_bb in sorted(active_sizes):
            if first_in and size_bb > 5.0:
                continue
            amount = int(round(size_bb * bb))
            legal_target = (
                amount >= max(1, min_target)
                and (max_target <= 0 or amount <= max_target)
            )
            frequency = float(distribution.get(("raise", size_bb), 0.0))
            choices.append({
                "amount": amount,
                "size_bb": size_bb,
                "frequency": frequency,
                "frequency_pct": 100.0 * frequency,
                "legal_in_current_state": legal_target,
                "enabled_for_hand": frequency > 0.0 and legal_target,
                "disabled_reason": (
                    "NOT IN THIS HAND RANGE" if frequency <= 0.0
                    else "NOT LEGAL IN CURRENT STATE" if not legal_target
                    else ""
                ),
            })
        if not choices:
            return None
        return {
            "scenario_id": int(scenario["id"]),
            "scenario_match_mode": (
                "exact" if not scenario_inferred
                else "actions-size-unverified" if distance < 0
                else "nearest-inferred"
            ),
            "scenario_inferred": bool(scenario_inferred),
            "distance": float(distance),
            "hand_class": hand_class,
            "hand_inferred": bool(hand_inferred),
            "hand_inference_method": str(hand_method),
            "choices": choices,
        }
    except (KeyError, TypeError, ValueError, AttributeError, RuntimeError, OverflowError):
        return None


def preflop_174_catalog_summary() -> dict[str, Any]:
    data = load_preflop_174_data()
    scenarios = _scenarios()
    history_groups: dict[tuple[Any, ...], list[int]] = {}
    matrix_groups: dict[tuple[Any, ...], list[int]] = {}
    for item in scenarios:
        history_key = (
            str(item.get("position", "")).upper(),
            tuple((
                str(event.get("position", "")).upper(),
                _normalise_action(event.get("action")),
                None if event.get("size_bb") is None else round(float(event["size_bb"]), 5),
            ) for event in (item.get("history", []) or [])),
        )
        history_groups.setdefault(history_key, []).append(int(item["id"]))
        matrix_groups.setdefault(_scenario_strategy_signature(item), []).append(int(item["id"]))
    duplicate_history_groups = sorted(
        (sorted(ids) for ids in history_groups.values() if len(ids) > 1),
        key=lambda ids: ids[0],
    )
    duplicate_matrix_groups = sorted(
        (sorted(ids) for ids in matrix_groups.values() if len(ids) > 1),
        key=lambda ids: ids[0],
    )
    ambiguous_history_groups = []
    for ids in duplicate_history_groups:
        signatures = {
            _scenario_strategy_signature(item)
            for item in scenarios if int(item["id"]) in set(ids)
        }
        if len(signatures) > 1:
            ambiguous_history_groups.append(ids)
    return {
        "scenario_count": len(scenarios),
        "unique_action_history_count": len(history_groups),
        "duplicate_action_history_groups": duplicate_history_groups,
        "ambiguous_duplicate_history_groups": ambiguous_history_groups,
        "unique_169_cell_strategy_matrix_count": len(matrix_groups),
        "duplicate_strategy_matrix_groups": duplicate_matrix_groups,
        "hand_classes_per_scenario": len(data["hand_order"]),
        "scenario_ids": [int(item["id"]) for item in scenarios],
        "unresolved_hand_cells": sum(1 for item in scenarios for row in item["hands"] if not row),
        "multi_raise_size_scenarios": [int(item["id"]) for item in scenarios
            if len({tuple(option) for option in item["action_options"] if option[0] == "raise"}) > 1],
    }
