"""Screenshot-derived Pigeon Poker 6-max preflop policy.

The embedded frequency table was reconstructed from the user's supplied charts.
It is a frequency approximation, not solver-exported exact combo data.
"""
from __future__ import annotations

import base64
import json
import random
import zlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_DATA_B64 = "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"

POSITIONS_BY_CLOCKWISE_DISTANCE = {0: "BTN", 1: "SB", 2: "BB", 3: "UTG", 4: "HJ", 5: "CO"}
OPEN_ORDER = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
DEVIATION_BY_LEVEL = {1: 0.30, 2: 0.20, 3: 0.10, 4: 0.05, 5: 0.0}


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(zlib.decompress(base64.b64decode(_DATA_B64)).decode("utf-8"))


@dataclass(frozen=True)
class ScreenshotRangeDecision:
    action: str
    amount: int | None
    equity_estimate: float = 0.0
    source: str = "screenshot-range"
    node_id: str = ""
    hand_class: str = ""
    action_frequency: float = 0.0


def _position_map(table: Any, hand: Any) -> dict[str, str] | None:
    players = list(getattr(hand, "players", ()) or ())
    if len(players) != 6:
        return None
    dealer = getattr(table, "dealer_index", None)
    if dealer is None:
        dealer = getattr(hand, "dealer_index", None)
    if dealer is None:
        return None
    dealer = int(dealer) % 6
    result = {}
    for index, player in enumerate(players):
        player_id = str(getattr(player, "player_id", ""))
        if not player_id:
            return None
        result[player_id] = POSITIONS_BY_CLOCKWISE_DISTANCE[(index - dealer) % 6]
    return result


def _hand_class(player: Any) -> str | None:
    cards = list(getattr(player, "hole_cards", ()) or ())
    if len(cards) != 2:
        return None
    ranks = "23456789TJQKA"
    parsed = []
    for card in cards:
        value = str(card).strip()
        if len(value) != 2:
            return None
        rank, suit = value[0].upper(), value[1].lower()
        if rank not in ranks or suit not in "shdc":
            return None
        parsed.append((ranks.index(rank), rank, suit))
    if parsed[0][0] < parsed[1][0]:
        parsed.reverse()
    high, low = parsed[0], parsed[1]
    if high[0] == low[0]:
        return high[1] + low[1]
    suited = parsed[0][2] == parsed[1][2]
    return high[1] + low[1] + ("s" if suited else "o")


def _preflop_action_events(hand: Any, actor_id: str) -> list[dict[str, Any]]:
    events = []
    for event in list(getattr(hand, "events", ()) or ()):
        if not isinstance(event, dict) or event.get("type") != "action":
            continue
        street = str(event.get("street", "preflop")).lower()
        if street != "preflop":
            continue
        player_id = str(event.get("player_id") or event.get("player") or "")
        if player_id == actor_id:
            continue
        action = str(event.get("action", "")).lower().replace("-", "_")
        if action:
            events.append({**event, "_action": action, "_player_id": player_id})
    return events


def _node_for_actor(table: Any, hand: Any, actor_id: str) -> str | None:
    positions = _position_map(table, hand)
    if positions is None or actor_id not in positions:
        return None
    actor_pos = positions[actor_id]
    actor_order = OPEN_ORDER.index(actor_pos)
    events = _preflop_action_events(hand, actor_id)
    raises = [e for e in events if e["_action"] in {"raise", "bet", "all_in", "allin", "jam"}]
    non_folds = [e for e in events if e["_action"] not in {"fold"}]
    if not raises:
        # First-in node only: every previous voluntary action must be a fold.
        if actor_pos == "BB" or non_folds:
            return None
        return {"UTG":"01_UTG_OPEN", "HJ":"02_HJ_OPEN", "CO":"03_CO_OPEN",
                "BTN":"04_BTN_OPEN", "SB":"05_SB_OPEN"}.get(actor_pos)
    if len(raises) != 1 or len(non_folds) != 1:
        return None
    opener_id = raises[0]["_player_id"]
    opener_pos = positions.get(opener_id)
    if opener_pos not in OPEN_ORDER[:-1]:
        return None
    opener_order = OPEN_ORDER.index(opener_pos)
    if opener_order >= actor_order:
        return None
    # No limps/calls or re-raises are represented by these 20 screenshot nodes.
    if raises[0]["_action"] not in {"raise", "bet"}:
        return None
    # The source chart assumes 2.5 BB opens, except the SB's 3.5 BB open.
    # Validate the recorded total target when the engine exposes it; if the
    # action record omits a target field, keep the otherwise exact action line.
    recorded_target = raises[0].get("target")
    if recorded_target is not None:
        try:
            expected_open = 3.5 if opener_pos == "SB" else 2.5
            expected_cents = expected_open * int(getattr(hand, "big_blind", 1))
            if abs(float(recorded_target) - expected_cents) > max(1.0, expected_cents * 0.06):
                return None
        except (TypeError, ValueError):
            return None
    lookup = {
        ("UTG", "HJ"): "06_HJ_VS_UTG", ("UTG", "CO"): "07_CO_VS_UTG",
        ("UTG", "BTN"): "08_BTN_VS_UTG", ("UTG", "SB"): "09_SB_VS_UTG",
        ("UTG", "BB"): "10_BB_VS_UTG",
        ("HJ", "CO"): "11_CO_VS_HJ", ("HJ", "BTN"): "12_BTN_VS_HJ",
        ("HJ", "SB"): "13_SB_VS_HJ", ("HJ", "BB"): "14_BB_VS_HJ",
        ("CO", "BTN"): "15_BTN_VS_CO", ("CO", "SB"): "16_SB_VS_CO",
        ("CO", "BB"): "17_BB_VS_CO",
        ("BTN", "SB"): "18_SB_VS_BTN", ("BTN", "BB"): "19_BB_VS_BTN",
        ("SB", "BB"): "20_BB_VS_SB",
    }
    # Any earlier non-fold action other than the single open means this is outside
    # the supplied chart coverage (e.g. a limp, cold-call, squeeze, or 4-bet).
    if any(e is not raises[0] and e["_action"] != "fold" for e in events):
        return None
    return lookup.get((opener_pos, actor_pos))


def _legal_actions(hand: Any, actor_id: str) -> dict[str, Any]:
    try:
        value = hand.legal_actions(actor_id)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _sample_action(probabilities: dict[str, float], rng: random.Random) -> tuple[str, float] | None:
    total = sum(max(0.0, float(v)) for v in probabilities.values())
    if total <= 0:
        return None
    threshold = rng.random() * total
    upto = 0.0
    last = None
    for action, probability in probabilities.items():
        probability = max(0.0, float(probability))
        if probability <= 0:
            continue
        last = (action, probability / total)
        upto += probability
        if threshold < upto:
            return last
    return last


def choose_preflop_action(table: Any, hand: Any, actor_id: str, cpu: Any,
                          fallback_decision: Any = None) -> ScreenshotRangeDecision | None:
    """Return a range-based decision for a covered screenshot node, else None.

    Existing CPU levels are preserved through the project's deviation schedule:
    Levels 1-4 occasionally use the legacy policy; level 5 follows the supplied
    mixed frequencies. Unsupported preflop trees always remain on the legacy CPU.
    """
    if str(getattr(hand, "street", "")).lower() != "preflop":
        return None
    node_id = _node_for_actor(table, hand, str(actor_id))
    if not node_id:
        return None
    try:
        player = hand.player(actor_id)
        combo = _hand_class(player)
    except Exception:
        return None
    if not combo:
        return None
    entry = _data()
    row = next((r for r in entry["rows"] if r["node"] == node_id and r["hand"] == combo), None)
    if row is None:
        return None
    rng = getattr(cpu, "rng", None)
    if not hasattr(rng, "random"):
        rng = random.Random()
    try:
        level = int(getattr(cpu, "level", 5))
    except Exception:
        level = 5
    deviation = DEVIATION_BY_LEVEL.get(level, 0.0)
    if fallback_decision is not None and deviation > 0 and rng.random() < deviation:
        return fallback_decision

    legal = _legal_actions(hand, actor_id)
    legal_names = set(str(x).lower() for x in legal.get("actions", ()))
    raw = {k: float(v) for k, v in row["p"].items()}
    probabilities = {k: v for k, v in raw.items() if v > 0 and k in legal_names}
    sampled = _sample_action(probabilities, rng)
    if sampled is None:
        return None
    action, normalized_frequency = sampled
    amount = None
    if action == "raise":
        node = entry["nodes"].get(node_id, {})
        desired = int(round(float(node.get("raise_size", 0)) * int(getattr(hand, "big_blind", 1))))
        try:
            min_target = int(legal.get("min_target", desired))
            max_target = int(legal.get("max_target", desired))
            amount = min(max(desired, min_target), max_target)
        except Exception:
            amount = desired
        if amount <= 0:
            return None
    return ScreenshotRangeDecision(
        action=action, amount=amount, node_id=node_id, hand_class=combo,
        action_frequency=float(raw.get(action, 0.0)),
    )
