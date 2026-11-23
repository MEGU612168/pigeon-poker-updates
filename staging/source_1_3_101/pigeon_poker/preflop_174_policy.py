from __future__ import annotations

import math
import random
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

from .preflop_174_policy_data import load_preflop_174_data

POSITIONS = ("UTG", "HJ", "CO", "BTN", "SB", "BB")

# These source-ID pairs were SHA-256 checked against the original 174-image
# archive and contain byte-identical cropped range images. They are aliases
# only for choosing which identical bitmap to display; the BOT's 174 strategy
# rows remain separate and untouched.
_RANGE_IMAGE_ALIAS_GROUPS = (
    (148, 288),
    (195, 204),
    (201, 211),
    (238, 243),
    (239, 244),
    (245, 251),
    (259, 263),
)


def _range_image_canonical_id(source_id: int) -> int:
    for group in _RANGE_IMAGE_ALIAS_GROUPS:
        if source_id in group:
            return min(group)
    return source_id


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


def resolve_exact_preflop_174_scenario(
    actor_position: str, actual_history: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return a uniquely matching source scenario; never use nearest-node inference.

    Action order and acting positions must match across the complete history.
    Recorded raise sizes are checked tightly. A source row with a missing size
    can match only when the complete position/action sequence identifies one
    and only one of the 174 source scenarios.
    """
    actor = str(actor_position or "").upper()
    if actor not in POSITIONS or not isinstance(actual_history, list):
        return None

    matches: list[dict[str, Any]] = []
    for scenario in _scenarios():
        if str(scenario.get("position", "")).upper() != actor:
            continue
        expected_history = scenario.get("history")
        if not isinstance(expected_history, list) or len(expected_history) != len(actual_history):
            continue

        matched = True
        for expected, actual in zip(expected_history, actual_history):
            if not isinstance(expected, dict) or not isinstance(actual, dict):
                matched = False
                break
            expected_position = str(expected.get("position", "")).upper()
            actual_position = str(actual.get("position", "")).upper()
            expected_action = _normalise_action(expected.get("action"))
            actual_action = _normalise_action(actual.get("action"))
            if expected_position != actual_position or expected_action != actual_action:
                matched = False
                break
            if expected_action == "raise":
                expected_size = expected.get("size_bb")
                actual_size = actual.get("size_bb")
                if expected_size is not None:
                    if actual_size is None:
                        matched = False
                        break
                    try:
                        e, a = float(expected_size), float(actual_size)
                    except (TypeError, ValueError, OverflowError):
                        matched = False
                        break
                    if not math.isfinite(e) or not math.isfinite(a):
                        matched = False
                        break
                    if abs(e - a) > max(0.03, abs(e) * 0.01):
                        matched = False
                        break
        if matched:
            matches.append(scenario)

    if len(matches) == 1:
        return matches[0]
    if not matches:
        return None

    # If the complete action history yields multiple records, coalesce only
    # IDs whose ORIGINAL range PNGs were verified byte-identical. This affects
    # only the bitmap selector; no strategy rows or frequencies are merged.
    canonical = {
        _range_image_canonical_id(int(item.get("id", -1)))
        for item in matches
    }
    if len(canonical) != 1:
        return None
    canonical_id = next(iter(canonical))
    return next(
        (item for item in matches if int(item.get("id", -1)) == canonical_id),
        None,
    )


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
    distribution, method = _infer_hand_distribution(scenario, hand_class)
    if distribution:
        return distribution, True, method
    # Every source scenario has at least one measured hand, but keep a transparent
    # last safety branch in case a future source archive is damaged.
    aggregate: dict[tuple[str, float | None], float] = {}
    for action, size, frequency in scenario.get("overall", []):
        key = (str(action), None if size is None else float(size))
        aggregate[key] = aggregate.get(key, 0.0) + float(frequency)
    return _normalise_distribution(aggregate), True, "scenario-overall-frequency-fallback"


def _choose_scenario(actor_position: str, actual_history: list[dict[str, Any]], rng: Any) -> tuple[dict[str, Any], bool, float]:
    candidates = [s for s in _scenarios() if s["position"] == actor_position]
    exact = [s for s in candidates if len(s["history"]) == len(actual_history)
             and all(_event_matches(want, got) for want, got in zip(s["history"], actual_history))]
    if exact:
        # Keep source images as independent records; only select among identical matched histories.
        if len(exact) == 1:
            return exact[0], False, 0.0
        picker = getattr(rng, "choice", None)
        selected = picker(exact) if callable(picker) else exact[0]
        return selected, False, 0.0
    ranked = [(_history_distance(s["history"], actual_history), s) for s in candidates]
    if not ranked:
        raise RuntimeError(f"No 174-scenario reference exists for actor position {actor_position}")
    ranked.sort(key=lambda item: item[0])
    best_score = ranked[0][0]
    near = [s for score, s in ranked if abs(score - best_score) <= 1e-9]
    picker = getattr(rng, "choice", None)
    selected = picker(near) if callable(picker) else near[0]
    return selected, True, best_score


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


def _safe_legal_fallback(player_id: str, legal: dict[str, Any], hand_class: str, scenario_id: int) -> SimpleNamespace:
    available = _legal_actions(legal)
    to_call = max(0, int(legal.get("to_call", 0) or 0))
    if "check" in available and to_call == 0:
        action = "check"
    elif "fold" in available and to_call > 0:
        action = "fold"
    elif "call" in available:
        action = "call"
    elif "fold" in available:
        action = "fold"
    elif "check" in available:
        action = "check"
    elif "raise" in available and int(legal.get("min_target", 0) or 0) > 0:
        action, amount = "raise", int(legal["min_target"])
        return SimpleNamespace(player_id=str(player_id), action=action, amount=amount,
            source="preflop-174-legal-guardrail", node_id=f"174_IMAGE_{scenario_id}",
            hand_class=hand_class, action_frequency=1.0, inferred=True,
            size_source="legal-guardrail", note="The measured action branches were not legal in the current hand; used a legal-action guardrail.")
    else:
        raise RuntimeError("No legal preflop action is available")
    return SimpleNamespace(player_id=str(player_id), action=action, amount=None,
        source="preflop-174-legal-guardrail", node_id=f"174_IMAGE_{scenario_id}",
        hand_class=hand_class, action_frequency=1.0, inferred=True,
        size_source="legal-guardrail", note="The measured action branches were not legal in the current hand; used a legal-action guardrail.")


def choose_preflop_174_action(table: Any, hand: Any, player_id: str, cpu: Any) -> SimpleNamespace:
    """Select a legal preflop action from all 174 source scenarios.

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
    scenario, scenario_inferred, distance = _choose_scenario(actor_position, actual_history, rng)
    player = hand.player(player_id)
    hand_class = _hand_class(getattr(player, "hole_cards", ()))
    if hand_class is None:
        raise RuntimeError("CPU hole cards could not be mapped to a 169-class hand")
    distribution, hand_inferred, hand_method = _scenario_distribution(scenario, hand_class)
    bb = _big_blind(hand, table)
    choices = _legal_choices(hand, player_id, distribution, bb)
    if not choices:
        return _safe_legal_fallback(player_id, legal, hand_class, int(scenario["id"]))
    total = sum(item["frequency"] for item in choices)
    if total <= 0:
        return _safe_legal_fallback(player_id, legal, hand_class, int(scenario["id"]))
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
    match_label = "exact" if exact else f"nearest-inferred distance={distance:.3f}"
    note = (f"174-scenario #{source_image} ({match_label}); {hand_method}; "
            "hand frequencies estimated from source-image colour proportions.")
    return SimpleNamespace(
        player_id=str(player_id), action=chosen["action"], amount=chosen["amount"],
        source="preflop-174-scenario-policy", node_id=f"174_IMAGE_{source_image}",
        hand_class=hand_class, action_frequency=float(chosen["frequency"]) / total,
        inferred=inferred,
        size_source="174-image-exact" if not inferred else "174-image-inference",
        note=note, source_image_no=source_image,
        scenario_match_mode="exact" if exact else "nearest-inferred",
        action_size_bb=chosen.get("size_bb"),
        hand_inference_method=hand_method,
    )


def preflop_174_catalog_summary() -> dict[str, Any]:
    data = load_preflop_174_data()
    scenarios = _scenarios()
    return {
        "scenario_count": len(scenarios),
        "hand_classes_per_scenario": len(data["hand_order"]),
        "scenario_ids": [int(item["id"]) for item in scenarios],
        "unresolved_hand_cells": sum(1 for item in scenarios for row in item["hands"] if not row),
        "multi_raise_size_scenarios": [int(item["id"]) for item in scenarios
            if len({tuple(option) for option in item["action_options"] if option[0] == "raise"}) > 1],
    }
