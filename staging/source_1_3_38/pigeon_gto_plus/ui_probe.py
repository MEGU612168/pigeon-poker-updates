#!/usr/bin/env python3
"""GTO+ window diagnostic using native Windows APIs through ctypes.

This version deliberately avoids psutil, pywinauto, comtypes, and UI Automation
so it can run in the bundled Python environment without extra dependencies.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
import json
import os
import re
import sys
import struct
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_NAME = "GTO+"
MAX_CONTROLS_DEFAULT = 3500


def _normalise(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _find_gto_processes() -> list[dict[str, Any]]:
    """Find GTO.exe processes with Toolhelp32; no third-party package required."""
    if os.name != "nt":
        raise RuntimeError("この診断はWindows専用です。")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    def process_image_path(pid: int) -> str:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            length = wintypes.DWORD(len(buffer))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                return buffer.value
            return ""
        finally:
            kernel32.CloseHandle(handle)

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise OSError(error, "CreateToolhelp32Snapshot failed while enumerating processes")

    rows: list[dict[str, Any]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        has_entry = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
        while has_entry:
            name = str(entry.szExeFile or "")
            pid = int(entry.th32ProcessID)
            if name.casefold() == "gto.exe":
                exe = process_image_path(pid)
                rows.append({
                    "pid": pid,
                    "name": name,
                    "exe_name": Path(exe).name if exe else name,
                    "exe": exe,
                })
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            has_entry = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
    finally:
        kernel32.CloseHandle(snapshot)
    return rows


def _win32_api():
    if os.name != "nt":
        raise RuntimeError("この診断はWindows専用です。")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                    ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumChildWindows.argtypes = [wintypes.HWND, EnumChildProc, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.IsWindowEnabled.restype = wintypes.BOOL
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
    user32.GetDlgCtrlID.restype = ctypes.c_int
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user32.mouse_event.restype = None
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user32.keybd_event.restype = None
    # Bounded cross-process Edit-control messaging. The timeout avoids hanging
    # Pigeon Poker if GTO+ stops responding while a probe is running.
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM

    return user32, EnumWindowsProc, EnumChildProc, RECT, POINT


def _window_pid(user32, hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    return int(pid.value)


def _window_text(user32, hwnd: int) -> str:
    try:
        length = max(0, min(int(user32.GetWindowTextLengthW(wintypes.HWND(hwnd))), 32767))
        buf = ctypes.create_unicode_buffer(length + 2)
        user32.GetWindowTextW(wintypes.HWND(hwnd), buf, len(buf))
        return _normalise(buf.value)
    except Exception:
        return ""


def _class_name(user32, hwnd: int) -> str:
    try:
        buf = ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(wintypes.HWND(hwnd), buf, len(buf))
        return _normalise(buf.value)
    except Exception:
        return ""


def _rect(user32, RECT, hwnd: int) -> list[int] | None:
    try:
        rc = RECT()
        if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc)):
            return None
        return [int(rc.left), int(rc.top), int(rc.right), int(rc.bottom)]
    except Exception:
        return None


def _all_hwnds(user32, EnumWindowsProc, EnumChildProc) -> tuple[list[int], dict[int, list[int]]]:
    roots: list[int] = []
    def on_root(hwnd, _):
        roots.append(int(hwnd))
        return True
    callback = EnumWindowsProc(on_root)
    user32.EnumWindows(callback, 0)
    children_by_root: dict[int, list[int]] = {}
    for root in roots:
        children: list[int] = []
        def on_child(hwnd, _):
            children.append(int(hwnd))
            return True
        child_callback = EnumChildProc(on_child)
        user32.EnumChildWindows(wintypes.HWND(root), child_callback, 0)
        children_by_root[root] = children
    return roots, children_by_root


def _control_record(user32, RECT, hwnd: int, index: int) -> dict[str, Any]:
    parent = int(user32.GetParent(wintypes.HWND(hwnd)) or 0)
    rect = _rect(user32, RECT, hwnd)
    return {
        "index": index,
        "name": _window_text(user32, hwnd),
        "control_type": _class_name(user32, hwnd),
        "class_name": _class_name(user32, hwnd),
        "automation_id": None,
        "control_id": int(user32.GetDlgCtrlID(wintypes.HWND(hwnd))),
        "process_id": _window_pid(user32, hwnd),
        "handle": int(hwnd),
        "parent_handle": parent,
        "rectangle": rect,
        "visible": bool(user32.IsWindowVisible(wintypes.HWND(hwnd))),
        "enabled": bool(user32.IsWindowEnabled(wintypes.HWND(hwnd))),
        "style": int(user32.GetWindowLongW(wintypes.HWND(hwnd), -16)),
    }



def _menu_tree(user32, hwnd: int, max_depth: int = 4) -> list[dict[str, Any]]:
    """Read the native Win32 menu hierarchy without opening or changing menus."""
    def _native_int(value: Any) -> int:
        # ctypes scalar wrappers expose the native value through .value; int(c_uint)
        # can raise ValueError on Windows, so unwrap before conversion.
        raw = getattr(value, "value", value)
        return int(raw or 0)

    try:
        user32.GetMenu.argtypes = [wintypes.HWND]
        user32.GetMenu.restype = wintypes.HMENU
        user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
        user32.GetSubMenu.restype = wintypes.HMENU
        user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
        user32.GetMenuItemCount.restype = ctypes.c_int
        user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
        user32.GetMenuItemID.restype = wintypes.UINT
        user32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR,
                                          ctypes.c_int, wintypes.UINT]
        user32.GetMenuStringW.restype = ctypes.c_int
        root_menu = _native_int(user32.GetMenu(wintypes.HWND(hwnd)))
        if not root_menu:
            return []

        def walk(menu_handle: int, depth: int) -> list[dict[str, Any]]:
            if not menu_handle or depth > max_depth:
                return []
            items: list[dict[str, Any]] = []
            count = int(user32.GetMenuItemCount(wintypes.HMENU(menu_handle)))
            for pos in range(max(0, min(count, 256))):
                buf = ctypes.create_unicode_buffer(512)
                user32.GetMenuStringW(wintypes.HMENU(menu_handle), pos, buf, len(buf), 0x0400)  # MF_BYPOSITION
                label = buf.value
                command_id = _native_int(user32.GetMenuItemID(wintypes.HMENU(menu_handle), pos))
                submenu = _native_int(user32.GetSubMenu(wintypes.HMENU(menu_handle), pos))
                item: dict[str, Any] = {
                    "position": pos,
                    "label": label,
                    "command_id": None if command_id == 0xFFFFFFFF else command_id,
                }
                if submenu:
                    item["children"] = walk(submenu, depth + 1)
                items.append(item)
            return items

        return walk(root_menu, 0)
    except Exception as exc:
        return [{"error": f"{type(exc).__name__}: {exc}"}]


# Reference anchors re-measured from the actual 1272x586 client screenshot
# inside the user's 2026-11-19 diagnostic ZIP. The prior y coordinates were
# 63px too low and did not point at the OOP matrix. These are advisory anchors.
_VISUAL_COORDINATE_REFERENCE = {
    "reference_client_size": [1272, 586],
    "basis": "pixel-measured from user's captured GTO+ client image; OOP matrix bounds checked visually",
    "anchors": {
        "oop_range_matrix": {"rect": [43, 139, 123, 218], "center": [83, 178.5]},
        "ip_range_matrix": {"rect": [43, 249, 123, 327], "center": [83, 288]},
        "board_text_entry": {"rect": [36, 358, 132, 383], "center": [84, 370.5]},
        "build_tree_button": {"rect": [36, 394, 131, 429], "center": [83.5, 411.5]},
        "run_solver_button": {"rect": [36, 440, 131, 475], "center": [83.5, 457.5]},
    },
}


# The GTO+ Starting Range Editor Source code input field, measured directly
# from the successful embedded 680x476 capture produced after the OOP matrix
# click (2026-11-19 03:26:51). The white edit area is x=107..411, y=366..382.
# This probe only focuses the field; it never types or pastes text.
_OOP_SOURCE_FIELD_REFERENCE = {
    "reference_client_size": [680, 476],
    "rect": [107, 366, 411, 382],
    "center": [259, 374],
    "basis": "pixel-measured from gto_plus_ui_20261119_032647_oop_editor_open.bmp in the exact embedded GTO+ client",
}

# The current Pigeon-embedded GTO+ client screenshot is 680x476. On this
# embedded view, GTO+ keeps its left-side setup controls at their measured
# pixel positions instead of proportionally shrinking them with the host.
# Coordinates were measured directly from the 2026-11-19 03:20:55 capture.
_OOP_SINGLE_STEP_REFERENCE = {
    "reference_client_size": [680, 476],
    "oop_range_matrix_rect": [27, 88, 82, 144],
    "oop_range_matrix_center": [54, 116],
    "basis": "pixel-measured from gto_plus_ui_20261119_032055_window_primary.bmp",
}

# The embedded GTO+ left-side setup controls use fixed client-pixel anchors.
# The host may add unused vertical space (e.g. 665x570 instead of 680x476),
# so scaling anchors by the full client height moves clicks away from controls.
# Keep a conservative envelope to reject accidentally selected host windows.
_OOP_EMBEDDED_CLIENT_LIMITS = {
    "min_width": 620,
    "max_width": 900,
    "min_height": 450,
    "max_height": 700,
    "required_right": 502,
    "required_bottom": 383,
}


def _validated_oop_client_size(user32, hwnd: int, RECT, stage: str) -> tuple[int, int]:
    """Validate the calibrated embedded GTO+ view without assuming an exact size."""
    client = RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
        raise OSError(f"GetClientRect failed during {stage}: {ctypes.get_last_error()}")
    width = int(client.right - client.left)
    height = int(client.bottom - client.top)
    limits = _OOP_EMBEDDED_CLIENT_LIMITS
    if not (limits["min_width"] <= width <= limits["max_width"]
            and limits["min_height"] <= height <= limits["max_height"]):
        raise RuntimeError(
            f"{stage}: embedded GTO+ client is outside the calibrated view envelope "
            f"({limits['min_width']}..{limits['max_width']} x "
            f"{limits['min_height']}..{limits['max_height']}); "
            f"actual={width}x{height}; no click or range change sent"
        )
    if width <= limits["required_right"] or height <= limits["required_bottom"]:
        raise RuntimeError(
            f"{stage}: calibrated OOP controls do not fit in client area "
            f"{width}x{height}; no click or range change sent"
        )
    return width, height



def _open_oop_range_editor(user32, hwnd: int, RECT, POINT) -> dict[str, Any]:
    """Open the OOP Starting Range Editor on the exact embedded GTO+ target.

    Safety: use the calibrated embedded-client envelope and fixed measured
    matrix anchor. Click once, then return. No hand cell, range text, weights,
    tree, or solver operation is touched.
    """
    width, height = _validated_oop_client_size(
        user32, hwnd, RECT, "Open OOP range editor"
    )
    # GTO+ keeps these controls at their measured client-pixel positions; extra
    # blank client height must not rescale the Y coordinate.
    x0, y0, x1, y1 = _OOP_SINGLE_STEP_REFERENCE["oop_range_matrix_rect"]
    anchor_x, anchor_y = _OOP_SINGLE_STEP_REFERENCE["oop_range_matrix_center"]
    matrix_rect = [int(x0), int(y0), int(x1), int(y1)]
    click_x, click_y = int(anchor_x), int(anchor_y)
    if not (matrix_rect[0] <= click_x <= matrix_rect[2] and
            matrix_rect[1] <= click_y <= matrix_rect[3]):
        raise RuntimeError(
            f"OOP click point is outside measured matrix: point=({click_x},{click_y}), "
            f"matrix={matrix_rect}; no click sent"
        )
    if not (0 <= click_x < width and 0 <= click_y < height):
        raise RuntimeError(
            f"OOP click point is outside client area: ({click_x},{click_y}) in {width}x{height}; no click sent"
        )

    screen_point = POINT(click_x, click_y)
    if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(screen_point)):
        raise OSError(f"ClientToScreen failed: {ctypes.get_last_error()}")

    previous_foreground = int(user32.GetForegroundWindow() or 0)
    previous_cursor = POINT()
    have_cursor = bool(user32.GetCursorPos(ctypes.byref(previous_cursor)))
    foreground_host = _top_level_ancestor(user32, hwnd)
    if not foreground_host or not user32.IsWindow(wintypes.HWND(foreground_host)):
        raise RuntimeError(f"Could not resolve a valid top-level host for embedded GTO+ HWND={hwnd}; no click sent")
    user32.ShowWindow(wintypes.HWND(foreground_host), 9)  # SW_RESTORE
    user32.BringWindowToTop(wintypes.HWND(hwnd))
    focus_ok = bool(user32.SetForegroundWindow(wintypes.HWND(foreground_host)))
    time.sleep(0.25)
    foreground_now = int(user32.GetForegroundWindow() or 0)
    if foreground_now != int(foreground_host):
        raise RuntimeError(
            f"GTO+ foreground check failed; no click sent (requested_child={hwnd}, "
            f"foreground_host={foreground_host}, actual={foreground_now}, SetForegroundWindow={focus_ok})"
        )

    moved = bool(user32.SetCursorPos(int(screen_point.x), int(screen_point.y)))
    if not moved:
        raise OSError(f"SetCursorPos failed: {ctypes.get_last_error()}")
    mouse_down_sent = False
    try:
        time.sleep(0.08)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        mouse_down_sent = True
        time.sleep(0.06)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        mouse_down_sent = False
        time.sleep(0.80)
    finally:
        if mouse_down_sent:
            user32.mouse_event(0x0004, 0, 0, 0, 0)  # always release the button
        if have_cursor:
            user32.SetCursorPos(int(previous_cursor.x), int(previous_cursor.y))

    return {
        "action": "single_left_click_open_oop_range_editor",
        "target_hwnd": int(hwnd),
        "target_pid": _window_pid(user32, hwnd),
        "client_size": [width, height],
        "reference_client_size": [ref_w, ref_h],
        "scale": [round(sx, 6), round(sy, 6)],
        "matrix_rect_client": matrix_scaled,
        "click_client": [click_x, click_y],
        "click_screen": [int(screen_point.x), int(screen_point.y)],
        "foreground_verified": True,
        "foreground_host_hwnd": int(foreground_host),
        "set_foreground_window_return": focus_ok,
        "previous_foreground_hwnd": previous_foreground,
        "range_values_changed_by_probe": False,
        "tree_built": False,
        "solver_run": False,
    }

def _window_observation(user32, RECT, hwnd: int) -> dict[str, Any] | None:
    """Return read-only identity/geometry for one live HWND."""
    value = int(hwnd or 0)
    if not value or not user32.IsWindow(wintypes.HWND(value)):
        return None
    return {
        "hwnd": value,
        "pid": _window_pid(user32, value),
        "class": _class_name(user32, value),
        "title": _window_text(user32, value),
        "control_id": int(user32.GetDlgCtrlID(wintypes.HWND(value))),
        "parent_hwnd": int(user32.GetParent(wintypes.HWND(value)) or 0),
        "owner_hwnd": int(user32.GetWindow(wintypes.HWND(value), 4) or 0),
        "rect_screen": _rect(user32, RECT, value),
        "visible": bool(user32.IsWindowVisible(wintypes.HWND(value))),
        "enabled": bool(user32.IsWindowEnabled(wintypes.HWND(value))),
    }


def _gui_thread_focus_snapshot(user32, RECT, POINT, target_hwnd: int,
                                foreground_hwnd: int | None = None,
                                source_point_screen: tuple[int, int] | None = None) -> dict[str, Any]:
    """Observe GUI focus/caret state with GetGUIThreadInfo; never sends input."""
    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", RECT),
        ]

    user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
    user32.GetGUIThreadInfo.restype = wintypes.BOOL

    target_pid = wintypes.DWORD(0)
    target_thread = int(user32.GetWindowThreadProcessId(
        wintypes.HWND(target_hwnd), ctypes.byref(target_pid)))
    host = int(foreground_hwnd or 0)
    threads: dict[int, dict[str, Any]] = {}
    candidates = [("gto_target", int(target_hwnd))]
    if host:
        candidates.append(("foreground_host", host))
    for label, window in candidates:
        pid = wintypes.DWORD(0)
        tid = int(user32.GetWindowThreadProcessId(wintypes.HWND(window), ctypes.byref(pid)))
        if not tid or tid in threads:
            continue
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        ok = bool(user32.GetGUIThreadInfo(wintypes.DWORD(tid), ctypes.byref(info)))
        record: dict[str, Any] = {
            "thread_id": tid,
            "pid": int(pid.value),
            "query_labels": [label],
            "success": ok,
        }
        if not ok:
            record["error_code"] = int(ctypes.get_last_error())
        else:
            record["flags"] = int(info.flags)
            record["flags_hex"] = f"0x{int(info.flags):08X}"
            handles = {
                "active": int(info.hwndActive or 0),
                "focus": int(info.hwndFocus or 0),
                "capture": int(info.hwndCapture or 0),
                "menu_owner": int(info.hwndMenuOwner or 0),
                "move_size": int(info.hwndMoveSize or 0),
                "caret": int(info.hwndCaret or 0),
            }
            record["handles"] = handles
            record["windows"] = {
                key: _window_observation(user32, RECT, value)
                for key, value in handles.items()
            }
            caret = info.rcCaret
            caret_client = [int(caret.left), int(caret.top), int(caret.right), int(caret.bottom)]
            record["caret_rect_client"] = caret_client if handles["caret"] else None
            record["caret_rect_screen"] = None
            if handles["caret"]:
                top_left = POINT(int(caret.left), int(caret.top))
                bottom_right = POINT(int(caret.right), int(caret.bottom))
                try:
                    if (user32.ClientToScreen(wintypes.HWND(handles["caret"]), ctypes.byref(top_left))
                            and user32.ClientToScreen(wintypes.HWND(handles["caret"]), ctypes.byref(bottom_right))):
                        record["caret_rect_screen"] = [int(top_left.x), int(top_left.y),
                                                       int(bottom_right.x), int(bottom_right.y)]
                except Exception as exc:
                    record["caret_conversion_error"] = f"{type(exc).__name__}: {exc}"
        threads[tid] = record
    if source_point_screen is not None:
        point = POINT(int(source_point_screen[0]), int(source_point_screen[1]))
        under = int(user32.WindowFromPoint(point) or 0)
        under_info = _window_observation(user32, RECT, under)
    else:
        under_info = None
    foreground = int(user32.GetForegroundWindow() or 0)
    return {
        "method": "GetGUIThreadInfo (read-only)",
        "target_hwnd": int(target_hwnd),
        "target_pid": int(target_pid.value),
        "target_thread_id": target_thread,
        "foreground_hwnd": foreground,
        "foreground_window": _window_observation(user32, RECT, foreground),
        "threads": list(threads.values()),
        "window_from_point_at_source_field": under_info,
        "source_point_screen": list(source_point_screen) if source_point_screen else None,
        "input_sent_by_observer": False,
    }


def _focus_oop_source_text_field(user32, hwnd: int, RECT, POINT) -> dict[str, Any]:
    """Focus the Source code input in the already-open OOP Starting Range Editor.

    Safety: this sends exactly one left click to the measured text field. It
    sends no keyboard events, clipboard content, text, range changes, tree build,
    or solver command.
    """
    client = RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
        raise OSError(f"GetClientRect failed: {ctypes.get_last_error()}")
    width = int(client.right - client.left)
    height = int(client.bottom - client.top)
    ref_w, ref_h = _OOP_SOURCE_FIELD_REFERENCE["reference_client_size"]
    if abs(width - ref_w) > 12 or abs(height - ref_h) > 12:
        raise RuntimeError(
            f"Source-field focus requires the verified embedded layout: "
            f"actual={width}x{height}, reference={ref_w}x{ref_h}; no click sent"
        )
    sx, sy = width / float(ref_w), height / float(ref_h)
    anchor = _OOP_SOURCE_FIELD_REFERENCE["center"]
    click_x = int(round(anchor[0] * sx))
    click_y = int(round(anchor[1] * sy))
    field_rect = _OOP_SOURCE_FIELD_REFERENCE["rect"]
    scaled_rect = [int(round(field_rect[0] * sx)), int(round(field_rect[1] * sy)),
                   int(round(field_rect[2] * sx)), int(round(field_rect[3] * sy))]
    if not (scaled_rect[0] <= click_x <= scaled_rect[2] and scaled_rect[1] <= click_y <= scaled_rect[3]):
        raise RuntimeError(f"Scaled source-field click is outside the measured field: point=({click_x},{click_y}), rect={scaled_rect}")
    if not (0 <= click_x < width and 0 <= click_y < height):
        raise RuntimeError(f"Scaled source-field point is outside client area: ({click_x},{click_y}) in {width}x{height}")

    screen_point = POINT(click_x, click_y)
    if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(screen_point)):
        raise OSError(f"ClientToScreen failed: {ctypes.get_last_error()}")

    previous_foreground = int(user32.GetForegroundWindow() or 0)
    previous_cursor = POINT()
    have_cursor = bool(user32.GetCursorPos(ctypes.byref(previous_cursor)))
    foreground_host = _top_level_ancestor(user32, hwnd)
    if not foreground_host or not user32.IsWindow(wintypes.HWND(foreground_host)):
        raise RuntimeError(f"Could not resolve a valid top-level host for embedded GTO+ HWND={hwnd}; no source-field click sent")
    user32.ShowWindow(wintypes.HWND(foreground_host), 9)  # SW_RESTORE
    user32.BringWindowToTop(wintypes.HWND(hwnd))
    focus_ok = bool(user32.SetForegroundWindow(wintypes.HWND(foreground_host)))
    time.sleep(0.20)
    foreground_now = int(user32.GetForegroundWindow() or 0)
    if foreground_now != int(foreground_host):
        raise RuntimeError(
            f"GTO+ foreground check failed before source-field click; no click sent "
            f"(requested_child={hwnd}, foreground_host={foreground_host}, actual={foreground_now}, SetForegroundWindow={focus_ok})"
        )

    moved = bool(user32.SetCursorPos(int(screen_point.x), int(screen_point.y)))
    if not moved:
        raise OSError(f"SetCursorPos failed: {ctypes.get_last_error()}")
    mouse_down_sent = False
    try:
        time.sleep(0.06)
        user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
        mouse_down_sent = True
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
        mouse_down_sent = False
        time.sleep(0.15)
    finally:
        if mouse_down_sent:
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        if have_cursor:
            user32.SetCursorPos(int(previous_cursor.x), int(previous_cursor.y))

    focus_diagnostics = _gui_thread_focus_snapshot(
        user32, RECT, POINT, hwnd, foreground_host,
        source_point_screen=(int(screen_point.x), int(screen_point.y)),
    )
    return {
        "action": "single_left_click_focus_oop_source_text_field",
        "target_hwnd": int(hwnd),
        "target_pid": _window_pid(user32, hwnd),
        "client_size": [width, height],
        "reference_client_size": [ref_w, ref_h],
        "scale": [round(sx, 6), round(sy, 6)],
        "measured_field_rect_client": scaled_rect,
        "click_client": [click_x, click_y],
        "click_screen": [int(screen_point.x), int(screen_point.y)],
        "foreground_verified": True,
        "foreground_host_hwnd": int(foreground_host),
        "set_foreground_window_return": focus_ok,
        "previous_foreground_hwnd": previous_foreground,
        "focus_diagnostics": focus_diagnostics,
        "text_typed": False,
        "clipboard_used": False,
        "range_values_changed_by_probe": False,
        "tree_built": False,
        "solver_run": False,
    }


def _send_message_timeout(user32, hwnd: int, message: int, wparam: int = 0,
                          lparam: int = 0, timeout_ms: int = 1500) -> int:
    result = ctypes.c_size_t(0)
    ok = user32.SendMessageTimeoutW(
        wintypes.HWND(hwnd), wintypes.UINT(message), wintypes.WPARAM(wparam),
        wintypes.LPARAM(lparam), 0x0002, wintypes.UINT(timeout_ms), ctypes.byref(result),
    )  # SMTO_ABORTIFHUNG
    if not ok:
        raise TimeoutError(
            f"SendMessageTimeoutW timed out/failed: hwnd={hwnd}, message=0x{message:04X}, "
            f"winerror={ctypes.get_last_error()}"
        )
    return int(result.value)


def _read_native_edit_text(user32, hwnd: int) -> str:
    WM_GETTEXTLENGTH = 0x000E
    WM_GETTEXT = 0x000D
    length = _send_message_timeout(user32, hwnd, WM_GETTEXTLENGTH, 0, 0)
    capacity = max(2, min(int(length) + 2, 4096))
    buffer = ctypes.create_unicode_buffer(capacity)
    _send_message_timeout(
        user32, hwnd, WM_GETTEXT, capacity,
        ctypes.cast(buffer, ctypes.c_void_p).value or 0,
    )
    return buffer.value


def _write_native_edit_text(user32, hwnd: int, text: str) -> None:
    WM_SETTEXT = 0x000C
    buffer = ctypes.create_unicode_buffer(text)
    _send_message_timeout(
        user32, hwnd, WM_SETTEXT, 0,
        ctypes.cast(buffer, ctypes.c_void_p).value or 0,
    )


def _probe_oop_source_field_input(user32, root_hwnd: int, RECT, POINT,
                                  output_dir: Path, stem: str) -> dict[str, Any]:
    """Temporarily write 'AA' to the native Source code Edit control, read it
    back, then restore the exact original text (only if originally blank).

    The probe never clicks the editor's Done button, never selects a hand cell,
    and never builds a tree or runs the solver. If the field is non-empty or the
    control identity is ambiguous, it aborts without changing anything.
    """
    target_pid = _window_pid(user32, root_hwnd)
    children: list[int] = []
    EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _collect(child, _):
        children.append(int(child))
        return True

    callback = EnumChildProc(_collect)
    user32.EnumChildWindows(wintypes.HWND(root_hwnd), callback, 0)
    candidates = []
    for child in children:
        if _window_pid(user32, child) != target_pid:
            continue
        if _class_name(user32, child) != "Edit":
            continue
        if int(user32.GetDlgCtrlID(wintypes.HWND(child))) != 5458:
            continue
        if not user32.IsWindowVisible(wintypes.HWND(child)) or not user32.IsWindowEnabled(wintypes.HWND(child)):
            continue
        child_rect = _rect(user32, RECT, child)
        if child_rect:
            candidates.append((child, child_rect))

    if len(candidates) != 1:
        return {
            "action": "temporary_source_code_edit_test",
            "status": "skipped_ambiguous_or_missing_control",
            "target_pid": target_pid,
            "candidate_count": len(candidates),
            "expected_class": "Edit",
            "expected_control_id": 5458,
            "text_changed": False,
            "tree_built": False,
            "solver_run": False,
        }

    edit_hwnd, edit_rect = candidates[0]
    # Verify that this Edit is located where the previously captured Source code
    # field is expected, relative to the root client origin.
    client = RECT()
    if not user32.GetClientRect(wintypes.HWND(root_hwnd), ctypes.byref(client)):
        raise OSError(f"GetClientRect failed: {ctypes.get_last_error()}")
    origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(wintypes.HWND(root_hwnd), ctypes.byref(origin)):
        raise OSError(f"ClientToScreen failed: {ctypes.get_last_error()}")
    ref_center = _OOP_SOURCE_FIELD_REFERENCE["center"]
    expected_center = [int(origin.x + ref_center[0]), int(origin.y + ref_center[1])]
    actual_center = [(edit_rect[0] + edit_rect[2]) // 2, (edit_rect[1] + edit_rect[3]) // 2]
    delta = [abs(actual_center[0] - expected_center[0]), abs(actual_center[1] - expected_center[1])]
    if delta[0] > 35 or delta[1] > 35:
        return {
            "action": "temporary_source_code_edit_test",
            "status": "skipped_control_outside_expected_source_field",
            "target_pid": target_pid,
            "target_hwnd": int(edit_hwnd),
            "control_id": 5458,
            "control_rect_screen": edit_rect,
            "expected_center_screen": expected_center,
            "actual_center_screen": actual_center,
            "center_delta": delta,
            "text_changed": False,
            "tree_built": False,
            "solver_run": False,
        }

    original_text = _read_native_edit_text(user32, edit_hwnd)
    if original_text != "":
        return {
            "action": "temporary_source_code_edit_test",
            "status": "skipped_nonempty_field_preserved",
            "target_pid": target_pid,
            "target_hwnd": int(edit_hwnd),
            "control_id": 5458,
            "original_text_length": len(original_text),
            "text_changed": False,
            "tree_built": False,
            "solver_run": False,
        }

    test_text = "AA"  # one valid, harmless combo token; it is never committed.
    write_verified = False
    readback = None
    capture_test = None
    restore_verified = False
    restore_error = None
    capture_restored = None
    try:
        _write_native_edit_text(user32, edit_hwnd, test_text)
        readback = _read_native_edit_text(user32, edit_hwnd)
        write_verified = readback == test_text
        if not write_verified:
            raise RuntimeError(f"Source code text readback mismatch: expected={test_text!r}, got={readback!r}")

        test_capture_path = output_dir / f"{stem}_source_text_temporary.bmp"
        pth, method, err, geometry = _capture_window(
            user32, root_hwnd, _rect(user32, RECT, root_hwnd), test_capture_path, RECT, POINT
        )
        capture_test = {"screenshot": pth, "capture_method": method,
                        "capture_error": err, "capture_geometry": geometry}
        if err:
            raise RuntimeError(f"Temporary text screenshot failed: {err}")
    finally:
        # Restore only the exact original value. The probe entered this branch
        # only after confirming that the original field was empty.
        try:
            _write_native_edit_text(user32, edit_hwnd, original_text)
            restore_value = _read_native_edit_text(user32, edit_hwnd)
            restore_verified = restore_value == original_text
            if not restore_verified:
                restore_error = f"restore readback mismatch: {restore_value!r}"
        except Exception as exc:
            restore_error = f"{type(exc).__name__}: {exc}"

    restored_capture_path = output_dir / f"{stem}_source_text_restored.bmp"
    pth, method, err, geometry = _capture_window(
        user32, root_hwnd, _rect(user32, RECT, root_hwnd), restored_capture_path, RECT, POINT
    )
    capture_restored = {"screenshot": pth, "capture_method": method,
                        "capture_error": err, "capture_geometry": geometry}

    status = "write_readback_and_restore_verified" if write_verified and restore_verified else "test_incomplete"
    return {
        "action": "temporary_source_code_edit_test",
        "status": status,
        "target_pid": target_pid,
        "target_hwnd": int(edit_hwnd),
        "control_id": 5458,
        "control_class": "Edit",
        "control_rect_screen": edit_rect,
        "expected_center_screen": expected_center,
        "actual_center_screen": actual_center,
        "center_delta": delta,
        "test_text": test_text,
        "write_readback": readback,
        "write_verified": write_verified,
        "original_text_restored": restore_verified,
        "restore_error": restore_error,
        "temporary_capture": capture_test,
        "restored_capture": capture_restored,
        "done_button_clicked": False,
        "range_committed": False,
        "tree_built": False,
        "solver_run": False,
    }


def _capture_window(user32, hwnd: int, rect: list[int] | None, target: Path,
                    RECT, POINT) -> tuple[str | None, str | None, str | None, dict[str, Any] | None]:
    """Capture only the GTO+ client area using Win32 GDI.

    GetWindowRect can include a host/container area when GTO+ has been docked.
    For coordinate-based automation, the useful origin is the client origin
    converted to desktop coordinates with ClientToScreen. The fallback BitBlt
    therefore copies that exact client rectangle, not the larger outer frame.
    """
    if not rect or len(rect) != 4:
        return None, None, "window rectangle unavailable", None

    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL

    client = RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
        return None, None, f"GetClientRect failed: {ctypes.get_last_error()}", None
    width = int(client.right - client.left)
    height = int(client.bottom - client.top)
    if width < 160 or height < 120 or width > 10000 or height > 10000:
        return None, None, f"client rectangle is not capturable: {width}x{height}", None

    origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin)):
        return None, None, f"ClientToScreen failed: {ctypes.get_last_error()}", None
    screen_left, screen_top = int(origin.x), int(origin.y)
    geometry = {
        "window_rect_screen": [int(v) for v in rect],
        "client_rect_local": [int(client.left), int(client.top), int(client.right), int(client.bottom)],
        "client_origin_screen": [screen_left, screen_top],
        "client_size": [width, height],
    }

    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi32.BitBlt.restype = wintypes.BOOL

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    screen_dc = user32.GetDC(None)
    if not screen_dc:
        return None, None, f"GetDC failed: {ctypes.get_last_error()}", geometry
    memory_dc = None
    bitmap = None
    old_object = None
    capture_method = None
    restore_foreground = int(user32.GetForegroundWindow() or 0)
    try:
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        if not memory_dc:
            raise OSError(f"CreateCompatibleDC failed: {ctypes.get_last_error()}")
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not bitmap:
            raise OSError(f"CreateCompatibleBitmap failed: {ctypes.get_last_error()}")
        old_object = gdi32.SelectObject(memory_dc, bitmap)

        # PW_CLIENTONLY (1) + PW_RENDERFULLCONTENT (2): render the client area.
        rendered = bool(user32.PrintWindow(wintypes.HWND(hwnd), memory_dc, 3))
        if rendered:
            capture_method = "PrintWindow(PW_CLIENTONLY|PW_RENDERFULLCONTENT)"
        else:
            SW_RESTORE = 9
            user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
            user32.BringWindowToTop(wintypes.HWND(hwnd))
            focus_ok = bool(user32.SetForegroundWindow(wintypes.HWND(hwnd)))
            time.sleep(0.35)
            foreground_hwnd = int(user32.GetForegroundWindow() or 0)
            SRCCOPY = 0x00CC0020
            CAPTUREBLT = 0x40000000
            copied = bool(gdi32.BitBlt(memory_dc, 0, 0, width, height,
                                       screen_dc, screen_left, screen_top, SRCCOPY | CAPTUREBLT))
            if not copied:
                raise OSError(f"PrintWindow and client BitBlt failed: {ctypes.get_last_error()}")
            capture_method = (
                "BitBlt(client screen rect after foreground request; "
                f"SetForegroundWindow={focus_ok}, foreground_hwnd={foreground_hwnd})"
            )

        image_size = width * height * 4
        pixels = ctypes.create_string_buffer(image_size)
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        info.bmiHeader.biSizeImage = image_size
        gdi32.SelectObject(memory_dc, old_object)
        old_object = None
        gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                                    wintypes.UINT, ctypes.c_void_p,
                                    ctypes.POINTER(BITMAPINFO), wintypes.UINT]
        gdi32.GetDIBits.restype = ctypes.c_int
        lines = gdi32.GetDIBits(screen_dc, bitmap, 0, height, pixels,
                                ctypes.byref(info), 0)
        if int(lines) != height:
            raise OSError(f"GetDIBits returned {lines}/{height} scan lines: {ctypes.get_last_error()}")

        file_header = struct.pack("<2sIHHI", b"BM", 14 + 40 + image_size, 0, 0, 54)
        dib_header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0,
                                 image_size, 0, 0, 0, 0)
        target.parent.mkdir(parents=True, exist_ok=True)
        target = target.with_suffix(".bmp")
        target.write_bytes(file_header + dib_header + pixels.raw)
        if not target.is_file() or target.stat().st_size != 54 + image_size:
            raise OSError("BMP output validation failed")
        return str(target), capture_method, None, geometry
    except Exception as exc:
        return None, capture_method, f"{type(exc).__name__}: {exc}", geometry
    finally:
        if restore_foreground and restore_foreground != int(hwnd):
            try:
                user32.SetForegroundWindow(wintypes.HWND(restore_foreground))
            except Exception:
                pass
        try:
            if old_object and memory_dc:
                gdi32.SelectObject(memory_dc, old_object)
        except Exception:
            pass
        try:
            if bitmap:
                gdi32.DeleteObject(bitmap)
        except Exception:
            pass
        try:
            if memory_dc:
                gdi32.DeleteDC(memory_dc)
        except Exception:
            pass
        try:
            user32.ReleaseDC(None, screen_dc)
        except Exception:
            pass



# Batch-stage anchors measured from the user's actual GTO+ 1.9.1 client screenshot (884x611).
# Kept separate from the older 1272x586 diagnostic layout to prevent cross-layout misclicks.
_BATCH_SETUP_COORDINATE_REFERENCE = {
    "reference_client_size": [884, 611],
    "basis": "pixel-measured from gto_plus_ui_20261119_023338_window_primary.bmp",
    "anchors": {
        "oop_range_matrix": {"rect": [27, 88, 82, 144], "center": [54, 116]},
        "ip_range_matrix": {"rect": [27, 159, 82, 215], "center": [54, 187]},
        "board_text_entry": {"rect": [24, 232, 84, 247], "center": [54, 239]},
        "build_tree_button": {"rect": [24, 253, 85, 276], "center": [54, 265]},
        "run_solver_button": {"rect": [24, 282, 85, 306], "center": [54, 294]},
    },
}

_OOP_DONE_BUTTON_REFERENCE = {
    "reference_client_size": [680, 476],
    "rect": [418, 359, 502, 383],
    "center": [460, 371],
    "basis": "pixel-measured from gto_plus_ui_20261119_034101_oop_editor_open.bmp; blue 完了 button",
}


def _click_oop_editor_done(user32, root_hwnd: int, RECT, POINT) -> dict[str, Any]:
    """Click only the measured OOP editor 完了 button in the verified embedded layout."""
    width, height = _validated_oop_client_size(
        user32, root_hwnd, RECT, "Click OOP editor Done"
    )
    # Retain the original size in the report for diagnostics; click coordinates
    # themselves remain fixed client-pixel anchors.
    ref_w, ref_h = _OOP_DONE_BUTTON_REFERENCE["reference_client_size"]
    # The editor's measured button remains at this fixed client-pixel anchor.
    # Do not scale it against unused client height.
    x0, y0, x1, y1 = _OOP_DONE_BUTTON_REFERENCE["rect"]
    ax, ay = _OOP_DONE_BUTTON_REFERENCE["center"]
    button_rect_client = [int(x0), int(y0), int(x1), int(y1)]
    cx, cy = int(ax), int(ay)
    if not (button_rect_client[0] <= cx <= button_rect_client[2] and button_rect_client[1] <= cy <= button_rect_client[3]):
        raise RuntimeError(f"OOP Done point outside measured button: point={(cx,cy)} rect={button_rect_client}; no click sent")
    if not (0 <= cx < width and 0 <= cy < height):
        raise RuntimeError(f"OOP Done point outside client area: {(cx,cy)} / {(width,height)}; no click sent")
    screen = POINT(cx, cy)
    if not user32.ClientToScreen(wintypes.HWND(root_hwnd), ctypes.byref(screen)):
        raise OSError(f"ClientToScreen failed for OOP Done click: {ctypes.get_last_error()}")

    host = _top_level_ancestor(user32, root_hwnd)
    if not host or not user32.IsWindow(wintypes.HWND(host)):
        raise RuntimeError("Could not resolve Pigeon host window; OOP Done click not sent")
    hit_hwnd = int(user32.WindowFromPoint(screen) or 0)
    if not hit_hwnd or not _window_is_related_to_embedded_target(
            user32, hit_hwnd, root_hwnd, host):
        raise RuntimeError(
            f"OOP Done target is not inside the exact embedded GTO+ ownership chain "
            f"(hit_hwnd={hit_hwnd}, hit_pid={_window_pid(user32, hit_hwnd) if hit_hwnd else None}); "
            "no click sent"
        )
    hit_pid = _window_pid(user32, hit_hwnd)
    hit_class = _class_name(user32, hit_hwnd)
    hit_rect = _rect(user32, RECT, hit_hwnd)
    previous_foreground = int(user32.GetForegroundWindow() or 0)
    previous_cursor = POINT()
    have_cursor = bool(user32.GetCursorPos(ctypes.byref(previous_cursor)))
    user32.ShowWindow(wintypes.HWND(host), 9)
    user32.BringWindowToTop(wintypes.HWND(root_hwnd))
    set_foreground = bool(user32.SetForegroundWindow(wintypes.HWND(host)))
    time.sleep(0.20)
    actual_foreground = int(user32.GetForegroundWindow() or 0)
    if actual_foreground != int(host):
        raise RuntimeError(f"Foreground safety check failed before OOP Done; no click sent (expected={host}, actual={actual_foreground}, SetForegroundWindow={set_foreground})")
    if not user32.SetCursorPos(int(screen.x), int(screen.y)):
        raise OSError(f"SetCursorPos failed for OOP Done click: {ctypes.get_last_error()}")
    down = False
    try:
        time.sleep(0.04)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        down = True
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        down = False
        time.sleep(0.55)
    finally:
        if down:
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        if have_cursor:
            user32.SetCursorPos(int(previous_cursor.x), int(previous_cursor.y))
    return {
        "action": "click_oop_source_editor_done",
        "target_hwnd": int(root_hwnd), "target_pid": _window_pid(user32, root_hwnd),
        "client_size": [width, height], "reference_client_size": [ref_w, ref_h],
        "button_rect_client": button_rect_client, "click_client": [cx, cy],
        "click_screen": [int(screen.x), int(screen.y)],
        "foreground_verified": True, "foreground_host_hwnd": int(host),
        "button_hit_hwnd": int(hit_hwnd), "button_hit_pid": hit_pid,
        "button_hit_class": hit_class, "button_hit_rect_screen": hit_rect,
        "set_foreground_window_return": set_foreground,
        "previous_foreground_hwnd": previous_foreground,
    }


def _window_is_related_to_embedded_target(user32, candidate: int, root_hwnd: int, host_hwnd: int) -> bool:
    """Accept only a control parented/owned by the exact embedded GTO window or its Pigeon host."""
    pending = [int(candidate)]
    seen = set()
    for _ in range(64):
        if not pending:
            break
        current = int(pending.pop())
        if not current or current in seen:
            continue
        seen.add(current)
        if current in (int(root_hwnd), int(host_hwnd)):
            return True
        parent = int(user32.GetParent(wintypes.HWND(current)) or 0)
        owner = int(user32.GetWindow(wintypes.HWND(current), 4) or 0)  # GW_OWNER
        if parent and parent not in seen:
            pending.append(parent)
        if owner and owner not in seen:
            pending.append(owner)
    return False


def _locate_embedded_oop_source_edit(user32, EnumWindowsProc, EnumChildProc,
                                     root_hwnd: int, RECT, POINT) -> tuple[list[tuple[int, list[int]]], dict[str, Any]]:
    """Find the Source Edit at its measured screen point, including owned popup dialogs.

    The embedded GTO+ main HWND does not expose its popup editor in EnumChildWindows
    on all 1.9.1 builds. Use WindowFromPoint and enumerate only windows whose parent/
    owner chain returns to the exact embedded HWND or its Pigeon host. The screen
    rectangle and control ID are both checked to avoid matching stale GTO.exe instances.
    """
    width, height = _validated_oop_client_size(
        user32, root_hwnd, RECT, "Locate OOP Source code field"
    )
    client = RECT()
    if not user32.GetClientRect(wintypes.HWND(root_hwnd), ctypes.byref(client)):
        raise OSError(f"GetClientRect failed while locating Source code field: {ctypes.get_last_error()}")
    origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(wintypes.HWND(root_hwnd), ctypes.byref(origin)):
        raise OSError(f"ClientToScreen failed while locating Source code field: {ctypes.get_last_error()}")
    x0, y0, x1, y1 = _OOP_SOURCE_FIELD_REFERENCE["rect"]
    expected_rect = [int(origin.x+x0), int(origin.y+y0), int(origin.x+x1), int(origin.y+y1)]
    cx, cy = _OOP_SOURCE_FIELD_REFERENCE["center"]
    point = POINT(int(origin.x+cx), int(origin.y+cy))
    under = int(user32.WindowFromPoint(point) or 0)
    under_info = None
    if under:
        under_rect = _rect(user32, RECT, under)
        under_info = {
            "hwnd": under, "pid": _window_pid(user32, under),
            "class": _class_name(user32, under),
            "control_id": int(user32.GetDlgCtrlID(wintypes.HWND(under))),
            "title": _window_text(user32, under), "rect_screen": under_rect,
            "visible": bool(user32.IsWindowVisible(wintypes.HWND(under))),
        }

    host_hwnd = _top_level_ancestor(user32, root_hwnd)
    roots, children_by_root = _all_hwnds(user32, EnumWindowsProc, EnumChildProc)
    candidate_hwnds = {under} if under else set()
    candidate_hwnds.add(int(root_hwnd))
    if host_hwnd:
        candidate_hwnds.add(int(host_hwnd))
    # Include descendants of the embedded root and of any owned/hosted popup that
    # is actually related to this exact Pigeon integration target.
    for top in roots:
        top = int(top)
        if top == int(root_hwnd) or top == int(host_hwnd) or _window_is_related_to_embedded_target(user32, top, root_hwnd, host_hwnd):
            candidate_hwnds.add(top)
            candidate_hwnds.update(int(x) for x in children_by_root.get(top, []))
    # Also include direct descendants even if their owner chain was omitted by EnumWindows.
    children: list[int] = []
    EnumChild = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(child, _):
        children.append(int(child))
        return True
    child_cb = EnumChild(collect)
    user32.EnumChildWindows(wintypes.HWND(root_hwnd), child_cb, 0)
    candidate_hwnds.update(children)

    found = []
    edit_candidates = []
    for candidate in sorted(candidate_hwnds):
        if not candidate or not user32.IsWindow(wintypes.HWND(candidate)):
            continue
        cls = _class_name(user32, candidate)
        if cls != "Edit":
            continue
        rect = _rect(user32, RECT, candidate)
        cid = int(user32.GetDlgCtrlID(wintypes.HWND(candidate)))
        pid = _window_pid(user32, candidate)
        related = _window_is_related_to_embedded_target(user32, candidate, root_hwnd, host_hwnd)
        if rect:
            center = [(rect[0]+rect[2])//2, (rect[1]+rect[3])//2]
            expected_center = [(expected_rect[0]+expected_rect[2])//2,
                              (expected_rect[1]+expected_rect[3])//2]
            delta = [abs(center[0]-expected_center[0]), abs(center[1]-expected_center[1])]
        else:
            delta = [999999, 999999]
        edit_candidates.append({"hwnd": candidate, "pid": pid, "control_id": cid,
                                "rect_screen": rect, "related_to_exact_host": related,
                                "center_delta": delta,
                                "visible": bool(user32.IsWindowVisible(wintypes.HWND(candidate))),
                                "enabled": bool(user32.IsWindowEnabled(wintypes.HWND(candidate)))})
        if (cid == 5458 and related and rect and delta[0] <= 24 and delta[1] <= 18
                and user32.IsWindowVisible(wintypes.HWND(candidate))
                and user32.IsWindowEnabled(wintypes.HWND(candidate))):
            found.append((candidate, rect))

    diagnostics = {
        "target_hwnd": int(root_hwnd), "target_pid": _window_pid(user32, root_hwnd),
        "host_hwnd": int(host_hwnd or 0), "host_pid": _window_pid(user32, host_hwnd) if host_hwnd else None,
        "client_size": [width, height], "expected_source_rect_screen": expected_rect,
        "window_from_point": under_info, "edit_candidates": edit_candidates,
        "matched_count": len(found),
    }
    return found, diagnostics


def _commit_oop_test_range_aa(user32, EnumWindowsProc, EnumChildProc, root_hwnd: int, RECT, POINT,
                              output_dir: Path, stem: str) -> dict[str, Any]:
    """Commit only OOP=AA after verifying the exact blank Source code Edit control.

    If the editor is closed, open it through the verified OOP matrix anchor. Never
    overwrites non-empty Source code. The helper does not touch IP, board, stacks,
    tree construction, or Solver execution.
    """
    width, height = _validated_oop_client_size(
        user32, root_hwnd, RECT, "OOP AA commit"
    )

    edits, field_lookup = _locate_embedded_oop_source_edit(
        user32, EnumWindowsProc, EnumChildProc, root_hwnd, RECT, POINT
    )
    if len(edits) > 1:
        raise RuntimeError(f"OOP AA commit found {len(edits)} related Source Edit controls; ambiguous target; lookup={json.dumps(field_lookup, ensure_ascii=False)}; no range changed")
    opened = None
    if not edits:
        # Require the editor to be closed before starting. This avoids clicking
        # the underlying OOP matrix if an already-open custom-drawn editor has no HWND.
        opened = _open_oop_range_editor(user32, root_hwnd, RECT, POINT)
        time.sleep(0.65)
        edits, field_lookup = _locate_embedded_oop_source_edit(
            user32, EnumWindowsProc, EnumChildProc, root_hwnd, RECT, POINT
        )
    if len(edits) != 1:
        raise RuntimeError(
            "OOP AA commit could not resolve exactly one Source code Edit (class Edit, id=5458) "
            "at the measured field inside the exact embedded-window ownership chain; "
            f"found={len(edits)}; lookup={json.dumps(field_lookup, ensure_ascii=False)}; no range changed"
        )

    edit_hwnd, edit_rect_screen = edits[0]
    # Confirm native Edit class/ID and that its measured center matches the Source-code field.
    if _class_name(user32, edit_hwnd) != "Edit" or int(user32.GetDlgCtrlID(wintypes.HWND(edit_hwnd))) != 5458:
        raise RuntimeError("OOP Source code control identity changed; no range changed")
    origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(wintypes.HWND(root_hwnd), ctypes.byref(origin)):
        raise OSError(f"ClientToScreen failed while verifying OOP Source code field: {ctypes.get_last_error()}")
    relative_rect = [edit_rect_screen[0]-int(origin.x), edit_rect_screen[1]-int(origin.y),
                     edit_rect_screen[2]-int(origin.x), edit_rect_screen[3]-int(origin.y)]
    actual_center = [(relative_rect[0]+relative_rect[2])//2, (relative_rect[1]+relative_rect[3])//2]
    expected_center = _OOP_SOURCE_FIELD_REFERENCE["center"]
    center_delta = [abs(actual_center[0]-expected_center[0]), abs(actual_center[1]-expected_center[1])]
    if center_delta[0] > 20 or center_delta[1] > 20:
        raise RuntimeError(f"OOP Source code Edit control is not at verified field position: relative_rect={relative_rect}, center={actual_center}, expected={expected_center}; no range changed")

    original = _read_native_edit_text(user32, edit_hwnd)
    if original != "":
        raise RuntimeError(f"OOP Source code field is not empty (length={len(original)}); preserving existing text and aborting without overwrite")

    # Type test token through the verified native Edit control and read it back.
    _write_native_edit_text(user32, edit_hwnd, "AA")
    readback = _read_native_edit_text(user32, edit_hwnd)
    if readback != "AA":
        try:
            _write_native_edit_text(user32, edit_hwnd, original)
        finally:
            raise RuntimeError(f"OOP Source code readback mismatch: expected 'AA', got {readback!r}; original value restore attempted")
    typed_capture = _batch_capture(user32, root_hwnd, RECT, POINT, output_dir, stem, "oop_aa_before_done")
    if typed_capture.get("capture_error"):
        _write_native_edit_text(user32, edit_hwnd, original)
        if _read_native_edit_text(user32, edit_hwnd) != original:
            raise RuntimeError("OOP pre-Done screenshot failed and original Source code could not be restored")
        raise RuntimeError(f"OOP pre-Done screenshot failed: {typed_capture['capture_error']}; original Source code restored")

    try:
        done_click = _click_oop_editor_done(user32, root_hwnd, RECT, POINT)
    except Exception:
        _write_native_edit_text(user32, edit_hwnd, original)
        restored = _read_native_edit_text(user32, edit_hwnd)
        if restored != original:
            raise RuntimeError("OOP Done click failed and source field rollback also failed")
        raise

    deadline = time.monotonic() + 2.0
    remaining, post_done_lookup = _locate_embedded_oop_source_edit(
        user32, EnumWindowsProc, EnumChildProc, root_hwnd, RECT, POINT
    )
    while remaining and time.monotonic() < deadline:
        time.sleep(0.10)
        remaining, post_done_lookup = _locate_embedded_oop_source_edit(
            user32, EnumWindowsProc, EnumChildProc, root_hwnd, RECT, POINT
        )
    after_capture = _batch_capture(user32, root_hwnd, RECT, POINT, output_dir, stem, "oop_aa_after_done")
    if remaining:
        return {
            "stage": "OOP_AA_commit", "status": "done_clicked_but_editor_still_open_unconfirmed",
            "range_text": "AA", "source_text_readback": readback,
            "source_control_id": 5458, "source_rect_screen": edit_rect_screen,
            "source_rect_client": relative_rect, "source_center_delta": center_delta,
            "opened_editor": opened, "source_field_lookup": field_lookup,
            "post_done_field_lookup": post_done_lookup,
            "pre_done_capture": typed_capture,
            "done_click": done_click, "post_done_capture": after_capture,
            "editor_closed_after_done": False, "tree_built": False, "solver_run": False,
            "note": "Done click was sent but edit control remains. Commit is not claimed as confirmed.",
        }
    if after_capture.get("capture_error"):
        return {
            "stage": "OOP_AA_commit", "status": "editor_closed_post_done_capture_failed",
            "range_text": "AA", "source_text_readback": readback,
            "source_control_id": 5458, "source_rect_screen": edit_rect_screen,
            "source_rect_client": relative_rect, "source_center_delta": center_delta,
            "opened_editor": opened, "source_field_lookup": field_lookup,
            "post_done_field_lookup": post_done_lookup,
            "pre_done_capture": typed_capture,
            "done_click": done_click, "post_done_capture": after_capture,
            "editor_closed_after_done": True, "tree_built": False, "solver_run": False,
            "note": "Done clicked and editor closed, but post-Done screenshot failed; visual commit verification remains incomplete.",
        }
    return {
        "stage": "OOP_AA_commit", "status": "done_clicked_editor_closed",
        "range_text": "AA", "source_text_readback": readback,
        "source_control_id": 5458, "source_rect_screen": edit_rect_screen,
        "source_rect_client": relative_rect, "source_center_delta": center_delta,
        "opened_editor": opened, "source_field_lookup": field_lookup,
        "post_done_field_lookup": post_done_lookup,
        "pre_done_capture": typed_capture,
        "done_click": done_click, "post_done_capture": after_capture,
        "editor_closed_after_done": True, "tree_built": False, "solver_run": False,
        "note": "AA source text was written and read back, Done was clicked, and the editor closed. Visual range-grid interpretation should be checked from the saved post-Done screenshot.",
    }


def _batch_visible_source_edits(user32, RECT, root_hwnd: int) -> list[tuple[int, list[int]]]:
    """Return visible native Source-code Edit controls (id 5458) in this GTO window."""
    target_pid = _window_pid(user32, root_hwnd)
    children: list[int] = []
    EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _collect(child, _):
        children.append(int(child))
        return True
    callback = EnumChildProc(_collect)
    user32.EnumChildWindows(wintypes.HWND(root_hwnd), callback, 0)
    found = []
    for child in children:
        if _window_pid(user32, child) != target_pid:
            continue
        if _class_name(user32, child) != "Edit":
            continue
        if int(user32.GetDlgCtrlID(wintypes.HWND(child))) != 5458:
            continue
        if not user32.IsWindowVisible(wintypes.HWND(child)) or not user32.IsWindowEnabled(wintypes.HWND(child)):
            continue
        rect = _rect(user32, RECT, child)
        if rect:
            found.append((child, rect))
    return found


def _top_level_ancestor(user32, hwnd: int) -> int:
    """Return the top-level foreground host for an HWND, including embedded child windows."""
    current = int(hwnd or 0)
    if not current:
        return 0
    for _ in range(32):
        parent = int(user32.GetParent(wintypes.HWND(current)) or 0)
        if not parent:
            return current
        current = parent
    return current


def _batch_click_client(user32, root_hwnd: int, RECT, POINT, x: float, y: float,
                        reference_size: tuple[int, int], *, label: str) -> dict[str, Any]:
    """Click a measured client-relative point only after verifying the target is foreground."""
    client = RECT()
    if not user32.GetClientRect(wintypes.HWND(root_hwnd), ctypes.byref(client)):
        raise OSError(f"GetClientRect failed before {label}: {ctypes.get_last_error()}")
    width, height = int(client.right-client.left), int(client.bottom-client.top)
    ref_w, ref_h = reference_size
    if width < 700 or height < 500:
        raise RuntimeError(f"{label}: client area too small for measured layout: {width}x{height}")
    actual_ratio = width / float(height)
    reference_ratio = ref_w / float(ref_h)
    if abs(actual_ratio-reference_ratio) > 0.10:
        raise RuntimeError(f"{label}: client aspect ratio differs from measured GTO+ layout ({width}x{height}); refusing unsafe click")
    sx, sy = width/float(ref_w), height/float(ref_h)
    cx, cy = int(round(x*sx)), int(round(y*sy))
    if not (0 <= cx < width and 0 <= cy < height):
        raise RuntimeError(f"{label} point outside client area: {(cx,cy)} / {(width,height)}")
    screen = POINT(cx, cy)
    if not user32.ClientToScreen(wintypes.HWND(root_hwnd), ctypes.byref(screen)):
        raise OSError(f"ClientToScreen failed before {label}: {ctypes.get_last_error()}")
    prev_fg = int(user32.GetForegroundWindow() or 0)
    cursor = POINT()
    have_cursor = bool(user32.GetCursorPos(ctypes.byref(cursor)))
    foreground_host = _top_level_ancestor(user32, root_hwnd)
    user32.ShowWindow(wintypes.HWND(foreground_host), 9)
    user32.BringWindowToTop(wintypes.HWND(root_hwnd))
    set_fg = bool(user32.SetForegroundWindow(wintypes.HWND(foreground_host)))
    time.sleep(0.18)
    fg = int(user32.GetForegroundWindow() or 0)
    if fg != int(foreground_host):
        raise RuntimeError(f"Foreground safety check failed before {label}; no click sent (target={root_hwnd}, foreground_host={foreground_host}, foreground={fg}, set={set_fg})")
    if not user32.SetCursorPos(int(screen.x), int(screen.y)):
        raise OSError(f"SetCursorPos failed before {label}: {ctypes.get_last_error()}")
    down = False
    try:
        time.sleep(0.04)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        down = True
        time.sleep(0.045)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        down = False
        time.sleep(0.55)
    finally:
        if down:
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        if have_cursor:
            user32.SetCursorPos(int(cursor.x), int(cursor.y))
    return {
        "action": "single_left_click", "label": label, "target_hwnd": int(root_hwnd),
        "target_pid": _window_pid(user32, root_hwnd),
        "client_size": [width, height], "reference_size": [ref_w, ref_h],
        "scale": [round(sx,6), round(sy,6)], "client_point": [cx,cy],
        "screen_point": [int(screen.x),int(screen.y)],
        "foreground_verified": True, "set_foreground_return": set_fg,
        "foreground_host_hwnd": int(foreground_host),
        "previous_foreground_hwnd": prev_fg,
    }


def _batch_capture(user32, root_hwnd: int, RECT, POINT, output_dir: Path,
                   stem: str, suffix: str) -> dict[str, Any]:
    target = output_dir / f"{stem}_{suffix}.bmp"
    pth, method, err, geometry = _capture_window(
        user32, root_hwnd, _rect(user32, RECT, root_hwnd), target, RECT, POINT
    )
    return {"screenshot": pth, "capture_method": method,
            "capture_error": err, "capture_geometry": geometry}


def _batch_commit_range(user32, root_hwnd: int, RECT, POINT, output_dir: Path,
                        stem: str, role: str, text: str, *, editor_already_open: bool=False) -> dict[str, Any]:
    """Set one test range and commit with Done. Stops rather than overwriting nonblank source text."""
    if role not in ("OOP", "IP"):
        raise ValueError("role must be OOP or IP")
    if not editor_already_open:
        anchor = _BATCH_SETUP_COORDINATE_REFERENCE["anchors"]["oop_range_matrix" if role == "OOP" else "ip_range_matrix"]["center"]
        opened = _batch_click_client(user32, root_hwnd, RECT, POINT, anchor[0], anchor[1],
                                     tuple(_BATCH_SETUP_COORDINATE_REFERENCE["reference_client_size"]),
                                     label=f"open_{role.lower()}_range_editor")
        time.sleep(0.4)
    else:
        opened = {"action": "reuse_existing_editor", "label": f"{role}_range_editor_already_open",
                  "target_hwnd": int(root_hwnd), "target_pid": _window_pid(user32, root_hwnd)}

    edits = _batch_visible_source_edits(user32, RECT, root_hwnd)
    if len(edits) != 1:
        raise RuntimeError(f"{role} source field expected exactly one visible Edit id=5458; found {len(edits)}")
    edit_hwnd, edit_rect = edits[0]
    original = _read_native_edit_text(user32, edit_hwnd)
    if original.strip():
        raise RuntimeError(f"{role} Source code field is not empty; preserving existing text and aborting batch")
    client = RECT()
    if not user32.GetClientRect(wintypes.HWND(root_hwnd), ctypes.byref(client)):
        raise OSError(f"GetClientRect failed for {role} commit")
    origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(wintypes.HWND(root_hwnd), ctypes.byref(origin)):
        raise OSError(f"ClientToScreen failed for {role} commit")
    actual_center = [(edit_rect[0]+edit_rect[2])//2, (edit_rect[1]+edit_rect[3])//2]
    # The Source code Edit field was measured at client center (268,443) in 884x611.
    sx = (client.right-client.left)/884.0
    sy = (client.bottom-client.top)/611.0
    expected_center = [int(origin.x+round(268*sx)), int(origin.y+round(443*sy))]
    if abs(actual_center[0]-expected_center[0]) > 35 or abs(actual_center[1]-expected_center[1]) > 35:
        raise RuntimeError(f"{role} Edit id=5458 is outside the measured Source code field (actual={actual_center}, expected={expected_center})")

    _write_native_edit_text(user32, edit_hwnd, text)
    readback = _read_native_edit_text(user32, edit_hwnd)
    if readback != text:
        _write_native_edit_text(user32, edit_hwnd, original)
        raise RuntimeError(f"{role} source write/readback mismatch: expected {text!r}, got {readback!r}")
    typed_capture = _batch_capture(user32, root_hwnd, RECT, POINT, output_dir, stem, f"{role.lower()}_range_before_done")
    if typed_capture.get("capture_error"):
        _write_native_edit_text(user32, edit_hwnd, original)
        raise RuntimeError(f"{role} pre-Done capture failed: {typed_capture['capture_error']}")

    # Done button is a skin-drawn control, measured in the 884x611 client image.
    try:
        done_click = _batch_click_client(user32, root_hwnd, RECT, POINT, 467, 438,
                                         (884,611), label=f"commit_{role.lower()}_range_done")
    except Exception:
        # If Done cannot be safely clicked, restore the exact original text in the still-open editor.
        try:
            _write_native_edit_text(user32, edit_hwnd, original)
            if _read_native_edit_text(user32, edit_hwnd) != original:
                raise RuntimeError("failed to restore source field after Done click failure")
        except Exception as restore_exc:
            raise RuntimeError(f"Done click failed and Source code rollback also failed: {restore_exc}")
        raise
    time.sleep(0.65)
    remaining = _batch_visible_source_edits(user32, RECT, root_hwnd)
    if remaining:
        try:
            _write_native_edit_text(user32, edit_hwnd, original)
            restored = _read_native_edit_text(user32, edit_hwnd) == original
        except Exception:
            restored = False
        raise RuntimeError(f"{role} editor did not close after Done; original source text restored={restored}; refusing to continue")
    committed_capture = _batch_capture(user32, root_hwnd, RECT, POINT, output_dir, stem, f"{role.lower()}_range_committed")
    if committed_capture.get("capture_error"):
        raise RuntimeError(f"{role} post-Done capture failed: {committed_capture['capture_error']}")
    return {
        "stage": f"{role}_range_commit", "status": "source_written_readback_verified_done_clicked_editor_closed",
        "range_text": text, "source_control_id": 5458, "source_control_class": "Edit",
        "source_rect_screen": edit_rect, "source_text_readback": readback,
        "opened_editor": opened, "done_click": done_click,
        "pre_done_capture": typed_capture, "committed_capture": committed_capture,
        "editor_closed_after_done": True, "tree_built": False, "solver_run": False,
    }


def _batch_press_escape(user32, expected_pid: int, *, root_hwnd: int | None = None, allow_root: bool = True) -> int:
    """Send Escape only while the exact embedded GTO child is hosted by the foreground Pigeon window."""
    hwnd = int(user32.GetForegroundWindow() or 0)
    if not hwnd:
        return 0
    if root_hwnd is not None:
        if _window_pid(user32, root_hwnd) != int(expected_pid):
            return 0
        host = _top_level_ancestor(user32, root_hwnd)
        if hwnd != host:
            return 0
        if root_hwnd == hwnd and not allow_root:
            return 0
    elif _window_pid(user32, hwnd) != int(expected_pid):
        return 0
    user32.keybd_event(0x1B, 0, 0, 0)
    user32.keybd_event(0x1B, 0, 0x0002, 0)
    time.sleep(0.35)
    return hwnd

def _batch_child_controls(user32, RECT, root_hwnd: int) -> list[dict[str, Any]]:
    target_pid = _window_pid(user32, root_hwnd)
    children: list[int] = []
    EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _collect(child, _):
        children.append(int(child)); return True
    callback = EnumChildProc(_collect)
    user32.EnumChildWindows(wintypes.HWND(root_hwnd), callback, 0)
    return [_control_record(user32, RECT, child, i) for i, child in enumerate(children)
            if _window_pid(user32, child) == target_pid]


def _run_batch_pre_solve_probe(user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                               root_hwnd: int, root_pid: int, output_dir: Path,
                               stem: str) -> dict[str, Any]:
    """Four-stage calibration: commit OOP/IP test ranges, inspect Board and Build Tree dialogs.

    Uses test ranges OOP=AA and IP=KK. It does not set board/pot/stack yet and never
    builds a tree or runs Solver. Board and Build Tree dialogs are opened only for
    capture/control enumeration, then dismissed with Escape.
    """
    steps: list[dict[str, Any]] = []
    captures: list[dict[str, Any]] = []
    errors: list[str] = []
    # Earlier diagnostic run leaves the OOP editor open. Reuse it only if the
    # exact source Edit control is present; otherwise open OOP from its matrix.
    existing_edits = _batch_visible_source_edits(user32, RECT, root_hwnd)
    if len(existing_edits) > 1:
        raise RuntimeError(f"Ambiguous open Source code fields: {len(existing_edits)}")
    steps.append(_batch_commit_range(user32, root_hwnd, RECT, POINT, output_dir, stem,
                                     "OOP", "AA", editor_already_open=bool(existing_edits)))
    steps.append(_batch_commit_range(user32, root_hwnd, RECT, POINT, output_dir, stem,
                                     "IP", "KK", editor_already_open=False))

    # Stage 3: Open Board selector, capture its real 1.9.1 UI, then cancel without selection.
    board_anchor = _BATCH_SETUP_COORDINATE_REFERENCE["anchors"]["board_text_entry"]["center"]
    board_click = _batch_click_client(user32, root_hwnd, RECT, POINT, board_anchor[0], board_anchor[1],
                                      tuple(_BATCH_SETUP_COORDINATE_REFERENCE["reference_client_size"]),
                                      label="open_board_selector")
    time.sleep(0.45)
    board_capture = _batch_capture(user32, root_hwnd, RECT, POINT, output_dir, stem, "board_selector_open")
    board_controls = _batch_child_controls(user32, RECT, root_hwnd)
    board_top_dialogs = []
    roots_before_board_close, _ = _all_hwnds(user32, EnumWindowsProc, EnumChildProc)
    for candidate in roots_before_board_close:
        candidate = int(candidate)
        if candidate == int(root_hwnd) or _window_pid(user32, candidate) != int(root_pid):
            continue
        if not user32.IsWindowVisible(wintypes.HWND(candidate)):
            continue
        dialog_rect = _rect(user32, RECT, candidate)
        if not dialog_rect or dialog_rect[2]-dialog_rect[0] < 120 or dialog_rect[3]-dialog_rect[1] < 80:
            continue
        dialog_capture = _batch_capture(user32, candidate, RECT, POINT, output_dir, stem,
                                        f"board_selector_dialog_{len(board_top_dialogs)+1}")
        board_top_dialogs.append({"hwnd": candidate, "pid": int(root_pid),
                                  "title": _window_text(user32, candidate),
                                  "rect": dialog_rect,
                                  "controls": _batch_child_controls(user32, RECT, candidate),
                                  "capture": dialog_capture})
        captures.append(dialog_capture)
    board_escape_target = _batch_press_escape(user32, root_pid, root_hwnd=root_hwnd, allow_root=True)
    board_closed = _batch_capture(user32, root_hwnd, RECT, POINT, output_dir, stem, "board_selector_closed")
    steps.append({"stage": "board_selector_probe", "status": "opened_captured_escape_sent",
                  "click": board_click, "open_capture": board_capture,
                  "native_child_controls": board_controls, "top_level_dialogs": board_top_dialogs,
                  "escape_target_hwnd": board_escape_target,
                  "closed_capture": board_closed, "board_changed": False})
    captures.extend([board_capture, board_closed])

    # Stage 4: Open Build Tree setup to discover current pot/stack dialog controls;
    # do not enter parameters or click Build Tree.
    build_anchor = _BATCH_SETUP_COORDINATE_REFERENCE["anchors"]["build_tree_button"]["center"]
    build_click = _batch_click_client(user32, root_hwnd, RECT, POINT, build_anchor[0], build_anchor[1],
                                      tuple(_BATCH_SETUP_COORDINATE_REFERENCE["reference_client_size"]),
                                      label="open_build_tree_setup")
    time.sleep(0.75)
    build_capture = _batch_capture(user32, root_hwnd, RECT, POINT, output_dir, stem, "build_tree_setup_open")
    build_controls = _batch_child_controls(user32, RECT, root_hwnd)
    # Record any separate GTO-owned dialog windows and capture them.
    top_dialogs = []
    roots_now, _ = _all_hwnds(user32, EnumWindowsProc, EnumChildProc)
    for candidate in roots_now:
        candidate = int(candidate)
        if candidate == int(root_hwnd) or _window_pid(user32, candidate) != int(root_pid):
            continue
        if not user32.IsWindowVisible(wintypes.HWND(candidate)):
            continue
        rect = _rect(user32, RECT, candidate)
        if not rect:
            continue
        cw, ch = rect[2]-rect[0], rect[3]-rect[1]
        if cw < 120 or ch < 80:
            continue
        shot = _batch_capture(user32, candidate, RECT, POINT, output_dir, stem,
                              f"build_tree_dialog_{len(top_dialogs)+1}")
        top_dialogs.append({"hwnd": candidate, "pid": int(root_pid),
                            "title": _window_text(user32, candidate), "rect": rect,
                            "controls": _batch_child_controls(user32, RECT, candidate),
                            "capture": shot})
        captures.append(shot)
    captures.append(build_capture)
    escape_targets = [_batch_press_escape(user32, root_pid, root_hwnd=root_hwnd, allow_root=True), _batch_press_escape(user32, root_pid, root_hwnd=root_hwnd, allow_root=False)]
    build_closed = _batch_capture(user32, root_hwnd, RECT, POINT, output_dir, stem, "build_tree_setup_closed")
    captures.append(build_closed)
    steps.append({"stage": "build_tree_setup_probe", "status": "opened_captured_escape_sent",
                  "click": build_click, "open_capture": build_capture,
                  "native_child_controls": build_controls, "top_level_dialogs": top_dialogs,
                  "escape_target_hwnds": escape_targets, "closed_capture": build_closed,
                  "pot_stack_values_changed": False, "tree_built": False, "solver_run": False})
    return {"status": "completed_four_stage_setup_probe", "steps": steps,
            "coordinate_reference": _BATCH_SETUP_COORDINATE_REFERENCE,
            "extra_captures": captures, "errors": errors,
            "test_ranges": {"OOP": "AA", "IP": "KK"},
            "board": None, "pot": None, "effective_stack": None,
            "rake": None, "tree_built": False, "solver_run": False,
            "notes": ["OOP=AA and IP=KK were committed as controlled test ranges.",
                      "Board selector and Build Tree setup were opened and captured, then dismissed.",
                      "Board/pot/stack/rake were not changed. Build Tree and Solver were not run."]}

def run_probe(output_dir: Path, *, title_hint: str | None = None,
              max_controls: int = MAX_CONTROLS_DEFAULT,
              screenshot: bool = True,
              open_oop_range_editor: bool = False,
              focus_oop_source_field: bool = False,
              probe_oop_source_field_input: bool = False,
              commit_oop_aa: bool = False,
              batch_setup_probe: bool = False,
              target_pid: int | None = None,
              target_hwnd: int | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"gto_plus_ui_{stamp}"
    processes = _find_gto_processes()
    pids = {x["pid"] for x in processes}
    errors: list[str] = []

    user32, EnumWindowsProc, EnumChildProc, RECT, POINT = _win32_api()
    roots, children_by_root = _all_hwnds(user32, EnumWindowsProc, EnumChildProc)
    hint = _normalise(title_hint).casefold() if title_hint else None
    matching_roots = []
    for root in roots:
        pid = _window_pid(user32, root)
        title = _window_text(user32, root)
        rect = _rect(user32, RECT, root)
        # Ignore IME helpers and zero-sized utility windows owned by GTO.exe.
        # Only keep real display windows or explicit title-hint matches.
        has_display_area = bool(rect and (rect[2] - rect[0]) >= 200 and (rect[3] - rect[1]) >= 150)
        visible = bool(user32.IsWindowVisible(wintypes.HWND(root)))
        if (pid in pids and has_display_area and visible) or (hint and hint in title.casefold() and has_display_area):
            matching_roots.append((root, pid, title, "pid" if pid in pids else "title"))

    # GTO+ may be embedded/reparented below the Pigeon Poker top-level window.
    # Search every descendant HWND for a GTO+ PID and promote it to a report root
    # when its parent belongs to a different process.
    if pids:
        for root in roots:
            for hwnd in children_by_root.get(root, []):
                pid = _window_pid(user32, hwnd)
                parent = int(user32.GetParent(wintypes.HWND(hwnd)) or 0)
                parent_pid = _window_pid(user32, parent) if parent else None
                if pid in pids and parent_pid not in pids:
                    matching_roots.append((hwnd, pid, _window_text(user32, hwnd), "embedded-pid"))

    # Deduplicate handles, preferring explicit process matches.
    dedup: dict[int, tuple[int, int, str, str]] = {}
    for item in matching_roots:
        dedup[item[0]] = item
    selected = list(dedup.values())
    def _window_priority(item):
        hwnd, _pid, title, _match = item
        rect = _rect(user32, RECT, hwnd) or [0, 0, 0, 0]
        area = max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])
        return (bool(user32.IsWindowVisible(wintypes.HWND(hwnd))), area, bool(title))
    selected.sort(key=_window_priority, reverse=True)

    # When launched from Pigeon Poker, never guess which of several GTO.exe
    # instances is the embedded solver. Use the exact HWND/PID held by the
    # integration object; refuse to interact if that identity no longer matches.
    target_resolution = {
        "requested_pid": int(target_pid) if target_pid else None,
        "requested_hwnd": int(target_hwnd) if target_hwnd else None,
        "resolved": False,
        "reason": None,
    }
    if target_hwnd:
        hwnd_value = int(target_hwnd)
        if not user32.IsWindow(wintypes.HWND(hwnd_value)):
            target_resolution["reason"] = "Pigeon embedded HWND is no longer a valid window"
            primary_hwnd = None
            primary_item = None
        else:
            actual_pid = _window_pid(user32, hwnd_value)
            target_resolution["actual_pid"] = actual_pid
            if target_pid and actual_pid != int(target_pid):
                target_resolution["reason"] = f"Embedded HWND PID mismatch: expected {target_pid}, got {actual_pid}"
                primary_hwnd = None
                primary_item = None
            else:
                match = next((item for item in selected if int(item[0]) == hwnd_value), None)
                if match is None:
                    match = (hwnd_value, actual_pid, _window_text(user32, hwnd_value), "pigeon-embedded-target")
                    selected.insert(0, match)
                primary_item = match
                primary_hwnd = hwnd_value
                target_resolution["resolved"] = True
                target_resolution["reason"] = "Exact embedded HWND supplied by Pigeon Poker integration"
    elif target_pid:
        pid_matches = [item for item in selected if int(item[1]) == int(target_pid)]
        if pid_matches:
            primary_item = max(pid_matches, key=_window_priority)
            primary_hwnd = int(primary_item[0])
            target_resolution["resolved"] = True
            target_resolution["actual_pid"] = int(target_pid)
            target_resolution["reason"] = "Window selected by exact Pigeon integration PID"
        else:
            primary_hwnd = None
            primary_item = None
            target_resolution["reason"] = f"No GTO+ window found for Pigeon integration PID {target_pid}"
    else:
        # CLI-only fallback for old direct diagnostics. App-triggered batch
        # actions always pass the authoritative embedded HWND and PID.
        primary_hwnd = int(selected[0][0]) if selected else None
        primary_item = selected[0] if selected else None
        target_resolution["resolved"] = bool(primary_item)
        target_resolution["reason"] = "Fallback: largest visible GTO+ window (no app target supplied)"

    interaction_result = None
    source_focus_result = None
    focus_diagnostics_after_source_click = None
    source_input_test_result = None
    oop_range_commit_result = None
    batch_setup_result = None
    pre_interaction_capture = None
    oop_editor_open_capture = None
    oop_source_focused_capture = None
    if open_oop_range_editor:
        if primary_hwnd is None:
            errors.append("OOP range-editor probe skipped: no primary GTO+ window was found.")
        else:
            # Save the exact state before sending the single probe click.
            pre_target = output_dir / f"{stem}_window_before_oop_probe.bmp"
            pre_path, pre_method, pre_error, pre_geometry = _capture_window(
                user32, primary_hwnd, _rect(user32, RECT, primary_hwnd), pre_target, RECT, POINT
            )
            pre_interaction_capture = {
                "screenshot": pre_path,
                "capture_method": pre_method,
                "capture_error": pre_error,
                "capture_geometry": pre_geometry,
            }
            if pre_error:
                errors.append(f"Pre-click screenshot failed: {pre_error}")
            try:
                interaction_result = _open_oop_range_editor(user32, primary_hwnd, RECT, POINT)
                # Always save a post-click frame so the editor-open action is
                # visually auditable; earlier builds omitted this unless the
                # separate Source-field focus flag was enabled.
                open_target = output_dir / f"{stem}_oop_editor_open.bmp"
                pth, method, err, geom = _capture_window(
                    user32, primary_hwnd, _rect(user32, RECT, primary_hwnd), open_target, RECT, POINT
                )
                oop_editor_open_capture = {"screenshot": pth, "capture_method": method,
                                           "capture_error": err, "capture_geometry": geom}
                if err:
                    errors.append(f"OOP editor-open screenshot failed: {err}")
                if focus_oop_source_field:
                    source_focus_result = _focus_oop_source_text_field(user32, primary_hwnd, RECT, POINT)
                    focus_diagnostics_after_source_click = source_focus_result.get("focus_diagnostics")
                    field_target = output_dir / f"{stem}_oop_source_field_focused.bmp"
                    pth, method, err, geom = _capture_window(
                        user32, primary_hwnd, _rect(user32, RECT, primary_hwnd), field_target, RECT, POINT
                    )
                    oop_source_focused_capture = {"screenshot": pth, "capture_method": method,
                                                  "capture_error": err, "capture_geometry": geom}
                    if err:
                        errors.append(f"OOP source-field screenshot failed: {err}")
                    if probe_oop_source_field_input:
                        source_input_test_result = _probe_oop_source_field_input(
                            user32, primary_hwnd, RECT, POINT, output_dir, stem
                        )
                        if source_input_test_result.get("status") not in (
                            "write_readback_and_restore_verified",
                            "skipped_nonempty_field_preserved",
                        ):
                            errors.append("Source-field temporary write test did not fully verify: " +
                                          str(source_input_test_result.get("status")))
            except Exception as exc:
                errors.append(f"OOP range/source-field probe failed before/while interacting: {type(exc).__name__}: {exc}")

    if commit_oop_aa:
        if primary_hwnd is None or primary_item is None or not target_resolution.get("resolved"):
            errors.append("OOP AA commit skipped: exact Pigeon-embedded GTO+ target could not be resolved. " + str(target_resolution.get("reason")))
            oop_range_commit_result = {"status": "skipped_no_exact_target", "tree_built": False, "solver_run": False}
        else:
            try:
                oop_range_commit_result = _commit_oop_test_range_aa(
                    user32, EnumWindowsProc, EnumChildProc, int(primary_hwnd), RECT, POINT, output_dir, stem
                )
                if oop_range_commit_result.get("status") != "done_clicked_editor_closed":
                    errors.append("OOP AA commit did not reach confirmed editor-close state: " + str(oop_range_commit_result.get("status")))
            except Exception as exc:
                errors.append(f"OOP AA commit stopped safely: {type(exc).__name__}: {exc}")
                oop_range_commit_result = {"status": "aborted_or_failed", "error": f"{type(exc).__name__}: {exc}", "tree_built": False, "solver_run": False}

    if batch_setup_probe:
        if primary_hwnd is None or primary_item is None or not target_resolution.get("resolved"):
            errors.append("Batch setup probe skipped: exact Pigeon-embedded GTO+ target could not be resolved. " + str(target_resolution.get("reason")))
        else:
            try:
                batch_setup_result = _run_batch_pre_solve_probe(
                    user32, EnumWindowsProc, EnumChildProc, RECT, POINT, int(primary_hwnd),
                    int(primary_item[1]), output_dir, stem
                )
            except Exception as exc:
                errors.append(f"Batch setup probe stopped safely: {type(exc).__name__}: {exc}")
                batch_setup_result = {"status": "stopped_with_error",
                                      "error": f"{type(exc).__name__}: {exc}",
                                      "tree_built": False, "solver_run": False}

    # The range editor may be a native top-level dialog in some GTO+ builds.
    # Include any newly visible, sizeable windows owned by the same GTO process.
    if open_oop_range_editor and primary_item is not None:
        try:
            roots_after, _children_after = _all_hwnds(user32, EnumWindowsProc, EnumChildProc)
            known_handles = {int(item[0]) for item in selected}
            primary_pid = int(primary_item[1])
            for candidate in roots_after:
                if int(candidate) in known_handles or _window_pid(user32, candidate) != primary_pid:
                    continue
                candidate_rect = _rect(user32, RECT, candidate)
                if not candidate_rect or not user32.IsWindowVisible(wintypes.HWND(candidate)):
                    continue
                cw = candidate_rect[2] - candidate_rect[0]
                ch = candidate_rect[3] - candidate_rect[1]
                if cw >= 220 and ch >= 140:
                    selected.append((int(candidate), primary_pid, _window_text(user32, candidate), "range-editor-dialog-candidate"))
                    known_handles.add(int(candidate))
        except Exception as exc:
            errors.append(f"Could not enumerate range-editor dialog windows: {type(exc).__name__}: {exc}")

    report: dict[str, Any] = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "os": sys.platform,
        "python": sys.version,
        "backend": "Windows user32 API via ctypes (no COM / pywinauto)",
        "processes": processes,
        "windows": [],
        "primary_capture_target": ({
            "handle": int(primary_item[0]),
            "pid": int(primary_item[1]),
            "title": primary_item[2],
            "selection_rule": ("exact Pigeon integration embedded HWND" if target_hwnd else
                               "exact Pigeon integration PID" if target_pid else
                               "largest visible GTO+ window fallback"),
        } if primary_item else None),
        "pigeon_target_resolution": target_resolution,
        "visual_coordinate_reference": _VISUAL_COORDINATE_REFERENCE,
        "oop_single_step_coordinate_reference": _OOP_SINGLE_STEP_REFERENCE,
        "oop_source_field_reference": _OOP_SOURCE_FIELD_REFERENCE,
        "pre_interaction_capture": pre_interaction_capture,
        "oop_editor_open_capture": oop_editor_open_capture,
        "oop_source_focused_capture": oop_source_focused_capture,
        "focus_diagnostics_after_source_click": focus_diagnostics_after_source_click,
        "oop_source_input_test": source_input_test_result,
        "oop_range_commit_test": oop_range_commit_result,
        "batch_pre_solve_setup_probe": batch_setup_result,
        "errors": errors,
        "read_only": not (open_oop_range_editor or focus_oop_source_field or probe_oop_source_field_input or commit_oop_aa or batch_setup_probe),
        "actions_performed": [a for a in (interaction_result, source_focus_result) if a] +
                             ([{"action": "commit_oop_test_range_aa", "status": (oop_range_commit_result or {}).get("status")}] if commit_oop_aa else []) +
                             ([{"action": "four_stage_pre_solve_setup_probe", "status": (batch_setup_result or {}).get("status")}] if batch_setup_probe else []),
        "notes": [
            ("OOP Source code AA was written and read back, then Done was clicked once. The report records whether the editor closed. No IP/board/pot/stack/tree/Solver operation was run."
             if commit_oop_aa else
             (("One OOP range-matrix click opened the Starting Range Editor; then one click focused the Source code input field. No text was typed/pasted, no hand cell was selected, no range weights/text were changed, and no tree/solver operation was run."
               if focus_oop_source_field else "One OOP range-matrix click was issued to open the Starting Range Editor; no hand cell was selected, no range weights/text were changed, and no tree/solver operation was run.")
              if open_oop_range_editor else "Read-only inspection only: no clicks, keystrokes, solver runs, or GTO+ file changes.")),
            "Win32 class names and control IDs are reported; UI Automation IDs are not available from this backend.",
            "The OOP single-step probe uses the exact Pigeon-embedded HWND and the dedicated 680x476 measured OOP matrix anchor; other GTO.exe windows are metadata-only.",
            "A post-click screenshot is always saved as oop_editor_open, independently of the optional Source-field focus probe.",
            ("Source code input probe temporarily wrote 'AA' to the identified native Edit control, read it back, and restored the original blank value; Done was not clicked and no tree/Solver was run."
             if probe_oop_source_field_input else "No temporary Source code text was written."),
            (f"OOP AA commit result: {(oop_range_commit_result or {}).get('status')}; only OOP test range was targeted; IP/board/pot/stack/tree/Solver were not changed."
             if commit_oop_aa else "No OOP range commit was attempted."),
            ("Batch probe completed: OOP=AA and IP=KK test ranges were committed; Board and Build Tree setup dialogs were opened and dismissed. Board/pot/stack/rake were not changed, and no tree/Solver was run."
             if batch_setup_probe and (batch_setup_result or {}).get("status") == "completed_four_stage_setup_probe" else
             "Batch probe was attempted but did not complete; inspect batch_pre_solve_setup_probe. Do not assume any range was committed. No tree/Solver operation is claimed."
             if batch_setup_probe else "No batch setup probe was executed."),
        ],
    }

    if not processes:
        errors.append("GTO.exe process was not found. Open GTO+ inside Pigeon Poker (② launch, then ③ connect) and run the diagnostic again.")
    if processes and not selected:
        errors.append("GTO.exe is running, but no top-level or embedded GTO+ window was found. Check that the GTO+ window is visible and not running under a different Windows account/session.")
    if not processes and not selected and hint:
        errors.append(f"No window matched title hint: {title_hint!r}")

    for w_index, (hwnd, pid, title, match) in enumerate(selected, 1):
        rect = _rect(user32, RECT, hwnd)
        record = {
            "title": title,
            "pid": pid,
            "match": match,
            "handle": int(hwnd),
            "class_name": _class_name(user32, hwnd),
            "rectangle": rect,
            "controls": [],
            "screenshot": None,
        }
        record["capture_role"] = ("primary" if int(hwnd) == primary_hwnd else
                                  "range_editor_dialog_candidate" if match == "range-editor-dialog-candidate" else
                                  "secondary_metadata_only")
        record["menu_items"] = _menu_tree(user32, hwnd) if int(hwnd) == primary_hwnd else []
        should_capture = int(hwnd) == primary_hwnd or match == "range-editor-dialog-candidate"
        if screenshot and should_capture:
            suffix = "window_primary" if int(hwnd) == primary_hwnd else f"range_editor_candidate_{w_index}"
            shot_target = output_dir / f"{stem}_{suffix}.bmp"
            shot_path, shot_method, shot_error, capture_geometry = _capture_window(
                user32, hwnd, rect, shot_target, RECT, POINT
            )
            record["screenshot"] = shot_path
            record["screenshot_capture_method"] = shot_method
            record["screenshot_error"] = shot_error
            record["capture_geometry"] = capture_geometry
            if not shot_path:
                errors.append(f"Primary GTO+ screenshot unavailable for hwnd={hwnd}, title={title!r}: {shot_error or 'unknown error'}")
        elif screenshot:
            record["screenshot"] = None
            record["screenshot_capture_method"] = "skipped: secondary GTO+ window"
            record["screenshot_error"] = None
            record["capture_geometry"] = None
        descendants: list[int] = []
        def on_child(hwnd_child, _):
            descendants.append(int(hwnd_child))
            return True
        child_callback = EnumChildProc(on_child)
        user32.EnumChildWindows(wintypes.HWND(hwnd), child_callback, 0)
        controls = [hwnd] + [h for h in descendants if _window_pid(user32, h) == pid]
        controls = controls[:max_controls]
        for index, control_hwnd in enumerate(controls):
            record["controls"].append(_control_record(user32, RECT, control_hwnd, index))
        record["total_controls_seen"] = len(descendants) + 1
        record["truncated_controls"] = max(0, len(descendants) + 1 - len(controls))
        report["windows"].append(record)

    json_path = output_dir / f"{stem}.json"
    txt_path = output_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "PIGEON POKER — GTO+ WIN32 WINDOW DIAGNOSTIC",
        f"Created: {report['created_at']}",
        f"Python: {report['python']}",
        f"Backend: {report['backend']}",
        f"GTO+ processes: {len(processes)}",
        f"Matched windows: {len(selected)}",
        "",
        (("INTERACTION PROBE: click OOP matrix to open Starting Range Editor, then click Source code input field to focus it; no text typed/pasted; no range edits, tree build, or solver run."
          if focus_oop_source_field else "INTERACTION PROBE: one click at corrected OOP matrix center; before/after screenshots saved; no range values changed; no tree build or solver run.")
         if open_oop_range_editor else "READ-ONLY: no clicks, keystrokes, solver runs, or file changes."),
        f"Actions performed: {json.dumps(report.get('actions_performed', []), ensure_ascii=False)}",
        f"Primary capture target: {report.get('primary_capture_target')}",
        f"Visual coordinate reference: {json.dumps(_VISUAL_COORDINATE_REFERENCE, ensure_ascii=False)}",
        f"OOP source-field reference: {json.dumps(_OOP_SOURCE_FIELD_REFERENCE, ensure_ascii=False)}",
        f"Source-field focus action: {json.dumps(source_focus_result, ensure_ascii=False)}",
        f"GUI thread focus/caret after source click: {json.dumps(focus_diagnostics_after_source_click, ensure_ascii=False)}",
        f"Source-field temporary input test: {json.dumps(source_input_test_result, ensure_ascii=False)}",
        f"OOP AA range commit test: {json.dumps(oop_range_commit_result, ensure_ascii=False)}",
        f"Batch pre-solve setup probe: {json.dumps(batch_setup_result, ensure_ascii=False)}",
        "",
    ]
    for wi, window in enumerate(report["windows"], 1):
        lines += [f"=== WINDOW {wi} ===", f"Title: {window['title']!r}",
                  f"PID: {window['pid']}", f"HWND: {window['handle']}",
                  f"Match: {window['match']}", f"Class: {window['class_name']!r}",
                  f"Rectangle: {window['rectangle']}",
                  f"Screenshot: {window['screenshot']}",
                  f"Screenshot method: {window.get('screenshot_capture_method')}",
                  f"Capture geometry: {window.get('capture_geometry')}",
                  f"Capture role: {window.get('capture_role')}",
                  f"Screenshot error: {window.get('screenshot_error')}",
                  f"Menu items: {json.dumps(window.get('menu_items', []), ensure_ascii=False)}",
                  f"Controls: {len(window['controls'])}"]
        for c in window["controls"]:
            lines.append(
                f"[{c['index']:04d}] class={c['class_name']!r} name={c['name']!r} "
                f"id={c['control_id']} enabled={c['enabled']} visible={c['visible']} "
                f"rect={c['rectangle']} hwnd={c['handle']}"
            )
        lines.append("")
    if errors:
        lines += ["=== NOTES / ERRORS ===", *[f"- {e}" for e in errors], ""]
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    zip_path = output_dir / f"{stem}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(json_path, json_path.name)
        zf.write(txt_path, txt_path.name)
        for capture in (pre_interaction_capture, oop_editor_open_capture, oop_source_focused_capture):
            if capture and capture.get("screenshot"):
                cap_path = Path(capture["screenshot"])
                if cap_path.is_file():
                    zf.write(cap_path, cap_path.name)
        if source_input_test_result:
            for capture_key in ("temporary_capture", "restored_capture"):
                capture = source_input_test_result.get(capture_key) or {}
                if capture.get("screenshot"):
                    cap_path = Path(capture["screenshot"])
                    if cap_path.is_file():
                        zf.write(cap_path, cap_path.name)
        if oop_range_commit_result:
            for capture_key in ("pre_done_capture", "post_done_capture"):
                capture = oop_range_commit_result.get(capture_key) or {}
                if capture.get("screenshot"):
                    cap_path = Path(capture["screenshot"])
                    if cap_path.is_file():
                        zf.write(cap_path, cap_path.name)
        if batch_setup_result:
            for capture in batch_setup_result.get("extra_captures", []):
                if capture and capture.get("screenshot"):
                    cap_path = Path(capture["screenshot"])
                    if cap_path.is_file():
                        zf.write(cap_path, cap_path.name)
            for step in batch_setup_result.get("steps", []):
                for key in ("pre_done_capture", "committed_capture", "open_capture", "closed_capture"):
                    capture = step.get(key) or {}
                    if capture.get("screenshot"):
                        cap_path = Path(capture["screenshot"])
                        if cap_path.is_file():
                            zf.write(cap_path, cap_path.name)
                for dlg in step.get("top_level_dialogs", []):
                    capture = dlg.get("capture") or {}
                    if capture.get("screenshot"):
                        cap_path = Path(capture["screenshot"])
                        if cap_path.is_file():
                            zf.write(cap_path, cap_path.name)
        for window in report["windows"]:
            shot = window.get("screenshot")
            if shot and Path(shot).is_file():
                zf.write(shot, Path(shot).name)
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only GTO+ Win32 window inspection")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "diagnostics"))
    parser.add_argument("--title-hint", default=None)
    parser.add_argument("--max-controls", type=int, default=MAX_CONTROLS_DEFAULT)
    parser.add_argument("--no-screenshot", action="store_true")
    parser.add_argument("--open-oop-range-editor", action="store_true",
                        help="対象GTO+のOOPレンジ表をクリックし、Starting Range Editorを開いて撮影します。")
    parser.add_argument("--focus-oop-source-field", action="store_true",
                        help="Starting Range Editorを開いた後、Source code入力欄をクリックしてフォーカスします。文字入力はしません。")
    parser.add_argument("--probe-oop-source-field-input", action="store_true",
                        help="Source code欄が空の場合に限りAAを一時入力して読戻し、元の空欄へ復元します。Done/ツリー/Solveは実行しません。")
    parser.add_argument("--commit-oop-aa", action="store_true",
                        help="空のOOP Source code欄だけにAAを入力してDone確定します。既存文字列は保護し、IP/Board/Tree/Solverには触れません。")
    parser.add_argument("--batch-pre-solve-probe", action="store_true",
                        help="OOP=AA/IP=KKをDone確定し、Board/Build Tree設定画面を撮影して閉じる4段階テストです。Tree/Solverは実行しません。")
    parser.add_argument("--target-pid", type=int, default=None,
                        help="Pigeon Poker integrationが保持するGTO+ PID")
    parser.add_argument("--target-hwnd", type=int, default=None,
                        help="Pigeon Poker integrationが保持する埋め込みGTO+ HWND")
    args = parser.parse_args()
    try:
        do_focus_field = bool(args.focus_oop_source_field or args.probe_oop_source_field_input)
        do_open_editor = bool(args.open_oop_range_editor or do_focus_field)
        result = run_probe(Path(args.output), title_hint=args.title_hint,
                           max_controls=max(1, min(args.max_controls, 10000)),
                           screenshot=not args.no_screenshot,
                           open_oop_range_editor=do_open_editor,
                           focus_oop_source_field=do_focus_field,
                           probe_oop_source_field_input=args.probe_oop_source_field_input,
                           commit_oop_aa=args.commit_oop_aa,
                           batch_setup_probe=args.batch_pre_solve_probe,
                           target_pid=args.target_pid, target_hwnd=args.target_hwnd)
        print(f"診断レポートを作成しました: {result}")
        if args.commit_oop_aa:
            with zipfile.ZipFile(result, "r") as archive:
                json_name = next((name for name in archive.namelist() if name.endswith(".json")), None)
                if not json_name:
                    raise RuntimeError("OOP AA commit diagnostic JSON is missing from output ZIP")
                commit_json = json.loads(archive.read(json_name).decode("utf-8"))
            commit_status = (commit_json.get("oop_range_commit_test") or {}).get("status")
            if commit_status != "done_clicked_editor_closed":
                details = (commit_json.get("oop_range_commit_test") or {}).get("error") or "; ".join(commit_json.get("errors", [])) or str(commit_status)
                print(f"OOP AAレンジ確定は未確認です: {details}", file=sys.stderr)
                return 3
            print("OOP=AAを入力し、Doneクリック後に編集画面が閉じたことを確認しました。IP/Board/pot/stack/Tree/Solverは変更していません。")
        elif args.batch_pre_solve_probe:
            with zipfile.ZipFile(result, "r") as archive:
                json_name = next((name for name in archive.namelist() if name.endswith(".json")), None)
                if not json_name:
                    raise RuntimeError("Batch diagnostic JSON is missing from output ZIP")
                batch_json = json.loads(archive.read(json_name).decode("utf-8"))
            batch_status = (batch_json.get("batch_pre_solve_setup_probe") or {}).get("status")
            if batch_status != "completed_four_stage_setup_probe":
                details = (batch_json.get("batch_pre_solve_setup_probe") or {}).get("error") or "; ".join(batch_json.get("errors", [])) or "no detailed error was recorded"
                print(f"4工程まとめてテストは未完了です: {details}", file=sys.stderr)
                return 3
            print("OOP=AA/IP=KKをDone確定し、Board/Build Tree設定画面を撮影して閉じます。Board・pot・stackは変更せず、Tree/Solverは実行しません。")
        elif args.probe_oop_source_field_input:
            print("Source code欄にAAを一時設定し、読戻し確認後に元の空欄へ復元します。Doneは押さず、レンジ確定・ツリー構築・Solver実行は行いません。")
        elif do_open_editor:
            print("OOPレンジ編集画面のプローブです。Source code欄フォーカスはクリックのみで、文字入力・レンジ変更・ツリー構築・Solver実行は行っていません。")
        else:
            print("読み取り専用です。GTO+の設定変更・クリック・Solveは行っていません。")
        return 0
    except Exception as exc:
        print(f"診断に失敗しました: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
