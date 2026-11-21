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


def load_real_screenshot_range():
    strategy_path = SOURCE.parent / "pigeon_poker" / "preflop_gto_strategy.py"
    spec = importlib.util.spec_from_file_location(
        "pigeon_preflop_strategy_display_smoke", strategy_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the bundled screenshot-derived preflop policy")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    data = module._data()
    node = next(
        item for item in data["nodes"]
        if len(item.get("hands", {})) == 169
        and all(hand in item["hands"] for hand in module.HAND_ORDER)
    )
    return list(module.HAND_ORDER), node["hands"]


def test_paid_range_canvas_uses_the_application_draw_functions(root, fit_helper, parent):
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

    window = tk.Toplevel(parent)
    window.title("Pigeon Poker range canvas smoke test")
    window.geometry("620x680+0+0")
    root.update_idletasks()
    fit_helper(
        window, max_outer_width=660, max_outer_height=720,
        margin=12, anchor=parent, top_left_of_anchor=True,
    )
    canvas = tk.Canvas(
        window, width=580, height=580, bg="#0b1018",
        highlightthickness=0, bd=0,
    )
    canvas.pack(fill="both", expand=True)
    window.deiconify()
    window.lift()
    root.update()

    order, hands = load_real_screenshot_range()
    palette = {
        "raise": "#e05252", "allin": "#e05252",
        "call": "#45a879", "limp": "#45a879",
        "check": "#45a879", "fold": "#438ac5",
    }
    namespace = {
        "canvas": canvas, "order": order, "hands": hands,
        "palette": palette, "math": math, "tk": tk,
    }
    module_ast = ast.Module(
        body=[nested[name] for name in required], type_ignores=[]
    )
    ast.fix_missing_locations(module_ast)
    exec(compile(module_ast, str(SOURCE), "exec"), namespace)

    namespace["safe_draw"]()
    root.update()
    canvas.update()
    drawn_items = canvas.find_all()
    assert len(drawn_items) >= 169 * 3, len(drawn_items)
    print("PASS real screenshot-derived range data creates all 169 Canvas cells")

    # Confirm the actual Windows Canvas surface contains strategy colors, not
    # merely retained drawing commands on an all-black client area.
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = wintypes.COLORREF
    hdc = user32.GetDC(canvas.winfo_id())
    if not hdc:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        canvas_width = max(1, canvas.winfo_width())
        canvas_height = max(1, canvas.winfo_height())
        cell_width = canvas_width / 13.0
        cell_height = canvas_height / 13.0
        sample = None
        for index, hand_class in enumerate(order):
            choices = hands.get(hand_class, [])
            total = sum(max(0.0, float(item.get("frequency", 0.0) or 0.0)) for item in choices)
            if total <= 0:
                continue
            cumulative = 0.0
            for choice in choices:
                frequency = max(0.0, float(choice.get("frequency", 0.0) or 0.0))
                action = str(choice.get("action", "fold")).lower().replace("_", "")
                if frequency > 0.2:
                    fraction = (cumulative + (frequency / total) / 2.0)
                    row, col = divmod(index, 13)
                    px = min(canvas_width - 2, max(2, int((col + fraction) * cell_width)))
                    py = min(canvas_height - 2, max(2, int((row + 0.25) * cell_height)))
                    expected = palette.get(action, "#438ac5")
                    sample = (px, py, expected)
                    break
                cumulative += frequency / total
            if sample:
                break
        assert sample is not None, "No visible color segment in real screenshot-derived chart"
        px, py, expected = sample
        root.update()
        canvas.update()
        pixel = int(gdi32.GetPixel(hdc, px, py))
        actual_rgb = (pixel & 0xFF, (pixel >> 8) & 0xFF, (pixel >> 16) & 0xFF)
        expected_rgb = tuple(int(expected[i:i+2], 16) for i in (1, 3, 5))
        assert all(abs(a - e) <= 4 for a, e in zip(actual_rgb, expected_rgb)), {
            "point": (px, py), "actual_rgb": actual_rgb, "expected_rgb": expected_rgb,
            "pixel": hex(pixel),
        }
        print("PASS Windows Canvas pixels visibly contain the screenshot-derived range colors")
    finally:
        user32.ReleaseDC(canvas.winfo_id(), hdc)

    # A bad frequency must be ignored safely rather than aborting the paint.
    first_hand = order[0]
    original = hands[first_hand]
    hands[first_hand] = [{"action": "raise", "frequency": "not-a-number"}]
    namespace["safe_draw"]()
    root.update()
    assert len(canvas.find_all()) >= 169 * 3
    hands[first_hand] = original
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
            margin=12, anchor=table, top_left_of_anchor=True,
        )
        root.update()
        assert range_size and min(range_size) > 0, range_size
        assert_inside_work_area(range_window, margin=11)
        table_rect, _ = native_bounds(table)
        range_rect, _ = native_bounds(range_window)
        assert range_rect[0] == table_rect[0] + 12, (table_rect, range_rect)
        # Keep the upper-left alignment while clamping down to the work area's
        # top inset when there is no vertical space for the additional 12 px.
        assert table_rect[1] <= range_rect[1] <= table_rect[1] + 12, (table_rect, range_rect)
        print("PASS paid-range window opens at the table's upper-left corner")

        test_paid_range_canvas_uses_the_application_draw_functions(root, fit, table)
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
