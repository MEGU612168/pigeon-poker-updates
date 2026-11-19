"""Screenshot-derived 6-max preflop policy reused from the Pio import chart."""
from __future__ import annotations

import base64
import gzip
import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable

from .preflop_range_data import DATA_B64

_POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
_OPEN_NODE = {
    "UTG": "01_UTG_OPEN", "HJ": "02_HJ_OPEN", "CO": "03_CO_OPEN",
    "BTN": "04_BTN_OPEN", "SB": "05_SB_OPEN",
}
_DEFENSE_NODE = {
    ("HJ", "UTG"): "06_HJ_VS_UTG", ("CO", "UTG"): "07_CO_VS_UTG",
    ("BTN", "UTG"): "08_BTN_VS_UTG", ("SB", "UTG"): "09_SB_VS_UTG",
    ("BB", "UTG"): "10_BB_VS_UTG", ("CO", "HJ"): "11_CO_VS_HJ",
    ("BTN", "HJ"): "12_BTN_VS_HJ", ("SB", "HJ"): "13_SB_VS_HJ",
    ("BB", "HJ"): "14_BB_VS_HJ", ("BTN", "CO"): "15_BTN_VS_CO",
    ("SB", "CO"): "16_SB_VS_CO", ("BB", "CO"): "17_BB_VS_CO",
    ("SB", "BTN"): "18_SB_VS_BTN", ("BB", "BTN"): "19_BB_VS_BTN",
    ("BB", "SB"): "20_BB_VS_SB",
}
_LEVEL_DEVIATION = {1: .30, 2: .20, 3: .10, 4: .05, 5: 0.0}
_RANK_ORDER = "23456789TJQKA"
_SUITS = {"s": "s", "♠": "s", "h": "h", "♥": "h",
          "d": "d", "♦": "d", "c": "c", "♣": "c"}


@dataclass(frozen=True)
class PreflopRangeDecision:
    action: str
    amount: int | None
    equity_estimate: float = 0.0
    strategy_source: str = "screenshot_preflop_range"
    node_id: str = ""
    combo: str = ""
    cpu_level: int = 5


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    parsed = json.loads(gzip.decompress(base64.b64decode(DATA_B64)).decode("utf-8"))
    if parsed.get("schema") != 1 or len(parsed.get("nodes", {})) != 20:
        raise RuntimeError("Incomplete preflop chart")
    return parsed


def hand_class_from_cards(cards: Any) -> str | None:
    if isinstance(cards, str):
        raw = cards.strip().replace(" ", "").replace("10", "T")
        if len(raw) != 4:
            return None
        cards = (raw[:2], raw[2:])
    try:
        cards = list(cards)
    except TypeError:
        return None
    if len(cards) != 2:
        return None

    parsed = []
    for card in cards:
        if hasattr(card, "rank") and hasattr(card, "suit"):
            rank, suit_raw = str(card.rank).upper(), str(card.suit)
        else:
            value = str(card).strip().replace("10", "T")
            if len(value) < 2:
                return None
            rank, suit_raw = value[0].upper(), value[-1]
        suit = _SUITS.get(suit_raw)
        if rank not in _RANK_ORDER or suit is None:
            return None
        parsed.append((rank, suit))

    (r1, s1), (r2, s2) = parsed
    if r1 == r2:
        return r1 + r2
    high, low = (r1, r2) if _RANK_ORDER.index(r1) > _RANK_ORDER.index(r2) else (r2, r1)
    return high + low + ("s" if s1 == s2 else "o")


def _position(hand: Any, player_id: str) -> str | None:
    players = getattr(hand, "players", None)
    if not isinstance(players, (list, tuple)) or len(players) != 6:
        return None
    seat_map = getattr(hand, "seat_by_id", {}) or {}
    try:
        idx = int(seat_map[player_id])
    except (KeyError, TypeError, ValueError):
        try:
            actor = hand.player(player_id)
            idx = next(i for i, p in enumerate(players) if p is actor)
        except Exception:
            return None
    try:
        button = int(hand.dealer_index) % 6
    except (AttributeError, TypeError, ValueError):
        return None
    return _POSITIONS[(idx - button) % 6]


def _event_player_id(event: dict[str, Any], hand: Any) -> str | None:
    seat_map = getattr(hand, "seat_by_id", {}) or {}
    candidate = event.get("player_id")
    if candidate is not None and str(candidate) in seat_map:
        return str(candidate)
    name = str(event.get("player", ""))
    for player in getattr(hand, "players", ()):
        if name and name in {str(getattr(player, "name", "")),
                             str(getattr(player, "player_id", ""))}:
            return str(player.player_id)
    return None


def _action_history(hand: Any) -> list[dict[str, Any]] | None:
    result = []
    for event in getattr(hand, "events", ()) or ():
        if event.get("type") != "action":
            continue
        if str(event.get("street", "preflop")).lower() != "preflop":
            continue
        pid = _event_player_id(event, hand)
        if pid is None:
            return None
        action = str(event.get("action", "")).lower().replace("_", "-")
        result.append({"player_id": pid, "action": action, "event": event})
    return result


def _raise_size_bb(item: dict[str, Any], hand: Any) -> float | None:
    bb = float(getattr(hand, "big_blind", 0) or 0)
    if bb <= 0:
        return None
    target = item["event"].get("target")
    if target is None:
        try:
            target = getattr(hand.player(item["player_id"]), "street_contribution", None)
        except Exception:
            return None
    try:
        return float(target) / bb
    except (TypeError, ValueError):
        return None


def match_preflop_node(hand: Any, player_id: str) -> str | None:
    current = _position(hand, player_id)
    if current is None:
        return None
    history = _action_history(hand)
    if history is None or any(x["action"] not in {"fold", "raise", "bet"} for x in history):
        return None
    raises = [x for x in history if x["action"] in {"raise", "bet"}]
    if not raises:
        return _OPEN_NODE.get(current) if all(x["action"] == "fold" for x in history) else None
    if len(raises) != 1 or any(x["action"] != "fold" and x is not raises[0] for x in history):
        return None
    opener = raises[0]
    opener_pos = _position(hand, opener["player_id"])
    if opener_pos is None or opener_pos == current:
        return None
    expected = 3.5 if opener_pos == "SB" else 2.5
    actual = _raise_size_bb(opener, hand)
    if actual is None or abs(actual - expected) > .06:
        return None
    return _DEFENSE_NODE.get((current, opener_pos))


def choose_preflop_range_decision(
    hand: Any,
    player_id: str,
    *,
    rng: Any,
    level: int = 5,
    fallback_provider: Callable[[], Any] | None = None,
) -> PreflopRangeDecision | Any | None:
    """Sample the screenshot chart; retain established level-specific deviations."""
    node_id = match_preflop_node(hand, player_id)
    if node_id is None:
        return None
    try:
        player = hand.player(player_id)
        combo = hand_class_from_cards(getattr(player, "hole_cards", ()))
        node = _data()["nodes"][node_id]
        probabilities = node["hands"].get(combo)
        if not probabilities:
            return None

        cpu_level = max(1, min(5, int(level)))
        if float(rng.random()) < _LEVEL_DEVIATION[cpu_level]:
            return fallback_provider() if fallback_provider is not None else None

        legal = hand.legal_actions(player_id)
        legal_actions = {str(a).lower() for a in legal.get("actions", ())}
        choices: list[tuple[str, int | None, float]] = []
        for key, raw_weight in probabilities.items():
            weight = max(0.0, float(raw_weight))
            if weight <= 0:
                continue
            if key == "raise":
                action = "raise" if "raise" in legal_actions else ("bet" if "bet" in legal_actions else None)
                bb = int(getattr(hand, "big_blind", 0) or 0)
                if action is None or bb <= 0:
                    continue
                target = int(round(float(node["raise_bb"]) * bb))
                minimum, maximum = legal.get("min_target"), legal.get("max_target")
                if minimum is not None:
                    target = max(target, int(minimum))
                if maximum is not None:
                    if minimum is not None and int(maximum) < int(minimum):
                        continue
                    target = min(target, int(maximum))
                choices.append((action, target, weight))
            elif key == "call":
                if "call" in legal_actions:
                    choices.append(("call", None, weight))
                elif "check" in legal_actions:
                    choices.append(("check", None, weight))
            elif key == "fold" and "fold" in legal_actions:
                choices.append(("fold", None, weight))

        total = sum(choice[2] for choice in choices)
        if total <= 0:
            return None
        pick = float(rng.random()) * total
        selected = choices[-1]
        for choice in choices:
            pick -= choice[2]
            if pick <= 0:
                selected = choice
                break
        action, amount, _ = selected
        return PreflopRangeDecision(action, amount, 0.0,
                                    "screenshot_preflop_range", node_id, combo, cpu_level)
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        return None


def chart_summary() -> dict[str, Any]:
    nodes = _data()["nodes"]
    return {"nodes": len(nodes), "hand_rows": sum(len(x["hands"]) for x in nodes.values())}
