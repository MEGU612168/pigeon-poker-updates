from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

from pigeon_poker.preflop_174_policy import (  # noqa: E402
    _scenarios,
    _strict_range_history_matches,
    find_exact_preflop_174_scenario,
)


def _history(scenario: dict) -> list[dict]:
    return [
        {
            "position": item["position"],
            "action": item["action"],
            "size_bb": item.get("size_bb"),
        }
        for item in scenario.get("history", [])
    ]


def test_catalog_still_contains_exactly_174_source_scenarios():
    scenarios = _scenarios()
    assert len(scenarios) == 174
    assert {int(item["id"]) for item in scenarios} == set(range(128, 302))


def test_paid_range_lookup_never_uses_nearest_node_inference():
    assert find_exact_preflop_174_scenario("UNKNOWN", []) is None
    # An impossible raise size must not be treated as a nearest-node match,
    # even if UTG has a legitimate empty-history source node.
    assert find_exact_preflop_174_scenario("UTG", [
        {"position": "UTG", "action": "raise", "size_bb": 9999.0}
    ]) is None


def test_missing_raise_sizes_do_not_create_false_exact_matches():
    for scenario in _scenarios():
        history = _history(scenario)
        if any(item["action"] == "raise" and item.get("size_bb") is None
               for item in history):
            assert find_exact_preflop_174_scenario(scenario["position"], history) is None


def test_changed_raise_size_is_not_treated_as_the_original_situation():
    candidate = next(
        scenario for scenario in _scenarios()
        if any(item["action"] == "raise" and item.get("size_bb") is not None
               for item in scenario.get("history", []))
    )
    history = _history(candidate)
    index = next(i for i, item in enumerate(history)
                 if item["action"] == "raise" and item.get("size_bb") is not None)
    history[index]["size_bb"] = float(history[index]["size_bb"]) + 5.0
    assert find_exact_preflop_174_scenario(candidate["position"], history) is None


def test_allin_without_target_size_is_still_an_exact_action_class():
    scenario = next(
        scenario for scenario in _scenarios()
        if (
            any(item.get("action") == "allin" and item.get("size_bb") is None
                for item in scenario.get("history", []))
            and not any(item.get("action") == "raise" and item.get("size_bb") is None
                        for item in scenario.get("history", []))
        )
    )
    history = _history(scenario)
    assert find_exact_preflop_174_scenario(scenario["position"], history) == int(scenario["id"])


def test_key_source_situations_146_and_147_keep_their_own_image_ids():
    by_id = {int(item["id"]): item for item in _scenarios()}
    for source_id in (146, 147):
        scenario = by_id[source_id]
        assert find_exact_preflop_174_scenario(
            scenario["position"], _history(scenario)
        ) == source_id


def test_all_unambiguous_fully_sized_histories_resolve_to_their_source_id():
    keyed = {}
    for scenario in _scenarios():
        history = _history(scenario)
        if any(item["action"] == "raise" and item.get("size_bb") is None
               for item in history):
            continue
        key = (scenario["position"], tuple(
            (x["position"], x["action"], x.get("size_bb")) for x in history
        ))
        keyed.setdefault(key, []).append(int(scenario["id"]))
    for (position, history_key), ids in keyed.items():
        history = [
            {"position": p, "action": a, "size_bb": size}
            for p, a, size in history_key
        ]
        result = find_exact_preflop_174_scenario(position, history)
        if len(ids) == 1:
            assert result == ids[0]
        else:
            assert result is None


def test_live_resolution_does_not_depend_on_the_legacy_bitmap_catalogue():
    import pigeon_poker.range_image_catalog as legacy_images
    from pigeon_poker.range_scenario_resolver import resolve_range_image_for_hand

    scenario = next(
        item for item in _scenarios()
        if (
            not any(action.get("action") == "raise" and action.get("size_bb") is None
                    for action in item.get("history", []))
            and find_exact_preflop_174_scenario(item["position"], _history(item)) == int(item["id"])
        )
    )
    table, hand, actor_id = _live_fixture_for_scenario(scenario)
    original_loader = legacy_images._load_catalog
    legacy_images._load_catalog = lambda: (_ for _ in ()).throw(
        AssertionError("The live range resolver must not load bitmap assets")
    )
    try:
        chart = resolve_range_image_for_hand(table, hand, actor_id)
        assert chart is not None
        assert int(chart["source_id"]) == int(scenario["id"])
    finally:
        legacy_images._load_catalog = original_loader




def test_bot_chart_and_raise_sizes_share_the_same_source_for_all_174_situations():
    import random
    from types import SimpleNamespace

    from pigeon_poker.preflop_174_policy import (
        choose_preflop_174_action, preflop_174_raise_size_options,
    )
    from pigeon_poker.range_scenario_resolver import resolve_range_image_for_hand

    failures = []
    for scenario in _scenarios():
        table, hand, actor_id = _live_fixture_for_scenario(scenario)
        chart = resolve_range_image_for_hand(table, hand, actor_id)
        assert chart is not None, f"Range chart unavailable for source #{scenario['id']}"

        cpu = SimpleNamespace(rng=random.Random(20261126), level=1, archetype="balanced")
        decision = choose_preflop_174_action(table, hand, actor_id, cpu)
        bot_source_id = getattr(decision, "source_image_no", None)
        if bot_source_id is None:
            failures.append((int(scenario["id"]), "BOT decision omitted its source scenario ID"))
        elif int(bot_source_id) != int(chart["source_id"]):
            failures.append((
                int(scenario["id"]), "BOT and chart source IDs differ",
                int(bot_source_id), int(chart["source_id"]),
            ))

        if getattr(decision, "source", "") == "preflop-174-scenario-policy":
            assert decision.node_id == f"174_IMAGE_{chart['source_id']}"
            if decision.action == "raise":
                assert decision.amount is not None
                assert decision.action_size_bb is not None
                assert abs(float(decision.amount) / 100.0 - float(decision.action_size_bb)) <= 0.01

        legal = hand.legal_actions(actor_id)
        if "raise" in legal["actions"]:
            sizes = preflop_174_raise_size_options(table, hand, actor_id)
            if sizes is None:
                failures.append((int(scenario["id"]), "raise-size menu missing"))
            elif int(sizes["scenario_id"]) != int(chart["source_id"]):
                failures.append((
                    int(scenario["id"]), "sizing menu and chart source IDs differ",
                    int(sizes["scenario_id"]), int(chart["source_id"]),
                ))
            else:
                expected_sizes = {
                    float(size)
                    for row in scenario["hands"]
                    for option_index, frequency in (row or [])
                    if float(frequency) > 0
                    for action, size in [scenario["action_options"][int(option_index)]]
                    if str(action).lower() == "raise" and size is not None
                }
                actual_sizes = {float(item["size_bb"]) for item in sizes["choices"]}
                if actual_sizes != expected_sizes:
                    failures.append((
                        int(scenario["id"]), "source raise sizes not all shown",
                        sorted(expected_sizes), sorted(actual_sizes),
                    ))

    assert not failures, (
        f"{len(failures)} / 174 scenarios did not use one consistent source across "
        f"the paid chart, BOT, and hero sizing menu: {failures}"
    )


def test_fold_only_live_prefixes_resolve_to_their_first_in_chart_and_bot():
    import random
    from types import SimpleNamespace

    from pigeon_poker.preflop_174_policy import choose_preflop_174_action
    from pigeon_poker.range_scenario_resolver import resolve_range_image_for_hand

    expected = {"UTG": 128, "HJ": 129, "CO": 130, "BTN": 131, "SB": 132}
    by_id = {int(item["id"]): item for item in _scenarios()}
    for position, source_id in expected.items():
        scenario = by_id[source_id]
        table, hand, actor_id = _live_fixture_for_scenario(scenario)
        if position == "UTG":
            assert hand.events == []
        else:
            assert hand.events
            assert all(event["action"] == "fold" for event in hand.events)
        chart = resolve_range_image_for_hand(table, hand, actor_id)
        assert chart is not None and int(chart["source_id"]) == source_id
        decision = choose_preflop_174_action(
            table, hand, actor_id,
            SimpleNamespace(rng=random.Random(21), level=1, archetype="balanced"),
        )
        assert int(decision.source_image_no) == source_id
        if position in {"UTG", "HJ", "CO", "BTN"}:
            assert decision.action != "call"



def test_bot_uses_the_169_hand_frequencies_for_each_first_in_and_response_family():
    import random
    from types import SimpleNamespace

    from pigeon_poker.preflop_174_policy import (
        _HAND_ORDER, _actual_history, _normalise_action, _position_map,
        _scenario_distribution, _filter_first_in_distribution,
        choose_preflop_174_action,
    )
    from pigeon_poker.range_scenario_resolver import resolve_range_image_for_hand

    by_id = {int(item["id"]): item for item in _scenarios()}
    source_ids = (128, 129, 130, 131, 132, 135, 146, 147, 153, 232)
    failures = []

    def cards_for(hand_class):
        if len(hand_class) == 2:
            return (hand_class[0] + "s", hand_class[1] + "h")
        high, low, suited = hand_class[0], hand_class[1], hand_class[2]
        return (high + "s", low + ("s" if suited == "s" else "h"))

    for source_id in source_ids:
        source = by_id[source_id]
        for hand_class in _HAND_ORDER:
            table, hand, actor_id = _live_fixture_for_scenario(
                source, cards=cards_for(hand_class)
            )
            chart = resolve_range_image_for_hand(table, hand, actor_id)
            assert chart is not None, f"Missing live chart for #{source_id} / {hand_class}"
            selected_source = by_id[int(chart["source_id"])]
            positions = _position_map(table, hand)
            history = _actual_history(table, hand, actor_id, positions)
            distribution, _hand_inferred, _method = _scenario_distribution(
                selected_source, hand_class
            )
            distribution = _filter_first_in_distribution(
                selected_source["position"], history, distribution
            )
            decision = choose_preflop_174_action(
                table, hand, actor_id,
                SimpleNamespace(rng=random.Random(1000 + source_id), level=1, archetype="balanced"),
            )
            action = _normalise_action(decision.action)
            if action == "raise":
                matching = [
                    frequency for (candidate_action, size), frequency in distribution.items()
                    if candidate_action == "raise" and size is not None
                    and decision.action_size_bb is not None
                    and abs(float(size) - float(decision.action_size_bb)) <= 0.0001
                ]
            else:
                matching = [
                    frequency for (candidate_action, _size), frequency in distribution.items()
                    if candidate_action == action
                ]
            if not matching or not any(float(value) > 0.0 for value in matching):
                failures.append((source_id, hand_class, decision.action, decision.action_size_bb))
            if int(getattr(decision, "source_image_no", -1)) != int(chart["source_id"]):
                failures.append((
                    source_id, hand_class, "source mismatch",
                    getattr(decision, "source_image_no", None), chart["source_id"],
                ))

    assert not failures, (
        f"BOT did not use the matching per-hand 174-source frequencies "
        f"for {len(failures)} combinations: {failures[:80]}"
    )


def test_paid_range_resolves_when_live_raise_amount_is_omitted_but_history_is_unique():
    from pigeon_poker.preflop_174_policy import choose_preflop_174_action
    from pigeon_poker.range_scenario_resolver import resolve_range_image_for_hand

    groups = {}
    for scenario in _scenarios():
        key = (
            str(scenario["position"]).upper(),
            tuple(
                (str(item["position"]).upper(), str(item["action"]).lower())
                for item in scenario.get("history", [])
            ),
        )
        groups.setdefault(key, []).append(scenario)

    scenario = next(
        item for values in groups.values() if len(values) == 1
        for item in values
        if any(str(action.get("action", "")).lower() == "raise"
               for action in item.get("history", []))
    )
    table, hand, actor_id = _live_fixture_for_scenario(scenario)
    for event in hand.events:
        if str(event.get("action", "")).lower() == "raise":
            event.pop("target", None)

    chart = resolve_range_image_for_hand(table, hand, actor_id)
    assert chart is not None, f"Paid range was not resolved for source #{scenario['id']}"
    assert int(chart["source_id"]) == int(scenario["id"])
    assert chart["raise_size_verified"] is False
    assert chart["action_history_exact"] is True
    assert chart["match_mode"].startswith("actions-size-unverified-")

    cpu = type("CPU", (), {"rng": __import__("random").Random(7), "level": 1,
                           "archetype": "balanced"})()
    decision = choose_preflop_174_action(table, hand, actor_id, cpu)
    assert int(decision.source_image_no) == int(chart["source_id"])
    assert decision.scenario_match_mode == "actions-size-unverified"
    assert "raise size unavailable" in decision.note


def test_paid_range_does_not_ignore_a_known_but_wrong_live_raise_amount():
    from pigeon_poker.range_scenario_resolver import resolve_range_image_for_hand

    scenario = next(
        item for item in _scenarios()
        if any(str(action.get("action", "")).lower() == "raise"
               and action.get("size_bb") is not None
               for action in item.get("history", []))
    )
    table, hand, actor_id = _live_fixture_for_scenario(scenario)
    raise_event = next(
        event for event in hand.events
        if str(event.get("action", "")).lower() == "raise"
    )
    raise_event["target"] = 9999999
    assert resolve_range_image_for_hand(table, hand, actor_id) is None


def run_tests():
    tests = [
        test_catalog_still_contains_exactly_174_source_scenarios,
        test_complete_174_situation_and_source_image_inventory,
        test_paid_range_lookup_never_uses_nearest_node_inference,
        test_paid_range_resolves_when_live_raise_amount_is_omitted_but_history_is_unique,
        test_paid_range_does_not_ignore_a_known_but_wrong_live_raise_amount,
        test_missing_raise_sizes_do_not_create_false_exact_matches,
        test_changed_raise_size_is_not_treated_as_the_original_situation,
        test_allin_without_target_size_is_still_an_exact_action_class,
        test_key_source_situations_146_and_147_keep_their_own_image_ids,
        test_all_unambiguous_fully_sized_histories_resolve_to_their_source_id,
        test_all_174_live_histories_resolve_to_their_own_paid_image,
        test_live_range_signature_invalidates_when_eligibility_or_history_changes,
        test_ambiguous_live_nodes_use_action_menu_and_all_in_state,
        test_live_resolution_does_not_depend_on_the_legacy_bitmap_catalogue,
        test_bot_chart_and_raise_sizes_share_the_same_source_for_all_174_situations,
        test_fold_only_live_prefixes_resolve_to_their_first_in_chart_and_bot,
        test_bot_uses_the_169_hand_frequencies_for_each_first_in_and_response_family,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174-range lookup tests")


class _LivePlayer:
    def __init__(self, player_id: str, position: str, all_in: bool = False):
        self.player_id = player_id
        self.name = position
        self.position = position
        self.all_in = bool(all_in)
        self.stack = 0 if all_in else 10000
        self.hole_cards = ("As", "Ah")


class _LiveHand:
    def __init__(self, events, next_to_act: str, legal_actions, all_in_positions=()):
        # dealer_index=0 and this seat order give the six standard positions.
        all_in_positions = set(all_in_positions)
        self.players = [
            _LivePlayer("btn", "BTN", "BTN" in all_in_positions),
            _LivePlayer("sb", "SB", "SB" in all_in_positions),
            _LivePlayer("bb", "BB", "BB" in all_in_positions),
            _LivePlayer("utg", "UTG", "UTG" in all_in_positions),
            _LivePlayer("hj", "HJ", "HJ" in all_in_positions),
            _LivePlayer("co", "CO", "CO" in all_in_positions),
        ]
        self.seat_by_id = {player.player_id: index for index, player in enumerate(self.players)}
        self.events = events
        self.next_to_act = next_to_act
        self.street = "preflop"
        self.finished = False
        self.big_blind = 100
        self.dealer_index = 0
        self._legal_actions = list(legal_actions)

    def legal_actions(self, player_id):
        actions = list(self._legal_actions)
        return {
            "actions": actions,
            "to_call": 100 if "call" in actions else 0,
            "raise_allowed": "raise" in actions,
            "min_target": 100,
            "max_target": 100000,
        }

    def player(self, player_id):
        return next(player for player in self.players if player.player_id == player_id)


class _LiveTable:
    dealer_index = 0


def _live_fixture_for_scenario(scenario: dict, cards=("As", "Ah")):
    from pigeon_poker.preflop_174_policy import POSITION_BY_SEAT_FROM_BUTTON

    player_by_position = {
        position: player_id
        for position, player_id in zip(
            POSITION_BY_SEAT_FROM_BUTTON,
            ("btn", "sb", "bb", "utg", "hj", "co"),
        )
    }
    events = []
    # The original first-in charts omit the implicit folds before the actor.
    # A real live hand contains them, so exercise that exact runtime shape.
    if not scenario.get("history"):
        position_order = ("UTG", "HJ", "CO", "BTN", "SB", "BB")
        actor_index = position_order.index(str(scenario["position"]))
        for position in position_order[:actor_index]:
            events.append({
                "type": "action", "street": "preflop",
                "player_id": player_by_position[position],
                "player": player_by_position[position],
                "action": "fold",
            })
    for item in scenario.get("history", []):
        action = str(item["action"]).lower()
        event = {
            "type": "action",
            "street": "preflop",
            "player_id": player_by_position[item["position"]],
            "player": player_by_position[item["position"]],
            "action": action,
        }
        if action == "raise":
            event["target"] = round(float(item["size_bb"]) * 100)
        events.append(event)
    actor_id = player_by_position[scenario["position"]]
    legal_actions = [
        option[0] for option in scenario.get("action_options", [])
        if isinstance(option, (list, tuple)) and option
    ]
    all_in_positions = {
        252: ("CO",),
        253: ("CO", "BTN"),
    }.get(int(scenario["id"]), ())
    table = _LiveTable()
    hand = _LiveHand(events, actor_id, legal_actions, all_in_positions)
    hand.player(actor_id).hole_cards = tuple(cards)
    return table, hand, actor_id


def test_all_174_live_histories_resolve_to_their_own_paid_image():
    from pigeon_poker.range_scenario_resolver import resolve_range_image_for_hand
    from pigeon_poker.range_chart_canvas import build_range_chart_model

    failures = []
    for scenario in _scenarios():
        table, hand, actor_id = _live_fixture_for_scenario(scenario)
        chart = resolve_range_image_for_hand(table, hand, actor_id)
        expected_id = int(scenario["id"])
        actual_id = int(chart["source_id"]) if chart else None
        expected_model = build_range_chart_model(expected_id)
        actual_model = build_range_chart_model(actual_id) if actual_id is not None else None
        if actual_model is not None:
            expected_model = {key: value for key, value in expected_model.items() if key != "source_id"}
            actual_model = {key: value for key, value in actual_model.items() if key != "source_id"}
        if actual_model != expected_model:
            history = _history(scenario)
            candidates = [
                item for item in _scenarios()
                if item["position"] == scenario["position"]
                and _strict_range_history_matches(item.get("history", []), history)
            ]
            metadata = {
                key: value for key, value in scenario.items()
                if key not in {"hands", "history", "overall"}
            }
            candidate_details = []
            for item in candidates:
                matrix = json.dumps(item.get("hands", []), ensure_ascii=False, separators=(",", ":"))
                candidate_details.append({
                    "id": int(item["id"]),
                    "metadata": {
                        key: value for key, value in item.items()
                        if key not in {"hands", "history", "overall"}
                    },
                    "overall": item.get("overall"),
                    "matrix_sha256": hashlib.sha256(matrix.encode("utf-8")).hexdigest(),
                    "strategy_sha256": hashlib.sha256(json.dumps(item.get("hands", []), sort_keys=True).encode("utf-8")).hexdigest(),
                })
            failures.append({
                "expected_id": expected_id,
                "actor": scenario["position"],
                "history": scenario.get("history", []),
                "actual_id": actual_id,
                "candidate_ids": [int(item["id"]) for item in candidates],
                "metadata": metadata,
                "candidate_details": candidate_details,
            })
    assert not failures, f"{len(failures)} / 174 live histories failed paid image resolution: {failures}"


def test_live_range_signature_invalidates_when_eligibility_or_history_changes():
    from pigeon_poker.range_scenario_resolver import live_range_lookup_signature

    table, hand, _actor_id = _live_fixture_for_scenario(_scenarios()[18])
    busy = live_range_lookup_signature(
        hand, current_hand_key="T:1", cash_deal_busy=True,
        dealer_index=table.dealer_index,
    )
    ready = live_range_lookup_signature(
        hand, current_hand_key="T:1", cash_deal_busy=False,
        dealer_index=table.dealer_index,
    )
    assert busy != ready

    before = live_range_lookup_signature(
        hand, current_hand_key="T:1", dealer_index=table.dealer_index,
    )
    # Changing an existing raise target without changing event count must
    # invalidate the cached image lookup too.
    raise_event = next((event for event in hand.events if event.get("action") == "raise"), None)
    if raise_event is not None:
        raise_event["target"] = int(raise_event["target"]) + 25
        after = live_range_lookup_signature(
            hand, current_hand_key="T:1", dealer_index=table.dealer_index,
        )
        assert before != after





def test_ambiguous_live_nodes_use_action_menu_and_all_in_state():
    from pigeon_poker.range_scenario_resolver import resolve_range_image_for_hand
    from pigeon_poker.range_chart_canvas import build_range_chart_model

    by_id = {int(item["id"]): item for item in _scenarios()}
    for source_id in (244, 245, 252, 253, 266, 267):
        scenario = by_id[source_id]
        table, hand, actor_id = _live_fixture_for_scenario(scenario)
        chart = resolve_range_image_for_hand(table, hand, actor_id)
        assert chart is not None, f"Ambiguous source #{source_id} remained unavailable"
        actual_model = build_range_chart_model(int(chart["source_id"]))
        expected_model = build_range_chart_model(source_id)
        assert {k: v for k, v in actual_model.items() if k != "source_id"} == {k: v for k, v in expected_model.items() if k != "source_id"}


def test_complete_174_situation_and_source_image_inventory():
    import hashlib
    from pigeon_poker.preflop_174_policy_data import load_preflop_174_data
    from pigeon_poker.range_image_catalog import _load_catalog

    data = load_preflop_174_data()
    scenarios = data["scenarios"]
    assert len(scenarios) == 174
    assert [int(item["id"]) for item in scenarios] == sorted(int(item["id"]) for item in scenarios)
    assert {int(item["id"]) for item in scenarios} == set(range(128, 302))
    assert len(data["hand_order"]) == 169
    assert len(set(data["hand_order"])) == 169

    for scenario in scenarios:
        assert scenario["position"] in {"UTG", "HJ", "CO", "BTN", "SB", "BB"}
        assert len(scenario.get("hands", [])) == 169
        assert scenario.get("action_options")
        assert isinstance(scenario.get("history"), list)
        for row in scenario["hands"]:
            for option_index, frequency in row:
                assert 0 <= int(option_index) < len(scenario["action_options"])
                assert 0.0 <= float(frequency) <= 1.0
            if row:
                assert abs(sum(float(frequency) for _, frequency in row) - 1.0) <= 0.001

    catalog = _load_catalog()
    assert len(catalog["entries"]) == 174
    assert set(catalog["frames"]) == set(range(128, 302))
    assert {int(item["source_id"]) for item in catalog["entries"]} == set(range(128, 302))

    def semantic_key(item):
        return json.dumps(
            {
                "position": item["position"],
                "history": item.get("history", []),
                "action_options": item.get("action_options", []),
                "overall": item.get("overall", []),
                "hands": item.get("hands", []),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    semantic_groups = {}
    image_groups = {}
    for item in scenarios:
        semantic_groups.setdefault(semantic_key(item), []).append(int(item["id"]))
        image_hash = hashlib.sha256(catalog["frames"][int(item["id"])]).hexdigest()
        image_groups.setdefault(image_hash, []).append(int(item["id"]))
    semantic_duplicates = sorted(sorted(ids) for ids in semantic_groups.values() if len(ids) > 1)
    image_duplicates = sorted(sorted(ids) for ids in image_groups.values() if len(ids) > 1)
    # The source set has 174 numeric entries but these three pairs are exact
    # duplicates of the complete poker decision situation, not merely image
    # duplicates. Keep this explicit so the app never overstates uniqueness.
    assert len(semantic_groups) == 171
    assert semantic_duplicates == [[195, 204], [196, 205], [238, 243]]
    assert len(image_groups) == 162
    print(
        "174-SCENARIO AUDIT:",
        f"ids={len(scenarios)}",
        f"unique_semantic_situations={len(semantic_groups)}",
        f"duplicate_situation_groups={semantic_duplicates}",
        f"unique_source_images={len(image_groups)}",
        f"duplicate_image_groups={image_duplicates}",
    )


if __name__ == "__main__":
    run_tests()
