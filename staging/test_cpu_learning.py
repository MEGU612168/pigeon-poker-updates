from __future__ import annotations

import tempfile
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent / "source_1_3_101"))
from pigeon_poker.cpu_learning import CPULearningStore
from pigeon_poker import preflop_screenshot_ranges as preflop_ranges


class FakePlayer:
    def __init__(self, player_id: str, name: str):
        self.player_id = player_id
        self.name = name
        self.eligible = True
        self.stack = 10000
        # Deliberately no hole_cards: the learning store must use public actions only.


class FakeHand:
    def __init__(self):
        self.players = [
            FakePlayer("cpu-A", "CPU A"),
            FakePlayer("cpu-B", "CPU B"),
            FakePlayer("hero", "YOU"),
        ]
        self.events = [
            {"type": "action", "street": "preflop", "player_id": "cpu-A",
             "action": "raise", "paid": 250, "target": 250,
             "pot_before": 75, "to_call_before": 0},
            {"type": "action", "street": "preflop", "player_id": "cpu-B",
             "action": "call", "paid": 250, "target": 250,
             "pot_before": 325, "to_call_before": 250},
            {"type": "action", "street": "preflop", "player_id": "hero",
             "action": "call", "paid": 250, "target": 250,
             "pot_before": 575, "to_call_before": 250},
            {"type": "street", "street": "flop", "board": ["2c", "7d", "Jh"]},
            {"type": "action", "street": "flop", "player_id": "cpu-A",
             "action": "bet", "paid": 300, "target": 300,
             "pot_before": 750, "to_call_before": 0},
            {"type": "action", "street": "flop", "player_id": "cpu-B",
             "action": "fold", "paid": 0, "target": 300,
             "pot_before": 1050, "to_call_before": 300},
        ]


def test_persists_per_cpu_public_action_statistics_and_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "cpu-learning.sqlite3"
        hand = FakeHand()
        store = CPULearningStore(db)

        assert store.record_hand("hand-001", "NL10", hand, ["cpu-A", "cpu-B"])
        profiles = store.get_profiles("NL10", ["cpu-A", "cpu-B"])
        assert profiles["cpu-A"]["sample_hands"] == 1.0
        assert profiles["cpu-B"]["sample_hands"] == 1.0
        assert profiles["cpu-A"]["vpip_rate"] > 0.0
        assert profiles["cpu-A"]["pfr_rate"] > 0.0
        assert profiles["cpu-B"]["vpip_rate"] > 0.0
        assert profiles["cpu-B"]["faced_bet_opportunities"] == 1.0
        assert profiles["cpu-B"]["fold_to_bet_rate"] > 0.55
        assert profiles["cpu-A"]["cbet_opportunities"] == 1.0
        assert profiles["cpu-A"]["cbet_rate"] > 0.0

        # A retry after a crash/relaunch must not count the same hand twice.
        assert not store.record_hand("hand-001", "NL10", hand, ["cpu-A", "cpu-B"])
        reopened = CPULearningStore(db)
        again = reopened.get_profiles("NL10", ["cpu-A", "cpu-B"])
        assert again["cpu-A"]["sample_hands"] == 1.0
        assert again["cpu-B"]["sample_hands"] == 1.0


def test_learning_is_separated_by_stake_and_cpu_identity():
    with tempfile.TemporaryDirectory() as tmp:
        store = CPULearningStore(Path(tmp) / "cpu-learning.sqlite3")
        hand = FakeHand()
        assert store.record_hand("hand-002", "NL2", hand, ["cpu-A"])
        assert store.get_profiles("NL2", ["cpu-A"])["cpu-A"]["sample_hands"] == 1.0
        assert store.get_profiles("NL10", ["cpu-A"]) == {}
        assert store.get_profiles("NL2", ["cpu-B"]) == {}


def test_missing_hand_key_or_unknown_cpu_does_not_create_learning_rows():
    with tempfile.TemporaryDirectory() as tmp:
        store = CPULearningStore(Path(tmp) / "cpu-learning.sqlite3")
        hand = FakeHand()
        assert not store.record_hand("", "NL10", hand, ["cpu-A"])
        assert not store.record_hand("hand-003", "NL10", hand, [])
        assert store.get_profiles("NL10", ["cpu-A", "cpu-B"]) == {}


def test_rates_are_smoothed_and_sample_size_is_exposed():
    with tempfile.TemporaryDirectory() as tmp:
        store = CPULearningStore(Path(tmp) / "cpu-learning.sqlite3")
        profiles = store.get_profiles("NL10", ["cpu-A"])
        assert profiles == {}
        hand = FakeHand()
        assert store.record_hand("hand-004", "NL10", hand, ["cpu-A"])
        profile = store.get_profiles("NL10", ["cpu-A"])["cpu-A"]
        for key in ("vpip_rate", "pfr_rate", "three_bet_rate", "four_bet_rate",
                    "fold_to_bet_rate", "postflop_aggression_rate",
                    "postflop_call_rate", "cbet_rate", "fold_to_cbet_rate"):
            assert 0.0 <= profile[key] <= 1.0, (key, profile[key])
        assert profile["sample_hands"] == 1.0



def test_unacted_cpu_receives_learned_profile_without_fake_chart_range():
    original_support = preflop_ranges._supports_100bb_effective_stack
    original_positions = preflop_ranges._seat_position_map
    original_blockers = preflop_ranges._known_public_blockers
    try:
        preflop_ranges._supports_100bb_effective_stack = lambda hand: True
        preflop_ranges._seat_position_map = lambda table, hand: {
            "hero": "CO", "cpu-A": "BTN",
        }
        preflop_ranges._known_public_blockers = lambda hand, exclude: (
            {("A", "s"), ("A", "h")}, ["As", "Ah"],
        )
        hand = SimpleNamespace(
            players=[FakePlayer("hero", "YOU"), FakePlayer("cpu-A", "CPU A")],
            events=[],
            board=[],
        )
        result = preflop_ranges.estimate_preflop_opponent_ranges(
            object(), hand, exclude_player_id="hero",
            opponent_profiles={"cpu-A": {"archetype": "balanced", "level": 3}},
            opponent_learning={"cpu-A": {
                "sample_hands": 40.0,
                "vpip_rate": 0.42,
                "pfr_rate": 0.18,
                "faced_bet_opportunities": 30.0,
                "fold_to_bet_rate": 0.25,
                "postflop_actions": 40.0,
                "postflop_call_rate": 0.52,
                "postflop_aggression_rate": 0.34,
            }},
        )
        row = result["players"]["cpu-A"]
        assert row["supported"] is False
        assert row["reason"] == "behavior-profile-prior"
        assert row["learned_archetype"] == "calling_station"
        assert row["learned_behavior"]["sample_hands"] == 40.0

        aggressive_result = preflop_ranges.estimate_preflop_opponent_ranges(
            object(), hand, exclude_player_id="hero",
            opponent_profiles={"cpu-A": {"archetype": "balanced", "level": 3}},
            opponent_learning={"cpu-A": {
                "sample_hands": 40.0,
                "vpip_rate": 0.24,
                "pfr_rate": 0.20,
                "faced_bet_opportunities": 30.0,
                "fold_to_bet_rate": 0.55,
                "postflop_actions": 5.0,
                "postflop_call_rate": 0.28,
                "postflop_aggression_rate": 0.20,
                "three_bet_opportunities": 20.0,
                "three_bet_rate": 0.27,
                "four_bet_opportunities": 3.0,
                "four_bet_rate": 0.08,
            }},
        )
        aggressive_row = aggressive_result["players"]["cpu-A"]
        assert aggressive_row["learned_archetype"] == "aggressive"
        assert aggressive_row["learned_archetype_basis"] == "three_bet_rate"
    finally:
        preflop_ranges._supports_100bb_effective_stack = original_support
        preflop_ranges._seat_position_map = original_positions
        preflop_ranges._known_public_blockers = original_blockers


def test_learns_fold_call_raise_by_street_and_faced_bet_size():
    with tempfile.TemporaryDirectory() as tmp:
        store = CPULearningStore(Path(tmp) / "cpu-learning.sqlite3")
        observations = [
            ("flop", 25, 100, "fold", "small"),
            ("flop", 60, 100, "call", "medium"),
            ("turn", 120, 100, "raise", "large"),
            ("river", 180, 100, "fold", "overbet"),
        ]
        for index, (street, bet, pot, outcome, bucket) in enumerate(observations):
            hand = FakeHand()
            transitions = [{"type": "street", "street": "flop",
                            "board": ["2c", "7d", "Jh"]}]
            if street in {"turn", "river"}:
                transitions.append({"type": "street", "street": "turn",
                                    "board": ["2c", "7d", "Jh", "9s"]})
            if street == "river":
                transitions.append({"type": "street", "street": "river",
                                    "board": ["2c", "7d", "Jh", "9s", "3c"]})
            hand.events = [
                {"type": "action", "street": "preflop", "player_id": "cpu-A",
                 "action": "raise", "paid": 250, "target": 250,
                 "pot_before": 75, "to_call_before": 0},
                {"type": "action", "street": "preflop", "player_id": "cpu-B",
                 "action": "call", "paid": 250, "target": 250,
                 "pot_before": 325, "to_call_before": 250},
                *transitions,
                {"type": "action", "street": street, "player_id": "cpu-A",
                 "action": "bet", "paid": bet, "target": bet,
                 "pot_before": pot, "to_call_before": 0},
                {"type": "action", "street": street, "player_id": "cpu-B",
                 "action": outcome, "paid": bet if outcome in {"call", "raise"} else 0,
                 "target": bet, "pot_before": pot + bet, "to_call_before": bet},
            ]
            assert store.record_hand(
                f"size-hand-{index}", "NL10", hand, ["cpu-A", "cpu-B"]
            )
        profile = store.get_profiles("NL10", ["cpu-B"])["cpu-B"]
        expected_outcomes = {
            "flop_small": "fold",
            "flop_medium": "call",
            "turn_large": "raise",
            "river_overbet": "fold",
        }
        for prefix, expected in expected_outcomes.items():
            assert profile[f"{prefix}_response_opportunities"] == 1.0
            rates = {
                "fold": profile[f"{prefix}_fold_rate"],
                "call": profile[f"{prefix}_call_rate"],
                "raise": profile[f"{prefix}_raise_rate"],
            }
            assert abs(sum(rates.values()) - 1.0) < 1e-9
            assert rates[expected] == max(rates.values())


def test_old_cpu_learning_database_is_migrated_without_losing_rows():
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "legacy-learning.sqlite3"
        with sqlite3.connect(db) as connection:
            connection.execute(
                """
                CREATE TABLE cpu_behavior_stats (
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
                "INSERT INTO cpu_behavior_stats(stake, cpu_id, hands) VALUES (?, ?, ?)",
                ("NL10", "cpu-A", 12),
            )
        store = CPULearningStore(db)
        profile = store.get_profiles("NL10", ["cpu-A"])["cpu-A"]
        assert profile["sample_hands"] == 12.0
        assert profile["flop_small_response_opportunities"] == 0.0
        assert 0.0 <= profile["flop_small_fold_rate"] <= 1.0


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
            print("PASS", name)
    print("ALL CPU LEARNING TESTS PASSED")
