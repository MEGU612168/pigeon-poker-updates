from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

from pigeon_poker.preflop_174_policy_data import load_preflop_174_data
from pigeon_poker.range_chart_canvas import build_range_chart_model, draw_preflop_range_canvas


def main():
    if sys.platform != "win32":
        raise SystemExit("This test must run on Windows to exercise the native Tk Canvas renderer.")

    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    canvas = tk.Canvas(root, background="#0b1018", width=770, height=800)
    canvas.pack()
    failures = []
    try:
        scenarios = load_preflop_174_data()["scenarios"]
        if len(scenarios) != 174:
            raise AssertionError(f"Expected 174 source scenarios, got {len(scenarios)}")
        for scenario in scenarios:
            source_id = int(scenario["id"])
            model = build_range_chart_model(source_id)
            draw_preflop_range_canvas(canvas, model)
            root.update_idletasks()
            cells = canvas.find_withtag("range-cell")
            if len(cells) != 169:
                failures.append((source_id, "cell count", len(cells)))
                continue
            fills = {
                canvas.itemcget(item_id, "fill")
                for item_id in cells
            }
            if len(fills) < 2:
                failures.append((source_id, "no visible cell contrast", sorted(fills)))
            if any(fill in {"", "#000000", "black"} for fill in fills):
                failures.append((source_id, "black cell fill", sorted(fills)))
        if failures:
            raise AssertionError(f"Native Windows Tk Canvas failed for {len(failures)} / 174 charts: {failures}")
    finally:
        root.destroy()

    print("PASS: native Windows Tk Canvas drew 174 / 174 source-backed range charts (169 cells each)")


if __name__ == "__main__":
    main()
