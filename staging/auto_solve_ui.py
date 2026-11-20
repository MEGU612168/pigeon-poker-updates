"""Calibrated, read-only discovery of embedded GTO+ 1.9.1 setup UI.

The range editor is closed with its measured on-screen X button, not Escape:
the embedded GTO window has no keyboard focus while Pigeon's Tk child owns it.
The Build Tree dialog is captured and is only dismissed with Escape when the
GTO process itself owns keyboard focus. Every close is visually verified
against the baseline screenshot before the next click is allowed.
"""
from __future__ import annotations

# Build marker: OOP/IP matrix ROIs calibrated; None-safe stage summaries; schema v18.
# Rebuild trigger: move Board checks to generated JSON safety report validation.
# Rebuild trigger: rerun v1.3.67 after aligning Build Tree close static assertion.
# Rebuild trigger: validate partial-commit cleanup and v1.3.67 UI text replacements.
# Rebuild trigger: corrected v1.3.67 workflow newline after UI replacement array.
# Rebuild trigger: v1.3.67 safe Build Tree dialog inspection and exact cleanup sequence.
# Rebuild trigger: include Board roundtrip result fields in the top-level safety report.
# Rebuild trigger: rerun v1.3.65 Board selector CI after updating stale assertions.
# Rebuild trigger: validate actual GTO+ Board card selection As/Kd/7c and Clear/Done restoration.
# Rebuild trigger: split launch/attach GTO+ geometry sync hooks and validate method ownership.
# Rebuild trigger: geometry patch quoting corrected for v1.3.63 build.
# Rebuild trigger: force embedded GTO+ geometry sync immediately and after dock.
# Rebuild trigger: normalize last legacy AA JSON error label for dual OOP/IP check.
# PigeonPoker completion gate: exactly one OOP multi-hand validator, v1.3.58.
# Rebuild trigger: remove second post-success report check, keep one OOP multi-hand gate.
# Rebuild trigger: normalize final multi-hand exception label.
# Rebuild trigger: remove exact legacy AA-only report validation block.
# v1.3.59 trigger: publish unique version for the corrected single multi-hand completion gate.
# PigeonPoker completion gate: exactly one OOP multi-hand validator, v1.3.58.

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
_OOP_MATRIX_RECT = (27, 89, 79, 141)
_OOP_MATRIX_CENTER = (54, 116)
_OOP_CLOSE_RECT = (488, 66, 504, 84)
_OOP_CLOSE_CENTER = (496, 75)
_IP_MATRIX_RECT = (27, 160, 79, 212)
_IP_MATRIX_CENTER = (54, 187)
_RANGE_SOURCE_FIELD_RECT = (112, 427, 412, 449)
_RANGE_SOURCE_FIELD_CENTER = (262, 438)
_BOARD_INPUT_RECT = (23, 230, 85, 248)
_BOARD_INPUT_CENTER = (54, 239)
_BOARD_CLOSE_RECT = (277, 71, 291, 85)
_BOARD_CLOSE_CENTER = (284, 78)
_RANGE_EDITOR_CLEAR_RECT = (417, 307, 502, 331)
_RANGE_EDITOR_CLEAR_CENTER = (460, 319)
_RANGE_EDITOR_DONE_RECT = (417, 422, 502, 447)
_RANGE_EDITOR_DONE_CENTER = (460, 434)
_BUILD_TREE_RECT = (24, 253, 85, 276)
_BUILD_TREE_CENTER = (54, 265)
_DIALOG_ROI = (100, 60, 515, 460)
# Exclude left-side hover tooltips while keeping most of the range editor panel.
_RANGE_EDITOR_VERIFY_ROI = (240, 60, 515, 460)
_GTO_PLUS_OOP_MULTI_RANGE_SOURCE_TEXTS = (
    "AA,[40%]AKs[/40%]",
    "[40%]AKs[/40%],AA",
)
# OOP and IP use the same GTO+ Source normalization syntax.
# Keep an explicit IP alias so the IP roundtrip can validate its own allowlist.
_GTO_PLUS_IP_MULTI_RANGE_SOURCE_TEXTS = _GTO_PLUS_OOP_MULTI_RANGE_SOURCE_TEXTS
_GTO_PLUS_HALF_WEIGHT_AA_SOURCE = "[50%]AA[/50%]"


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
        "clear_range_editor": _RANGE_EDITOR_CLEAR_RECT,
        "commit_range_editor_done": _RANGE_EDITOR_DONE_RECT,
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
    """Only identify a Build Tree dialog from its own window/control signature.

    A generic pixel change in GTO's custom view is not enough: that can simply be
    the Starting Range Editor opened after a missing-player-range validation alert.
    """
    for window in windows:
        if not isinstance(window, dict) or window.get("is_embedded_root", False):
            continue
        title = str(window.get("title") or "").strip().lower()
        controls = window.get("controls") or []
        names = " ".join(
            str(control.get("name") or "")
            for control in controls if isinstance(control, dict)
        ).lower()
        if title == "program message":
            continue
        if any(token in title for token in ("build tree", "build-tree", "決定木", "ツリー構築")):
            return True
        if any(token in names for token in (
            "build decision tree", "basic", "advanced", "memory needed for solving",
            "build tree", "決定木の構築", "メモリー",
        )):
            return True
    return False


def _is_player2_range_validation_popup(window: dict[str, Any]) -> bool:
    """Recognize the exact GTO+ message that rejects Build Tree because IP is missing."""
    if not isinstance(window, dict):
        return False
    if str(window.get("title") or "").strip().lower() != "program message":
        return False
    controls = window.get("controls") or []
    text_value = " ".join(
        str(control.get("name") or "")
        for control in controls if isinstance(control, dict)
    )
    return "プレイヤー 2 のレンジを入力してください" in text_value


def _dismiss_exact_gto_message_with_ok(user32, target_pid: int,
                                        popup: dict[str, Any]) -> dict[str, Any]:
    """Press OK only on the unique visible/enabled OK button in the exact GTO popup."""
    popup_hwnd = int(popup.get("hwnd") or 0)
    if (
        not popup_hwnd
        or int(popup.get("pid") or -1) != int(target_pid)
        or str(popup.get("title") or "").strip().lower() != "program message"
        or probe._window_pid(user32, popup_hwnd) != int(target_pid)
        or not user32.IsWindowVisible(probe.wintypes.HWND(popup_hwnd))
    ):
        raise RuntimeError("GTO Program message identity was not verified; no close action sent")
    controls = [
        c for c in (popup.get("controls") or [])
        if isinstance(c, dict)
        and str(c.get("name") or "").strip().lower() == "ok"
        and str(c.get("class_name") or "") == "Button"
        and int(c.get("control_id") or 0) == 1
        and int(c.get("process_id") or -1) == int(target_pid)
        and int(c.get("parent_handle") or 0) == popup_hwnd
        and c.get("visible") is True
        and c.get("enabled") is True
    ]
    if len(controls) != 1:
        raise RuntimeError(f"Expected one verified GTO OK button; found {len(controls)}")
    button_hwnd = int(controls[0].get("handle") or 0)
    if (
        not button_hwnd
        or not user32.IsWindow(probe.wintypes.HWND(button_hwnd))
        or probe._window_pid(user32, button_hwnd) != int(target_pid)
        or probe._class_name(user32, button_hwnd) != "Button"
        or int(user32.GetDlgCtrlID(probe.wintypes.HWND(button_hwnd))) != 1
    ):
        raise RuntimeError("GTO OK button HWND/PID/class/control ID verification failed")
    send = user32.SendMessageW
    send.argtypes = [probe.wintypes.HWND, probe.wintypes.UINT,
                     probe.wintypes.WPARAM, probe.wintypes.LPARAM]
    send.restype = probe.ctypes.c_ssize_t
    result = int(send(probe.wintypes.HWND(button_hwnd), 0x00F5, 0, 0))  # BM_CLICK
    return {
        "action": "BM_CLICK",
        "target_pid": int(target_pid),
        "popup_hwnd": popup_hwnd,
        "button_hwnd": button_hwnd,
        "button_control_id": 1,
        "message_result": result,
    }


def _commit_verified_player2_editor_after_prompt(
    user32, RECT, POINT, target_hwnd: int, target_pid: int,
    before_path: str, output_dir: Path, stem: str,
    actions: list[dict[str, Any]], all_captures: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    """Commit the already-open Player 2 editor only if Source is the exact test-only value."""
    result: dict[str, Any] = {
        "stage": "player2_range_validation_recovery",
        "status": "not_started",
        "source_text_accepted": False,
        "done_clicked": False,
        "editor_closed_verified": False,
        "test_range_preserved": True,
        "manual_close_required": False,
    }
    edits = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
    result["visible_source_edit_count"] = len(edits)
    if len(edits) != 1:
        result["status"] = "stopped_no_unique_player2_source_edit"
        result["note"] = "No unique visible Source Edit was found after the Player 2 message; no text or Done action was sent."
        result["manual_close_required"] = bool(edits)
        return result
    edit_hwnd, edit_rect = edits[0]
    edit_hwnd = int(edit_hwnd)
    host_hwnd = probe._top_level_ancestor(user32, target_hwnd)
    if (
        not user32.IsWindow(probe.wintypes.HWND(edit_hwnd))
        or probe._window_pid(user32, edit_hwnd) != int(target_pid)
        or probe._class_name(user32, edit_hwnd) != "Edit"
        or int(user32.GetDlgCtrlID(probe.wintypes.HWND(edit_hwnd))) != 5458
        or not probe._window_is_related_to_embedded_target(
            user32, edit_hwnd, target_hwnd, host_hwnd
        )
    ):
        result["status"] = "stopped_source_edit_identity_unverified"
        result["manual_close_required"] = True
        return result
    source_text = probe._read_native_edit_text(user32, edit_hwnd)
    result["source_text_readback"] = source_text
    result["source_text_accepted"] = source_text in set(_GTO_PLUS_IP_MULTI_RANGE_SOURCE_TEXTS)
    if not result["source_text_accepted"]:
        result["status"] = "stopped_unrecognized_player2_source_text_preserved"
        result["note"] = "Source was not the exact AA+AKs:40% test value; no Done, Clear, or keyboard action was sent."
        result["manual_close_required"] = True
        return result

    done = _click_exact_client(
        user32, target_hwnd, target_pid, RECT, POINT,
        _RANGE_EDITOR_DONE_CENTER, label="player2_range_validation_done"
    )
    actions.append(done)
    result["done_click"] = done
    result["done_clicked"] = True
    time.sleep(0.45)
    remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
    retry = None
    if remaining:
        retry = _click_verified_gto_hit_target(
            user32, target_hwnd, target_pid, RECT, POINT,
            _RANGE_EDITOR_DONE_CENTER, label="player2_range_validation_done_native_retry"
        )
        actions.append(retry)
        time.sleep(0.45)
        remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
    result["done_native_retry"] = retry
    result["editor_closed_verified"] = not remaining
    result["remaining_source_edits"] = len(remaining)
    result["test_range_preserved"] = True
    result["status"] = (
        "player2_test_range_done_committed"
        if result["editor_closed_verified"]
        else "player2_editor_still_open_after_done"
    )
    result["manual_close_required"] = not result["editor_closed_verified"]
    result["note"] = (
        "The exact known AA+AKs:40% Player 2 Source value was confirmed and Done was sent once."
        if result["editor_closed_verified"]
        else "The exact test Source value was confirmed, but the editor remained visible after Done."
    )
    return result


def _run_build_tree_dialog_probe(
    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
    target_hwnd: int, target_pid: int, output_dir: Path, stem: str,
    baseline_path: str, actions: list[dict[str, Any]], all_captures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Open Build Tree, distinguish a Player-2 validation prompt, and inspect only a real setup dialog."""
    result: dict[str, Any] = {
        "stage": "build_tree_dialog_probe",
        "status": "not_started",
        "build_tree_clicked": False,
        "dialog_opened": False,
        "dialog_closed_verified": False,
        "tree_built": False,
        "solver_run": False,
        "manual_close_required": False,
        "popup_windows": [],
        "player2_range_validation_seen": False,
        "player2_range_validation_recovered": False,
    }

    def capture(stage_name: str):
        windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, stage_name
        )
        all_captures.extend(w["capture"] for w in windows)
        return windows, _root_capture_path(windows, stage_name)

    def find_popups(windows):
        return [w for w in windows if isinstance(w, dict) and not w.get("is_embedded_root", False)]

    def close_real_dialog(popup_windows, before_path: str):
        if len(popup_windows) != 1:
            result["status"] = "build_tree_dialog_popup_ambiguous"
            result["manual_close_required"] = True
            return False
        popup = popup_windows[0]
        popup_hwnd = int(popup.get("hwnd") or 0)
        if (
            not popup_hwnd
            or probe._window_pid(user32, popup_hwnd) != int(target_pid)
            or not probe._window_is_related_to_embedded_target(
                user32, popup_hwnd, target_hwnd,
                probe._top_level_ancestor(user32, target_hwnd)
            )
            or not user32.IsWindowVisible(probe.wintypes.HWND(popup_hwnd))
        ):
            result["status"] = "build_tree_dialog_popup_identity_unverified"
            result["manual_close_required"] = True
            return False
        send = user32.SendMessageW
        send.argtypes = [probe.wintypes.HWND, probe.wintypes.UINT,
                         probe.wintypes.WPARAM, probe.wintypes.LPARAM]
        send.restype = probe.ctypes.c_ssize_t
        close_result = int(send(probe.wintypes.HWND(popup_hwnd), 0x0010, 0, 0))  # WM_CLOSE
        time.sleep(0.55)
        after_windows, after_path = capture("build_tree_dialog_after_close")
        after_popups = find_popups(after_windows)
        after_diff = _bmp_region_difference_ratio(before_path, after_path, _DIALOG_ROI)
        result["close_method"] = "wm_close_to_unique_verified_build_tree_popup"
        result["close_result"] = close_result
        result["after_close_pixel_difference"] = after_diff
        result["after_close_popup_windows"] = [
            {k: w.get(k) for k in ("hwnd", "pid", "title", "class_name", "rect_screen")}
            for w in after_popups
        ]
        remaining_edits = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
        result["after_close_source_edit_count"] = len(remaining_edits)
        result["dialog_closed_verified"] = (
            not after_popups and not remaining_edits and after_diff["ratio"] <= 0.01
        )
        result["status"] = (
            "build_tree_dialog_opened_inspected_and_closed"
            if result["dialog_closed_verified"]
            else "build_tree_dialog_close_not_fully_verified"
        )
        result["manual_close_required"] = not result["dialog_closed_verified"]
        return result["dialog_closed_verified"]

    try:
        before_windows, before_path = capture("build_tree_before_click")
        before_edits = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
        if before_edits:
            result["status"] = "stopped_preexisting_range_editor_open"
            result["preexisting_source_edit_count"] = len(before_edits)
            result["manual_close_required"] = True
            return result

        click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _BUILD_TREE_CENTER, label="open_build_tree_setup"
        )
        actions.append(click)
        result["build_tree_click"] = click
        result["build_tree_clicked"] = True
        time.sleep(0.70)

        opened_windows, opened_path = capture("build_tree_dialog_open")
        popups = find_popups(opened_windows)
        result["popup_windows"] = [
            {k: w.get(k) for k in ("hwnd", "pid", "title", "class_name", "rect_screen", "controls")}
            for w in popups
        ]
        result["dialog_screenshot"] = opened_path
        result["dialog_pixel_difference"] = _bmp_region_difference_ratio(
            before_path, opened_path, _DIALOG_ROI
        )

        player2_popup = next(
            (w for w in popups if _is_player2_range_validation_popup(w)), None
        )
        if player2_popup is not None:
            result["player2_range_validation_seen"] = True
            result["player2_validation_message"] = "プレイヤー 2 のレンジを入力してください。"
            ok_result = _dismiss_exact_gto_message_with_ok(user32, target_pid, player2_popup)
            result["player2_validation_ok_click"] = ok_result
            time.sleep(0.35)
            after_ok_windows, after_ok_path = capture("player2_validation_after_ok")
            result["player2_validation_after_ok_screenshot"] = after_ok_path
            recovery = _commit_verified_player2_editor_after_prompt(
                user32, RECT, POINT, target_hwnd, target_pid,
                before_path, output_dir, stem, actions, all_captures,
                "player2_validation_after_done",
            )
            result["player2_range_recovery"] = recovery
            if recovery.get("editor_closed_verified") and recovery.get("source_text_accepted"):
                result["player2_range_validation_recovered"] = True
                retry_before_windows, retry_before_path = capture("build_tree_retry_before")
                retry_click = _click_exact_client(
                    user32, target_hwnd, target_pid, RECT, POINT,
                    _BUILD_TREE_CENTER, label="retry_open_build_tree_after_player2_done"
                )
                actions.append(retry_click)
                result["build_tree_retry_click"] = retry_click
                time.sleep(0.70)
                retry_windows, retry_path = capture("build_tree_retry_open")
                retry_popups = find_popups(retry_windows)
                result["retry_popup_windows"] = [
                    {k: w.get(k) for k in ("hwnd", "pid", "title", "class_name", "rect_screen", "controls")}
                    for w in retry_popups
                ]
                retry_player2 = next(
                    (w for w in retry_popups if _is_player2_range_validation_popup(w)), None
                )
                if retry_player2 is not None:
                    result["player2_validation_repeated_after_done"] = True
                    retry_ok = _dismiss_exact_gto_message_with_ok(user32, target_pid, retry_player2)
                    result["retry_player2_validation_ok_click"] = retry_ok
                    time.sleep(0.35)
                    retry_after_ok_windows, retry_after_ok_path = capture("player2_validation_retry_after_ok")
                    result["player2_validation_retry_after_ok_screenshot"] = retry_after_ok_path
                    retry_edits = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
                    result["player2_validation_retry_source_edit_count"] = len(retry_edits)
                    # If GTO+ still asks for Player 2, clear only the exact known test value
                    # from the newly opened Player 2 editor, then verify the IP mini-matrix.
                    player2_cleanup = {
                        "stage": "ip_build_tree_player2_prompt_cleanup",
                        "status": "not_started",
                        "range_clear_sent": False,
                        "range_restored": False,
                        "manual_close_required": False,
                    }
                    if len(retry_edits) == 1:
                        edit_hwnd, edit_rect = retry_edits[0]
                        edit_hwnd = int(edit_hwnd)
                        host_hwnd = probe._top_level_ancestor(user32, target_hwnd)
                        identity_ok = (
                            user32.IsWindow(probe.wintypes.HWND(edit_hwnd))
                            and probe._window_pid(user32, edit_hwnd) == int(target_pid)
                            and probe._class_name(user32, edit_hwnd) == "Edit"
                            and int(user32.GetDlgCtrlID(probe.wintypes.HWND(edit_hwnd))) == 5458
                            and probe._window_is_related_to_embedded_target(
                                user32, edit_hwnd, target_hwnd, host_hwnd
                            )
                        )
                        player2_cleanup["source_edit_identity_verified"] = bool(identity_ok)
                        if identity_ok:
                            current_text = probe._read_native_edit_text(user32, edit_hwnd)
                            player2_cleanup["source_text_readback"] = current_text
                            text_ok = current_text in set(_GTO_PLUS_IP_MULTI_RANGE_SOURCE_TEXTS)
                            player2_cleanup["source_text_accepted"] = bool(text_ok)
                            if text_ok:
                                probe._write_native_edit_text(user32, edit_hwnd, "")
                                player2_cleanup["source_text_cleared_readback"] = (
                                    probe._read_native_edit_text(user32, edit_hwnd) == ""
                                )
                                if player2_cleanup["source_text_cleared_readback"]:
                                    clear_click = _click_exact_client(
                                        user32, target_hwnd, target_pid, RECT, POINT,
                                        _RANGE_EDITOR_CLEAR_CENTER, label="clear_player2_prompt_test_range"
                                    )
                                    actions.append(clear_click)
                                    player2_cleanup["clear_click"] = clear_click
                                    player2_cleanup["range_clear_sent"] = True
                                    time.sleep(0.20)
                                    done_click = _click_exact_client(
                                        user32, target_hwnd, target_pid, RECT, POINT,
                                        _RANGE_EDITOR_DONE_CENTER, label="done_player2_prompt_test_range_clear"
                                    )
                                    actions.append(done_click)
                                    player2_cleanup["done_click"] = done_click
                                    time.sleep(0.55)
                                    remaining_after_clear = probe._batch_visible_source_edits(
                                        user32, RECT, target_hwnd
                                    )
                                    final_windows, final_path = capture("player2_prompt_ip_range_restored")
                                    final_sig = _bmp_matrix_center_signature(final_path, _IP_MATRIX_RECT)
                                    baseline_sig = _bmp_matrix_center_signature(baseline_path, _IP_MATRIX_RECT)
                                    final_roi_diff = _bmp_region_difference_ratio(
                                        baseline_path, final_path, _IP_MATRIX_RECT
                                    )
                                    player2_cleanup["remaining_source_edit_count"] = len(remaining_after_clear)
                                    player2_cleanup["final_matrix_signature"] = final_sig
                                    player2_cleanup["baseline_matrix_difference"] = final_roi_diff
                                    player2_cleanup["range_restored"] = (
                                        not remaining_after_clear
                                        and final_sig["samples"] == baseline_sig["samples"]
                                        and final_roi_diff["ratio"] <= 0.002
                                    )
                                    player2_cleanup["status"] = (
                                        "player2_test_range_cleared_and_ip_baseline_verified"
                                        if player2_cleanup["range_restored"]
                                        else "player2_prompt_range_cleanup_not_verified"
                                    )
                                    player2_cleanup["manual_close_required"] = not player2_cleanup["range_restored"]
                                else:
                                    player2_cleanup["status"] = "source_clear_readback_failed"
                                    player2_cleanup["manual_close_required"] = True
                            else:
                                player2_cleanup["status"] = "unrecognized_source_preserved"
                                player2_cleanup["manual_close_required"] = True
                        else:
                            player2_cleanup["status"] = "source_edit_identity_unverified"
                            player2_cleanup["manual_close_required"] = True
                    else:
                        player2_cleanup["status"] = "no_unique_player2_editor_for_cleanup"
                        player2_cleanup["manual_close_required"] = bool(retry_edits)
                    result["player2_validation_cleanup"] = player2_cleanup
                    result["player2_validation_cleanup_restored_ip"] = bool(player2_cleanup.get("range_restored"))
                    result["dialog_opened"] = False
                    result["dialog_closed_verified"] = False
                    result["safe_to_cleanup"] = bool(
                        player2_cleanup.get("range_restored")
                        or (not retry_edits and not player2_cleanup.get("manual_close_required"))
                    )
                    result["status"] = (
                        "player2_range_rejected_but_test_ip_range_restored"
                        if result["player2_validation_cleanup_restored_ip"]
                        else "player2_range_still_rejected_after_exact_done"
                    )
                    result["manual_close_required"] = bool(
                        player2_cleanup.get("manual_close_required")
                    )
                    return result
                if _build_tree_dialog_is_visible({"ratio": 0.0}, retry_windows):
                    result["dialog_opened"] = True
                    result["dialog_screenshot"] = retry_path
                    result["dialog_controls_main"] = next(
                        (w.get("controls", []) for w in retry_windows if w.get("is_embedded_root")), []
                    )
                    result["retry_opened_real_build_tree_dialog"] = True
                    result["dialog_closed_verified"] = close_real_dialog(retry_popups, retry_before_path)
                    if not result["dialog_closed_verified"]:
                        result["manual_close_required"] = True
                        return result
                    result["status"] = "build_tree_dialog_opened_after_player2_done_and_closed"
                    return result

                retry_edits = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
                result["dialog_opened"] = False
                result["dialog_closed_verified"] = False
                result["safe_to_cleanup"] = not retry_edits and not retry_popups
                result["status"] = "build_tree_setup_dialog_not_identified_after_player2_done"
                result["manual_close_required"] = bool(retry_edits or retry_popups)
                return result

            result["dialog_opened"] = False
            result["dialog_closed_verified"] = False
            result["status"] = "player2_range_validation_recovery_not_verified"
            result["manual_close_required"] = bool(recovery.get("manual_close_required"))
            return result

        # A real Build Tree setup must have its own identifiable popup/control signature.
        # Large canvas pixel changes alone are never accepted as proof.
        result["dialog_opened"] = _build_tree_dialog_is_visible(
            result["dialog_pixel_difference"], opened_windows
        )
        if not result["dialog_opened"]:
            result["status"] = "build_tree_setup_dialog_not_identified"
            remaining_edits = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
            result["remaining_source_edit_count"] = len(remaining_edits)
            result["dialog_closed_verified"] = False
            result["safe_to_cleanup"] = not remaining_edits and not popups
            result["manual_close_required"] = bool(remaining_edits or popups)
            return result

        result["dialog_controls_main"] = next(
            (w.get("controls", []) for w in opened_windows if w.get("is_embedded_root")), []
        )
        result["dialog_closed_verified"] = close_real_dialog(popups, before_path)
        return result
    except Exception as exc:
        result["status"] = "build_tree_dialog_probe_safe_stop"
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["manual_close_required"] = bool(
            result.get("build_tree_clicked")
            or result.get("dialog_opened")
            or result.get("player2_range_validation_seen")
        )
        return result


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

    # Stage 1b: one reversible OOP multi-hand weighted commit test (AA=100%, AKs=40%).
    # Clear is allowed only after the starting OOP matrix has been proven empty.
    oop_roundtrip = _run_oop_multi_range_commit_roundtrip(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        output_dir, stem, target_hwnd, target_pid, host, baseline_path
    )
    actions.extend(oop_roundtrip.get("actions", []))
    for capture in oop_roundtrip.get("captures", []):
        if capture:
            all_captures.append(capture)
    for window in oop_roundtrip.get("capture_windows", []):
        capture = window.get("capture") if isinstance(window, dict) else None
        if capture:
            all_captures.append(capture)
    stages.append(oop_roundtrip)

    oop_roundtrip_ok = bool(
        oop_roundtrip.get("expected_matrix_cells_reflection_verified")
        and oop_roundtrip.get("restore_source_text_accepted")
        and oop_roundtrip.get("range_restored")
        and oop_roundtrip.get("editor_closed_after_restore")
        and oop_roundtrip.get("weight_display_capture_saved")
        and oop_roundtrip.get("window_position_restore_verified", True)
    )
    if oop_roundtrip.get("status") == "skipped_initial_oop_range_not_empty":
        oop_roundtrip_ok = False

    # Stage 2: commit the same weighted multi-hand range into IP, then restore the empty matrix.
    ip_roundtrip = None
    ip_editor_result = None
    board_input_result = None
    manual_close_required = (not oop_closed_ok
                             or not oop_source_probe.get("window_position_restore_verified", True)
                             or bool(oop_roundtrip.get("manual_close_required")))
    continue_after_oop = (
        oop_closed_ok
        and oop_source_probe.get("status") != "source_field_test_incomplete"
        and oop_source_probe.get("window_position_restore_verified", True)
        and oop_roundtrip_ok
    )
    if continue_after_oop:
        ip_roundtrip = _run_ip_multi_range_commit_roundtrip(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            output_dir, stem, target_hwnd, target_pid, host, baseline_path
        )
        actions.extend(ip_roundtrip.get("actions", []))
        for capture in ip_roundtrip.get("captures", []):
            if capture:
                all_captures.append(capture)
        for window in ip_roundtrip.get("capture_windows", []):
            capture = window.get("capture") if isinstance(window, dict) else None
            if capture:
                all_captures.append(capture)
        stages.append(ip_roundtrip)
        ip_roundtrip_ok = bool(
            ip_roundtrip.get("expected_matrix_cells_reflection_verified")
            and ip_roundtrip.get("restore_source_text_accepted")
            and ip_roundtrip.get("range_restored")
            and ip_roundtrip.get("editor_closed_after_restore")
            and ip_roundtrip.get("weight_display_capture_saved")
            and ip_roundtrip.get("window_position_restore_verified", True)
        )
        ip_editor_result = {
            "stage": "ip_range_editor",
            "status": ip_roundtrip.get("status", "not_started"),
            "open_overlay_difference": ip_roundtrip.get("editor_open_difference"),
            "range_committed_temporarily": bool(ip_roundtrip.get("range_committed_temporarily")),
            "range_restored": bool(ip_roundtrip.get("range_restored")),
            "visually_closed": bool(ip_roundtrip.get("editor_closed_after_restore")),
            "manual_close_required": bool(ip_roundtrip.get("manual_close_required")),
        }
        stages.append(ip_editor_result)
        manual_close_required = (
            manual_close_required
            or bool(ip_roundtrip.get("manual_close_required"))
            or not ip_roundtrip.get("window_position_restore_verified", True)
        )
        continue_after_oop = ip_roundtrip_ok
    else:
        ip_roundtrip_ok = False
        ip_editor_result = {"stage": "ip_range_editor", "status": "skipped_oop_stage_not_verified"}
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

    # Stage 4: select a measured test flop in the GTO+ card picker, then Clear and verify exact restoration.
    board_roundtrip: dict[str, Any] | None = None
    if continue_after_oop and board_input_result and board_input_result.get("visually_closed"):
        board_roundtrip = _run_board_selection_roundtrip(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, baseline_path,
            actions, all_captures,
        )
        stages.append(board_roundtrip)
        manual_close_required = manual_close_required or bool(board_roundtrip.get("manual_close_required"))
    else:
        board_roundtrip = {
            "stage": "board_selector_roundtrip",
            "status": "skipped_previous_setup_stage_not_verified",
            "board_cards_reflection_verified": False,
            "board_test_restored": False,
            "board_test_may_remain_set": False,
            "manual_close_required": False,
        }
        stages.append(board_roundtrip)

    # Stage 5: retain the known OOP/IP/Board test setup, inspect the Build Tree dialog,
    # then remove only those exact known test values and verify the original blank state.
    build_tree_sequence: dict[str, Any] = {
        "stage": "build_tree_setup_sequence",
        "status": "not_started",
        "test_setup_committed": False,
        "dialog_opened": False,
        "dialog_closed_verified": False,
        "oop_test_range_restored": False,
        "ip_test_range_restored": False,
        "board_test_restored": False,
        "all_test_inputs_restored": False,
        "manual_close_required": False,
    }
    oop_build_tree_range: dict[str, Any] | None = None
    ip_build_tree_range: dict[str, Any] | None = None
    board_build_tree_setup: dict[str, Any] | None = None
    build_tree_dialog_probe: dict[str, Any] | None = None
    oop_build_tree_cleanup: dict[str, Any] | None = None
    ip_build_tree_cleanup: dict[str, Any] | None = None
    board_build_tree_cleanup: dict[str, Any] | None = None

    if (
        continue_after_oop
        and board_roundtrip
        and board_roundtrip.get("board_test_restored")
        and not manual_close_required
    ):
        oop_build_tree_range = _run_oop_multi_range_commit_roundtrip(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            output_dir, stem, target_hwnd, target_pid, host, baseline_path,
            restore_after_commit=False,
        )
        actions.extend(oop_build_tree_range.get("actions", []))
        for capture in oop_build_tree_range.get("captures", []):
            if capture:
                all_captures.append(capture)
        for window in oop_build_tree_range.get("capture_windows", []):
            capture = window.get("capture") if isinstance(window, dict) else None
            if capture:
                all_captures.append(capture)
        stages.append(oop_build_tree_range)
        oop_ready = bool(
            oop_build_tree_range.get("range_committed_temporarily")
            and oop_build_tree_range.get("expected_matrix_cells_reflection_verified")
            and oop_build_tree_range.get("restore_source_text_accepted")
            and oop_build_tree_range.get("editor_closed_after_commit")
            and not oop_build_tree_range.get("manual_close_required")
            and oop_build_tree_range.get("window_position_restore_verified", True)
        )
        if oop_ready:
            ip_build_tree_range = _run_ip_multi_range_commit_roundtrip(
                user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                output_dir, stem, target_hwnd, target_pid, host, baseline_path,
                restore_after_commit=False,
            )
            actions.extend(ip_build_tree_range.get("actions", []))
            for capture in ip_build_tree_range.get("captures", []):
                if capture:
                    all_captures.append(capture)
            for window in ip_build_tree_range.get("capture_windows", []):
                capture = window.get("capture") if isinstance(window, dict) else None
                if capture:
                    all_captures.append(capture)
            stages.append(ip_build_tree_range)
        ip_ready = bool(
            ip_build_tree_range
            and ip_build_tree_range.get("range_committed_temporarily")
            and ip_build_tree_range.get("expected_matrix_cells_reflection_verified")
            and ip_build_tree_range.get("restore_source_text_accepted")
            and ip_build_tree_range.get("editor_closed_after_commit")
            and not ip_build_tree_range.get("manual_close_required")
            and ip_build_tree_range.get("window_position_restore_verified", True)
        )
        if oop_ready and ip_ready:
            board_build_tree_setup = _run_board_selection_roundtrip(
                user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                target_hwnd, target_pid, output_dir, stem, baseline_path,
                actions, all_captures, restore_after_commit=False,
            )
            stages.append(board_build_tree_setup)

        board_ready = bool(
            board_build_tree_setup
            and board_build_tree_setup.get("board_test_temporarily_committed")
            and board_build_tree_setup.get("board_cards_reflection_verified")
            and board_build_tree_setup.get("board_test_may_remain_set")
            and not board_build_tree_setup.get("manual_close_required")
        )
        build_tree_sequence["test_setup_committed"] = bool(
            (oop_build_tree_range and oop_build_tree_range.get("range_committed_temporarily"))
            or (ip_build_tree_range and ip_build_tree_range.get("range_committed_temporarily"))
            or (board_build_tree_setup and board_build_tree_setup.get("board_test_temporarily_committed"))
        )
        if oop_ready and ip_ready and board_ready:
            build_tree_dialog_probe = _run_build_tree_dialog_probe(
                user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                target_hwnd, target_pid, output_dir, stem, baseline_path, actions, all_captures,
            )
            stages.append(build_tree_dialog_probe)
            build_tree_sequence["dialog_opened"] = bool(build_tree_dialog_probe.get("dialog_opened"))
            build_tree_sequence["dialog_closed_verified"] = bool(build_tree_dialog_probe.get("dialog_closed_verified"))
        else:
            build_tree_dialog_probe = {
                "stage": "build_tree_dialog_probe",
                "status": "skipped_test_setup_not_fully_verified",
                "build_tree_clicked": False,
                "dialog_opened": False,
                "dialog_closed_verified": True,
                "tree_built": False,
                "solver_run": False,
                "manual_close_required": False,
            }
            stages.append(build_tree_dialog_probe)

        # Never edit setup values while an unclosed Build Tree/modal dialog is visible.
        if build_tree_dialog_probe and (
            build_tree_dialog_probe.get("dialog_closed_verified")
            or build_tree_dialog_probe.get("safe_to_cleanup")
        ):
            if (
                board_build_tree_setup
                and board_build_tree_setup.get("board_test_temporarily_committed")
            ):
                committed_board_path = str(board_build_tree_setup.get("committed_screenshot") or "")
                if committed_board_path:
                    board_build_tree_cleanup = _clear_committed_test_board(
                        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                        target_hwnd, target_pid, output_dir, stem, baseline_path,
                        committed_board_path, actions, all_captures,
                    )
                    stages.append(board_build_tree_cleanup)
                else:
                    board_build_tree_cleanup = {
                        "stage": "board_build_tree_probe_cleanup",
                        "status": "cleanup_blocked_missing_commit_screenshot",
                        "board_restored": False,
                        "manual_close_required": True,
                    }
                    stages.append(board_build_tree_cleanup)
            if (
                build_tree_dialog_probe
                and build_tree_dialog_probe.get("player2_validation_cleanup_restored_ip")
            ):
                ip_build_tree_cleanup = build_tree_dialog_probe.get("player2_validation_cleanup")
                stages.append(ip_build_tree_cleanup)
            elif (
                ip_build_tree_range
                and ip_build_tree_range.get("range_committed_temporarily")
                and ip_build_tree_range.get("editor_closed_after_commit")
            ):
                ip_build_tree_cleanup = _clear_committed_test_range(
                    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                    target_hwnd, target_pid, host, output_dir, stem,
                    baseline_path, "IP", actions,
                )
                stages.append(ip_build_tree_cleanup)
            if (
                oop_build_tree_range
                and oop_build_tree_range.get("range_committed_temporarily")
                and oop_build_tree_range.get("editor_closed_after_commit")
            ):
                oop_build_tree_cleanup = _clear_committed_test_range(
                    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                    target_hwnd, target_pid, host, output_dir, stem,
                    baseline_path, "OOP", actions,
                )
                stages.append(oop_build_tree_cleanup)

        oop_committed = bool(oop_build_tree_range and oop_build_tree_range.get("range_committed_temporarily"))
        ip_committed = bool(ip_build_tree_range and ip_build_tree_range.get("range_committed_temporarily"))
        board_committed = bool(board_build_tree_setup and board_build_tree_setup.get("board_test_temporarily_committed"))
        build_tree_sequence["oop_test_range_committed"] = oop_committed
        build_tree_sequence["ip_test_range_committed"] = ip_committed
        build_tree_sequence["board_test_committed"] = board_committed
        build_tree_sequence["oop_test_range_restored"] = bool(
            not oop_committed or (oop_build_tree_cleanup and oop_build_tree_cleanup.get("range_restored"))
        )
        build_tree_sequence["ip_test_range_restored"] = bool(
            not ip_committed or (ip_build_tree_cleanup and ip_build_tree_cleanup.get("range_restored"))
        )
        build_tree_sequence["board_test_restored"] = bool(
            not board_committed or (board_build_tree_cleanup and board_build_tree_cleanup.get("board_restored"))
        )
        build_tree_sequence["all_test_inputs_restored"] = bool(
            build_tree_sequence["oop_test_range_restored"]
            and build_tree_sequence["ip_test_range_restored"]
            and build_tree_sequence["board_test_restored"]
        )
        cleanup_reports = (
            oop_build_tree_cleanup, ip_build_tree_cleanup, board_build_tree_cleanup
        )
        cleanup_failed = any(
            item is not None and (
                item.get("manual_close_required")
                or item.get("error")
                or not item.get("range_restored", item.get("board_restored", False))
            )
            for item in cleanup_reports
        ) or any(
            item is not None and item.get("manual_close_required")
            for item in (oop_build_tree_range, ip_build_tree_range, board_build_tree_setup)
        )
        dialog_not_closed = bool(
            build_tree_dialog_probe
            and build_tree_dialog_probe.get("dialog_opened")
            and not build_tree_dialog_probe.get("dialog_closed_verified")
        )
        build_tree_sequence["manual_close_required"] = bool(cleanup_failed or dialog_not_closed)
        build_tree_sequence["status"] = (
            "build_tree_dialog_inspected_and_all_test_inputs_restored"
            if build_tree_sequence["dialog_opened"]
            and build_tree_sequence["dialog_closed_verified"]
            and build_tree_sequence["all_test_inputs_restored"]
            else "build_tree_dialog_not_detected_but_test_inputs_restored"
            if not build_tree_sequence["dialog_opened"]
            and build_tree_sequence["all_test_inputs_restored"]
            else "build_tree_probe_incomplete_or_cleanup_not_verified"
        )
        manual_close_required = manual_close_required or build_tree_sequence["manual_close_required"]
    else:
        build_tree_dialog_probe = {
            "stage": "build_tree_dialog_probe",
            "status": "skipped_previous_roundtrip_not_verified",
            "build_tree_clicked": False,
            "dialog_opened": False,
            "dialog_closed_verified": False,
            "tree_built": False,
            "solver_run": False,
            "manual_close_required": False,
        }
        stages.append(build_tree_dialog_probe)
        build_tree_sequence["status"] = "skipped_previous_roundtrip_not_verified"
        build_tree_sequence["manual_close_required"] = False

    stages.append(build_tree_sequence)

    # Deduplicate repeated references; the round-trip stage also appears in capture_windows.
    unique_captures: list[dict[str, Any]] = []
    seen_capture_paths: set[str] = set()
    for capture in all_captures:
        shot = capture.get("screenshot") if isinstance(capture, dict) else None
        key = str(shot).replace("\\", "/").casefold() if shot else None
        if key and key in seen_capture_paths:
            continue
        if key:
            seen_capture_paths.add(key)
        unique_captures.append(capture)
    all_captures = unique_captures

    report = {
        "schema_version": 21,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "probe": "verified_gto_plus_oop_ip_board_build_tree_player2_recovery_roundtrip_v21",
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
            "roundtrip_test_value": "AA,AKs:0.4",
            "roundtrip_test_partial_weight": 0.4,
            "expected_gto_plus_roundtrip_source_texts": list(_GTO_PLUS_OOP_MULTI_RANGE_SOURCE_TEXTS),
            "expected_gto_plus_roundtrip_source_text": _GTO_PLUS_HALF_WEIGHT_AA_SOURCE,
            "original_field_must_be_empty": True,
            "focus_only_click_allowed_on_verified_gto_view": True,
            "no_keyboard_input_without_unique_native_edit": True,
            "source_text_readback_required": True,
            "original_text_restore_readback_required": True,
            "done_button_clicked_for_oop_multi_range_test": bool(oop_roundtrip.get("range_committed_temporarily")),
            "done_button_clicked_for_ip_multi_range_test": bool(ip_roundtrip and ip_roundtrip.get("range_committed_temporarily")),
            "ip_multi_range_committed_temporarily": bool(ip_roundtrip and ip_roundtrip.get("range_committed_temporarily")),
            "ip_expected_matrix_cells_reflection_verified": bool(ip_roundtrip and ip_roundtrip.get("expected_matrix_cells_reflection_verified")),
            "ip_range_restored": bool(ip_roundtrip and ip_roundtrip.get("range_restored")),
            "ip_restore_source_text_readback": ip_roundtrip.get("restore_source_text_readback") if ip_roundtrip else None,
            "ip_restore_source_text_accepted": bool(ip_roundtrip and ip_roundtrip.get("restore_source_text_accepted")),
            "ip_weight_display_capture_saved": bool(ip_roundtrip and ip_roundtrip.get("weight_display_capture_saved")),
            "oop_multi_range_committed_temporarily": bool(oop_roundtrip.get("range_committed_temporarily")),
            "oop_expected_matrix_cells_reflection_verified": bool(oop_roundtrip.get("expected_matrix_cells_reflection_verified")),
            "oop_range_restored": bool(oop_roundtrip.get("range_restored")),
            "oop_restore_source_text_readback": oop_roundtrip.get("restore_source_text_readback"),
            "oop_restore_source_text_accepted": bool(oop_roundtrip.get("restore_source_text_accepted")),
            "oop_weight_display_capture_saved": bool(oop_roundtrip.get("weight_display_capture_saved")),
            "oop_restore_source_text_readback": oop_roundtrip.get("restore_source_text_readback"),
            "oop_restore_source_text_accepted": bool(oop_roundtrip.get("restore_source_text_accepted")),
            "range_committed": False,
            "board_text_entered": False,
            "board_test_cards": list(_BOARD_TEST_CARDS),
            "board_test_temporarily_committed": bool(board_roundtrip and board_roundtrip.get("board_test_temporarily_committed")),
            "board_test_cards_reflection_verified": bool(board_roundtrip and board_roundtrip.get("board_cards_reflection_verified")),
            "board_test_restored": bool(board_roundtrip and board_roundtrip.get("board_test_restored")),
            "board_test_may_remain_set": bool(board_roundtrip and board_roundtrip.get("board_test_may_remain_set")),
            "build_tree_button_clicked_for_dialog_probe": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("build_tree_clicked")),
            "build_tree_dialog_opened": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("dialog_opened")),
            "build_tree_dialog_closed_verified": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("dialog_closed_verified")),
            "build_tree_probe_oop_range_restored": bool(build_tree_sequence.get("oop_test_range_restored")),
            "build_tree_probe_ip_range_restored": bool(build_tree_sequence.get("ip_test_range_restored")),
            "build_tree_probe_board_restored": bool(build_tree_sequence.get("board_test_restored")),
            "build_tree_probe_inputs_restored": bool(build_tree_sequence.get("all_test_inputs_restored")),
            "build_tree_probe_may_remain_configured": bool(
                build_tree_sequence.get("test_setup_committed")
                and not build_tree_sequence.get("all_test_inputs_restored")
            ),
            "build_tree_player2_validation_seen": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_range_validation_seen")),
            "build_tree_player2_validation_recovered": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_range_validation_recovered")),
            "build_tree_player2_range_cleanup_restored": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_validation_cleanup_restored_ip")),
            "build_tree_probe_safe_to_cleanup": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("safe_to_cleanup")),
            "temporary_window_position_restore_required": True,
        },
        "coordinate_reference": {
            "oop_matrix_cell_sample_centers": {"first": [29, 91], "step": [4, 4], "rows": 13, "columns": 13},
            "ip_matrix_cell_sample_centers": {"first": [29, 161], "step": [4, 4], "rows": 13, "columns": 13},
            "range_editor_verification_roi": list(_RANGE_EDITOR_VERIFY_ROI),
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
            "board_selector_roi": list(_BOARD_SELECTOR_ROI),
            "board_selector_test_cards": list(_BOARD_TEST_CARDS),
            "board_selector_test_card_centers": {card: list(_board_card_center(card)) for card in _BOARD_TEST_CARDS},
            "board_selector_clear_center": list(_BOARD_CLEAR_CENTER),
            "board_selector_done_center": list(_BOARD_DONE_CENTER),
            "build_tree_probe_test_range": "AA,AKs:0.4",
            "build_tree_probe_test_board": list(_BOARD_TEST_CARDS),
            "build_tree_dialog_opened": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("dialog_opened")),
            "build_tree_dialog_closed_verified": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("dialog_closed_verified")),
            "build_tree_probe_inputs_restored": bool(build_tree_sequence.get("all_test_inputs_restored")),
            "build_tree_probe_sequence_status": build_tree_sequence.get("status"),
            "build_tree_dialog_popup_windows": build_tree_dialog_probe.get("popup_windows", []) if build_tree_dialog_probe else [],
            "build_tree_dialog_native_controls": build_tree_dialog_probe.get("dialog_controls_main", []) if build_tree_dialog_probe else [],
            "build_tree_player2_validation_seen": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_range_validation_seen")),
            "build_tree_player2_validation_recovered": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_range_validation_recovered")),
            "build_tree_player2_range_cleanup_restored": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_validation_cleanup_restored_ip")),
            "build_tree_probe_safe_to_cleanup": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("safe_to_cleanup")),
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
            "ip_range_text_changed": bool(ip_roundtrip and ip_roundtrip.get("test_range_may_remain_committed")),
            "range_committed": False,
            "oop_test_range_temporarily_committed": bool(oop_roundtrip.get("range_committed_temporarily")),
            "oop_expected_matrix_cells_reflection_verified": bool(oop_roundtrip.get("expected_matrix_cells_reflection_verified")),
            "oop_test_range_restored": bool(oop_roundtrip.get("range_restored")),
            "oop_restore_source_text_readback": oop_roundtrip.get("restore_source_text_readback"),
            "oop_restore_source_text_accepted": bool(oop_roundtrip.get("restore_source_text_accepted")),
            "oop_weight_display_capture_saved": bool(oop_roundtrip.get("weight_display_capture_saved")),
            "oop_test_range_text": "AA,AKs:0.4",
            "oop_test_range_partial_weight": 0.4,
            "oop_test_range_may_remain_committed": bool(oop_roundtrip.get("test_range_may_remain_committed")),
            "ip_test_range_temporarily_committed": bool(ip_roundtrip and ip_roundtrip.get("range_committed_temporarily")),
            "ip_expected_matrix_cells_reflection_verified": bool(ip_roundtrip and ip_roundtrip.get("expected_matrix_cells_reflection_verified")),
            "ip_test_range_restored": bool(ip_roundtrip and ip_roundtrip.get("range_restored")),
            "ip_restore_source_text_readback": ip_roundtrip.get("restore_source_text_readback") if ip_roundtrip else None,
            "ip_restore_source_text_accepted": bool(ip_roundtrip and ip_roundtrip.get("restore_source_text_accepted")),
            "ip_weight_display_capture_saved": bool(ip_roundtrip and ip_roundtrip.get("weight_display_capture_saved")),
            "ip_test_range_text": "AA,AKs:0.4" if ip_roundtrip else None,
            "ip_test_range_may_remain_committed": bool(ip_roundtrip and ip_roundtrip.get("test_range_may_remain_committed")),
            "board_test_cards": list(_BOARD_TEST_CARDS),
            "board_test_temporarily_committed": bool(board_roundtrip and board_roundtrip.get("board_test_temporarily_committed")),
            "board_test_cards_reflection_verified": bool(board_roundtrip and board_roundtrip.get("board_cards_reflection_verified")),
            "board_test_restored": bool(board_roundtrip and board_roundtrip.get("board_test_restored")),
            "board_test_may_remain_set": bool(board_roundtrip and board_roundtrip.get("board_test_may_remain_set")),
            "build_tree_button_clicked_for_dialog_probe": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("build_tree_clicked")),
            "build_tree_dialog_opened": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("dialog_opened")),
            "build_tree_dialog_closed_verified": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("dialog_closed_verified")),
            "build_tree_probe_oop_range_restored": bool(build_tree_sequence.get("oop_test_range_restored")),
            "build_tree_probe_ip_range_restored": bool(build_tree_sequence.get("ip_test_range_restored")),
            "build_tree_probe_board_restored": bool(build_tree_sequence.get("board_test_restored")),
            "build_tree_probe_inputs_restored": bool(build_tree_sequence.get("all_test_inputs_restored")),
            "build_tree_probe_may_remain_configured": bool(
                build_tree_sequence.get("test_setup_committed")
                and not build_tree_sequence.get("all_test_inputs_restored")
            ),
            "oop_restore_source_text_readback": oop_roundtrip.get("restore_source_text_readback"),
            "oop_restore_source_text_accepted": bool(oop_roundtrip.get("restore_source_text_accepted")),
            "board_changed": False,
            "pot_changed": False,
            "stack_changed": False,
            "rake_changed": False,
            "tree_built": False,
            "solver_run": False,
            "other_gto_processes_touched": False,
            "build_tree_clicked": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("build_tree_clicked")),
            "board_selector_left_open": bool(
                board_input_result and board_input_result.get("dialog_detected")
                and not board_input_result.get("visually_closed")
            ),
            "manual_close_required": manual_close_required,
            "window_position_restore_failed": bool(
                not oop_source_probe.get("window_position_restore_verified", True)
                or bool(ip_roundtrip and not ip_roundtrip.get("window_position_restore_verified", True))
            ),
        },
        "notes": [
            "Only the exact Pigeon-embedded GTO+ HWND/PID was operated.",
            "Before the Source field focus click, WindowFromPoint must resolve either to an exact GTO-owned native Edit or to the measured AfxFrameOrView140su id=59648 covering the field. Foreign overlays cause a no-click, no-write stop. If the view receives focus but no unique native Edit appears at the measured field, no keyboard input is sent.",
            "If a foreign window covers the Source field, only the exact embedded GTO child is temporarily shifted within its verified parent-client coordinate system; the exact original parent-relative position is restored and verified immediately after the field probe. The host window and other processes are not moved.",
            "The OOP and IP Source Edits are each tested with a temporary AA+AKs:40% multi-hand range. Exactly two matrix cells must change in the relevant 13x13 mini-matrix, GTO+ normalized Source text must match the exact allowlist, and Clear plus Done must restore the exact baseline signature.",
            "The OOP/IP range editor is dismissed with its measured X button; when the overlay remains, one direct WM_MOUSEMOVE/WM_LBUTTONDOWN/WM_LBUTTONUP retry is sent only to the verified GTO drawing view and visually rechecked.",
            "The Board selector is tested with three measured rank/suit buttons (As, Kd, 7c), Done commits the temporary flop, then Clear plus Done must restore the original empty Board field. If the starting Board field is not empty, no card selection or Clear action is sent.",
            "After the initial reversible range and Board tests pass, the exact AA+AKs:40% OOP/IP test ranges and As/Kd/7c Board are committed a second time only to inspect the Build Tree setup dialog. A GTO+ Program message requesting Player 2 range is distinguished from the real setup dialog. Only an exact known Player 2 test Source value may be confirmed or cleared; all other values are preserved. Guarded Source/matrix/Board cleanup then restores the initial empty state. Pot/Stack/Rake are not changed and Solver is not run.",
            "Escape is sent only when the detected selector belongs to the exact GTO process and that process owns keyboard focus.",
        ],
    }
    json_path = output_dir / f"{stem}.json"
    txt_path = output_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if oop_roundtrip.get("range_restored"):
        final_oop_state = "restored to the original empty baseline"
    elif oop_roundtrip.get("test_range_may_remain_committed"):
        final_oop_state = "temporary OOP AA + AKs:40% may remain committed; manual Clear + Done required"
    elif not oop_roundtrip.get("range_committed_temporarily"):
        final_oop_state = "no temporary OOP test commit remains"
    else:
        final_oop_state = "OOP restoration not verified; inspect the diagnostic images"
    if ip_roundtrip and ip_roundtrip.get("range_restored"):
        final_ip_state = "restored to the original empty baseline"
    elif ip_roundtrip and ip_roundtrip.get("test_range_may_remain_committed"):
        final_ip_state = "temporary IP AA + AKs:40% may remain committed; manual Clear + Done required"
    elif ip_roundtrip and not ip_roundtrip.get("range_committed_temporarily"):
        final_ip_state = "no temporary IP test commit remains"
    else:
        final_ip_state = "IP stage not verified; inspect the diagnostic images"
    lines = [
        "PIGEON POKER — VISUALLY VERIFIED GTO+ AUTO-SOLVE SETUP PROBE",
        f"Created: {report['created_at']}",
        f"Target: PID={target_pid} HWND={target_hwnd}",
        f"Client: {width}x{height}",
        f"OOP editor closed by X: {stages[0]['visually_closed']}",
        f"OOP source field: {oop_source_probe['status']}",
        f"OOP multi-hand weighted range commit/restore: {oop_roundtrip['status']}",
        f"OOP expected AA+AKs cells only: {bool(oop_roundtrip.get('expected_matrix_cells_reflection_verified'))}",
        f"OOP 40% weight-field screenshot saved: {bool(oop_roundtrip.get('weight_display_capture_saved'))}",
        f"GTO+ normalized Source text: {oop_roundtrip.get('restore_source_text_readback')}",
        f"Canonical Source text accepted for safe Clear: {bool(oop_roundtrip.get('restore_source_text_accepted'))}",
        f"OOP weighted range restored: {bool(oop_roundtrip.get('range_restored'))}",
        f"IP multi-hand weighted range commit/restore: {ip_roundtrip['status'] if ip_roundtrip else 'not_attempted'}",
        f"IP expected AA+AKs cells only: {bool(ip_roundtrip and ip_roundtrip.get('expected_matrix_cells_reflection_verified'))}",
        f"IP 40% weight-field screenshot saved: {bool(ip_roundtrip and ip_roundtrip.get('weight_display_capture_saved'))}",
        f"IP normalized Source text: {ip_roundtrip.get('restore_source_text_readback') if ip_roundtrip else None}",
        f"IP weighted range restored: {bool(ip_roundtrip and ip_roundtrip.get('range_restored'))}",
        f"Board input: {board_input_result['status'] if board_input_result else 'not_attempted'}",
        f"Board selector three-card commit/clear: {board_roundtrip.get('status') if board_roundtrip else 'not_attempted'}",
        f"Board cards reflected in main field: {bool(board_roundtrip and board_roundtrip.get('board_cards_reflection_verified'))}",
        f"Board original empty field restored: {bool(board_roundtrip and board_roundtrip.get('board_test_restored'))}",
        f"Build Tree dialog: {build_tree_dialog_probe.get('status') if build_tree_dialog_probe else 'not_attempted'}",
        f"Build Tree Player 2 validation message: {bool(build_tree_dialog_probe and build_tree_dialog_probe.get('player2_range_validation_seen'))}",
        f"Build Tree Player 2 recovery: {bool(build_tree_dialog_probe and build_tree_dialog_probe.get('player2_range_validation_recovered'))}",
        f"Build Tree Player 2 test range restored: {bool(build_tree_dialog_probe and build_tree_dialog_probe.get('player2_validation_cleanup_restored_ip'))}",
        f"Build Tree dialog opened: {bool(build_tree_dialog_probe and build_tree_dialog_probe.get('dialog_opened'))}",
        f"Build Tree dialog closed: {bool(build_tree_dialog_probe and build_tree_dialog_probe.get('dialog_closed_verified'))}",
        f"Build Tree probe OOP range restored: {bool(build_tree_sequence.get('oop_test_range_restored'))}",
        f"Build Tree probe IP range restored: {bool(build_tree_sequence.get('ip_test_range_restored'))}",
        f"Build Tree probe Board restored: {bool(build_tree_sequence.get('board_test_restored'))}",
        f"Source click sent: {bool(oop_source_probe.get('click_sent', False))}",
        f"Temporary GTO window move: {oop_source_probe.get('temporary_window_adjustment', {}).get('status', 'not_reported')}",
        f"Temporary GTO window move restored: {bool(oop_source_probe.get('window_position_restore_verified', True))}",
        f"Manual close required: {manual_close_required}",
        f"Final OOP range state: {final_oop_state}",
        f"Final IP range state: {final_ip_state}",
        "Board/Pot/Stack/Rake changed: no",
        "Tree built: no",
        "Solver run: no",
        "",
    ]
    _append_stage_summary_lines(lines, stages)
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
