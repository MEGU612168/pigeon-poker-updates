from __future__ import annotations

import base64
import bz2
import gzip
import json
import math
import random
from dataclasses import dataclass
from typing import Any

RANKS = "AKQJT98765432"
SUITS = "shdc"
POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")
PREFLOP_ORDER = {"UTG": 0, "HJ": 1, "CO": 2, "BTN": 3, "SB": 4, "BB": 5}
OPEN_SIZE_BB = {"UTG": 2.0, "HJ": 2.0, "CO": 2.3, "BTN": 2.5, "SB": 3.0}
OPEN_NODE = {
    "UTG": "01_UTG_OPEN",
    "HJ": "02_HJ_OPEN", "CO": "03_CO_OPEN",
    "BTN": "04_BTN_OPEN", "SB": "05_SB_OPEN",
}
DEFEND_NODE = {
    ("UTG", "HJ"): "06_HJ_VS_UTG",
    ("UTG", "CO"): "07_CO_VS_UTG",
    ("UTG", "BTN"): "08_BTN_VS_UTG",
    ("UTG", "SB"): "09_SB_VS_UTG",
    ("UTG", "BB"): "10_BB_VS_UTG",
    ("HJ", "CO"): "11_CO_VS_HJ",
    ("HJ", "BTN"): "12_BTN_VS_HJ",
    ("HJ", "SB"): "13_SB_VS_HJ",
    ("HJ", "BB"): "14_BB_VS_HJ",
    ("CO", "BTN"): "15_BTN_VS_CO",
    ("CO", "SB"): "16_SB_VS_CO",
    ("CO", "BB"): "17_BB_VS_CO",
    ("BTN", "SB"): "18_SB_VS_BTN",
    ("BTN", "BB"): "19_BB_VS_BTN",
    ("SB", "BB"): "20_BB_VS_SB",
}
THREEBET_SIZE_BB = {
    ("UTG", "HJ"): 6.5, ("UTG", "CO"): 6.5, ("UTG", "BTN"): 7.5,
    ("UTG", "SB"): 10.0, ("UTG", "BB"): 12.0,
    ("HJ", "CO"): 6.5, ("HJ", "BTN"): 7.5, ("HJ", "SB"): 11.0,
    ("HJ", "BB"): 12.3,
    ("CO", "BTN"): 7.5, ("CO", "SB"): 11.5, ("CO", "BB"): 13.5,
    ("BTN", "SB"): 12.0, ("BTN", "BB"): 13.0,
    ("SB", "BB"): 10.0,
}
BASE_DEFENSE = {
    ("UTG", "HJ"): (8.9, 0.0),
    ("UTG", "CO"): (9.0, 1.4),
    ("UTG", "BTN"): (7.6, 6.8),
    ("UTG", "SB"): (6.3, 6.2),
    ("UTG", "BB"): (5.2, 32.6),
    ("HJ", "CO"): (10.9, 0.7),
    ("HJ", "BTN"): (9.4, 5.6),
    ("HJ", "SB"): (7.5, 6.4),
    ("HJ", "BB"): (6.1, 37.0),
    ("CO", "BTN"): (12.2, 3.5),
    ("CO", "SB"): (10.6, 2.3),
    ("CO", "BB"): (9.0, 27.0),
    ("BTN", "SB"): (15.0, 0.5),
    ("BTN", "BB"): (13.9, 25.8),
    ("SB", "BB"): (17.2, 35.2),
}
# Canonical 169-class order: suited hands are upper-triangle labels, and
# offsuit labels always keep the higher rank first (for example, AKo not KAo).
HAND_ORDER = [
    (RANKS[r] * 2 if r == c else
     (RANKS[r] + RANKS[c] + "s" if r < c
      else RANKS[c] + RANKS[r] + "o"))
    for r in range(13) for c in range(13)
]
_DATA_B64 = (
    "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"
    "yRThQkJpCJ+A"
)
_CACHE: dict[str, Any] | None = None


@dataclass(frozen=True)
class PreflopGTODecision:
    player_id: str
    action: str
    amount: int | None
    source: str
    node_id: str
    hand_class: str
    action_frequency: float
    inferred: bool = False
    size_source: str = "screenshot"


def _data() -> dict[str, Any]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    compact = json.loads(bz2.decompress(base64.b64decode(_DATA_B64)))
    nodes = []
    nodes_by_id = {}
    rows = []
    for raw in compact.get("nodes", ()):
        actions = list(raw.get("a", ()))
        sizes = dict(raw.get("z", {}))
        hands: dict[str, list[dict[str, Any]]] = {}
        for hand_class, frequencies in zip(HAND_ORDER, raw.get("h", ())):
            hand_actions = []
            p: dict[str, float] = {}
            for action, units in zip(actions, frequencies):
                frequency = max(0.0, min(1.0, int(units) / 10000.0))
                p[action] = frequency
                if frequency > 0.00005:
                    hand_actions.append({
                        "action": action,
                        "frequency": frequency,
                        "amount_bb": sizes.get(action),
                    })
            if hand_actions:
                hands[hand_class] = hand_actions
                rows.append({
                    "node": raw["i"], "hand": hand_class, "p": p,
                })
        node = {
            "id": raw["i"],
            "description": raw.get("d", ""),
            "source_image": raw.get("p", ""),
            "action_totals": dict(raw.get("t", {})),
            "hands": hands,
            "active_range": bool(raw.get("r", False)),
        }
        nodes.append(node)
        nodes_by_id[node["id"]] = node
    # UTG first-in is not separately shown in the screenshots. Infer it from
    # the HJ/early-position open pattern, tightened to an approximately 17.5% range.
    if "01_UTG_OPEN" not in nodes_by_id:
        inferred_hands = {}
        utg_spot = {
            "kind": "open", "actor_position": "UTG",
            "effective_stack_bb": 100.0, "node_id": None,
        }
        for hand_class in HAND_ORDER:
            inferred_hands[hand_class] = _inferred_hand_actions(utg_spot, hand_class)
        utg_node = {
            "id": "01_UTG_OPEN",
            "description": "UTG first-in open to 2.0 BB (inferred from adjacent positions)",
            "source_image": "inferred from HJ/CO/BTN size and range progression",
            "action_totals": {"raise": 17.5, "fold": 82.5},
            "hands": inferred_hands,
            "active_range": False,
            "inferred": True,
        }
        nodes.insert(0, utg_node)
        nodes_by_id[utg_node["id"]] = utg_node
        for hand_class, choices in inferred_hands.items():
            p = {item["action"]: item["frequency"] for item in choices}
            rows.append({"node": "01_UTG_OPEN", "hand": hand_class, "p": p})
    _CACHE = {
        "schema": 2,
        "game": compact.get("g", "6-max cash"),
        "node_count": len(nodes),
        "source_images": len(compact.get("nodes", ())),
        "archive_screenshots": 174,
        "inference_enabled": True,
        "nodes": nodes,
        "nodes_by_id": nodes_by_id,
        "rows": rows,
        "method": (
            "27 screenshot-derived core nodes; hand-class matrix calibrated to "
            "the screenshot's aggregate action frequencies. Missing branches use "
            "position/action/size/stack/hand-class rule inference."
        ),
    }
    return _CACHE


def _hand_class(cards: Any) -> str | None:
    try:
        items = [str(card) for card in list(cards or ())]
    except Exception:
        return None
    if len(items) != 2 or items[0][0] not in RANKS or items[1][0] not in RANKS:
        return None
    r1, r2 = items[0][0], items[1][0]
    if r1 == r2:
        return r1 * 2
    i1, i2 = RANKS.index(r1), RANKS.index(r2)
    high, low = (r1, r2) if i1 < i2 else (r2, r1)
    return high + low + ("s" if items[0][1:2] == items[1][1:2] else "o")


def hand_class_from_cards(cards: Any) -> str | None:
    return _hand_class(cards)

def _position_map(table: Any, hand: Any) -> dict[str, str]:
    players = list(getattr(hand, "players", ()) or ())
    if len(players) != 6:
        positions = {}
        for p in players:
            pid = str(getattr(p, "player_id", ""))
            pos = str(getattr(p, "position", "")).upper()
            if pid and pos in PREFLOP_ORDER:
                positions[pid] = pos
        return positions
    dealer = getattr(table, "dealer_index", None)
    if dealer is None:
        dealer = getattr(hand, "dealer_index", None)
    try:
        dealer = int(dealer) % 6
    except (TypeError, ValueError, OverflowError):
        return {}
    seat_by_id = getattr(hand, "seat_by_id", {}) or {}
    result = {}
    for index, player in enumerate(players):
        pid = str(getattr(player, "player_id", ""))
        if not pid:
            continue
        try:
            seat = (
                int(seat_by_id[pid]) % 6
                if isinstance(seat_by_id, dict) and pid in seat_by_id else index
            )
        except (TypeError, ValueError, OverflowError):
            continue
        result[pid] = POSITIONS[(seat - dealer) % 6]
    return result


def _normalise_action(event: Any) -> str:
    if isinstance(event, dict):
        value = event.get("action") or event.get("decision") or event.get("type") or ""
    else:
        value = event
    action = str(value).lower().replace("-", "_").replace(" ", "_")
    if "fold" in action or action == "muck":
        return "fold"
    if "allin" in action or "all_in" in action or "jam" in action or "shove" in action:
        return "allin"
    if "raise" in action or action in {"bet", "open", "iso_raise", "three_bet", "four_bet"}:
        return "raise"
    if "check" in action:
        return "check"
    if "call" in action or action in {"complete", "limp"}:
        return "call"
    return action


def _big_blind(hand: Any, table: Any = None) -> int:
    for obj in (hand, table):
        if obj is None:
            continue
        for name in ("big_blind", "big_blind_amount", "bb_amount"):
            value = getattr(obj, name, None)
            try:
                amount = int(value)
                if amount > 0:
                    return amount
            except (TypeError, ValueError, OverflowError):
                pass
    return 100


def _event_target_bb(event: dict[str, Any], bb: int) -> float:
    for key in ("target", "raise_to", "to_amount", "total_contribution"):
        value = event.get(key)
        if value is not None:
            try:
                return max(0.0, float(value) / max(1, bb))
            except (TypeError, ValueError, OverflowError):
                pass
    value = event.get("amount", event.get("paid", 0))
    try:
        return max(0.0, float(value) / max(1, bb))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _preflop_records(
    table: Any, hand: Any, positions: dict[str, str],
    events: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    bb = _big_blind(hand, table)
    output = []
    raw_events = events if events is not None else list(getattr(hand, "events", ()) or ())
    players = list(getattr(hand, "players", ()) or ())
    id_by_name = {
        str(getattr(p, "name", "")): str(getattr(p, "player_id", ""))
        for p in players if str(getattr(p, "name", ""))
    }
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        street = str(event.get("street", "preflop")).lower().replace("-", "")
        if street not in {"preflop", "pre"}:
            continue
        action = _normalise_action(event)
        if action not in {"fold", "call", "check", "raise", "allin"}:
            continue
        raw_pid = str(event.get("player_id") or event.get("player") or "")
        pid = raw_pid if raw_pid in positions else id_by_name.get(raw_pid, raw_pid)
        pos = positions.get(pid)
        if not pos:
            continue
        output.append({
            "player_id": pid,
            "position": pos,
            "action": action,
            "amount_bb": _event_target_bb(event, bb),
            "event": event,
        })
    return output


def _same_size(actual: float, expected: float, tolerance: float = 0.12) -> bool:
    return abs(float(actual) - float(expected)) <= max(
        tolerance, abs(float(expected)) * 0.04
    )


def _resolve_spot(
    table: Any, hand: Any, player_id: str,
    prior_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    positions = _position_map(table, hand)
    actor_pos = positions.get(str(player_id))
    records = _preflop_records(table, hand, positions, prior_events)
    raises = [r for r in records if r["action"] in {"raise", "allin"}]
    calls = [r for r in records if r["action"] == "call"]
    bb = _big_blind(hand, table)
    eff = _effective_stack_bb(hand, player_id, positions, bb)
    spot = {
        "actor_id": str(player_id), "actor_position": actor_pos,
        "positions": positions, "records": records, "raises": raises,
        "calls": calls, "raise_count": len(raises), "call_count": len(calls),
        "effective_stack_bb": eff, "node_id": None, "kind": "uncovered",
        "opener_position": None, "opener_id": None,
        "open_size_bb": 0.0, "last_raise_bb": 0.0,
        "threebettor_position": None, "threebettor_id": None,
        "active_range": False,
    }
    if not actor_pos:
        return spot

    if not raises:
        if not calls:
            spot["kind"] = "open"
            spot["node_id"] = OPEN_NODE.get(actor_pos)
            return spot
        spot["kind"] = "limp_pot"
        if actor_pos == "BB" and len(calls) == 1 and calls[0]["position"] == "SB":
            spot["node_id"] = "21_BB_VS_SB_LIMP"
        return spot

    opener = raises[0]
    spot["opener_position"] = opener["position"]
    spot["opener_id"] = opener["player_id"]
    spot["open_size_bb"] = opener["amount_bb"]
    spot["last_raise_bb"] = raises[-1]["amount_bb"]

    if len(raises) == 1:
        spot["kind"] = "vs_open" if not calls else "multiway_vs_open"
        if not calls:
            node_id = DEFEND_NODE.get((opener["position"], actor_pos))
            standard = OPEN_SIZE_BB.get(opener["position"], opener["amount_bb"])
            if node_id and _same_size(opener["amount_bb"], standard, 0.10):
                spot["node_id"] = node_id
        spot["active_range"] = False
        return spot

    if len(raises) == 2:
        threebettor = raises[1]
        spot["threebettor_position"] = threebettor["position"]
        spot["threebettor_id"] = threebettor["player_id"]
        if str(player_id) == opener["player_id"]:
            spot["kind"] = "vs_3bet_original_opener"
            if (
                opener["position"] == "UTG"
                and threebettor["position"] == "HJ"
                and _same_size(opener["amount_bb"], 2.0, 0.10)
                and _same_size(threebettor["amount_bb"], 6.5, 0.20)
            ):
                spot["node_id"] = "25_UTG_VS_HJ_3BET"
                spot["active_range"] = True
            elif (
                opener["position"] == "BTN"
                and threebettor["position"] == "BB"
                and _same_size(opener["amount_bb"], 2.5, 0.10)
                and _same_size(threebettor["amount_bb"], 13.0, 0.30)
            ):
                spot["node_id"] = "26_BTN_VS_BB_3BET"
                spot["active_range"] = True
            return spot

        spot["kind"] = "cold_4bet"
        if (
            opener["position"] == "UTG"
            and threebettor["position"] == "HJ"
            and _same_size(opener["amount_bb"], 2.0, 0.10)
            and _same_size(threebettor["amount_bb"], 6.5, 0.20)
        ):
            spot["node_id"] = {
                "CO": "22_CO_COLD4BET_UTG_HJ",
                "BTN": "23_BTN_COLD4BET_UTG_HJ",
                "BB": "24_BB_COLD4BET_UTG_HJ",
            }.get(actor_pos)
        return spot

    if len(raises) == 3:
        spot["kind"] = "vs_4bet"
        if (
            opener["position"] == "BTN"
            and raises[1]["position"] == "BB"
            and raises[2]["position"] == "BTN"
            and _same_size(opener["amount_bb"], 2.5, 0.10)
            and _same_size(raises[1]["amount_bb"], 13.0, 0.30)
            and _same_size(raises[2]["amount_bb"], 27.0, 0.40)
            and actor_pos == "BB"
        ):
            spot["node_id"] = "27_BB_VS_BTN_4BET"
            spot["active_range"] = True
        return spot

    if len(raises) >= 4:
        spot["kind"] = "vs_5bet_or_later"
        if (
            opener["position"] == "BTN"
            and actor_pos == "BTN"
            and _same_size(opener["amount_bb"], 2.5, 0.10)
            and _same_size(raises[1]["amount_bb"], 13.0, 0.30)
            and _same_size(raises[2]["amount_bb"], 27.0, 0.40)
            and raises[-1]["action"] == "allin"
        ):
            spot["node_id"] = "28_BTN_VS_BB_5BET"
            spot["active_range"] = True
        return spot
    return spot


def _effective_stack_bb(hand: Any, player_id: str,
                        positions: dict[str, str], bb: int) -> float:
    players = list(getattr(hand, "players", ()) or ())
    by_id = {str(getattr(p, "player_id", "")): p for p in players}
    hero = by_id.get(str(player_id))
    try:
        effective = max(0.0, float(getattr(hero, "stack", 0) or 0)
                        + float(getattr(hero, "street_contribution", 0) or 0)) / max(1, bb)
    except (TypeError, ValueError, OverflowError):
        effective = 100.0
    for pid in positions:
        if pid == str(player_id):
            continue
        p = by_id.get(pid)
        if p is None or not bool(getattr(p, "eligible", True)):
            continue
        try:
            other = (
                float(getattr(p, "stack", 0) or 0)
                + float(getattr(p, "street_contribution", 0) or 0)
            ) / max(1, bb)
            effective = min(effective, max(0.0, other))
        except (TypeError, ValueError, OverflowError):
            continue
    return max(1.0, min(200.0, effective))


def _combos_for_class(hand_class: str) -> list[tuple[str, str]]:
    if not hand_class or len(hand_class) not in (2, 3):
        return []
    if hand_class[0] not in RANKS or hand_class[1] not in RANKS:
        return []
    a, b = hand_class[0], hand_class[1]
    if a == b:
        cards = [a + s for s in SUITS]
        return [(cards[i], cards[j]) for i in range(4) for j in range(i + 1, 4)]
    combos = []
    if len(hand_class) == 3 and hand_class[2] == "s":
        for suit in SUITS:
            combos.append((a + suit, b + suit))
    else:
        for s1 in SUITS:
            for s2 in SUITS:
                if s1 != s2:
                    combos.append((a + s1, b + s2))
    return combos


def _combo_count(hand_class: str) -> int:
    return 6 if len(hand_class) == 2 else (4 if hand_class.endswith("s") else 12)


def _rank_value(rank: str) -> int:
    return 14 - RANKS.index(rank)


def _hand_strength_features(hand_class: str) -> tuple[float, float, float]:
    a, b = hand_class[0], hand_class[1]
    ra, rb = _rank_value(a), _rank_value(b)
    if a == b:
        base = 0.58 + (ra - 2) * 0.035
        return min(1.0, base), min(1.0, base + 0.015), min(1.0, base - 0.01)
    high, low = max(ra, rb), min(ra, rb)
    suited = hand_class.endswith("s")
    gap = high - low - 1
    broadways = int(high >= 10) + int(low >= 10)
    base = 0.12 + (high - 2) * 0.022 + (low - 2) * 0.010
    base += 0.072 * broadways
    base += 0.085 if suited else 0.0
    base += 0.055 if gap == 0 else 0.035 if gap == 1 else 0.015 if gap == 2 else 0.0
    base -= min(0.12, max(0, gap - 3) * 0.018)
    if a == "A":
        base += 0.025
        if suited and low <= 5:
            base += 0.035
    base = max(0.0, min(1.0, base))
    raise_score = base
    if suited and a == "A":
        raise_score += 0.025
    if suited and gap <= 1:
        raise_score += 0.012
    if a == "A" and b in "KQJ":
        raise_score += 0.015
    call_score = base + (0.025 if suited else 0.0) + (0.018 if gap <= 2 else 0.0)
    if hand_class.endswith("o") and a == "A" and b in "KQJ":
        call_score += 0.018
    return base, min(1.0, raise_score), min(1.0, call_score)


def _combo_mass_average(values: dict[str, float]) -> float:
    return sum(_combo_count(k) * float(v) for k, v in values.items()) / 1326.0


def _sigmoid(x: float) -> float:
    if x > 25.0:
        return 1.0
    if x < -25.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _frequency_by_score(scores: dict[str, float], target: float,
                        smooth: float = 0.024) -> dict[str, float]:
    target = max(0.0, min(1.0, float(target)))
    if target <= 0.0:
        return {k: 0.0 for k in scores}
    if target >= 1.0:
        return {k: 1.0 for k in scores}
    lo, hi = min(scores.values()) - 1.0, max(scores.values()) + 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        probs = {k: _sigmoid((v - mid) / max(0.001, smooth))
                 for k, v in scores.items()}
        if _combo_mass_average(probs) > target:
            lo = mid
        else:
            hi = mid
    cut = (lo + hi) / 2.0
    return {k: _sigmoid((v - cut) / max(0.001, smooth))
            for k, v in scores.items()}


def _residual_frequency(scores: dict[str, float],
                        residual: dict[str, float],
                        target: float,
                        smooth: float = 0.028) -> dict[str, float]:
    target = max(0.0, min(1.0, float(target)))
    base_mass = _combo_mass_average(residual)
    if target <= 0.0 or base_mass <= 0.0:
        return {k: 0.0 for k in scores}
    max_mass = base_mass
    target = min(target, max_mass)
    lo, hi = min(scores.values()) - 1.0, max(scores.values()) + 1.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        probs = {
            k: residual.get(k, 0.0) * _sigmoid((scores[k] - mid) / max(0.001, smooth))
            for k in scores
        }
        if _combo_mass_average(probs) > target:
            lo = mid
        else:
            hi = mid
    cut = (lo + hi) / 2.0
    return {
        k: residual.get(k, 0.0) * _sigmoid((scores[k] - cut) / max(0.001, smooth))
        for k in scores
    }


def _threebet_size(opener: str, actor: str, open_size: float,
                   effective_stack: float, multiway: bool = False) -> float:
    base = THREEBET_SIZE_BB.get((opener, actor))
    if base is None:
        ip = _is_in_position(actor, opener)
        factor = 3.25 if ip else 5.0
        if actor == "BB" and opener == "SB":
            factor = 3.33
        if actor == "BB" and opener in {"CO", "BTN"}:
            factor = 5.2
        base = open_size * factor
        base = round(base * 2.0) / 2.0
    standard_open = OPEN_SIZE_BB.get(opener, open_size)
    if standard_open and not _same_size(open_size, standard_open, 0.10):
        base *= max(0.70, float(open_size) / standard_open)
    if multiway:
        base += 0.5 if _is_in_position(actor, opener) else 1.0
    if effective_stack < 99.0:
        base = 2.0 + (base - 2.0) * math.sqrt(max(0.05, effective_stack / 100.0))
    return max(2.0, min(base, max(2.0, effective_stack - 0.5)))


def _is_in_position(actor: str, opener: str) -> bool:
    if actor == "BB" and opener == "SB":
        return True
    if actor in {"CO", "BTN"} and opener in {"UTG", "HJ", "CO", "BTN"}:
        return PREFLOP_ORDER.get(actor, -1) > PREFLOP_ORDER.get(opener, 99)
    return False


def _infer_4bet_size(spot: dict[str, Any]) -> float:
    last_raise = max(2.0, float(spot.get("last_raise_bb") or 6.5))
    actor, threebettor = spot.get("actor_position"), spot.get("threebettor_position")
    if actor == spot.get("opener_position"):
        if (
            spot.get("opener_position") == "UTG"
            and threebettor == "HJ"
            and _same_size(float(spot.get("open_size_bb", 0)), 2.0, 0.10)
            and _same_size(last_raise, 6.5, 0.20)
        ):
            return 19.0
        return min(
            max(10.0, last_raise * 2.1),
            max(10.0, spot.get("effective_stack_bb", 100.0) - 0.5),
        )
    ip = _is_in_position(actor or "", threebettor or "")
    factor = 2.15 if ip else 2.9
    target = last_raise * factor
    if actor == "BB" and spot.get("opener_position") == "UTG":
        target = max(target, 19.0)
    if spot.get("effective_stack_bb", 100.0) < 99.0:
        target = 2.0 + (target - 2.0) * math.sqrt(
            max(0.05, spot.get("effective_stack_bb", 100.0) / 100.0)
        )
    return min(target, max(2.0, spot.get("effective_stack_bb", 100.0) - 0.5))


def _inferred_hand_actions(spot: dict[str, Any],
                           hand_class: str) -> list[dict[str, Any]]:
    base, raise_score, call_score = _hand_strength_features(hand_class)
    scores = {hand_class: base}
    # Build full 169-class score tables so every inferred node uses a coherent,
    # combo-weighted range rather than deciding each hand in isolation.
    base_scores, raise_scores, call_scores = {}, {}, {}
    for cls in HAND_ORDER:
        b, r, c = _hand_strength_features(cls)
        base_scores[cls], raise_scores[cls], call_scores[cls] = b, r, c

    kind = spot.get("kind")
    actor = spot.get("actor_position") or "UTG"
    opener = spot.get("opener_position") or "UTG"
    eff = float(spot.get("effective_stack_bb", 100.0))
    actions: dict[str, float] = {}
    sizes: dict[str, float | None] = {}

    if kind == "open":
        raise_pct = {"UTG": 17.5, "HJ": 19.6, "CO": 28.9, "BTN": 42.0, "SB": 37.5}.get(actor, 17.5)
        raise_prob = _frequency_by_score(raise_scores, raise_pct / 100.0)
        actions["raise"] = raise_prob[hand_class]
        sizes["raise"] = OPEN_SIZE_BB.get(actor, 2.0)
        if actor == "SB":
            residual = {k: 1.0 - v for k, v in _frequency_by_score(raise_scores, raise_pct / 100.0).items()}
            call_prob = _residual_frequency(call_scores, residual, 0.111)
            actions["call"] = call_prob[hand_class]
            sizes["call"] = None
        actions["fold"] = max(0.0, 1.0 - sum(actions.values()))
        sizes["fold"] = None
    elif kind in {"vs_open", "multiway_vs_open"}:
        raise_pct, call_pct = BASE_DEFENSE.get((opener, actor), (8.0, 3.0))
        open_size = float(spot.get("open_size_bb", OPEN_SIZE_BB.get(opener, 2.0)))
        standard = OPEN_SIZE_BB.get(opener, open_size)
        ratio = open_size / max(0.5, standard)
        if ratio > 1.0:
            raise_pct *= max(0.58, 1.0 - 0.20 * (ratio - 1.0))
            call_pct *= max(0.70, 1.0 - 0.10 * (ratio - 1.0))
        if kind == "multiway_vs_open":
            raise_pct *= 0.72
            call_pct *= 0.82
        raise_prob = _frequency_by_score(raise_scores, raise_pct / 100.0)
        actions["raise"] = raise_prob[hand_class]
        sizes["raise"] = _threebet_size(
            opener, actor, open_size, eff, multiway=(kind == "multiway_vs_open")
        )
        residual = {k: max(0.0, 1.0 - v) for k, v in raise_prob.items()}
        call_prob = _residual_frequency(call_scores, residual, call_pct / 100.0)
        actions["call"] = call_prob[hand_class]
        sizes["call"] = None
        actions["fold"] = max(0.0, 1.0 - sum(actions.values()))
        sizes["fold"] = None
    elif kind == "limp_pot":
        if actor == "BB":
            raise5 = _frequency_by_score(raise_scores, 0.213)
            residual = {k: 1.0 - v for k, v in raise5.items()}
            raise3 = _residual_frequency(call_scores, residual, 0.162)
            actions["raise5"] = raise5[hand_class]
            actions["raise3"] = raise3[hand_class]
            actions["check"] = max(0.0, 1.0 - actions["raise5"] - actions["raise3"])
            sizes.update({"raise5": 5.0, "raise3": 3.0, "check": None})
        else:
            actions["call"] = 0.12
            actions["fold"] = 0.88
            sizes.update({"call": None, "fold": None})
    elif kind in {"vs_3bet_original_opener", "cold_4bet"}:
        target = _infer_4bet_size(spot)
        cold = kind == "cold_4bet"
        raise_pct = 3.5 if cold else 6.0
        call_pct = 0.0 if cold else 18.0
        allin_pct = 0.3 if cold and actor == "BB" else (1.2 if not cold else 0.0)
        allin_prob = _frequency_by_score(raise_scores, allin_pct / 100.0)
        residual1 = {k: 1.0 - v for k, v in allin_prob.items()}
        raise_prob = _residual_frequency(raise_scores, residual1, raise_pct / 100.0)
        residual2 = {k: max(0.0, 1.0 - allin_prob[k] - raise_prob[k]) for k in HAND_ORDER}
        call_prob = _residual_frequency(call_scores, residual2, call_pct / 100.0)
        actions["allin"] = allin_prob[hand_class]
        actions["raise"] = raise_prob[hand_class]
        actions["call"] = call_prob[hand_class]
        actions["fold"] = max(0.0, 1.0 - sum(actions.values()))
        sizes.update({"allin": eff, "raise": target, "call": None, "fold": None})
    elif kind in {"vs_4bet", "vs_5bet_or_later"}:
        allin_pct = 8.0 if kind == "vs_4bet" else 5.0
        call_pct = 10.0 if kind == "vs_4bet" else 7.0
        allin_prob = _frequency_by_score(raise_scores, allin_pct / 100.0)
        residual = {k: 1.0 - v for k, v in allin_prob.items()}
        call_prob = _residual_frequency(call_scores, residual, call_pct / 100.0)
        actions["allin"] = allin_prob[hand_class]
        actions["call"] = call_prob[hand_class]
        actions["fold"] = max(0.0, 1.0 - sum(actions.values()))
        sizes.update({"allin": eff, "call": None, "fold": None})
    else:
        # Conservative but active extrapolation for unusual/uncovered preflop lines.
        if spot.get("raise_count", 0) <= 0:
            actions["raise"] = _frequency_by_score(raise_scores, 0.17)[hand_class]
            sizes["raise"] = OPEN_SIZE_BB.get(actor, 2.0)
            actions["fold"] = 1.0 - actions["raise"]
            sizes["fold"] = None
        else:
            actions["fold"] = 1.0
            sizes["fold"] = None

    return [
        {"action": a, "frequency": max(0.0, min(1.0, p)),
         "amount_bb": sizes.get(a)}
        for a, p in actions.items() if p > 0.00005
    ]


def _actions_for_hand(spot: dict[str, Any], hand_class: str) -> tuple[list[dict[str, Any]], bool]:
    node_id = spot.get("node_id")
    if node_id:
        node = _data()["nodes_by_id"].get(node_id)
        if node is not None:
            items = node["hands"].get(hand_class)
            if items:
                return items, bool(node.get("inferred", False))
            if node.get("active_range"):
                # This hand is outside the previous-action range. Keep the CPU
                # from pretending the screenshot has evidence for an impossible combo.
                return _inferred_hand_actions(spot, hand_class), True
    return _inferred_hand_actions(spot, hand_class), True


def _canonical_action(action: str) -> str:
    if action.startswith("raise"):
        return "raise"
    return action


def _legal_choices(hand: Any, player_id: str,
                   actions: list[dict[str, Any]], bb: int) -> list[dict[str, Any]]:
    legal = hand.legal_actions(player_id)
    legal_actions = {
        str(x).lower().replace("-", "_")
        for x in legal.get("actions", ())
    }
    to_call = max(0, int(legal.get("to_call", 0) or 0))
    can_raise = bool(legal.get("raise_allowed")) and (
        "raise" in legal_actions or "bet" in legal_actions
    )
    min_target = int(legal.get("min_target", 0) or 0)
    max_target = int(legal.get("max_target", 0) or 0)
    output = []
    for item in actions:
        action = str(item.get("action", "")).lower()
        freq = max(0.0, float(item.get("frequency", 0.0)))
        if freq <= 0:
            continue
        if action.startswith("raise"):
            if not can_raise:
                continue
            size_bb = item.get("amount_bb")
            if size_bb is None:
                continue
            target = int(round(float(size_bb) * bb))
            if target < min_target or target > max_target:
                continue
            output.append({
                "action": "raise" if "raise" in legal_actions else "bet",
                "amount": target, "frequency": freq,
                "amount_bb": float(size_bb), "source_action": action,
            })
        elif action == "allin":
            if "all_in" in legal_actions or "allin" in legal_actions:
                output.append({
                    "action": "all_in" if "all_in" in legal_actions else "allin",
                    "amount": None, "frequency": freq, "amount_bb": None,
                    "source_action": action,
                })
            elif can_raise and max_target > 0:
                output.append({
                    "action": "raise" if "raise" in legal_actions else "bet",
                    "amount": max_target, "frequency": freq,
                    "amount_bb": max_target / max(1, bb), "source_action": action,
                })
        elif action in {"call", "limp"}:
            if "call" in legal_actions and to_call > 0:
                output.append({
                    "action": "call", "amount": None, "frequency": freq,
                    "amount_bb": None, "source_action": action,
                })
            elif "check" in legal_actions and to_call == 0:
                output.append({
                    "action": "check", "amount": None, "frequency": freq,
                    "amount_bb": None, "source_action": action,
                })
        elif action == "check":
            if "check" in legal_actions and to_call == 0:
                output.append({
                    "action": "check", "amount": None, "frequency": freq,
                    "amount_bb": None, "source_action": action,
                })
        elif action == "fold":
            if "fold" in legal_actions:
                output.append({
                    "action": "fold", "amount": None, "frequency": freq,
                    "amount_bb": None, "source_action": action,
                })
    return output


def choose_preflop_action(
    table: Any, hand: Any, player_id: str, cpu: Any,
    range_estimator: Any = None,
) -> PreflopGTODecision:
    legal = hand.legal_actions(player_id)
    if not legal.get("actions"):
        raise ValueError("No legal preflop action is available")
    player = hand.player(player_id)
    hand_class = _hand_class(getattr(player, "hole_cards", ())) or "72o"
    spot = _resolve_spot(table, hand, player_id)
    raw, inferred = _actions_for_hand(spot, hand_class)
    choices = _legal_choices(hand, player_id, raw, _big_blind(hand, table))
    if not choices:
        legal_actions = {str(x).lower().replace("-", "_") for x in legal.get("actions", ())}
        fallback = "check" if "check" in legal_actions and int(legal.get("to_call", 0) or 0) == 0 else (
            "fold" if "fold" in legal_actions else "call" if "call" in legal_actions else next(iter(legal_actions))
        )
        return PreflopGTODecision(
            player_id=str(player_id), action=fallback, amount=None,
            source="gto-inferred-legal-fallback",
            node_id=str(spot.get("node_id") or "INFERRED"),
            hand_class=hand_class, action_frequency=1.0, inferred=True,
            size_source="legal-action-fallback",
        )
    total = sum(x["frequency"] for x in choices)
    if total <= 0:
        chosen = choices[0]
    else:
        rng = getattr(cpu, "rng", None) or random.Random()
        pick = float(rng.random()) * total
        chosen = choices[-1]
        for option in choices:
            pick -= option["frequency"]
            if pick <= 0:
                chosen = option
                break
    exact = not inferred
    return PreflopGTODecision(
        player_id=str(player_id),
        action=chosen["action"],
        amount=chosen["amount"],
        source="new-screenshot-gto" if exact else "gto-rule-inference",
        node_id=str(spot.get("node_id") or "INFERRED"),
        hand_class=hand_class,
        action_frequency=float(chosen["frequency"]),
        inferred=not exact,
        size_source="screenshot" if exact else "position-history-stack-rule",
    )


def _modal_size_from_node(node: dict[str, Any]) -> float | None:
    node_hands = node.get("hands", {})
    totals: dict[float, float] = {}
    for hand_class, choices in node_hands.items():
        mass = _combo_count(hand_class)
        for item in choices:
            action = str(item.get("action", ""))
            amount = item.get("amount_bb")
            if action.startswith("raise") and amount is not None:
                size = float(amount)
                totals[size] = totals.get(size, 0.0) + mass * float(item.get("frequency", 0.0))
    if not totals:
        return None
    return max(totals.items(), key=lambda item: (item[1], -item[0]))[0]


def _infer_spot_size(spot: dict[str, Any]) -> float | None:
    kind = spot.get("kind")
    actor = spot.get("actor_position") or "UTG"
    opener = spot.get("opener_position") or "UTG"
    eff = float(spot.get("effective_stack_bb", 100.0))
    if kind == "open":
        return OPEN_SIZE_BB.get(actor, 2.0)
    if kind in {"vs_open", "multiway_vs_open"}:
        return _threebet_size(
            opener, actor, float(spot.get("open_size_bb") or OPEN_SIZE_BB.get(opener, 2.0)),
            eff, multiway=(kind == "multiway_vs_open"),
        )
    if kind in {"vs_3bet_original_opener", "cold_4bet"}:
        return _infer_4bet_size(spot)
    return None


def preflop_gto_situation_size(
    table: Any, hand: Any, player_id: str,
) -> int | None:
    spot = _resolve_spot(table, hand, player_id)
    bb = _big_blind(hand, table)
    node_id = spot.get("node_id")
    if node_id:
        node = _data()["nodes_by_id"].get(node_id)
        if node is not None:
            size = _modal_size_from_node(node)
            # Screenshot nodes describe the 100 BB baseline. Preserve the
            # screenshot amount at baseline depth, but scale it down for
            # shorter effective stacks instead of proposing an oversized raise.
            effective_stack = float(spot.get("effective_stack_bb", 100.0))
            if size is not None and effective_stack < 99.0:
                stack_adjusted = _infer_spot_size(spot)
                if stack_adjusted is not None:
                    size = min(size, stack_adjusted)
            if size is not None:
                target = int(round(size * bb))
                legal = hand.legal_actions(player_id)
                min_target = int(legal.get("min_target", 0) or 0)
                max_target = int(legal.get("max_target", 0) or 0)
                if min_target <= target <= max_target:
                    return target
    size = _infer_spot_size(spot)
    if size is None:
        return None
    target = int(round(size * bb))
    legal = hand.legal_actions(player_id)
    min_target = int(legal.get("min_target", 0) or 0)
    max_target = int(legal.get("max_target", 0) or 0)
    if min_target > 0 and max_target >= min_target:
        if target < min_target or target > max_target:
            # Use the closest legal size without changing the human action.
            target = max(min_target, min(max_target, target))
    return target


def preflop_gto_action_options(
    table: Any, hand: Any, player_id: str,
) -> dict[str, Any]:
    player = hand.player(player_id)
    hand_class = _hand_class(getattr(player, "hole_cards", ())) or "72o"
    spot = _resolve_spot(table, hand, player_id)
    actions, inferred = _actions_for_hand(spot, hand_class)
    size = preflop_gto_situation_size(table, hand, player_id)
    return {
        "node_id": spot.get("node_id") or "INFERRED",
        "hand_class": hand_class,
        "actions": actions,
        "suggested_raise_target": size,
        "source": "gto-rule-inference" if inferred else "new-screenshot-gto",
        "inferred": inferred,
        "description": (
            _data()["nodes_by_id"].get(spot.get("node_id"), {}).get("description", "")
            if spot.get("node_id") else "Missing node inferred from the observed action history."
        ),
    }


def _observed_action_probability(
    choices: list[dict[str, Any]], action: str, amount_bb: float,
) -> float:
    total = 0.0
    for item in choices:
        item_action = str(item.get("action", ""))
        if action == "raise":
            if not item_action.startswith("raise"):
                continue
            size = item.get("amount_bb")
            if size is not None and amount_bb > 0 and not _same_size(float(size), amount_bb, 0.20):
                continue
        elif action == "allin":
            if item_action != "allin":
                continue
        elif action in {"call", "check", "fold"}:
            if item_action != action:
                continue
        total += float(item.get("frequency", 0.0))
    return total


def _classify_learned_behavior(learned: dict[str, Any]) -> tuple[str, str]:
    """Classify only from persistent observed behavior, never fabricate a screenshot-policy range."""
    sample = float(learned.get("sample_hands", 0.0) or 0.0)
    three_bet_opportunities = float(learned.get("three_bet_opportunities", 0.0) or 0.0)
    three_bet_rate = float(learned.get("three_bet_rate", 0.0) or 0.0)
    vpip = float(learned.get("vpip_rate", 0.0) or 0.0)
    pfr = float(learned.get("pfr_rate", 0.0) or 0.0)
    fold_to_bet = float(learned.get("fold_to_bet_rate", 0.5) or 0.0)
    postflop_actions = float(learned.get("postflop_actions", 0.0) or 0.0)
    postflop_call = float(learned.get("postflop_call_rate", 0.0) or 0.0)
    postflop_aggression = float(learned.get("postflop_aggression_rate", 0.0) or 0.0)
    if three_bet_opportunities >= 12.0 and three_bet_rate >= 0.20:
        return "aggressive", "three_bet_rate"
    if sample >= 10.0 and vpip >= 0.36 and pfr <= 0.24 and fold_to_bet <= 0.38:
        if postflop_actions < 8.0 or (postflop_call >= 0.42 and postflop_aggression <= 0.48):
            return "calling_station", "vpip_pfr_fold_to_bet"
    if sample >= 15.0 and vpip <= 0.22 and pfr <= 0.18:
        return "tight", "vpip_pfr"
    return "balanced", "smoothed_behavior_prior"


def estimate_preflop_opponent_ranges(
    table: Any,
    hand: Any,
    exclude_player_id: str | None = None,
    opponent_profiles: dict[str, Any] | None = None,
    opponent_learning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate opponent ranges from the new screenshot nodes and inferred branches."""
    positions = _position_map(table, hand)
    records = _preflop_records(table, hand, positions)
    players = list(getattr(hand, "players", ()) or ())
    hole_by_id = {
        str(getattr(p, "player_id", "")): tuple(
            str(card) for card in list(getattr(p, "hole_cards", ()) or ())
        )
        for p in players
    }
    hero_cards = set(hole_by_id.get(str(exclude_player_id), ())) if exclude_player_id else set()
    board = set(str(card) for card in list(getattr(hand, "board", ()) or ()))
    blockers = hero_cards | board
    prior: list[dict[str, Any]] = []
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        pid = record["player_id"]
        if pid == str(exclude_player_id or ""):
            prior.append(record)
            continue
        spot = _resolve_spot(table, hand, pid, prior_events=[
            r["event"] for r in prior if isinstance(r.get("event"), dict)
        ])
        action = record["action"]
        target_bb = float(record.get("amount_bb", 0.0))
        weights: dict[str, float] = {}
        inferred_any = False
        for hand_class in HAND_ORDER:
            choices, inferred = _actions_for_hand(spot, hand_class)
            inferred_any = inferred_any or inferred
            prob = _observed_action_probability(choices, action, target_bb)
            if prob > 0:
                weights[hand_class] = prob
        if not weights:
            # Unsupported custom line: use a broad, position-aware prior.
            fallback_spot = dict(spot)
            fallback_spot["kind"] = (
                "open" if not spot.get("raises") else "vs_open"
            )
            for hand_class in HAND_ORDER:
                weights[hand_class] = sum(
                    x["frequency"] for x in _inferred_hand_actions(fallback_spot, hand_class)
                    if x["action"] in ({"raise"} if action == "raise" else {action})
                )
            inferred_any = True
        # Apply known public and hero-card blockers to physical combinations.
        combos = []
        hand_class_mass: dict[str, float] = {}
        available_total = 0.0
        unblocked_total = 0.0
        for hand_class, weight in weights.items():
            physical = _combos_for_class(hand_class)
            available = [combo for combo in physical if not (set(combo) & blockers)]
            if not available or weight <= 0:
                continue
            class_mass = weight * len(available)
            hand_class_mass[hand_class] = class_mass
            available_total += len(available)
            unblocked_total += class_mass
            for combo in available:
                combos.append((combo, weight))
        total_mass = sum(weight for _, weight in combos)
        if total_mass > 0:
            combo_weights = tuple((combo, weight / total_mass) for combo, weight in combos)
            class_probs = {
                cls: mass / total_mass for cls, mass in hand_class_mass.items()
            }
        else:
            combo_weights = ()
            class_probs = {}
        profile = (opponent_profiles or {}).get(pid, {})
        learned = (opponent_learning or {}).get(pid, {})
        if isinstance(learned, dict) and isinstance(learned.get("stats"), dict):
            learned = learned["stats"]
        participation = 0.0 if action == "fold" else 1.0
        latest[pid] = {
            "supported": bool(class_probs),
            "hand_class_probabilities": class_probs,
            "unblocked_hand_class_probabilities": class_probs,
            "combo_probabilities": combo_weights,
            "combo_mass_without_hero_blockers": unblocked_total,
            "available_combos": available_total,
            "range_percent_of_available_combos": (
                100.0 * unblocked_total / max(1.0, available_total)
            ),
            "participation_probability": participation,
            "confidence": 0.88 if not inferred_any else 0.62,
            "source": "new screenshot node" if not inferred_any else "GTO rule inference",
            "method": "position/action/size-conditioned 6-max preflop GTO model",
            "archetype": (
                profile.get("learned_archetype")
                or profile.get("archetype") or "balanced"
            ) if isinstance(profile, dict) else "balanced",
            "learned_stats": learned if isinstance(learned, dict) else {},
            "learned_behavior": learned if isinstance(learned, dict) else {},
        }
        prior.append(record)

    # Include opponents who have not acted yet. They have no screenshot-policy-derived
    # hand range at this point, but persistent behavior is still a valid prior.
    acted_ids = {record["player_id"] for record in records}
    for player in players:
        pid = str(getattr(player, "player_id", ""))
        if not pid or pid == str(exclude_player_id or "") or pid in acted_ids:
            continue
        learned = (opponent_learning or {}).get(pid, {})
        if isinstance(learned, dict) and isinstance(learned.get("stats"), dict):
            learned = learned["stats"]
        if not isinstance(learned, dict):
            learned = {}
        learned_archetype, archetype_basis = _classify_learned_behavior(learned)
        sample_hands = max(0.0, float(learned.get("sample_hands", 0.0) or 0.0))
        vpip_rate = max(0.0, min(1.0, float(learned.get("vpip_rate", 0.0) or 0.0)))
        profile = (opponent_profiles or {}).get(pid, {})
        latest[pid] = {
            "supported": False,
            "reason": "behavior-profile-prior",
            "position": positions.get(pid),
            "hand_class_probabilities": {},
            "unblocked_hand_class_probabilities": {},
            "combo_probabilities": (),
            "participation_probability": vpip_rate if sample_hands >= 5.0 else 0.25,
            "confidence": min(0.72, sample_hands / (sample_hands + 35.0)),
            "source": "persistent CPU behavior profile",
            "method": "behavior prior only; no fabricated screenshot range",
            "archetype": learned_archetype if sample_hands >= 5.0 else (
                profile.get("learned_archetype") or profile.get("archetype") or "balanced"
            ) if isinstance(profile, dict) else "balanced",
            "learned_archetype": learned_archetype,
            "learned_archetype_basis": archetype_basis,
            "learned_stats": learned,
            "learned_behavior": learned,
        }

    if exclude_player_id is not None:
        latest.pop(str(exclude_player_id), None)
    return {
        "supported": True,
        "players": latest,
        "source": "new-preflop-gto-v2",
        "node_count": _data()["node_count"],
        "observed_action_count": len(records),
        "inference_enabled": True,
    }



def _node_for_actor(table: Any, hand: Any, actor_id: str) -> str | None:
    """Return the exact screenshot node when covered; otherwise None for inference."""
    return _resolve_spot(table, hand, actor_id).get("node_id")


def _node_for_situation_size(table: Any, hand: Any, actor_id: str) -> str | None:
    return _node_for_actor(table, hand, actor_id)

def coverage_summary() -> dict[str, Any]:
    data = _data()
    return {
        "schema": 2,
        "node_count": data["node_count"],
        "exact_screenshot_nodes": data["source_images"],
        "inferred_nodes": data["node_count"] - data["source_images"],
        "source_screenshots": data["source_images"],
        "archive_screenshots": data["archive_screenshots"],
        "missing_patterns": "inferred by position, action history, size, stack and hand strength",
        "open_sizes_bb": dict(OPEN_SIZE_BB),
        "fixed_2_5bb_opening": False,
    }
