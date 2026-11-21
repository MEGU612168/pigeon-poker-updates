from __future__ import annotations

import ast
import ctypes
import math
import os
from ctypes import wintypes
from pathlib import Path
import tkinter as tk


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


def test_paid_range_canvas_uses_the_application_draw_functions(root, fit_helper):
    source_text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(SOURCE))
    view = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_open_preflop_range_view"
    )
    nested = {
        node.name: node for node in ast.walk(view)
        if isinstance(node, ast.FunctionDef)
    }
    required = ("safe_frequency", "draw", "safe_draw")
    assert all(name in nested for name in required), required

    window = tk.Toplevel(root)
    window.title("Pigeon Poker range canvas smoke test")
    window.geometry("620x680+0+0")
    root.update_idletasks()
    fit_helper(
        window, max_outer_width=660, max_outer_height=720,
        margin=12, anchor=root,
    )
    canvas = tk.Canvas(
        window, width=580, height=580, bg="#0b1018",
        highlightthickness=0, bd=0,
    )
    canvas.pack(fill="both", expand=True)
    root.update()

    order = [f"H{i:03d}" for i in range(169)]
    hands = {
        hand: [
            {"action": "raise", "frequency": 0.4},
            {"action": "fold", "frequency": 0.6},
        ]
        for hand in order
    }
    palette = {
        "raise": "#e05252", "allin": "#e05252",
        "call": "#45a879", "limp": "#45a879",
        "check": "#45a879", "fold": "#438ac5",
    }
    namespace = {
        "canvas": canvas, "order": order, "hands": hands,
        "palette": palette, "math": math, "tk": tk,
    }
    module = ast.Module(
        body=[nested[name] for name in required], type_ignores=[]
    )
    ast.fix_missing_locations(module)
    exec(compile(module, str(SOURCE), "exec"), namespace)

    namespace["safe_draw"]()
    root.update()
    drawn_items = canvas.find_all()
    assert len(drawn_items) >= 169 * 3, len(drawn_items)
    print("PASS paid-range app draw function renders the 169-cell Canvas on Windows")

    # A bad frequency must be ignored safely rather than aborting the paint.
    hands[order[0]] = [{"action": "raise", "frequency": "not-a-number"}]
    namespace["safe_draw"]()
    root.update()
    assert len(canvas.find_all()) >= 169 * 3
    print("PASS malformed frequency data does not blank the range Canvas")

    # A renderer exception must produce a visible diagnostic, not an empty black canvas.
    namespace["draw"] = lambda _event=None: (_ for _ in ()).throw(RuntimeError("smoke"))
    namespace["safe_draw"]()
    root.update()
    visible_messages = [
        str(canvas.itemcget(item, "text"))
        for item in canvas.find_all()
        if str(canvas.type(item)) == "text"
    ]
    assert any(message.startswith("RANGE DISPLAY ERROR") for message in visible_messages), visible_messages
    print("PASS range-render errors produce a visible diagnostic instead of a black screen")


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

        range_window = tk.Toplevel(table)
        range_window.geometry("620x680+0+0")
        root.update_idletasks()
        range_size = fit(
            range_window, max_outer_width=660, max_outer_height=720,
            margin=12, anchor=table,
        )
        root.update()
        assert range_size and min(range_size) > 0, range_size
        assert_inside_work_area(range_window, margin=11)
        print("PASS paid-range outer frame is clamped to the same monitor work area")

        test_paid_range_canvas_uses_the_application_draw_functions(root, fit)
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
