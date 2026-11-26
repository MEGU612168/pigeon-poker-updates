"""Exact live-history resolver for the 174 preflop range charts.

This module intentionally has no dependency on range-image bitmaps, Pillow,
Tk PhotoImage, or the legacy screenshot decoder.
"""
from __future__ import annotations

import json
import math
from typing import Any

from .preflop_174_policy import (
    PAID_RANGE_ALL_IN_POSITION_REQUIREMENTS,
    _actual_history,
    _normalise_action,
    _scenarios,
    exact_preflop_174_source_candidates,
    find_exact_preflop_174_scenario,
)


_RANGE_LOOKUP_EVENT_FIELDS = (
    "type", "street", "player_id", "player", "action", "decision",
    "position", "is_all_in", "all_in", "jam", "target", "raise_to",
    "to_amount", "total_contribution", "target_amount", "amount", "paid",
)


def live_range_lookup_signature(
    hand: Any,
    *,
    current_hand_key: str = "",
    cash_busy: bool = False,
    cash_deal_busy: bool = False,
    cash_sitting_out: bool = False,
    dealer_index: Any = None,
) -> tuple[Any, ...]:
    """Snapshot all live fields that can change exact range eligibility."""
    if hand is None:
        return (
            None, str(current_hand_key), bool(cash_busy),
            bool(cash_deal_busy), bool(cash_sitting_out), repr(dealer_index),
        )

    events = list(getattr(hand, "events", ()) or ())
    event_state = []
    for event in events:
        if isinstance(event, dict):
            event_state.append(tuple(
                (field, repr(event.get(field))) for field in _RANGE_LOOKUP_EVENT_FIELDS
            ))
        else:
            event_state.append(("event", repr(event)))

    players = list(getattr(hand, "players", ()) or ())
    seat_by_id = getattr(hand, "seat_by_id", {}) or {}
    player_state = []
    for player in players:
        player_id = str(getattr(player, "player_id", "") or "")
        seat = seat_by_id.get(player_id) if isinstance(seat_by_id, dict) else None
        player_state.append((
            player_id,
            str(getattr(player, "position", "") or ""),
            repr(seat),
            bool(getattr(player, "all_in", False)),
            repr(getattr(player, "stack", None)),
        ))

    return (
        id(hand),
        str(current_hand_key),
        str(getattr(hand, "street", "") or ""),
        str(getattr(hand, "next_to_act", "") or ""),
        bool(getattr(hand, "finished", False)),
        tuple(event_state),
        tuple(player_state),
        repr(getattr(hand, "dealer_index", None)),
        repr(dealer_index),
        repr(getattr(hand, "big_blind", None)),
        bool(cash_busy),
        bool(cash_deal_busy),
        bool(cash_sitting_out),
    )


def _same_action(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if str(expected.get("position", "")).upper() != str(actual.get("position", "")).upper():
        return False
    action = str(expected.get("action", "")).lower()
    if action != str(actual.get("action", "")).lower():
        return False
    if action == "raise":
        try:
            expected_size = float(expected.get("size_bb"))
            actual_size = float(actual.get("amount_bb"))
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(expected_size) or not math.isfinite(actual_size):
            return False
        tolerance = max(0.12, abs(expected_size) * 0.04)
        return abs(expected_size - actual_size) <= tolerance
    return True


def resolve_range_image_for_situation(spot: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve an exact 174-scenario history without opening the bitmap archive."""
    if not isinstance(spot, dict):
        return None
    actor = str(spot.get("actor_position") or "").upper()
    actual = []
    for record in list(spot.get("records", []) or []):
        if not isinstance(record, dict):
            continue
        action = str(record.get("action", "")).lower()
        if action not in {"fold", "call", "check", "raise", "allin"}:
            continue
        actual.append({
            "position": str(record.get("position", "")).upper(),
            "action": action,
            "size_bb": record.get("amount_bb"),
        })
    source_id = find_exact_preflop_174_scenario(actor, actual)
    if source_id is None:
        return None
    scenario = next((item for item in _scenarios() if int(item["id"]) == int(source_id)), None)
    if scenario is None:
        return None
    return {
        "source_id": int(source_id),
        "source_file": f"scenario_{int(source_id)}",
        "actor_position": actor,
        "match_mode": "exact",
        "matched_history_count": len(scenario.get("history", []) or []),
        "prefix_complete": True,
    }


def _scenario_signature(scenario: dict[str, Any]) -> str:
    # Some separately indexed source records have different explanatory
    # metadata (or a zero-frequency action in "overall") but the exact same
    # 169-cell range. An alias is safe only when the fully rendered matrix,
    # including all frequencies and action sizes, is identical.
    from .range_chart_canvas import build_range_chart_model

    value = build_range_chart_model(int(scenario["id"]))
    value.pop("source_id", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _history_matches_when_live_raise_size_is_missing(
    expected_history: list[dict[str, Any]],
    actual_history: list[dict[str, Any]],
) -> bool:
    """Match the full action sequence when the runtime omitted a raise-to amount.

    A known but different raise size is never relaxed. This fallback is limited
    to events whose raise size is genuinely absent; the resolver must still
    disambiguate candidates by legal actions, all-in state, or identical
    169-hand strategy matrices before returning a paid chart.
    """
    if len(expected_history) != len(actual_history):
        return False
    missing_live_raise_size = False
    for expected, actual in zip(expected_history, actual_history):
        if str(expected.get("position", "")).upper() != str(actual.get("position", "")).upper():
            return False
        expected_action = _normalise_action(expected.get("action"))
        actual_action = _normalise_action(actual.get("action"))
        if expected_action != actual_action:
            return False
        if expected_action != "raise":
            continue
        expected_size = expected.get("size_bb")
        actual_size = actual.get("size_bb")
        if actual_size is None:
            missing_live_raise_size = True
            continue
        if expected_size is None:
            continue
        try:
            e = float(expected_size)
            a = float(actual_size)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(e) or not math.isfinite(a):
            return False
        if abs(e - a) > max(0.12, abs(e) * 0.04):
            return False
    return missing_live_raise_size


def _candidate_preflop_state_metrics(
    scenario: dict[str, Any],
    actual_history: list[dict[str, Any]],
    actor_position: str,
    bb: int,
) -> tuple[float | None, float | None]:
    """Rebuild source pot/to-call from forced blinds and the ordered actions.

    Raise sizes in the source are total raise-to targets. Prior all-ins without
    a source size can use a live all-in amount when the runtime provides one.
    A metric is omitted whenever the required contribution cannot be rebuilt.
    """
    source_history = list(scenario.get("history", []) or [])
    if len(source_history) != len(actual_history):
        return None, None
    committed = {"SB": 0.5, "BB": 1.0}
    current_bet = 1.0
    complete = True
    for expected, actual in zip(source_history, actual_history):
        position = str(expected.get("position", "")).upper()
        action = _normalise_action(expected.get("action"))
        if position not in {"UTG", "HJ", "CO", "BTN", "SB", "BB"}:
            complete = False
            break
        if action in {"fold", "check"}:
            continue
        if action == "call":
            committed[position] = max(committed.get(position, 0.0), current_bet)
            continue
        if action == "raise":
            size = expected.get("size_bb")
            if size is None:
                size = actual.get("size_bb")
            try:
                target = float(size)
            except (TypeError, ValueError, OverflowError):
                complete = False
                break
            if not math.isfinite(target) or target < current_bet - 0.05:
                complete = False
                break
            committed[position] = max(committed.get(position, 0.0), target)
            current_bet = max(current_bet, target)
            continue
        if action == "allin":
            size = expected.get("size_bb")
            if size is None:
                size = actual.get("size_bb")
            try:
                target = float(size)
            except (TypeError, ValueError, OverflowError):
                complete = False
                break
            if not math.isfinite(target) or target < committed.get(position, 0.0):
                complete = False
                break
            committed[position] = max(committed.get(position, 0.0), target)
            current_bet = max(current_bet, target)
            continue
        complete = False
        break
    if not complete:
        return None, None
    pot_bb = sum(committed.values())
    to_call_bb = max(0.0, current_bet - committed.get(str(actor_position).upper(), 0.0))
    return pot_bb, to_call_bb


def _disambiguate_with_live_preflop_state(
    candidates: list[dict[str, Any]],
    hand: Any,
    player_id: str,
    actor_position: str,
    actual_history: list[dict[str, Any]],
    bb: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """Use live pot and to-call only when they uniquely support source nodes."""
    if len(candidates) <= 1:
        return candidates, None

    metrics = {
        int(scenario["id"]): _candidate_preflop_state_metrics(
            scenario, actual_history, actor_position, bb
        )
        for scenario in candidates
    }

    try:
        legal = hand.legal_actions(player_id)
        raw_to_call = legal.get("to_call") if isinstance(legal, dict) else None
        observed_to_call = float(raw_to_call) / max(1, bb) if raw_to_call is not None else None
    except (TypeError, ValueError, OverflowError, AttributeError):
        observed_to_call = None

    try:
        raw_pot = getattr(hand, "pot", None)
        observed_pot = float(raw_pot) / max(1, bb) if raw_pot is not None else None
    except (TypeError, ValueError, OverflowError):
        observed_pot = None

    # Filter first by to-call. A mismatch is ignored when no candidate supports
    # it (for example, because the live engine includes an unmodelled ante).
    if observed_to_call is not None and math.isfinite(observed_to_call):
        matched = [
            scenario for scenario in candidates
            if metrics[int(scenario["id"])][1] is not None
            and abs(float(metrics[int(scenario["id"])][1]) - observed_to_call) <= 0.08
        ]
        if matched and len(matched) < len(candidates):
            candidates = matched

    if len(candidates) > 1 and observed_pot is not None and math.isfinite(observed_pot):
        matched = [
            scenario for scenario in candidates
            if metrics[int(scenario["id"])][0] is not None
            and abs(float(metrics[int(scenario["id"])][0]) - observed_pot) <= 0.08
        ]
        if matched and len(matched) < len(candidates):
            candidates = matched

    if len(candidates) == 1:
        return candidates, "exact-live-pot-and-call-state"
    return candidates, None


def resolve_range_image_for_hand(table: Any, hand: Any, player_id: str) -> dict[str, Any] | None:
    """Resolve a 174-source node from the live action history and legal state."""
    actor_position, positions, candidates = exact_preflop_174_source_candidates(
        table, hand, player_id
    )
    size_unverified = False
    if not candidates:
        actual_history = _actual_history(table, hand, player_id, positions)
        # Some runtime action records omit target/raise_to. Do not turn that
        # into a blanket miss: match the exact position/action sequence, but
        # retain only candidates whose known sizes agree with any recorded
        # live sizes. Ambiguous strategies remain unavailable.
        candidates = [
            scenario for scenario in _scenarios()
            if str(scenario.get("position", "")).upper() == str(actor_position or "").upper()
            and _history_matches_when_live_raise_size_is_missing(
                list(scenario.get("history", []) or []), actual_history
            )
        ]
        size_unverified = bool(candidates)
        if not candidates:
            return None

    match_mode = "exact-actions-size-unverified" if size_unverified else "exact"

    def resolved_mode(stage: str) -> str:
        return f"actions-size-unverified-{stage}" if size_unverified else f"exact-{stage}"

    if len(candidates) > 1:
        try:
            legal = hand.legal_actions(player_id)
            legal_actions = {
                _normalise_action(value)
                for value in (legal.get("actions", ()) if isinstance(legal, dict) else ())
            }
        except Exception:
            legal_actions = set()

        if legal_actions:
            compatible = []
            for scenario in candidates:
                option_actions = {
                    _normalise_action(option[0])
                    for option in scenario.get("action_options", [])
                    if isinstance(option, (list, tuple)) and option
                }
                if option_actions and option_actions.issubset(legal_actions):
                    compatible.append(scenario)
            if not compatible:
                return None
            largest_menu = max(
                len({
                    _normalise_action(option[0])
                    for option in scenario.get("action_options", [])
                    if isinstance(option, (list, tuple)) and option
                })
                for scenario in compatible
            )
            candidates = [
                scenario for scenario in compatible
                if len({
                    _normalise_action(option[0])
                    for option in scenario.get("action_options", [])
                    if isinstance(option, (list, tuple)) and option
                }) == largest_menu
            ]
            if len(candidates) == 1:
                match_mode = resolved_mode("live-actions")

    if len(candidates) > 1:
        actual_all_in_positions = {
            positions.get(str(getattr(player, "player_id", "") or ""))
            for player in (getattr(hand, "players", ()) or ())
            if bool(getattr(player, "all_in", False))
        }
        actual_all_in_positions.discard(None)
        compatible = [
            scenario for scenario in candidates
            if (
                int(scenario.get("id", -1)) not in PAID_RANGE_ALL_IN_POSITION_REQUIREMENTS
                or actual_all_in_positions
                == set(PAID_RANGE_ALL_IN_POSITION_REQUIREMENTS[int(scenario["id"])])
            )
        ]
        if not compatible:
            return None
        if len(compatible) < len(candidates):
            candidates = compatible
            if len(candidates) == 1:
                match_mode = resolved_mode("live-state")

    if len(candidates) > 1:
        bb = 100
        try:
            bb = int(getattr(hand, "big_blind", 100) or 100)
        except (TypeError, ValueError, OverflowError):
            bb = 100
        candidates, live_state_mode = _disambiguate_with_live_preflop_state(
            candidates, hand, player_id, str(actor_position or ""),
            _actual_history(table, hand, player_id, positions), max(1, bb),
        )
        if live_state_mode:
            match_mode = resolved_mode("live-pot-and-call-state")

    if len(candidates) > 1:
        signatures = {_scenario_signature(scenario) for scenario in candidates}
        if len(signatures) != 1:
            return None

        def canonical_key(scenario):
            source = str(scenario.get("history_parse_source", ""))
            return (
                0 if source == "full_header_manual_verified" else 1,
                int(scenario.get("id", 10**9)),
            )

        candidates = [min(candidates, key=canonical_key)]
        match_mode = resolved_mode("identical-strategy-data")

    try:
        source_id = int(candidates[0]["id"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None

    chosen = candidates[0]
    return {
        "source_id": source_id,
        "source_file": f"scenario_{source_id}",
        "actor_position": str(chosen.get("position", actor_position or "")).upper(),
        "match_mode": match_mode,
        "matched_history_count": len(chosen.get("history", []) or []),
        "prefix_complete": True,
        "raise_size_verified": not size_unverified,
        "action_history_exact": True,
    }
