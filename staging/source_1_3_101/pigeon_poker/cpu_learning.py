from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable


_COUNTERS = (
    "hands", "vpip_hands", "pfr_hands",
    "three_bet_opportunities", "three_bets",
    "four_bet_opportunities", "four_bets",
    "faced_bets", "folds_facing_bet",
    "postflop_actions", "postflop_aggressive", "postflop_calls",
    "cbet_opportunities", "cbets",
    "fold_to_cbet_opportunities", "folds_to_cbet",
)


def _action_name(event: dict[str, Any]) -> str:
    raw = str(event.get("action", "")).strip().lower().replace("-", "_").replace(" ", "_")
    if raw in {"all_in_call", "allin_call", "call_all_in", "called_all_in"}:
        return "call"
    if raw in {"call", "called"}:
        return "call"
    if raw in {"fold", "folded"}:
        return "fold"
    if raw in {"check", "checked"}:
        return "check"
    if raw in {"bet", "bet_to"}:
        return "bet"
    if raw in {"raise", "raise_to"}:
        return "raise"
    if event.get("is_all_in") or event.get("all_in") or event.get("jam"):
        return "raise"
    if raw in {"allin", "all_in", "jam", "shove"}:
        return "raise"
    return raw


def _integer(event: dict[str, Any], key: str, fallback: str | None = None) -> int:
    try:
        return max(0, int(event.get(key, event.get(fallback, 0) if fallback else 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


class CPULearningStore:
    """Persistent, per-CPU behavioral statistics derived only from public actions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cpu_behavior_stats (
                    stake TEXT NOT NULL,
                    cpu_id TEXT NOT NULL,
                    hands INTEGER NOT NULL DEFAULT 0,
                    vpip_hands INTEGER NOT NULL DEFAULT 0,
                    pfr_hands INTEGER NOT NULL DEFAULT 0,
                    three_bet_opportunities INTEGER NOT NULL DEFAULT 0,
                    three_bets INTEGER NOT NULL DEFAULT 0,
                    four_bet_opportunities INTEGER NOT NULL DEFAULT 0,
                    four_bets INTEGER NOT NULL DEFAULT 0,
                    faced_bets INTEGER NOT NULL DEFAULT 0,
                    folds_facing_bet INTEGER NOT NULL DEFAULT 0,
                    postflop_actions INTEGER NOT NULL DEFAULT 0,
                    postflop_aggressive INTEGER NOT NULL DEFAULT 0,
                    postflop_calls INTEGER NOT NULL DEFAULT 0,
                    cbet_opportunities INTEGER NOT NULL DEFAULT 0,
                    cbets INTEGER NOT NULL DEFAULT 0,
                    fold_to_cbet_opportunities INTEGER NOT NULL DEFAULT 0,
                    folds_to_cbet INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stake, cpu_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cpu_learning_hands (
                    stake TEXT NOT NULL,
                    hand_key TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (stake, hand_key)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=8.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=8000")
        return connection

    @staticmethod
    def _resolve_cpu_ids(hand: Any, cpu_ids: Iterable[str]) -> tuple[set[str], dict[str, str]]:
        wanted = {str(value) for value in cpu_ids if str(value)}
        name_to_id: dict[str, str] = {}
        for player in list(getattr(hand, "players", ()) or ()):
            player_id = str(getattr(player, "player_id", "") or "")
            name = str(getattr(player, "name", "") or "")
            if player_id in wanted and name:
                name_to_id[name] = player_id
        return wanted, name_to_id

    def record_hand(
        self,
        hand_key: str | None,
        stake: str,
        hand: Any,
        cpu_ids: Iterable[str],
    ) -> bool:
        """Record one completed hand once. No hole cards or hidden outcomes are inspected."""
        key = str(hand_key or "").strip()
        rate = str(stake or "").strip().upper()
        if not key or not rate:
            return False
        wanted, name_to_id = self._resolve_cpu_ids(hand, cpu_ids)
        if not wanted:
            return False

        deltas = {cpu_id: {name: 0 for name in _COUNTERS} for cpu_id in wanted}
        for values in deltas.values():
            values["hands"] = 1

        events = [
            event for event in list(getattr(hand, "events", ()) or ())
            if isinstance(event, dict) and event.get("type") == "action"
        ]
        preflop_raises = 0
        last_preflop_aggressor: str | None = None
        first_flop_action_by_player: set[str] = set()
        cbet_active = False
        cbet_aggressor: str | None = None

        for event in events:
            actor = str(event.get("player_id") or event.get("player") or "")
            actor = name_to_id.get(actor, actor)
            if actor not in wanted:
                if str(event.get("street", "preflop")).lower().replace("-", "") == "preflop":
                    if _action_name(event) == "raise":
                        preflop_raises += 1
                        last_preflop_aggressor = actor
                continue

            values = deltas[actor]
            street = str(event.get("street", "preflop")).lower().replace("-", "")
            action = _action_name(event)
            paid = _integer(event, "paid", "amount")
            to_call = _integer(event, "to_call_before")
            pot_before = max(1, _integer(event, "pot_before"))

            if street == "preflop":
                if action in {"call", "raise"} and (paid > 0 or action == "raise"):
                    values["vpip_hands"] = 1
                if action == "raise":
                    values["pfr_hands"] = 1
                    if preflop_raises == 1 and to_call > 0:
                        values["three_bet_opportunities"] += 1
                        values["three_bets"] += 1
                    elif preflop_raises >= 2 and to_call > 0:
                        values["four_bet_opportunities"] += 1
                        values["four_bets"] += 1
                    last_preflop_aggressor = actor
                    preflop_raises += 1
                elif to_call > 0 and preflop_raises == 1:
                    values["three_bet_opportunities"] += 1
                elif to_call > 0 and preflop_raises >= 2:
                    values["four_bet_opportunities"] += 1
                continue

            if street not in {"flop", "turn", "river"}:
                continue
            values["postflop_actions"] += 1
            if action in {"bet", "raise"}:
                values["postflop_aggressive"] += 1
            elif action == "call":
                values["postflop_calls"] += 1
            if to_call > 0:
                values["faced_bets"] += 1
                if action == "fold":
                    values["folds_facing_bet"] += 1
            if street == "flop" and cbet_active and actor != cbet_aggressor and to_call > 0:
                values["fold_to_cbet_opportunities"] += 1
                if action == "fold":
                    values["folds_to_cbet"] += 1

            if street == "flop" and actor not in first_flop_action_by_player:
                first_flop_action_by_player.add(actor)
                if actor == last_preflop_aggressor:
                    values["cbet_opportunities"] += 1
                    if action in {"bet", "raise"} and to_call == 0:
                        values["cbets"] += 1
                        cbet_active = True
                        cbet_aggressor = actor

        # Idempotency and aggregate increments share one transaction.
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "INSERT OR IGNORE INTO cpu_learning_hands(stake, hand_key) VALUES (?, ?)",
                (rate, key),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                return False
            for cpu_id, values in deltas.items():
                connection.execute(
                    """
                    INSERT INTO cpu_behavior_stats (
                        stake, cpu_id, hands, vpip_hands, pfr_hands,
                        three_bet_opportunities, three_bets,
                        four_bet_opportunities, four_bets,
                        faced_bets, folds_facing_bet,
                        postflop_actions, postflop_aggressive, postflop_calls,
                        cbet_opportunities, cbets,
                        fold_to_cbet_opportunities, folds_to_cbet
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(stake, cpu_id) DO UPDATE SET
                        hands = hands + excluded.hands,
                        vpip_hands = vpip_hands + excluded.vpip_hands,
                        pfr_hands = pfr_hands + excluded.pfr_hands,
                        three_bet_opportunities = three_bet_opportunities + excluded.three_bet_opportunities,
                        three_bets = three_bets + excluded.three_bets,
                        four_bet_opportunities = four_bet_opportunities + excluded.four_bet_opportunities,
                        four_bets = four_bets + excluded.four_bets,
                        faced_bets = faced_bets + excluded.faced_bets,
                        folds_facing_bet = folds_facing_bet + excluded.folds_facing_bet,
                        postflop_actions = postflop_actions + excluded.postflop_actions,
                        postflop_aggressive = postflop_aggressive + excluded.postflop_aggressive,
                        postflop_calls = postflop_calls + excluded.postflop_calls,
                        cbet_opportunities = cbet_opportunities + excluded.cbet_opportunities,
                        cbets = cbets + excluded.cbets,
                        fold_to_cbet_opportunities = fold_to_cbet_opportunities + excluded.fold_to_cbet_opportunities,
                        folds_to_cbet = folds_to_cbet + excluded.folds_to_cbet,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (rate, cpu_id, *(values[name] for name in _COUNTERS)),
                )
            connection.commit()
        return True

    def get_profiles(self, stake: str, cpu_ids: Iterable[str]) -> dict[str, dict[str, float]]:
        """Return sample-size-aware, gently smoothed rates for the requested CPU identities."""
        ids = sorted({str(value) for value in cpu_ids if str(value)})
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM cpu_behavior_stats WHERE stake = ? AND cpu_id IN ({placeholders})",
                (str(stake or "").upper(), *ids),
            ).fetchall()

        result: dict[str, dict[str, float]] = {}
        for row in rows:
            hands = int(row["hands"])
            postflop_actions = int(row["postflop_actions"])
            faced_bets = int(row["faced_bets"])
            cbet_opp = int(row["cbet_opportunities"])
            fold_cbet_opp = int(row["fold_to_cbet_opportunities"])
            three_bet_opp = int(row["three_bet_opportunities"])
            four_bet_opp = int(row["four_bet_opportunities"])
            result[str(row["cpu_id"])] = {
                "sample_hands": float(hands),
                "vpip_rate": (int(row["vpip_hands"]) + 2.2) / (hands + 10.0),
                "pfr_rate": (int(row["pfr_hands"]) + 1.6) / (hands + 10.0),
                "three_bet_opportunities": float(three_bet_opp),
                "three_bet_rate": (int(row["three_bets"]) + 0.42) / (three_bet_opp + 6.0),
                "four_bet_opportunities": float(four_bet_opp),
                "four_bet_rate": (int(row["four_bets"]) + 0.24) / (four_bet_opp + 6.0),
                "faced_bet_opportunities": float(faced_bets),
                "fold_to_bet_rate": (int(row["folds_facing_bet"]) + 4.4) / (faced_bets + 8.0),
                "postflop_actions": float(postflop_actions),
                "postflop_aggression_rate": (int(row["postflop_aggressive"]) + 1.8) / (postflop_actions + 8.0),
                "postflop_call_rate": (int(row["postflop_calls"]) + 2.4) / (postflop_actions + 8.0),
                "cbet_opportunities": float(cbet_opp),
                "cbet_rate": (int(row["cbets"]) + 2.4) / (cbet_opp + 8.0),
                "fold_to_cbet_opportunities": float(fold_cbet_opp),
                "fold_to_cbet_rate": (int(row["folds_to_cbet"]) + 4.4) / (fold_cbet_opp + 8.0),
            }
        return result
