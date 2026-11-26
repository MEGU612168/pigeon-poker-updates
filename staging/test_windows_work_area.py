from __future__ import annotations

import ast
import ctypes
import importlib.util
import math
import os
import sys
from ctypes import wintypes
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG), ("top", wintypes.LONG),
        ("right", wintypes.LONG), ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
        ("rcWork", RECT), ("dwFlags", wintypes.DWORD),
    ]


def load_fit_helper():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_fit_toplevel_to_monitor_work_area"
    )
    source = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), node)
    namespace = {"tk": tk, "os": os}
    exec("from __future__ import annotations\n" + source, namespace)
    return namespace[node.name]


def native_bounds(window):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    hwnd = int(window.winfo_id())
    root_hwnd = user32.GetAncestor(hwnd, 2) or hwnd
    rect = RECT()
    if not user32.GetWindowRect(root_hwnd, ctypes.byref(rect)):
        raise ctypes.WinError(ctypes.get_last_error())
    monitor = user32.MonitorFromWindow(root_hwnd, 2)
    if not monitor:
        raise RuntimeError("MonitorFromWindow returned no monitor")
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    return (
        (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)),
        (int(info.rcWork.left), int(info.rcWork.top),
         int(info.rcWork.right), int(info.rcWork.bottom)),
    )


def assert_inside_work_area(window, margin=0):
    rect, work = native_bounds(window)
    left, top, right, bottom = rect
    work_left, work_top, work_right, work_bottom = work
    assert left >= work_left + margin, (rect, work, margin)
    assert top >= work_top + margin, (rect, work, margin)
    assert right <= work_right - margin, (rect, work, margin)
    assert bottom <= work_bottom - margin, (rect, work, margin)


def all_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from all_widgets(child)


def load_full_range_view_method():
    sys.path.insert(0, str(SOURCE.parent))
    from pigeon_poker.range_image_catalog import (
        create_range_photo,
        RangeImageCatalogError,
        range_catalog_summary,
    )
    from pigeon_poker.range_chart_canvas import (
        build_range_chart_model,
        draw_preflop_range_canvas,
        RangeChartDataError,
    )
    summary = range_catalog_summary()
    assert summary["source_image_count"] == 174

    source_text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(SOURCE))
    method = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_open_preflop_range_view"
    )
    module_ast = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            method,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module_ast)
    namespace = {
        "tk": tk,
        "ttk": ttk,
        "time": __import__("time"),
        "messagebox": messagebox,
        "_fit_toplevel_to_monitor_work_area": load_fit_helper(),
        "create_range_photo": create_range_photo,
        "RangeImageCatalogError": RangeImageCatalogError,
        "build_range_chart_model": build_range_chart_model,
        "draw_preflop_range_canvas": draw_preflop_range_canvas,
        "RangeChartDataError": RangeChartDataError,
    }
    exec(compile(module_ast, str(SOURCE), "exec"), namespace)
    display_width = (summary["image_width"] + 1) // 2 if summary["image_width"] > 700 or summary["image_height"] > 550 else summary["image_width"]
    display_height = (summary["image_height"] + 1) // 2 if summary["image_width"] > 700 or summary["image_height"] > 550 else summary["image_height"]
    return namespace["_open_preflop_range_view"], create_range_photo, (display_width, display_height)


def test_paid_range_full_application_flow_on_windows(root, table):
    # Exercise the production 13x13 native Canvas renderer and its real
    # scrollable Toplevel, while separately checking archived source images.
    open_range, create_photo, expected_size = load_full_range_view_method()

    table_canvas = tk.Canvas(table, width=900, height=620, bg="#0a1220")
    table_canvas.pack(fill="both", expand=True)
    table.update_idletasks()
    root.update()

    # Use a genuine Tk root as the application master. A plain object cannot
    # own a native Tk Canvas or Toplevel.
    root.table_windows = {"smoke": {"canvas": table_canvas}}
    root.multi_tables = {}
    root.active_cash_table_id = None
    root.squeeze_deadline_jobs = {}

    chart = {
        "source_id": 301,
        "actor_position": "SB",
        "match_mode": "exact",
    }
    open_range(
        root,
        chart,
        title="LIVE PREFLOP RANGE",
        charge_label="Windows end-to-end smoke test",
        table_id="smoke",
    )
    root.update()
    table.update()
    root.update()

    range_window = next(
        widget for widget in all_widgets(root)
        if isinstance(widget, tk.Toplevel)
        and widget is not table
        and widget.title() == "PIGEON POKER • RANGE #301"
    )
    assert range_window.winfo_viewable(), "The actual range Toplevel is not viewable"

    range_widgets = list(all_widgets(range_window))
    labels = [widget for widget in range_widgets if isinstance(widget, tk.Label)]
    assert len(labels) == 2, (
        f"Range window should have its title and charge labels, got {len(labels)}"
    )
    assert all(not str(widget.cget("image")) for widget in labels), (
        "The native Canvas range view must not depend on a PhotoImage Label"
    )
    canvases = [widget for widget in range_widgets if isinstance(widget, tk.Canvas)]
    assert len(canvases) == 1, f"Range window should contain one Canvas, got {len(canvases)}"
    chart_canvas = canvases[0]
    cells = chart_canvas.find_withtag("range-cell")
    assert len(cells) == 169, f"Expected 169 hand-class cells, got {len(cells)}"
    frequency_bars = chart_canvas.find_withtag("range-frequency")
    assert frequency_bars, "The Canvas contains no action-frequency segments"
    first_cell_fill = chart_canvas.itemcget(cells[0], "fill")
    assert first_cell_fill.startswith("#"), first_cell_fill
    scrollregion = tuple(float(value) for value in chart_canvas.cget("scrollregion").split())
    assert len(scrollregion) == 4 and scrollregion[2] >= 700 and scrollregion[3] >= 770
    assert chart_canvas.winfo_width() >= 600
    assert chart_canvas.winfo_height() >= 500
    print("PASS live range Toplevel renders all 169 cells and action-frequency bars on native Canvas")

    table_rect, _ = native_bounds(table)
    range_rect, _ = native_bounds(range_window)
    assert range_rect[0] == table_rect[0] + 12, (table_rect, range_rect)
    assert table_rect[1] <= range_rect[1] <= table_rect[1] + 12, (
        table_rect, range_rect
    )
    assert_inside_work_area(range_window, margin=11)
    print("PASS native Canvas range window opens at table upper-left and stays inside work area")

    # Keep the archived source-asset loader smoke test separate from the live
    # Canvas view, which intentionally does not use images.
    for source_id in (128, 146, 174, 225, 258, 286, 301):
        extra = create_photo(root, source_id)
        assert (extra.width(), extra.height()) == expected_size, source_id
        del extra
    print("PASS selected source archive images load for multiple source IDs")


def main():
    if os.name != "nt":
        raise SystemExit("This smoke test must run on Windows")

    fit = load_fit_helper()
    root = tk.Tk()
    root.title("Pigeon Poker work-area smoke test")
    root.geometry("1480x900+0+0")
    try:
        root.update_idletasks()
        root_size = fit(root)
        root.update()
        assert root_size and min(root_size) > 0, root_size
        assert_inside_work_area(root, margin=0)
        print("PASS root outer frame is inside monitor work area")

        table = tk.Toplevel(root)
        table.geometry("1280x860+0+0")
        root.update_idletasks()
        table_size = fit(
            table, max_outer_width=1280, max_outer_height=860,
            margin=12, anchor=root,
        )
        root.update()
        assert table_size and min(table_size) > 0, table_size
        assert_inside_work_area(table, margin=11)
        print("PASS floating table outer frame preserves taskbar margin")

        test_paid_range_full_application_flow_on_windows(root, table)
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
