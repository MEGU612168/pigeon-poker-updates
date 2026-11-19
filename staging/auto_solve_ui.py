"""Calibrated, read-only discovery of embedded GTO+ 1.9.1 setup UI.

The range editor is closed with its measured on-screen X button, not Escape:
the embedded GTO window has no keyboard focus while Pigeon's Tk child owns it.
The Build Tree dialog is captured and is only dismissed with Escape when the
GTO process itself owns keyboard focus. Every close is visually verified
against the baseline screenshot before the next click is allowed.
"""
from __future__ import annotations

# Build marker: verified GTO view focus and post-click native Edit discovery, schema v8.

import argparse
import json
import os
import struct
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ui_probe as probe

_REFERENCE_SIZE = (665, 570)
_OOP_MATRIX_RECT = (27, 88, 82, 144)
_OOP_MATRIX_CENTER = (54, 116)
_OOP_CLOSE_RECT = (488, 66, 504, 84)
_OOP_CLOSE_CENTER = (496, 75)
_IP_MATRIX_RECT = (27, 159, 82, 215)
_IP_MATRIX_CENTER = (54, 187)
_RANGE_SOURCE_FIELD_RECT = (112, 427, 412, 449)
_RANGE_SOURCE_FIELD_CENTER = (262, 438)
_BOARD_INPUT_RECT = (23, 230, 85, 248)
_BOARD_INPUT_CENTER = (54, 239)
_BOARD_CLOSE_RECT = (277, 71, 291, 85)
_BOARD_CLOSE_CENTER = (284, 78)
_BUILD_TREE_RECT = (24, 253, 85, 276)
_BUILD_TREE_CENTER = (54, 265)
_DIALOG_ROI = (100, 60, 515, 460)


def _client_geometry(user32, hwnd: int, RECT) -> tuple[int, int]:
    client = RECT()
    if not user32.GetClientRect(probe.wintypes.HWND(hwnd), probe.ctypes.byref(client)):
        raise OSError(f"GetClientRect failed: {probe.ctypes.get_last_error()}")
    return int(client.right-client.left), int(client.bottom-client.top)


def _bmp_region_difference_ratio(path_a: str | Path, path_b: str | Path,
                                 roi: tuple[int, int, int, int] = _DIALOG_ROI) -> dict[str, Any]:
    """Compare actual 32-bit BMP pixels in a client-relative ROI."""
    a = Path(path_a).read_bytes()
    b = Path(path_b).read_bytes()

    def layout(data: bytes):
        if len(data) < 54 or data[:2] != b"BM":
            raise ValueError("capture is not a Windows BMP")
        offset = struct.unpack_from("<I", data, 10)[0]
        width, signed_height, planes, bpp, compression = struct.unpack_from("<iiHHI", data, 18)
        height = abs(signed_height)
        if width <= 0 or height <= 0 or planes != 1 or bpp != 32 or compression != 0:
            raise ValueError("capture is not an uncompressed 32-bit BMP")
        stride = ((width*bpp+31)//32)*4
        if offset + stride*height > len(data):
            raise ValueError("BMP pixel data is truncated")
        return offset, width, height, signed_height, stride

    la, lb = layout(a), layout(b)
    if la[1:3] != lb[1:3]:
        raise ValueError(f"capture dimensions differ: {la[1:3]} vs {lb[1:3]}")
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= la[1] and 0 <= y0 < y1 <= la[2]):
        raise ValueError(f"ROI outside capture dimensions: {roi}")
    changed = total = 0
    for y in range(y0, y1):
        ya = y if la[3] < 0 else la[2]-1-y
        yb = y if lb[3] < 0 else lb[2]-1-y
        row_a = la[0] + ya*la[4]
        row_b = lb[0] + yb*lb[4]
        for x in range(x0, x1):
            ia = row_a + x*4
            ib = row_b + x*4
            total += 1
            if a[ia:ia+3] != b[ib:ib+3]:
                changed += 1
    return {"changed_pixels": changed, "total_pixels": total,
            "ratio": changed/total if total else 1.0, "roi": list(roi)}


def _capture_related_windows(user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                             root_hwnd: int, root_pid: int, output_dir: Path,
                             stem: str, stage: str) -> list[dict[str, Any]]:
    host = probe._top_level_ancestor(user32, root_hwnd)
    roots, _ = probe._all_hwnds(user32, EnumWindowsProc, EnumChildProc)
    candidates = [int(root_hwnd)] + [int(hwnd) for hwnd in roots if int(hwnd) != int(root_hwnd)]
    captured: list[dict[str, Any]] = []
    seen: set[int] = set()
    for hwnd in candidates:
        hwnd = int(hwnd)
        if hwnd in seen or not hwnd or not user32.IsWindow(probe.wintypes.HWND(hwnd)):
            continue
        seen.add(hwnd)
        if probe._window_pid(user32, hwnd) != int(root_pid):
            continue
        if not user32.IsWindowVisible(probe.wintypes.HWND(hwnd)):
            continue
        if hwnd != int(root_hwnd) and not probe._window_is_related_to_embedded_target(
                user32, hwnd, root_hwnd, host):
            continue
        rect = probe._rect(user32, RECT, hwnd)
        if not rect:
            continue
        if hwnd != int(root_hwnd) and (rect[2]-rect[0] < 120 or rect[3]-rect[1] < 80):
            continue
        suffix = f"{stage}_main" if hwnd == int(root_hwnd) else f"{stage}_dialog_{len(captured)}"
        capture = probe._batch_capture(user32, hwnd, RECT, POINT, output_dir, stem, suffix)
        captured.append({
            "hwnd": hwnd,
            "pid": int(root_pid),
            "title": probe._window_text(user32, hwnd),
            "class_name": probe._class_name(user32, hwnd),
            "rect_screen": rect,
            "is_embedded_root": hwnd == int(root_hwnd),
            "controls": probe._batch_child_controls(user32, RECT, hwnd),
            "capture": capture,
        })
    return captured


def _root_capture_path(windows: list[dict[str, Any]], stage: str) -> str:
    root = next((w for w in windows if w.get("is_embedded_root")), None)
    if not root:
        raise RuntimeError(f"{stage}: exact embedded GTO window was not captured")
    capture = root.get("capture") or {}
    path = capture.get("screenshot")
    if not path or capture.get("capture_error"):
        raise RuntimeError(f"{stage}: embedded GTO screenshot failed: {capture.get('capture_error')}")
    return str(path)


def _click_verified_gto_hit_target(user32, root_hwnd: int, root_pid: int,
                                      RECT, POINT, point_client: tuple[int, int],
                                      *, label: str) -> dict[str, Any]:
    """Deliver a measured mouse click to the exact GTO child HWND under the target point.

    This is a fallback for custom-drawn controls whose hit target is the MFC view
    itself. It never sends messages to a foreign PID or an unrelated HWND.
    """
    hwnd = probe.wintypes.HWND(root_hwnd)
    client = RECT()
    if not user32.GetClientRect(hwnd, probe.ctypes.byref(client)):
        raise OSError(f"{label}: GetClientRect failed")
    origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(hwnd, probe.ctypes.byref(origin)):
        raise OSError(f"{label}: ClientToScreen failed")
    sx = int(origin.x + int(point_client[0]))
    sy = int(origin.y + int(point_client[1]))
    screen_point = POINT(sx, sy)
    hit = int(user32.WindowFromPoint(screen_point) or 0)
    if not hit or not user32.IsWindow(probe.wintypes.HWND(hit)):
        raise RuntimeError(f"{label}: no valid HWND at measured close point")
    hit_pid = probe._window_pid(user32, hit)
    hit_class = probe._class_name(user32, hit)
    hit_id = int(user32.GetDlgCtrlID(probe.wintypes.HWND(hit)))
    hit_rect = probe._rect(user32, RECT, hit)
    host = probe._top_level_ancestor(user32, root_hwnd)
    related = probe._window_is_related_to_embedded_target(
        user32, hit, root_hwnd, host
    )
    if (hit_pid != int(root_pid) or not related
            or hit_class != "AfxFrameOrView140su" or hit_id != 59648
            or not user32.IsWindowVisible(probe.wintypes.HWND(hit))
            or not user32.IsWindowEnabled(probe.wintypes.HWND(hit))
            or not hit_rect
            or not (hit_rect[0] <= sx < hit_rect[2]
                    and hit_rect[1] <= sy < hit_rect[3])):
        raise RuntimeError(
            f"{label}: hit target is not the exact GTO drawing view; "
            f"pid={hit_pid}, class={hit_class}, id={hit_id}, related={related}"
        )

    local = POINT(sx, sy)
    if not user32.ScreenToClient(probe.wintypes.HWND(hit),
                                 probe.ctypes.byref(local)):
        raise OSError(f"{label}: ScreenToClient on exact hit target failed")
    lx, ly = int(local.x), int(local.y)
    if not (0 <= lx <= 0x7FFF and 0 <= ly <= 0x7FFF):
        raise RuntimeError(f"{label}: hit target client point is out of range")
    lparam = (ly << 16) | (lx & 0xFFFF)

    send = user32.SendMessageW
    send.argtypes = [probe.wintypes.HWND, probe.wintypes.UINT,
                     probe.ctypes.c_size_t, probe.ctypes.c_ssize_t]
    send.restype = probe.ctypes.c_ssize_t
    move_result = send(probe.wintypes.HWND(hit), 0x0200, 0, lparam)  # WM_MOUSEMOVE
    down_result = send(probe.wintypes.HWND(hit), 0x0201, 0x0001, lparam)  # WM_LBUTTONDOWN
    up_result = send(probe.wintypes.HWND(hit), 0x0202, 0, lparam)  # WM_LBUTTONUP
    time.sleep(0.35)
    return {
        "action": "direct_mouse_message_click",
        "label": label,
        "target_hwnd": int(root_hwnd),
        "target_pid": int(root_pid),
        "hit_hwnd": hit,
        "hit_pid": hit_pid,
        "hit_class": hit_class,
        "hit_control_id": hit_id,
        "hit_rect_screen": hit_rect,
        "hit_related_to_exact_host": related,
        "client_point_on_hit_target": [lx, ly],
        "screen_point": [sx, sy],
        "wm_mousemove_result": int(move_result),
        "wm_lbuttondown_result": int(down_result),
        "wm_lbuttonup_result": int(up_result),
    }


def _click_exact_client(user32, root_hwnd: int, root_pid: int,
                        RECT, POINT, point: tuple[int, int], *,
                        label: str) -> dict[str, Any]:
    allowed = {
        "open_oop_range_editor": _OOP_MATRIX_RECT,
        "open_ip_range_editor": _IP_MATRIX_RECT,
        "focus_range_source_field": _RANGE_SOURCE_FIELD_RECT,
        "focus_board_input": _BOARD_INPUT_RECT,
        "close_board_selector": _BOARD_CLOSE_RECT,
        "close_oop_range_editor": _OOP_CLOSE_RECT,
        "open_build_tree_setup": _BUILD_TREE_RECT,
    }
    if label not in allowed:
        raise ValueError(f"{label}: no calibrated click target is registered")
    width, height = _client_geometry(user32, root_hwnd, RECT)
    ref_w, ref_h = _REFERENCE_SIZE
    if abs(width-ref_w) > 12 or abs(height-ref_h) > 12:
        raise RuntimeError(
            f"{label}: unverified GTO+ client geometry {width}x{height}; "
            f"expected {_REFERENCE_SIZE[0]}x{_REFERENCE_SIZE[1]}; no click sent"
        )
    if probe._window_pid(user32, root_hwnd) != int(root_pid):
        raise RuntimeError(f"{label}: embedded HWND PID changed; no click sent")
    x, y = point
    x0, y0, x1, y1 = allowed[label]
    if not (x0 <= x <= x1 and y0 <= y <= y1 and 0 <= x < width and 0 <= y < height):
        raise RuntimeError(f"{label}: click point is outside its measured target; no click sent")

    screen = POINT(int(x), int(y))
    if not user32.ClientToScreen(probe.wintypes.HWND(root_hwnd), probe.ctypes.byref(screen)):
        raise OSError(f"ClientToScreen failed before {label}: {probe.ctypes.get_last_error()}")
    host = probe._top_level_ancestor(user32, root_hwnd)
    if not host or not user32.IsWindow(probe.wintypes.HWND(host)):
        raise RuntimeError(f"{label}: exact Pigeon host is unavailable; no click sent")
    previous_fg = int(user32.GetForegroundWindow() or 0)
    cursor = POINT()
    have_cursor = bool(user32.GetCursorPos(probe.ctypes.byref(cursor)))
    user32.ShowWindow(probe.wintypes.HWND(host), 9)
    user32.BringWindowToTop(probe.wintypes.HWND(root_hwnd))
    set_fg = bool(user32.SetForegroundWindow(probe.wintypes.HWND(host)))
    time.sleep(0.20)
    actual_fg = int(user32.GetForegroundWindow() or 0)
    if actual_fg != int(host):
        raise RuntimeError(
            f"{label}: foreground safety check failed; no click sent "
            f"(expected host={host}, actual foreground={actual_fg}, SetForegroundWindow={set_fg})"
        )
    if not user32.SetCursorPos(int(screen.x), int(screen.y)):
        raise OSError(f"SetCursorPos failed before {label}: {probe.ctypes.get_last_error()}")
    down = False
    try:
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        down = True
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        down = False
        time.sleep(0.60)
    finally:
        if down:
            user32.mouse_event(0x0004, 0, 0, 0, 0)
        if have_cursor:
            user32.SetCursorPos(int(cursor.x), int(cursor.y))
    return {
        "action": "single_left_click",
        "label": label,
        "target_hwnd": int(root_hwnd),
        "target_pid": int(root_pid),
        "client_size": [width, height],
        "reference_size": [ref_w, ref_h],
        "client_point": [int(x), int(y)],
        "screen_point": [int(screen.x), int(screen.y)],
        "foreground_verified": True,
        "foreground_host_hwnd": int(host),
        "previous_foreground_hwnd": previous_fg,
        "set_foreground_window_return": set_fg,
    }


def _send_escape_only_to_gto_focused_thread(user32, RECT, POINT,
                                             root_hwnd: int, root_pid: int) -> dict[str, Any]:
    """Never send Escape to Pigeon's host thread; only a focused GTO-owned HWND qualifies."""
    host = probe._top_level_ancestor(user32, root_hwnd)
    foreground = int(user32.GetForegroundWindow() or 0)
    focus = probe._gui_thread_focus_snapshot(user32, RECT, POINT, root_hwnd, host)
    gto_focus = []
    for thread in focus.get("threads", []):
        handle = int((thread.get("handles") or {}).get("focus") or 0)
        if handle and probe._window_pid(user32, handle) == int(root_pid):
            gto_focus.append(handle)
    if not gto_focus:
        return {"status": "skipped_no_gto_owned_keyboard_focus",
                "foreground_hwnd": foreground, "gto_focus_hwnds": [],
                "focus_snapshot": focus, "escape_sent": False}
    user32.keybd_event(0x1B, 0, 0, 0)
    user32.keybd_event(0x1B, 0, 0x0002, 0)
    time.sleep(0.45)
    return {"status": "escape_sent_to_gto_owned_focus",
            "foreground_hwnd": foreground, "gto_focus_hwnds": gto_focus,
            "focus_snapshot": focus, "escape_sent": True}



def _build_tree_dialog_is_visible(appearance: dict[str, Any],
                                  windows: list[dict[str, Any]]) -> bool:
    """Only treat Build Tree as open when pixels changed or a related popup exists."""
    popup_detected = any(
        isinstance(window, dict) and not window.get("is_embedded_root", False)
        for window in windows
    )
    try:
        ratio = float((appearance or {}).get("ratio", 0.0))
    except (TypeError, ValueError, AttributeError):
        ratio = 0.0
    return popup_detected or ratio > 0.01


def _source_field_underlay_is_verified_edit(observation: dict[str, Any] | None,
                                             target_pid: int) -> bool:
    """True only when WindowFromPoint resolves to the expected Edit owned by this GTO+."""
    if not isinstance(observation, dict):
        return False
    try:
        return (
            int(observation.get("pid", -1)) == int(target_pid)
            and str(observation.get("class", "")) == "Edit"
            and observation.get("related_to_exact_host") is True
            and observation.get("visible") is True
            and observation.get("enabled") is True
            and isinstance(observation.get("rect_screen"), list)
            and len(observation["rect_screen"]) == 4
        )
    except (TypeError, ValueError):
        return False


def _source_field_underlay_is_verified_gto_view(observation: dict[str, Any] | None,
                                                 target_pid: int,
                                                 source_point_screen: tuple[int, int]) -> bool:
    """Permit a single focus-only click when the measured field is drawn by GTO's own view."""
    if not isinstance(observation, dict):
        return False
    try:
        rect = observation.get("rect_screen")
        x, y = map(int, source_point_screen)
        return (
            int(observation.get("pid", -1)) == int(target_pid)
            and str(observation.get("class", "")) == "AfxFrameOrView140su"
            and int(observation.get("control_id", -1)) == 59648
            and observation.get("related_to_exact_host") is True
            and observation.get("visible") is True
            and observation.get("enabled") is True
            and isinstance(rect, list) and len(rect) == 4
            and int(rect[0]) <= x < int(rect[2])
            and int(rect[1]) <= y < int(rect[3])
        )
    except (TypeError, ValueError):
        return False


def _source_field_occlusion_shift(source_rect_screen: list[int],
                                    occluder_rect_screen: list[int],
                                    margin: int = 5) -> int:
    """Smallest upward shift that puts the measured source field above an intersecting overlay."""
    if len(source_rect_screen) != 4 or len(occluder_rect_screen) != 4:
        raise ValueError("screen rectangles must contain left, top, right, bottom")
    sx0, sy0, sx1, sy1 = map(int, source_rect_screen)
    ox0, oy0, ox1, oy1 = map(int, occluder_rect_screen)
    intersects = sx0 < ox1 and sx1 > ox0 and sy0 < oy1 and sy1 > oy0
    if not intersects:
        return 0
    return max(0, sy1 - (oy0 - max(0, int(margin))))


def _temporary_source_field_window_adjustment(user32, root_hwnd: int,
                                                 RECT, POINT) -> dict[str, Any]:
    """Temporarily move the GTO child within its real parent to clear a foreign overlay.

    Embedded GTO+ is a WS_CHILD window. Its SetWindowPos coordinates are parent-client
    coordinates, not screen coordinates. The original parent-relative position is
    recorded and restored by the caller, then verified through GetWindowRect.
    """
    hwnd = probe.wintypes.HWND(root_hwnd)
    original_rect = probe._rect(user32, RECT, root_hwnd)
    if not original_rect:
        return {"status": "window_rect_unavailable", "moved": False}
    style = int(user32.GetWindowLongW(hwnd, -16))
    parent = int(user32.GetParent(hwnd) or 0)
    host = probe._top_level_ancestor(user32, root_hwnd)
    root_pid = probe._window_pid(user32, root_hwnd)
    if not (style & 0x40000000):  # WS_CHILD
        return {
            "status": "not_a_child_window",
            "moved": False,
            "window_style": style,
            "original_rect": original_rect,
        }
    if not parent or not user32.IsWindow(probe.wintypes.HWND(parent)):
        return {"status": "exact_parent_unavailable", "moved": False,
                "window_style": style, "original_rect": original_rect}
    parent_top = probe._top_level_ancestor(user32, parent)
    if (not host or int(parent_top or 0) != int(host)
            or probe._window_pid(user32, parent) != probe._window_pid(user32, host)):
        return {
            "status": "parent_ownership_not_verified",
            "moved": False,
            "window_style": style,
            "parent_hwnd": parent,
            "parent_pid": probe._window_pid(user32, parent),
            "host_hwnd": int(host or 0),
            "original_rect": original_rect,
        }

    parent_origin = POINT(int(original_rect[0]), int(original_rect[1]))
    if not user32.ScreenToClient(probe.wintypes.HWND(parent),
                                 probe.ctypes.byref(parent_origin)):
        return {"status": "parent_client_position_unavailable", "moved": False,
                "parent_hwnd": parent, "original_rect": original_rect}

    client = RECT()
    if not user32.GetClientRect(hwnd, probe.ctypes.byref(client)):
        return {"status": "client_rect_unavailable", "moved": False,
                "parent_hwnd": parent, "original_rect": original_rect}
    client_origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(hwnd, probe.ctypes.byref(client_origin)):
        return {"status": "client_origin_unavailable", "moved": False,
                "parent_hwnd": parent, "original_rect": original_rect}

    source_rect_screen = [
        int(client_origin.x + _RANGE_SOURCE_FIELD_RECT[0]),
        int(client_origin.y + _RANGE_SOURCE_FIELD_RECT[1]),
        int(client_origin.x + _RANGE_SOURCE_FIELD_RECT[2]),
        int(client_origin.y + _RANGE_SOURCE_FIELD_RECT[3]),
    ]
    source_center = POINT(
        int(client_origin.x + _RANGE_SOURCE_FIELD_CENTER[0]),
        int(client_origin.y + _RANGE_SOURCE_FIELD_CENTER[1]),
    )
    under = int(user32.WindowFromPoint(source_center) or 0)
    under_record = None
    if under:
        under_record = {
            "hwnd": under,
            "pid": probe._window_pid(user32, under),
            "class": probe._class_name(user32, under),
            "control_id": int(user32.GetDlgCtrlID(probe.wintypes.HWND(under))),
            "title": probe._window_text(user32, under),
            "rect_screen": probe._rect(user32, RECT, under),
            "visible": bool(user32.IsWindowVisible(probe.wintypes.HWND(under))),
            "enabled": bool(user32.IsWindowEnabled(probe.wintypes.HWND(under))),
            "related_to_exact_host": probe._window_is_related_to_embedded_target(
                user32, under, root_hwnd, host
            ),
        }
    if not under_record or under_record["pid"] == root_pid:
        return {
            "status": "source_point_not_occluded_by_foreign_window",
            "moved": False,
            "window_style": style,
            "parent_hwnd": parent,
            "original_rect": original_rect,
            "original_parent_client_xy": [int(parent_origin.x), int(parent_origin.y)],
            "source_rect_screen": source_rect_screen,
            "window_from_point_before": under_record,
        }

    occluder_rect = under_record.get("rect_screen")
    if not occluder_rect:
        return {
            "status": "foreign_occluder_geometry_unavailable",
            "moved": False,
            "window_style": style,
            "parent_hwnd": parent,
            "original_rect": original_rect,
            "original_parent_client_xy": [int(parent_origin.x), int(parent_origin.y)],
            "source_rect_screen": source_rect_screen,
            "window_from_point_before": under_record,
        }
    shift = _source_field_occlusion_shift(source_rect_screen, occluder_rect, margin=5)
    if shift <= 0:
        return {
            "status": "foreign_hit_target_without_measured_rect_intersection",
            "moved": False,
            "window_style": style,
            "parent_hwnd": parent,
            "original_rect": original_rect,
            "original_parent_client_xy": [int(parent_origin.x), int(parent_origin.y)],
            "source_rect_screen": source_rect_screen,
            "window_from_point_before": under_record,
        }

    new_x = int(parent_origin.x)
    new_y = int(parent_origin.y - shift)
    set_pos = user32.SetWindowPos
    set_pos.argtypes = [probe.wintypes.HWND, probe.wintypes.HWND,
                        probe.wintypes.INT, probe.wintypes.INT,
                        probe.wintypes.INT, probe.wintypes.INT,
                        probe.wintypes.UINT]
    set_pos.restype = probe.wintypes.BOOL
    moved = bool(set_pos(hwnd, probe.wintypes.HWND(0), new_x, new_y, 0, 0,
                         0x0001 | 0x0004 | 0x0010))  # NOSIZE|NOZORDER|NOACTIVATE
    if not moved:
        return {
            "status": "temporary_child_move_failed",
            "moved": False,
            "window_style": style,
            "parent_hwnd": parent,
            "original_rect": original_rect,
            "original_parent_client_xy": [int(parent_origin.x), int(parent_origin.y)],
            "target_parent_client_xy": [new_x, new_y],
            "shift_up": shift,
            "window_from_point_before": under_record,
        }

    temporary_rect = probe._rect(user32, RECT, root_hwnd)
    new_client_origin = POINT(int(client.left), int(client.top))
    origin_ok = bool(user32.ClientToScreen(hwnd, probe.ctypes.byref(new_client_origin)))
    new_source_rect = ([
        int(new_client_origin.x + _RANGE_SOURCE_FIELD_RECT[0]),
        int(new_client_origin.y + _RANGE_SOURCE_FIELD_RECT[1]),
        int(new_client_origin.x + _RANGE_SOURCE_FIELD_RECT[2]),
        int(new_client_origin.y + _RANGE_SOURCE_FIELD_RECT[3]),
    ] if origin_ok else None)
    new_center = POINT(
        int(new_client_origin.x + _RANGE_SOURCE_FIELD_CENTER[0]) if origin_ok else 0,
        int(new_client_origin.y + _RANGE_SOURCE_FIELD_CENTER[1]) if origin_ok else 0,
    )
    under_after = int(user32.WindowFromPoint(new_center) or 0) if origin_ok else 0
    after_record = None
    if under_after:
        after_record = {
            "hwnd": under_after,
            "pid": probe._window_pid(user32, under_after),
            "class": probe._class_name(user32, under_after),
            "control_id": int(user32.GetDlgCtrlID(probe.wintypes.HWND(under_after))),
            "rect_screen": probe._rect(user32, RECT, under_after),
        }
    verified = bool(
        temporary_rect
        and abs(int(temporary_rect[1]) - (int(original_rect[1]) - shift)) <= 3
        and origin_ok and new_source_rect
        and new_source_rect[3] <= int(occluder_rect[1]) - 4
        and after_record and after_record["pid"] == root_pid
    )
    if not verified:
        set_pos(hwnd, probe.wintypes.HWND(0), int(parent_origin.x), int(parent_origin.y),
                0, 0, 0x0001 | 0x0004 | 0x0010)
        restored = probe._rect(user32, RECT, root_hwnd)
        return {
            "status": "temporary_child_move_not_verified",
            "moved": False,
            "window_style": style,
            "parent_hwnd": parent,
            "original_rect": original_rect,
            "original_parent_client_xy": [int(parent_origin.x), int(parent_origin.y)],
            "observed_rect_after_move": temporary_rect,
            "source_rect_screen_after": new_source_rect,
            "window_from_point_after": after_record,
            "attempted_restore_rect": restored,
            "shift_up": shift,
        }
    return {
        "status": "temporarily_moved_child_above_foreign_overlay",
        "moved": True,
        "window_style": style,
        "parent_hwnd": parent,
        "original_rect": original_rect,
        "original_parent_client_xy": [int(parent_origin.x), int(parent_origin.y)],
        "temporary_parent_client_xy": [new_x, new_y],
        "temporary_rect": temporary_rect,
        "source_rect_screen_before": source_rect_screen,
        "source_rect_screen_after": new_source_rect,
        "window_from_point_before": under_record,
        "window_from_point_after": after_record,
        "shift_up": shift,
    }


def _restore_source_field_window_position(user32, root_hwnd: int,
                                          RECT, position: dict[str, Any]) -> dict[str, Any]:
    """Restore the exact original position using the coordinate system of the HWND."""
    if not position.get("moved"):
        return {"attempted": False, "verified": True,
                "status": position.get("status", "not_moved")}
    original = position.get("original_rect") or []
    if len(original) != 4:
        return {"attempted": False, "verified": False, "status": "original_rect_missing"}
    hwnd = probe.wintypes.HWND(root_hwnd)
    if int(position.get("window_style", 0)) & 0x40000000:
        parent = int(position.get("parent_hwnd") or 0)
        xy = position.get("original_parent_client_xy") or []
        if not parent or len(xy) != 2:
            return {"attempted": False, "verified": False,
                    "status": "original_parent_coordinates_missing"}
        x, y = map(int, xy)
    else:
        parent = 0
        x, y = int(original[0]), int(original[1])
    ok = bool(user32.SetWindowPos(
        hwnd, probe.wintypes.HWND(0), x, y, 0, 0,
        0x0001 | 0x0004 | 0x0010
    ))
    current = RECT()
    rect_ok = bool(user32.GetWindowRect(hwnd, probe.ctypes.byref(current)))
    current_rect = ([int(current.left), int(current.top), int(current.right), int(current.bottom)]
                    if rect_ok else None)
    verified = bool(ok and current_rect
                    and abs(current_rect[0]-int(original[0])) <= 2
                    and abs(current_rect[1]-int(original[1])) <= 2)
    return {
        "attempted": True,
        "verified": verified,
        "set_window_pos": ok,
        "parent_hwnd": parent or None,
        "restore_coordinates": [x, y],
        "restored_rect": current_rect,
        "status": "restored" if verified else "restore_not_verified",
    }


def _probe_source_field_readback_restore(user32, root_hwnd: int,
                                           EnumWindowsProc, EnumChildProc,
                                           RECT, POINT, output_dir: Path,
                                           stem: str, role: str) -> dict[str, Any]:
    """Expose the lower input on screen, run the guarded test, then restore the window."""
    position = _temporary_source_field_window_adjustment(user32, root_hwnd, RECT, POINT)
    result = None
    restore = {"attempted": False, "verified": True, "status": "not_moved"}
    try:
        result = _probe_source_field_readback_restore_at_current_position(
            user32, root_hwnd, EnumWindowsProc, EnumChildProc,
            RECT, POINT, output_dir, stem, role
        )
    finally:
        if position.get("moved"):
            restore = _restore_source_field_window_position(user32, root_hwnd, RECT, position)
    if result is None:
        raise RuntimeError(f"{role} source field probe did not return a result")
    result["temporary_window_adjustment"] = position
    result["temporary_window_restore"] = restore
    result["window_position_restore_verified"] = bool(restore.get("verified"))
    if not result["window_position_restore_verified"]:
        result["status"] = "source_field_test_incomplete"
    return result


def _probe_source_field_readback_restore_at_current_position(user32, root_hwnd: int,
                                           EnumWindowsProc, EnumChildProc,
                                           RECT, POINT, output_dir: Path,
                                           stem: str, role: str) -> dict[str, Any]:
    """Read back and restore the Source Edit only when it is the actual hit-tested HWND.

    Crucially, WindowFromPoint is checked before any click. A task-switcher or any
    other foreign overlay over the input point causes a no-click, no-write return.
    """
    if role not in {"OOP", "IP"}:
        raise ValueError("role must be OOP or IP")
    target_pid = probe._window_pid(user32, root_hwnd)
    client = RECT()
    if not user32.GetClientRect(probe.wintypes.HWND(root_hwnd), probe.ctypes.byref(client)):
        raise OSError(f"{role} Source field GetClientRect failed: {probe.ctypes.get_last_error()}")
    origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(probe.wintypes.HWND(root_hwnd), probe.ctypes.byref(origin)):
        raise OSError(f"{role} Source field ClientToScreen failed: {probe.ctypes.get_last_error()}")
    host = probe._top_level_ancestor(user32, root_hwnd)
    source_screen = (int(origin.x + _RANGE_SOURCE_FIELD_CENTER[0]),
                     int(origin.y + _RANGE_SOURCE_FIELD_CENTER[1]))
    point = POINT(*source_screen)
    under = int(user32.WindowFromPoint(point) or 0)
    under_record = None
    if under:
        related = probe._window_is_related_to_embedded_target(
            user32, under, root_hwnd, host
        )
        under_record = {
            "hwnd": under,
            "pid": probe._window_pid(user32, under),
            "class": probe._class_name(user32, under),
            "control_id": int(user32.GetDlgCtrlID(probe.wintypes.HWND(under))),
            "title": probe._window_text(user32, under),
            "rect_screen": probe._rect(user32, RECT, under),
            "visible": bool(user32.IsWindowVisible(probe.wintypes.HWND(under))),
            "enabled": bool(user32.IsWindowEnabled(probe.wintypes.HWND(under))),
            "related_to_exact_host": related,
        }
    base = {
        "stage": f"{role.lower()}_source_field",
        "field_click": None,
        "window_from_point_before_click": under_record,
        "target_pid": target_pid,
        "root_hwnd": int(root_hwnd),
        "host_hwnd": int(host or 0),
        "range_committed": False,
        "tree_built": False,
        "solver_run": False,
    }
    hit_native_edit = _source_field_underlay_is_verified_edit(under_record, target_pid)
    hit_gto_view = _source_field_underlay_is_verified_gto_view(
        under_record, target_pid, source_screen
    )
    if not (hit_native_edit or hit_gto_view):
        foreign = bool(under_record and int(under_record.get("pid", -1)) != target_pid)
        return {
            **base,
            "status": "source_field_occluded_by_foreign_window" if foreign
                      else "source_field_not_hit_testing_verified_gto_surface",
            "text_changed": False,
            "click_sent": False,
            "write_sent": False,
            "source_controls": probe._batch_child_controls(user32, RECT, root_hwnd),
        }

    click = _click_exact_client(
        user32, root_hwnd, target_pid, RECT, POINT,
        _RANGE_SOURCE_FIELD_CENTER, label="focus_range_source_field"
    )
    after_hwnd = int(user32.WindowFromPoint(point) or 0)
    after_record = None
    if after_hwnd:
        after_record = {
            "hwnd": after_hwnd,
            "pid": probe._window_pid(user32, after_hwnd),
            "class": probe._class_name(user32, after_hwnd),
            "control_id": int(user32.GetDlgCtrlID(probe.wintypes.HWND(after_hwnd))),
            "title": probe._window_text(user32, after_hwnd),
            "rect_screen": probe._rect(user32, RECT, after_hwnd),
            "visible": bool(user32.IsWindowVisible(probe.wintypes.HWND(after_hwnd))),
            "enabled": bool(user32.IsWindowEnabled(probe.wintypes.HWND(after_hwnd))),
            "related_to_exact_host": probe._window_is_related_to_embedded_target(
                user32, after_hwnd, root_hwnd, host
            ),
        }
    focus = probe._gui_thread_focus_snapshot(
        user32, RECT, POINT, root_hwnd, host,
        source_point_screen=source_screen
    )
    roots, children_by_root = probe._all_hwnds(user32, EnumWindowsProc, EnumChildProc)
    candidate_hwnds = {int(root_hwnd), int(host or 0), int(under or 0), int(after_hwnd or 0)}
    for top in roots:
        top = int(top)
        if (top == int(root_hwnd) or top == int(host)
                or probe._window_is_related_to_embedded_target(user32, top, root_hwnd, host)):
            candidate_hwnds.add(top)
            candidate_hwnds.update(int(child) for child in children_by_root.get(top, []))
    direct_children = []
    def collect_child(hwnd, _):
        direct_children.append(int(hwnd))
        return True
    child_callback = EnumChildProc(collect_child)
    user32.EnumChildWindows(probe.wintypes.HWND(root_hwnd), child_callback, 0)
    candidate_hwnds.update(direct_children)

    edit_candidates = []
    matches = []
    for candidate in sorted(candidate_hwnds):
        if not candidate or not user32.IsWindow(probe.wintypes.HWND(candidate)):
            continue
        cls = probe._class_name(user32, candidate)
        if cls != "Edit":
            continue
        rect = probe._rect(user32, RECT, candidate)
        pid = probe._window_pid(user32, candidate)
        control_id = int(user32.GetDlgCtrlID(probe.wintypes.HWND(candidate)))
        related = probe._window_is_related_to_embedded_target(user32, candidate, root_hwnd, host)
        if rect:
            center = [(rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2]
            delta = [abs(center[0] - source_screen[0]), abs(center[1] - source_screen[1])]
        else:
            delta = [999999, 999999]
        observation = {
            "hwnd": candidate, "pid": pid, "control_id": control_id,
            "class": cls, "rect_screen": rect, "related_to_exact_host": related,
            "center_delta": delta,
            "visible": bool(user32.IsWindowVisible(probe.wintypes.HWND(candidate))),
            "enabled": bool(user32.IsWindowEnabled(probe.wintypes.HWND(candidate))),
        }
        edit_candidates.append(observation)
        if _source_field_underlay_is_verified_edit(observation, target_pid) and delta[0] <= 35 and delta[1] <= 20:
            matches.append((candidate, rect))

    base.update({
        "field_click": click,
        "focus_snapshot": focus,
        "window_from_point_after_click": after_record,
        "pre_click_hit_kind": "native_edit" if hit_native_edit else "gto_custom_view",
        "focus_only_click": bool(hit_gto_view),
        "edit_candidates": edit_candidates,
        "candidate_count": len(matches),
        "click_sent": True,
    })
    edits = matches
    if len(edits) != 1:
        status = (
            "gto_view_focused_no_unique_native_edit_created"
            if hit_gto_view and len(edits) == 0
            else "native_source_edit_missing_or_ambiguous"
        )
        return {
            **base, "status": status,
            "text_changed": False,
            "write_sent": False,
            "source_controls": probe._batch_child_controls(user32, RECT, root_hwnd),
            "post_click_window_from_point": after_record,
        }
    edit_hwnd, edit_rect = edits[0]
    if (probe._window_pid(user32, edit_hwnd) != probe._window_pid(user32, root_hwnd)
            or probe._class_name(user32, edit_hwnd) != "Edit"
            or not probe._window_is_related_to_embedded_target(
                user32, edit_hwnd, root_hwnd, host
            )):
        return {**base, "status": "source_edit_identity_mismatch",
                "text_changed": False, "edit_hwnd": int(edit_hwnd),
                "edit_class": probe._class_name(user32, edit_hwnd),
                "edit_control_id": int(user32.GetDlgCtrlID(probe.wintypes.HWND(edit_hwnd))),
                "edit_rect_screen": edit_rect}

    relative_rect = [int(edit_rect[0] - origin.x), int(edit_rect[1] - origin.y),
                     int(edit_rect[2] - origin.x), int(edit_rect[3] - origin.y)]
    center = [(relative_rect[0] + relative_rect[2]) // 2,
              (relative_rect[1] + relative_rect[3]) // 2]
    delta = [abs(center[0] - _RANGE_SOURCE_FIELD_CENTER[0]),
             abs(center[1] - _RANGE_SOURCE_FIELD_CENTER[1])]
    if delta[0] > 35 or delta[1] > 20:
        return {**base, "status": "source_edit_outside_measured_field",
                "text_changed": False, "edit_hwnd": int(edit_hwnd),
                "edit_rect_screen": edit_rect, "edit_rect_client": relative_rect,
                "center_delta": delta}

    original = probe._read_native_edit_text(user32, edit_hwnd)
    if original != "":
        return {**base, "status": "nonempty_source_field_preserved",
                "text_changed": False, "edit_hwnd": int(edit_hwnd),
                "edit_rect_screen": edit_rect, "edit_rect_client": relative_rect,
                "original_text_length": len(original)}

    test_capture = None
    restore_capture = None
    test_readback = None
    restore_readback = None
    restore_error = None
    write_verified = False
    restore_verified = False
    try:
        probe._write_native_edit_text(user32, edit_hwnd, "AA")
        test_readback = probe._read_native_edit_text(user32, edit_hwnd)
        write_verified = test_readback == "AA"
        if not write_verified:
            raise RuntimeError(f"test write/readback mismatch: {test_readback!r}")
        test_capture = probe._batch_capture(
            user32, root_hwnd, RECT, POINT, output_dir, stem,
            f"{role.lower()}_source_text_temporary"
        )
        if test_capture.get("capture_error"):
            raise RuntimeError(f"temporary text capture failed: {test_capture['capture_error']}")
    except Exception as exc:
        restore_error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            probe._write_native_edit_text(user32, edit_hwnd, original)
            restore_readback = probe._read_native_edit_text(user32, edit_hwnd)
            restore_verified = restore_readback == original
            if not restore_verified:
                restore_error = (restore_error + "; " if restore_error else "") + "original text restore readback mismatch"
        except Exception as exc:
            restore_error = (restore_error + "; " if restore_error else "") + f"restore {type(exc).__name__}: {exc}"
    restore_capture = probe._batch_capture(
        user32, root_hwnd, RECT, POINT, output_dir, stem,
        f"{role.lower()}_source_text_restored"
    )
    status = (
        "write_readback_and_restore_verified"
        if write_verified and restore_verified and not (restore_capture or {}).get("capture_error")
        else "source_field_test_incomplete"
    )
    return {
        **base, "status": status, "edit_hwnd": int(edit_hwnd),
        "edit_control_id": int(user32.GetDlgCtrlID(probe.wintypes.HWND(edit_hwnd))), "edit_class": "Edit",
        "edit_rect_screen": edit_rect, "edit_rect_client": relative_rect,
        "center_delta": delta, "original_text_length": len(original),
        "test_text": "AA", "test_write_readback": test_readback,
        "write_verified": write_verified, "restore_readback": restore_readback,
        "restore_verified": restore_verified, "restore_error": restore_error,
        "temporary_capture": test_capture, "restored_capture": restore_capture,
        "text_changed": not restore_verified, "range_committed": False, "done_clicked": False,
    }

def run_setup_dialog_probe(output_dir: Path, *, target_pid: int, target_hwnd: int) -> Path:
    if os.name != "nt":
        raise OSError("This GTO+ setup probe is Windows-only.")
    if not target_pid or not target_hwnd:
        raise ValueError("An exact Pigeon-embedded GTO+ PID and HWND are required.")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"gto_auto_solve_ui_{stamp}"
    user32, EnumWindowsProc, EnumChildProc, RECT, POINT = probe._win32_api()
    if not user32.IsWindow(probe.wintypes.HWND(target_hwnd)):
        raise RuntimeError("Pigeon-embedded GTO+ HWND is no longer valid.")
    actual_pid = probe._window_pid(user32, target_hwnd)
    if actual_pid != int(target_pid):
        raise RuntimeError(f"Exact GTO+ PID mismatch: expected {target_pid}, got {actual_pid}.")

    width, height = _client_geometry(user32, target_hwnd, RECT)
    if abs(width-_REFERENCE_SIZE[0]) > 12 or abs(height-_REFERENCE_SIZE[1]) > 12:
        raise RuntimeError(
            f"Safe setup probe refused an uncalibrated GTO+ size: {width}x{height}; "
            f"expected {_REFERENCE_SIZE[0]}x{_REFERENCE_SIZE[1]}. No click was sent."
        )

    host = probe._top_level_ancestor(user32, target_hwnd)
    initial_windows = _capture_related_windows(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        target_hwnd, target_pid, output_dir, stem, "initial"
    )
    extra_initial = [w for w in initial_windows if not w["is_embedded_root"]]
    preexisting_source_edits = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
    if extra_initial or preexisting_source_edits:
        raise RuntimeError(
            "A related GTO+ popup or range editor is already open. "
            "The probe stopped without clicking to avoid disturbing the user's current dialog."
        )

    actions: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    all_captures: list[dict[str, Any]] = []
    baseline_windows = _capture_related_windows(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        target_hwnd, target_pid, output_dir, stem, "baseline"
    )
    baseline_path = _root_capture_path(baseline_windows, "baseline")
    all_captures.extend(w["capture"] for w in baseline_windows)
    main_controls = probe._batch_child_controls(user32, RECT, target_hwnd)

    # Stage 1: open the OOP editor, confirm that it visibly appeared, then close
    # it via its measured X control (Escape belongs to Pigeon's Tk thread here).
    oop_click = _click_exact_client(
        user32, target_hwnd, target_pid, RECT, POINT, _OOP_MATRIX_CENTER,
        label="open_oop_range_editor"
    )
    actions.append(oop_click)
    time.sleep(0.55)
    oop_windows = _capture_related_windows(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        target_hwnd, target_pid, output_dir, stem, "oop_editor_open"
    )
    oop_open_path = _root_capture_path(oop_windows, "oop_editor_open")
    oop_appearance = _bmp_region_difference_ratio(baseline_path, oop_open_path)
    all_captures.extend(w["capture"] for w in oop_windows)
    if oop_appearance["ratio"] < 0.05:
        raise RuntimeError(
            "OOP editor click did not produce the calibrated visible overlay; "
            "no close click or Build Tree click was sent."
        )

    oop_source_probe = _probe_source_field_readback_restore(
        user32, target_hwnd, EnumWindowsProc, EnumChildProc,
        RECT, POINT, output_dir, stem, "OOP"
    )
    if oop_source_probe.get("field_click"):
        actions.append(oop_source_probe["field_click"])
    for capture_key in ("temporary_capture", "restored_capture"):
        capture = oop_source_probe.get(capture_key)
        if capture:
            all_captures.append(capture)

    close_click = _click_exact_client(
        user32, target_hwnd, target_pid, RECT, POINT, _OOP_CLOSE_CENTER,
        label="close_oop_range_editor"
    )
    actions.append(close_click)
    oop_closed_windows = _capture_related_windows(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        target_hwnd, target_pid, output_dir, stem, "oop_editor_after_x"
    )
    oop_closed_path = _root_capture_path(oop_closed_windows, "oop_editor_after_x")
    oop_close_check = _bmp_region_difference_ratio(baseline_path, oop_closed_path)
    all_captures.extend(w["capture"] for w in oop_closed_windows)
    oop_closed_ok = oop_close_check["ratio"] <= 0.01
    oop_native_retry = None
    oop_native_retry_windows = []
    oop_native_retry_check = None
    oop_native_retry_error = None
    if not oop_closed_ok:
        try:
            oop_native_retry = _click_verified_gto_hit_target(
                user32, target_hwnd, target_pid, RECT, POINT, _OOP_CLOSE_CENTER,
                label="close_oop_range_editor_native_retry"
            )
            actions.append(oop_native_retry)
            oop_native_retry_windows = _capture_related_windows(
                user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                target_hwnd, target_pid, output_dir, stem, "oop_editor_after_native_close"
            )
            oop_native_retry_path = _root_capture_path(
                oop_native_retry_windows, "oop_editor_after_native_close"
            )
            oop_native_retry_check = _bmp_region_difference_ratio(
                baseline_path, oop_native_retry_path
            )
            all_captures.extend(w["capture"] for w in oop_native_retry_windows)
            oop_closed_ok = oop_native_retry_check["ratio"] <= 0.01
        except Exception as exc:
            oop_native_retry_error = f"{type(exc).__name__}: {exc}"
    stages.append({
        "stage": "oop_range_editor",
        "status": (
            "opened_and_closed_by_measured_x" if oop_closed_ok and oop_native_retry is None
            else "opened_and_closed_by_native_view_retry" if oop_closed_ok
            else "close_not_verified"
        ),
        "open_click": oop_click,
        "open_windows": oop_windows,
        "open_overlay_difference": oop_appearance,
        "close_click": close_click,
        "windows_after_x": oop_closed_windows,
        "baseline_difference_after_x": oop_close_check,
        "native_close_retry": oop_native_retry,
        "native_close_retry_error": oop_native_retry_error,
        "windows_after_native_close": oop_native_retry_windows,
        "baseline_difference_after_native_close": oop_native_retry_check,
        "visually_closed": oop_closed_ok,
        "range_text_changed": False,
        "range_committed": False,
    })
    stages.append(oop_source_probe)

    # Stage 2: calibrate the IP Source field using the same reversible AA test.
    # Never click Done: the test text is read back and restored before closing.
    ip_editor_result = None
    board_input_result = None
    manual_close_required = (not oop_closed_ok
                             or not oop_source_probe.get("window_position_restore_verified", True))
    continue_after_oop = (oop_closed_ok
                          and oop_source_probe.get("status") != "source_field_test_incomplete"
                          and oop_source_probe.get("window_position_restore_verified", True))
    if continue_after_oop:
        ip_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT, _IP_MATRIX_CENTER,
            label="open_ip_range_editor"
        )
        actions.append(ip_click)
        time.sleep(0.55)
        ip_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, "ip_editor_open"
        )
        ip_open_path = _root_capture_path(ip_windows, "ip_editor_open")
        ip_appearance = _bmp_region_difference_ratio(baseline_path, ip_open_path)
        all_captures.extend(w["capture"] for w in ip_windows)
        if ip_appearance["ratio"] >= 0.05:
            ip_source_probe = _probe_source_field_readback_restore(
                user32, target_hwnd, EnumWindowsProc, EnumChildProc,
                RECT, POINT, output_dir, stem, "IP"
            )
            if ip_source_probe.get("field_click"):
                if ip_source_probe.get("field_click"):
                    actions.append(ip_source_probe["field_click"])
            for capture_key in ("temporary_capture", "restored_capture"):
                capture = ip_source_probe.get(capture_key)
                if capture:
                    all_captures.append(capture)
            ip_close_click = _click_exact_client(
                user32, target_hwnd, target_pid, RECT, POINT, _OOP_CLOSE_CENTER,
                label="close_oop_range_editor"
            )
            actions.append(ip_close_click)
            ip_closed_windows = _capture_related_windows(
                user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                target_hwnd, target_pid, output_dir, stem, "ip_editor_after_x"
            )
            ip_closed_path = _root_capture_path(ip_closed_windows, "ip_editor_after_x")
            ip_close_check = _bmp_region_difference_ratio(baseline_path, ip_closed_path)
            all_captures.extend(w["capture"] for w in ip_closed_windows)
            ip_closed_ok = ip_close_check["ratio"] <= 0.01
            ip_native_retry = None
            ip_native_retry_windows = []
            ip_native_retry_check = None
            ip_native_retry_error = None
            if not ip_closed_ok:
                try:
                    ip_native_retry = _click_verified_gto_hit_target(
                        user32, target_hwnd, target_pid, RECT, POINT, _OOP_CLOSE_CENTER,
                        label="close_ip_range_editor_native_retry"
                    )
                    actions.append(ip_native_retry)
                    ip_native_retry_windows = _capture_related_windows(
                        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                        target_hwnd, target_pid, output_dir, stem, "ip_editor_after_native_close"
                    )
                    ip_native_retry_path = _root_capture_path(
                        ip_native_retry_windows, "ip_editor_after_native_close"
                    )
                    ip_native_retry_check = _bmp_region_difference_ratio(
                        baseline_path, ip_native_retry_path
                    )
                    all_captures.extend(w["capture"] for w in ip_native_retry_windows)
                    ip_closed_ok = ip_native_retry_check["ratio"] <= 0.01
                except Exception as exc:
                    ip_native_retry_error = f"{type(exc).__name__}: {exc}"
            manual_close_required = (manual_close_required or not ip_closed_ok
                                     or not ip_source_probe.get("window_position_restore_verified", True))
            ip_editor_result = {
                "stage": "ip_range_editor",
                "status": (
                    "opened_and_closed_by_measured_x" if ip_closed_ok and ip_native_retry is None
                    else "opened_and_closed_by_native_view_retry" if ip_closed_ok
                    else "close_not_verified"
                ),
                "open_click": ip_click,
                "open_windows": ip_windows,
                "open_overlay_difference": ip_appearance,
                "source_field_probe": ip_source_probe,
                "close_click": ip_close_click,
                "windows_after_x": ip_closed_windows,
                "baseline_difference_after_x": ip_close_check,
                "native_close_retry": ip_native_retry,
                "native_close_retry_error": ip_native_retry_error,
                "windows_after_native_close": ip_native_retry_windows,
                "baseline_difference_after_native_close": ip_native_retry_check,
                "visually_closed": ip_closed_ok,
                "range_committed": False,
            }
            stages.append(ip_editor_result)
            stages.append(ip_source_probe)
            continue_after_oop = (ip_closed_ok
                                  and ip_source_probe.get("status") != "source_field_test_incomplete"
                                  and ip_source_probe.get("window_position_restore_verified", True))
        else:
            ip_editor_result = {
                "stage": "ip_range_editor",
                "status": "editor_not_visibly_opened",
                "open_click": ip_click,
                "open_windows": ip_windows,
                "open_overlay_difference": ip_appearance,
                "range_committed": False,
            }
            stages.append(ip_editor_result)
            continue_after_oop = False

    # Stage 3: focus the Board entry only to identify its input mechanism.
    # No board text is typed and no card selection is made.
    if continue_after_oop:
        board_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT, _BOARD_INPUT_CENTER,
            label="focus_board_input"
        )
        actions.append(board_click)
        time.sleep(0.45)
        board_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, "board_input_open"
        )
        board_open_path = _root_capture_path(board_windows, "board_input_open")
        board_appearance = _bmp_region_difference_ratio(baseline_path, board_open_path)
        all_captures.extend(w["capture"] for w in board_windows)
        board_popup_detected = any(not w.get("is_embedded_root", False) for w in board_windows)
        board_dialog_detected = board_popup_detected or board_appearance["ratio"] >= 0.05
        board_controls = probe._batch_child_controls(user32, RECT, target_hwnd)
        board_focus = probe._gui_thread_focus_snapshot(
            user32, RECT, POINT, target_hwnd, host
        )
        board_close_click = None
        board_after_x_windows = []
        board_close_check = None
        board_native_retry = None
        board_after_native_windows = []
        board_native_retry_check = None
        board_close_error = None
        if board_dialog_detected:
            try:
                board_close_click = _click_exact_client(
                    user32, target_hwnd, target_pid, RECT, POINT,
                    _BOARD_CLOSE_CENTER, label="close_board_selector"
                )
                actions.append(board_close_click)
                time.sleep(0.35)
                board_after_x_windows = _capture_related_windows(
                    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                    target_hwnd, target_pid, output_dir, stem, "board_input_after_x"
                )
                board_after_path = _root_capture_path(board_after_x_windows, "board_input_after_x")
                board_close_check = _bmp_region_difference_ratio(baseline_path, board_after_path)
                all_captures.extend(w["capture"] for w in board_after_x_windows)
                if board_close_check["ratio"] > 0.01:
                    board_native_retry = _click_verified_gto_hit_target(
                        user32, target_hwnd, target_pid, RECT, POINT, _BOARD_CLOSE_CENTER,
                        label="close_board_selector_native_retry"
                    )
                    actions.append(board_native_retry)
                    board_after_native_windows = _capture_related_windows(
                        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                        target_hwnd, target_pid, output_dir, stem, "board_input_after_native_close"
                    )
                    board_after_native_path = _root_capture_path(
                        board_after_native_windows, "board_input_after_native_close"
                    )
                    board_native_retry_check = _bmp_region_difference_ratio(
                        baseline_path, board_after_native_path
                    )
                    all_captures.extend(w["capture"] for w in board_after_native_windows)
            except Exception as exc:
                board_close_error = f"{type(exc).__name__}: {exc}"
        board_final_close_check = (
            board_native_retry_check
            if board_native_retry_check is not None else board_close_check
        )
        board_closed_ok = bool(
            not board_dialog_detected
            or (board_final_close_check and board_final_close_check["ratio"] <= 0.01)
        )
        manual_close_required = manual_close_required or (board_dialog_detected and not board_closed_ok)
        board_input_result = {
            "stage": "board_input",
            "status": (
                "input_field_focused_no_popup" if not board_dialog_detected
                else "selector_opened_and_closed_by_x" if board_closed_ok
                else "selector_opened_manual_close_required"
            ),
            "click": board_click,
            "open_windows": board_windows,
            "visible_overlay_difference": board_appearance,
            "popup_detected": board_popup_detected,
            "dialog_detected": board_dialog_detected,
            "native_controls": board_controls,
            "focus_snapshot": board_focus,
            "close_click": board_close_click,
            "close_error": board_close_error,
            "native_close_retry": board_native_retry if board_dialog_detected else None,
            "windows_after_native_close": board_after_native_windows if board_dialog_detected else [],
            "baseline_difference_after_native_close": board_native_retry_check,
            "windows_after_x": board_after_x_windows,
            "baseline_difference_after_x": board_close_check,
            "final_baseline_difference": board_final_close_check,
            "visually_closed": board_closed_ok,
            "board_changed": False,
        }
        stages.append(board_input_result)

    report = {
        "schema_version": 9,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "probe": "verified_gto_plus_oop_ip_source_view_focus_native_edit_and_native_close_retry_v9",
        "target": {"pid": int(target_pid), "hwnd": int(target_hwnd), "host_hwnd": int(host)},
        "client_size": [width, height],
        "window_position_policy": {
            "move_only_exact_gto_embedded_child": True,
            "child_move_uses_exact_parent_client_coordinates": True,
            "only_when_source_field_is_hit_by_foreign_overlay": True,
            "original_parent_relative_position_restore_readback_required": True,
        },
        "input_calibration": {
            "method": "temporary child reposition in verified parent-client coordinates when WindowFromPoint hits a foreign overlay; focus-only click is allowed on exact GTO view 59648, followed by unique native Edit discovery by PID, ownership, class, and measured field geometry",
            "test_value": "AA",
            "original_field_must_be_empty": True,
            "focus_only_click_allowed_on_verified_gto_view": True,
            "no_keyboard_input_without_unique_native_edit": True,
            "source_text_readback_required": True,
            "original_text_restore_readback_required": True,
            "done_button_clicked": False,
            "range_committed": False,
            "board_text_entered": False,
            "temporary_window_position_restore_required": True,
        },
        "coordinate_reference": {
            "client_size": list(_REFERENCE_SIZE),
            "oop_matrix_rect": list(_OOP_MATRIX_RECT),
            "oop_matrix_center": list(_OOP_MATRIX_CENTER),
            "oop_close_rect": list(_OOP_CLOSE_RECT),
            "oop_close_center": list(_OOP_CLOSE_CENTER),
            "ip_matrix_rect": list(_IP_MATRIX_RECT),
            "ip_matrix_center": list(_IP_MATRIX_CENTER),
            "range_source_field_rect": list(_RANGE_SOURCE_FIELD_RECT),
            "range_source_field_center": list(_RANGE_SOURCE_FIELD_CENTER),
            "board_input_rect": list(_BOARD_INPUT_RECT),
            "board_input_center": list(_BOARD_INPUT_CENTER),
            "board_close_rect": list(_BOARD_CLOSE_RECT),
            "board_close_center": list(_BOARD_CLOSE_CENTER),
            "build_tree_button_rect": list(_BUILD_TREE_RECT),
            "build_tree_button_center": list(_BUILD_TREE_CENTER),
            "visual_verification_roi": list(_DIALOG_ROI),
            "source": "gto_auto_solve_ui_20261119_223035 uploaded diagnostic screenshot",
        },
        "main_window_controls_before": main_controls,
        "initial_windows": initial_windows,
        "stages": stages,
        "actions": actions,
        "all_captures": all_captures,
        "safety": {
            "oop_range_text_changed": bool(oop_source_probe.get("text_changed", False)),
            "ip_range_text_changed": any(
                bool(stage.get("text_changed", False))
                for stage in stages if stage.get("stage") == "ip_source_field"
            ),
            "range_committed": False,
            "board_changed": False,
            "pot_changed": False,
            "stack_changed": False,
            "rake_changed": False,
            "tree_built": False,
            "solver_run": False,
            "other_gto_processes_touched": False,
            "build_tree_clicked": False,
            "board_selector_left_open": bool(
                board_input_result and board_input_result.get("dialog_detected")
                and not board_input_result.get("visually_closed")
            ),
            "manual_close_required": manual_close_required,
            "window_position_restore_failed": bool(
                not oop_source_probe.get("window_position_restore_verified", True)
                or any(stage.get("stage") == "ip_source_field"
                       and not stage.get("window_position_restore_verified", True)
                       for stage in stages)
            ),
        },
        "notes": [
            "Only the exact Pigeon-embedded GTO+ HWND/PID was operated.",
            "Before the Source field focus click, WindowFromPoint must resolve either to an exact GTO-owned native Edit or to the measured AfxFrameOrView140su id=59648 covering the field. Foreign overlays cause a no-click, no-write stop. If the view receives focus but no unique native Edit appears at the measured field, no keyboard input is sent.",
            "If a foreign window covers the Source field, only the exact embedded GTO child is temporarily shifted within its verified parent-client coordinate system; the exact original parent-relative position is restored and verified immediately after the field probe. The host window and other processes are not moved.",
            "OOP and IP Source Edit fields are tested with AA only when the exact field is hit-tested and originally blank; text is read back and restored. Done is never clicked.",
            "The OOP/IP range editor is first dismissed with its measured X button; when the overlay remains, one direct WM_MOUSEMOVE/WM_LBUTTONDOWN/WM_LBUTTONUP retry is sent only to the verified GTO drawing view under that exact point and rechecked against baseline pixels.",
            "The Board selector is first dismissed with its measured X button; when it remains, the same exact-view-only mouse-message retry is used and visually checked. No board text is entered and no card is selected.",
            "No range is committed; no Board/Pot/Stack/Rake is changed; Build Tree and Solver are not run.",
            "Escape is sent only when the detected selector belongs to the exact GTO process and that process owns keyboard focus.",
        ],
    }
    json_path = output_dir / f"{stem}.json"
    txt_path = output_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "PIGEON POKER — VISUALLY VERIFIED GTO+ AUTO-SOLVE SETUP PROBE",
        f"Created: {report['created_at']}",
        f"Target: PID={target_pid} HWND={target_hwnd}",
        f"Client: {width}x{height}",
        f"OOP editor closed by X: {stages[0]['visually_closed']}",
        f"OOP source field: {oop_source_probe['status']}",
        f"IP range editor: {ip_editor_result['status'] if ip_editor_result else 'not_attempted'}",
        f"Board input: {board_input_result['status'] if board_input_result else 'not_attempted'}",
        f"Source click sent: {bool(oop_source_probe.get('click_sent', False))}",
        f"Temporary GTO window move: {oop_source_probe.get('temporary_window_adjustment', {}).get('status', 'not_reported')}",
        f"Temporary GTO window move restored: {bool(oop_source_probe.get('window_position_restore_verified', True))}",
        f"Manual close required: {manual_close_required}",
        "Range/board/pot/stack/rake changed: no",
        "Tree built: no",
        "Solver run: no",
        "",
    ]
    for stage in stages:
        lines.append(f"{stage['stage']}: {stage['status']}")
        if "visible_overlay_difference" in stage:
            lines.append(f"Overlay pixel ratio: {stage['visible_overlay_difference']['ratio']:.4f}")
        if "open_overlay_difference" in stage:
            lines.append(f"Editor-open pixel ratio: {stage['open_overlay_difference']['ratio']:.4f}")
        if "baseline_difference_after_escape" in stage and stage["baseline_difference_after_escape"]:
            lines.append(f"After Escape baseline pixel ratio: {stage['baseline_difference_after_escape']['ratio']:.4f}")
        if "baseline_difference_after_x" in stage:
            lines.append(f"After X baseline pixel ratio: {stage['baseline_difference_after_x']['ratio']:.4f}")
        if "baseline_difference_after_x" in stage and stage.get("stage") == "board_input":
            lines.append(f"Board selector closed by X: {bool(stage.get('visually_closed'))}")
    txt_path.write_text("\n".join(lines), encoding="utf-8")
    zip_path = output_dir / f"{stem}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(json_path, json_path.name)
        archive.write(txt_path, txt_path.name)
        for capture in all_captures:
            shot = capture.get("screenshot") if isinstance(capture, dict) else None
            if shot and Path(shot).is_file():
                archive.write(shot, Path(shot).name)
    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Visually verified GTO+ 1.9.1 setup dialog discovery")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "diagnostics"))
    parser.add_argument("--target-pid", type=int, required=True)
    parser.add_argument("--target-hwnd", type=int, required=True)
    args = parser.parse_args()
    try:
        path = run_setup_dialog_probe(
            Path(args.output), target_pid=int(args.target_pid), target_hwnd=int(args.target_hwnd)
        )
        print(f"Visually verified GTO+ setup diagnostic created: {path}")
        return 0
    except Exception as exc:
        print(f"GTO+ setup diagnostic stopped safely: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

# Rebuild after correcting the source path for the bundled Win32 UI observer.

# Candidate rebuild: package the exact v1.3.40 UI observer and preflop chart modules.

# Final packaging check: include exact UI probe and preflop chart modules.
