from __future__ import annotations

import ast
import ctypes
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
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
