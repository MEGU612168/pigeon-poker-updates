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
    # The few duplicate histories may share a source ID only when their
    # complete strategy matrices and menu metadata are identical.
    value = {
        key: scenario.get(key)
        for key in ("position", "history", "action_options", "overall", "hands")
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def resolve_range_image_for_hand(table: Any, hand: Any, player_id: str) -> dict[str, Any] | None:
    """Resolve the exact 174-source strategy node using live action/menu state."""
    actor_position, positions, candidates = exact_preflop_174_source_candidates(
        table, hand, player_id
    )
    if not candidates:
        return None

    match_mode = "exact"

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
                match_mode = "exact-live-actions"

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
                match_mode = "exact-live-state"

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
        match_mode = "exact-identical-strategy-data"

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
    }
