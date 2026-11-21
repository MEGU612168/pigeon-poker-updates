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


if __name__ == "__main__":
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()
            print("PASS", name)
    print("ALL CPU LEARNING TESTS PASSED")
