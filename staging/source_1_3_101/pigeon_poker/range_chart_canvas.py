"""Native Tk Canvas renderer for the 174 source-backed preflop range tables.

The runtime view is built from the authoritative 169-hand frequency matrix.
It deliberately does not decode, load, or display bitmap/PhotoImage assets.
"""
from __future__ import annotations

import math
from typing import Any

from .preflop_174_policy_data import load_preflop_174_data


class RangeChartDataError(RuntimeError):
    """The selected 174-scenario source matrix is missing or inconsistent."""


_CANVAS_WIDTH = 770
_CANVAS_BASE_HEIGHT = 770
_CELL_WIDTH = 51
_CELL_HEIGHT = 43
_CELL_GAP = 3
_GRID_LEFT = 35
_GRID_TOP = 78
_RAISE_COLORS = ("#3786df", "#e5a33d", "#a77ae5", "#27a6b8", "#d46aab", "#8cbf45")


def _normalise_action(value: Any) -> str:
    action = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if action in {"all_in", "allin", "jam", "shove"}:
        return "allin"
    if action in {"bet", "bet_to", "raise_to", "open", "3bet", "4bet", "squeeze"}:
        return "raise"
    if action in {"called", "complete", "limp"}:
        return "call"
    if action in {"folded", "muck"}:
        return "fold"
    return action


def _size_value(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise RangeChartDataError(f"Invalid action size in range source: {value!r}")
    if not math.isfinite(number):
        raise RangeChartDataError(f"Non-finite action size in range source: {value!r}")
    return number


def _action_label(action: str, size: float | None) -> str:
    if action == "fold":
        return "FOLD"
    if action == "call":
        return "CALL"
    if action == "check":
        return "CHECK"
    if action == "allin":
        return "ALL-IN"
    if action == "raise":
        return f"RAISE {size:g} BB" if size is not None else "RAISE"
    return action.replace("_", " ").upper()


def _action_short(action: str, size: float | None) -> str:
    if action == "fold":
        return "F"
    if action == "call":
        return "C"
    if action == "check":
        return "X"
    if action == "allin":
        return "AI"
    if action == "raise":
        return "R" if size is None else f"R{size:g}"
    return action[:3].upper()


def build_range_chart_model(source_id: int) -> dict[str, Any]:
    """Build one exact 169-hand chart from the authoritative 174-scenario data."""
    try:
        source_id = int(source_id)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RangeChartDataError("The selected range has an invalid source ID") from exc

    data = load_preflop_174_data()
    scenario = next(
        (item for item in data["scenarios"] if int(item.get("id", -1)) == source_id),
        None,
    )
    if scenario is None:
        raise RangeChartDataError(f"Preflop scenario #{source_id} is not in the 174-source dataset")

    hand_order = tuple(data.get("hand_order", ()))
    source_hands = list(scenario.get("hands", ()) or ())
    raw_options = list(scenario.get("action_options", ()) or ())
    if len(hand_order) != 169 or len(source_hands) != 169 or not raw_options:
        raise RangeChartDataError(f"Preflop scenario #{source_id} has an incomplete 169-hand matrix")

    options: list[dict[str, Any]] = []
    raise_sizes = sorted({
        _size_value(option[1] if len(option) > 1 else None)
        for option in raw_options
        if isinstance(option, (list, tuple)) and option
        and _normalise_action(option[0]) == "raise"
    }, key=lambda value: -1.0 if value is None else value)
    raise_color_by_size = {
        size: _RAISE_COLORS[index % len(_RAISE_COLORS)]
        for index, size in enumerate(raise_sizes)
    }

    for index, option in enumerate(raw_options):
        if not isinstance(option, (list, tuple)) or not option:
            raise RangeChartDataError(f"Scenario #{source_id} has an invalid action option #{index}")
        action = _normalise_action(option[0])
        size = _size_value(option[1] if len(option) > 1 else None)
        if action == "fold":
            color = "#64748b"
        elif action == "call":
            color = "#23a477"
        elif action == "check":
            color = "#7890a8"
        elif action == "allin":
            color = "#df5c57"
        elif action == "raise":
            color = raise_color_by_size[size]
        else:
            color = "#b38b55"
        options.append({
            "option_index": index,
            "action": action,
            "size_bb": size,
            "label": _action_label(action, size),
            "short": _action_short(action, size),
            "color": color,
        })

    cells: list[dict[str, Any]] = []
    used_option_indices: set[int] = set()
    measured_count = 0
    for hand_class, raw_row in zip(hand_order, source_hands):
        row = list(raw_row or ())
        actions = []
        if row:
            total = 0.0
            for pair in row:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise RangeChartDataError(
                        f"Scenario #{source_id} contains a malformed frequency row for {hand_class}"
                    )
                option_index = int(pair[0])
                frequency = float(pair[1])
                if option_index < 0 or option_index >= len(options):
                    raise RangeChartDataError(
                        f"Scenario #{source_id} references an unknown action for {hand_class}"
                    )
                if not math.isfinite(frequency) or frequency < 0.0 or frequency > 1.0:
                    raise RangeChartDataError(
                        f"Scenario #{source_id} has an invalid frequency for {hand_class}"
                    )
                if frequency <= 0.0:
                    continue
                option = options[option_index]
                used_option_indices.add(option_index)
                actions.append({
                    "option_index": option_index,
                    "action": option["action"],
                    "size_bb": option["size_bb"],
                    "label": option["label"],
                    "short": option["short"],
                    "color": option["color"],
                    "frequency": frequency,
                })
                total += frequency
            if not 0.999 <= total <= 1.001:
                raise RangeChartDataError(
                    f"Scenario #{source_id} frequencies for {hand_class} total {total:.6f}, not 100%"
                )
            measured_count += 1
            actions.sort(key=lambda item: (-item["frequency"], item["option_index"]))
        cells.append({
            "hand": str(hand_class),
            "measured": bool(row),
            "actions": actions,
        })

    legend = [
        {key: option[key] for key in ("label", "short", "color", "option_index")}
        for option in options if option["option_index"] in used_option_indices
    ]
    return {
        "source_id": source_id,
        "position": str(scenario.get("position", "")).upper(),
        "history_count": len(scenario.get("history", ()) or ()),
        "hand_order": hand_order,
        "cells": cells,
        "measured_count": measured_count,
        "blank_count": 169 - measured_count,
        "legend": legend,
    }


def _cell_summary(cell: dict[str, Any]) -> str:
    actions = cell["actions"]
    if not actions:
        return "NO SOURCE DATA"
    parts = [
        f"{item['short']} {round(float(item['frequency']) * 100):d}"
        for item in actions[:2]
    ]
    if len(actions) > 2:
        parts.append("+")
    return "  ".join(parts)


def draw_preflop_range_canvas(
    canvas: Any,
    model: dict[str, Any],
    *,
    title: str = "PREFLOP RANGE",
    charge_label: str = "",
) -> dict[str, Any]:
    """Paint a 13x13 frequency matrix with native Canvas primitives only."""
    if len(model.get("cells", ())) != 169:
        raise RangeChartDataError("The selected range does not contain exactly 169 hand classes")

    canvas.delete("all")
    grid_width = 13 * _CELL_WIDTH + 12 * _CELL_GAP
    grid_height = 13 * _CELL_HEIGHT + 12 * _CELL_GAP
    grid_right = _GRID_LEFT + grid_width
    grid_bottom = _GRID_TOP + grid_height

    canvas_width = max(_CANVAS_WIDTH, grid_right + 30)
    try:
        canvas.configure(
            background="#0b1018",
            width=canvas_width,
            height=_CANVAS_BASE_HEIGHT,
            scrollregion=(0, 0, canvas_width, _CANVAS_BASE_HEIGHT),
        )
    except Exception:
        # A small Canvas-compatible test double may omit optional Tk settings.
        pass

    canvas.create_rectangle(0, 0, canvas_width, _CANVAS_BASE_HEIGHT,
                            fill="#0b1018", outline="")
    canvas.create_text(
        _GRID_LEFT, 20, anchor="w", text=str(title).upper(),
        fill="#f2f6fc", font=("Segoe UI", 13, "bold"),
    )
    subtitle = (
        f"#{model['source_id']}  •  {model['position']}  •  "
        f"{model['history_count']} prior actions  •  "
        f"{model['measured_count']}/169 measured hands  •  "
        f"{model['blank_count']} blank source cells"
    )
    canvas.create_text(
        _GRID_LEFT, 47, anchor="w", text=subtitle,
        fill="#a7b8cc", font=("Segoe UI", 8),
    )
    if charge_label:
        canvas.create_text(
            grid_right, 20, anchor="e", text=str(charge_label),
            fill="#e8c36b", font=("Segoe UI", 8, "bold"),
        )

    for index, cell in enumerate(model["cells"]):
        row, column = divmod(index, 13)
        x = _GRID_LEFT + column * (_CELL_WIDTH + _CELL_GAP)
        y = _GRID_TOP + row * (_CELL_HEIGHT + _CELL_GAP)
        right = x + _CELL_WIDTH
        bottom = y + _CELL_HEIGHT
        measured = bool(cell["measured"])
        canvas.create_rectangle(
            x, y, right, bottom,
            fill="#172638" if measured else "#242d39",
            outline="#33475c" if measured else "#303a47",
            width=1,
            tags=("range-cell", f"hand:{cell['hand']}"),
        )
        canvas.create_text(
            x + _CELL_WIDTH / 2, y + 11,
            text=cell["hand"],
            fill="#f1f5fa" if measured else "#8a96a5",
            font=("Segoe UI", 8, "bold"),
        )
        if measured:
            canvas.create_text(
                x + _CELL_WIDTH / 2, y + 25,
                text=_cell_summary(cell),
                fill="#cbd7e5",
                font=("Segoe UI", 5),
            )
            bar_left = x + 2
            bar_top = bottom - 7
            usable_width = _CELL_WIDTH - 4
            position = bar_left
            actions = cell["actions"]
            for action_index, action in enumerate(actions):
                if action_index == len(actions) - 1:
                    segment_width = max(0, bar_left + usable_width - position)
                else:
                    segment_width = max(0, int(round(
                        usable_width * float(action["frequency"])
                    )))
                if segment_width > 0:
                    canvas.create_rectangle(
                        position, bar_top, position + segment_width, bottom - 3,
                        fill=action["color"], outline=action["color"],
                    )
                    position += segment_width
        else:
            canvas.create_text(
                x + _CELL_WIDTH / 2, y + 25,
                text="—",
                fill="#778394",
                font=("Segoe UI", 10, "bold"),
            )

    status_y = grid_bottom + 16
    status_id = canvas.create_text(
        _GRID_LEFT, status_y, anchor="w",
        text="Hover a hand to inspect its complete action-frequency mix. Blank cells are not treated as folds.",
        fill="#c3cfdd", font=("Segoe UI", 8),
    )

    legend_y = status_y + 29
    canvas.create_text(
        _GRID_LEFT, legend_y, anchor="w", text="ACTION KEY",
        fill="#91a4ba", font=("Segoe UI", 7, "bold"),
    )
    legend_x = _GRID_LEFT + 85
    legend_y += 1
    legend_rows = 1
    for item in model["legend"]:
        label = str(item["label"])
        item_width = 22 + max(34, len(label) * 6 + 4)
        if legend_x + item_width > canvas_width - 22:
            legend_x = _GRID_LEFT + 85
            legend_y += 23
            legend_rows += 1
        canvas.create_rectangle(
            legend_x, legend_y - 6, legend_x + 11, legend_y + 5,
            fill=item["color"], outline=item["color"],
        )
        canvas.create_text(
            legend_x + 16, legend_y, anchor="w", text=label,
            fill="#c7d3e0", font=("Segoe UI", 7),
        )
        legend_x += item_width

    final_height = max(_CANVAS_BASE_HEIGHT, legend_y + 28)
    try:
        canvas.configure(scrollregion=(0, 0, canvas_width, final_height))
    except Exception:
        pass

    cells_by_index = model["cells"]

    def show_hover(event):
        column = int((event.x - _GRID_LEFT) // (_CELL_WIDTH + _CELL_GAP))
        row = int((event.y - _GRID_TOP) // (_CELL_HEIGHT + _CELL_GAP))
        if not (0 <= row < 13 and 0 <= column < 13):
            canvas.itemconfigure(
                status_id,
                text="Hover a hand to inspect its complete action-frequency mix. Blank cells are not treated as folds.",
            )
            return
        local_x = event.x - (_GRID_LEFT + column * (_CELL_WIDTH + _CELL_GAP))
        local_y = event.y - (_GRID_TOP + row * (_CELL_HEIGHT + _CELL_GAP))
        cell = cells_by_index[row * 13 + column]
        if local_x > _CELL_WIDTH or local_y > _CELL_HEIGHT:
            return
        if not cell["measured"]:
            message = f"{cell['hand']}: no source frequency recorded; this cell is left unassigned"
        else:
            details = " • ".join(
                f"{item['label']}: {float(item['frequency']) * 100:.1f}%"
                for item in cell["actions"]
            )
            message = f"{cell['hand']}: {details}"
        canvas.itemconfigure(status_id, text=message)

    try:
        canvas.bind("<Motion>", show_hover)
        canvas.bind("<Leave>", lambda _event: canvas.itemconfigure(
            status_id,
            text="Hover a hand to inspect its complete action-frequency mix. Blank cells are not treated as folds.",
        ))
    except Exception:
        pass

    return {
        "canvas_width": canvas_width,
        "canvas_height": final_height,
        "cell_count": len(model["cells"]),
        "measured_count": model["measured_count"],
        "blank_count": model["blank_count"],
    }
