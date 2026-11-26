from __future__ import annotations

import math
import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

from pigeon_poker.preflop_174_policy_data import load_preflop_174_data
from pigeon_poker.range_chart_canvas import build_range_chart_model, draw_preflop_range_canvas


class FakeCanvas:
    def __init__(self):
        self.items = []
        self.bindings = {}
        self.next_id = 1
        self.options = {}

    def delete(self, _tag):
        self.items.clear()

    def configure(self, **kwargs):
        self.options.update(kwargs)

    config = configure

    def create_rectangle(self, *args, **kwargs):
        return self._add("rectangle", args, kwargs)

    def create_text(self, *args, **kwargs):
        return self._add("text", args, kwargs)

    def _add(self, kind, args, kwargs):
        item_id = self.next_id
        self.next_id += 1
        self.items.append({"id": item_id, "kind": kind, "args": args, "options": kwargs})
        return item_id

    def bind(self, sequence, callback):
        self.bindings[sequence] = callback

    def itemconfigure(self, item_id, **kwargs):
        item = next(item for item in self.items if item["id"] == item_id)
        item["options"].update(kwargs)


def test_all_174_source_matrices_build_complete_169_hand_models():
    data = load_preflop_174_data()
    assert len(data["scenarios"]) == 174
    assert len(data["hand_order"]) == 169
    assert {int(item["id"]) for item in data["scenarios"]} == set(range(128, 302))

    for scenario in data["scenarios"]:
        model = build_range_chart_model(int(scenario["id"]))
        assert model["source_id"] == int(scenario["id"])
        assert model["position"] == scenario["position"]
        assert len(model["cells"]) == 169
        assert model["measured_count"] + model["blank_count"] == 169
        for cell in model["cells"]:
            if not cell["measured"]:
                assert cell["actions"] == []
                continue
            total = sum(float(action["frequency"]) for action in cell["actions"])
            assert math.isclose(total, 1.0, abs_tol=0.001)
            assert all(0.0 < action["frequency"] <= 1.0 for action in cell["actions"])


def test_source_blank_cells_are_not_silently_converted_into_folds():
    scenario = next(
        item for item in load_preflop_174_data()["scenarios"]
        if any(not row for row in item["hands"])
    )
    model = build_range_chart_model(int(scenario["id"]))
    source_blanks = sum(not row for row in scenario["hands"])
    assert model["blank_count"] == source_blanks
    assert all(
        not cell["measured"] and not cell["actions"]
        for cell in model["cells"] if not cell["measured"]
    )


def test_native_canvas_draws_169_cells_without_any_photoimage():
    scenario = next(
        item for item in load_preflop_174_data()["scenarios"]
        if any(row for row in item["hands"])
    )
    model = build_range_chart_model(int(scenario["id"]))
    canvas = FakeCanvas()
    result = draw_preflop_range_canvas(
        canvas, model, title="LIVE PREFLOP RANGE", charge_label="1 BB paid this hand"
    )
    cell_backgrounds = [
        item for item in canvas.items
        if item["kind"] == "rectangle" and "range-cell" in item["options"].get("tags", ())
    ]
    assert result["cell_count"] == 169
    assert len(cell_backgrounds) == 169
    assert "PhotoImage" not in draw_preflop_range_canvas.__code__.co_names
    assert "<Motion>" in canvas.bindings
    assert any(item["kind"] == "text" for item in canvas.items)


def test_each_of_the_174_source_ids_resolves_to_a_chart():
    for source_id in range(128, 302):
        model = build_range_chart_model(source_id)
        assert model["source_id"] == source_id
        assert len(model["cells"]) == 169


def run_tests():
    tests = [
        test_all_174_source_matrices_build_complete_169_hand_models,
        test_source_blank_cells_are_not_silently_converted_into_folds,
        test_native_canvas_draws_169_cells_without_any_photoimage,
        test_each_of_the_174_source_ids_resolves_to_a_chart,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print(f"ALL PASS {len(tests)} native range chart tests; 174 charts x 169 hand classes")


if __name__ == "__main__":
    run_tests()
