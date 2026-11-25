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
from tkinter import messagebox


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
        "time": __import__("time"),
        "messagebox": messagebox,
        "_fit_toplevel_to_monitor_work_area": load_fit_helper(),
        "create_range_photo": create_range_photo,
        "RangeImageCatalogError": RangeImageCatalogError,
    }
    exec(compile(module_ast, str(SOURCE), "exec"), namespace)
    return namespace["_open_preflop_range_view"], create_range_photo, (summary["image_width"], summary["image_height"])


def test_paid_range_full_application_flow_on_windows(root, table):
    # Use the complete production method and the bundled screenshot-derived
    # bitmap. This test intentionally does not construct a Canvas renderer.
    open_range, create_photo, expected_size = load_full_range_view_method()

    table_canvas = tk.Canvas(table, width=900, height=620, bg="#0a1220")
    table_canvas.pack(fill="both", expand=True)
    table.update_idletasks()
    root.update()

    # Use a genuine Tk root as the application master. A plain object can
    # hold test attributes but cannot own a native Tk PhotoImage or Toplevel.
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
    assert len(labels) == 1, f"Range window should contain only one image Label, got {len(labels)}"
    assert not any(isinstance(widget, tk.Canvas) for widget in range_widgets), (
        "The range window must not use a Canvas renderer"
    )
    image_label = labels[0]
    image_name = str(image_label.cget("image"))
    assert image_name, "The range Label has no PhotoImage"
    photo = range_window._range_photo
    assert (photo.width(), photo.height()) == expected_size
    root.update()
    range_window.update()
    image_label.update()
    assert image_label.winfo_width() == photo.width()
    assert image_label.winfo_height() == photo.height()
    print("PASS full application range method shows one native PhotoImage with no Canvas")

    # Confirm the actual Windows child-window pixels contain the range bitmap,
    # not a black rectangle or retained/offscreen drawing commands.
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = wintypes.COLORREF

    px, py = 30, 80
    expected = str(photo.get(px, py))
    assert expected.startswith("#") and len(expected) == 7, expected
    hdc = user32.GetDC(image_label.winfo_id())
    if not hdc:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        pixel = int(gdi32.GetPixel(hdc, px, py))
        actual = (pixel & 0xFF, (pixel >> 8) & 0xFF, (pixel >> 16) & 0xFF)
        wanted = tuple(int(expected[i:i + 2], 16) for i in (1, 3, 5))
        assert all(abs(a - b) <= 4 for a, b in zip(actual, wanted)), {
            "point": (px, py), "actual_rgb": actual, "expected_rgb": wanted,
        }
        assert actual != (0, 0, 0), actual
    finally:
        user32.ReleaseDC(image_label.winfo_id(), hdc)
    print("PASS Windows label client pixels visibly contain the original range-table image")

    table_rect, _ = native_bounds(table)
    range_rect, _ = native_bounds(range_window)
    assert range_rect[0] == table_rect[0] + 12, (table_rect, range_rect)
    assert table_rect[1] <= range_rect[1] <= table_rect[1] + 12, (
        table_rect, range_rect
    )
    assert_inside_work_area(range_window, margin=11)
    print("PASS actual range bitmap window opens at table upper-left and stays inside work area")

    # Also load the first, middle, and last source images through the production
    # asset loader to verify image IDs beyond this one live scenario.
    for source_id in (128, 146, 174, 225, 258, 286, 301):
        extra = create_photo(root, source_id)
        assert (extra.width(), extra.height()) == expected_size, source_id
        del extra
    print("PASS selected source bitmaps load for multiple archive IDs")


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
