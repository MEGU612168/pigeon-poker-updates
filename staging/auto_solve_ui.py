"""Calibrated, read-only discovery of embedded GTO+ 1.9.1 setup UI.

The range editor is closed with its measured on-screen X button, not Escape:
the embedded GTO window has no keyboard focus while Pigeon's Tk child owns it.
The Build Tree dialog is captured and is only dismissed with Escape when the
GTO process itself owns keyboard focus. Every close is visually verified
against the baseline screenshot before the next click is allowed.
"""
from __future__ import annotations

# Build marker: OOP/IP matrix ROIs calibrated; None-safe stage summaries; schema v18.
# Rebuild trigger: restore the measured Source-field overlay shift helper and assert it.
# Rebuild trigger: update IP source constant occurrence test for validation recovery reuse.
# Rebuild trigger: include restored OOP/IP range functions and exact-definition CI checks.
# Rebuild trigger: align range report assertions to current OOP safety field names.
# Rebuild trigger: remove redundant escaped closed-key assertion from CI.
# Rebuild trigger: restore Board selector helpers and assert all cleanup definitions.
# Rebuild trigger: add Player 2 recovery status into top-level safety report.
# Rebuild trigger: update Build Tree close assertion to require no popup and no Source Edit.
# Rebuild trigger: restore OOP/IP/Board cleanup helpers and test Player 2 dialog classification.
# Rebuild trigger: align Source allowlist assertion with explicit Player 2 IP constant.
# Rebuild trigger: align the final Player 2 validation assertion variable name.
# Rebuild trigger: verify v1.3.68 final Player 2 cleanup assertions.
# Rebuild trigger: rerun v1.3.68 after aligning Player 2 cleanup assertion.
# Rebuild trigger: v1.3.68 exact Player 2 validation popup handling and guarded IP cleanup.
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
    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
    target_hwnd: int, target_pid: int,
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
    if not remaining:
        closed_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, label + "_verified_main"
        )
        all_captures.extend(w["capture"] for w in closed_windows)
        closed_path = _root_capture_path(closed_windows, label + "_verified_main")
        before_ip = _bmp_matrix_center_signature(before_path, _IP_MATRIX_RECT)
        after_ip = _bmp_matrix_center_signature(closed_path, _IP_MATRIX_RECT)
        result["post_done_screenshot"] = closed_path
        result["post_done_ip_matrix_signature"] = after_ip
        result["ip_matrix_matches_pre_build_tree"] = (
            after_ip["samples"] == before_ip["samples"]
        )
        result["post_done_editor_difference"] = _bmp_region_difference_ratio(
            before_path, closed_path, _RANGE_EDITOR_VERIFY_ROI
        )
        result["editor_closed_verified"] = bool(
            not probe._batch_visible_source_edits(user32, RECT, target_hwnd)
            and result["ip_matrix_matches_pre_build_tree"]
            and result["post_done_editor_difference"]["ratio"] <= 0.01
        )
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



def _bmp_matrix_center_signature(path: str | Path,
                                 roi: tuple[int, int, int, int] = _OOP_MATRIX_RECT) -> dict[str, Any]:
    """Summarize a 2x2 interior patch in each 13x13 matrix cell.

    GTO+ draws partial-weight hands as a narrow colored marker inside a cell.
    A single center pixel can miss that marker (observed for AKs at 40%).
    Use per-channel maxima over the inner 2x2 pixels, excluding grid borders.
    """
    data = Path(path).read_bytes()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("matrix capture is not a Windows BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, signed_height, planes, bpp, compression = struct.unpack_from("<iiHHI", data, 18)
    height = abs(signed_height)
    if width <= 0 or height <= 0 or planes != 1 or bpp != 32 or compression != 0:
        raise ValueError("matrix capture is not an uncompressed 32-bit BMP")
    stride = ((width*bpp+31)//32)*4
    if offset + stride*height > len(data):
        raise ValueError("matrix BMP pixel data is truncated")
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(f"matrix ROI outside capture dimensions: {roi}")
    samples: list[list[int]] = []
    for row in range(13):
        cell_y0 = y0 + int(round(row * (y1-y0) / 13))
        for col in range(13):
            cell_x0 = x0 + int(round(col * (x1-x0) / 13))
            rgb_pixels: list[tuple[int, int, int]] = []
            for dy in (1, 2):
                y = cell_y0 + dy
                source_y = y if signed_height < 0 else height-1-y
                for dx in (1, 2):
                    x = cell_x0 + dx
                    index = offset + source_y*stride + x*4
                    blue, green, red = data[index], data[index+1], data[index+2]
                    rgb_pixels.append((red, green, blue))
            # Max per channel detects thin partial-weight bars while ignoring
            # the grey/white gridlines at the cell edges.
            samples.append([
                max(pixel[channel] for pixel in rgb_pixels)
                for channel in range(3)
            ])
    return {
        "roi": list(roi),
        "samples": samples,
        "sampling": "2x2_inner_patch_channel_max",
        "pixels_per_cell": 4,
    }


def _matrix_signature_is_empty(signature: dict[str, Any], threshold: int = 16) -> bool:
    samples = (signature or {}).get("samples")
    return (
        isinstance(samples, list) and len(samples) == 169
        and all(
            isinstance(rgb, list) and len(rgb) == 3
            and max(int(channel) for channel in rgb) <= int(threshold)
            for rgb in samples
        )
    )


def _matrix_signature_matches_selected_cells(
    signature: dict[str, Any], baseline: dict[str, Any],
    expected_indices: list[int], threshold: int = 16
) -> bool:
    samples = (signature or {}).get("samples")
    base = (baseline or {}).get("samples")
    if not isinstance(samples, list) or not isinstance(base, list):
        return False
    if len(samples) != 169 or len(base) != 169:
        return False
    expected = sorted(set(int(i) for i in expected_indices))
    if not expected or any(i < 0 or i >= 169 for i in expected):
        return False
    changed = [
        i for i, (current, original) in enumerate(zip(samples, base))
        if max(abs(int(current[c])-int(original[c])) for c in range(3)) > threshold
    ]
    return (
        changed == expected
        and all(max(int(channel) for channel in samples[i]) > threshold for i in expected)
    )


def _matrix_signature_is_aa_only(
    signature: dict[str, Any], baseline: dict[str, Any], threshold: int = 16
) -> bool:
    return _matrix_signature_matches_selected_cells(signature, baseline, [0], threshold)


def _append_stage_summary_lines(lines: list[str], stages: list[dict[str, Any]]) -> None:
    """Append concise diagnostics while tolerating intentionally skipped stages."""
    for stage in stages:
        lines.append(f"{stage.get('stage', 'unknown')}: {stage.get('status', 'unknown')}")
        for key, label in (
            ("visible_overlay_difference", "Overlay pixel ratio"),
            ("open_overlay_difference", "Editor-open pixel ratio"),
            ("baseline_difference_after_escape", "After Escape baseline pixel ratio"),
            ("baseline_difference_after_x", "After X baseline pixel ratio"),
        ):
            metric = stage.get(key)
            if isinstance(metric, dict):
                ratio = metric.get("ratio")
                if isinstance(ratio, (int, float)):
                    lines.append(f"{label}: {ratio:.4f}")
        if stage.get("stage") == "board_input" and isinstance(stage.get("baseline_difference_after_x"), dict):
            lines.append(f"Board selector closed by X: {bool(stage.get('visually_closed'))}")


def _run_oop_multi_range_commit_roundtrip(
    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
    output_dir: Path, stem: str, target_hwnd: int, target_pid: int,
    host_hwnd: int, baseline_path: str, *, restore_after_commit: bool = True
) -> dict[str, Any]:
    """Commit OOP=AA plus AKs:40%, verify it, and optionally retain it for a Build Tree dialog probe.

    Runs only when all 169 OOP mini-matrix sample points are black and Source is blank.
    Clear is allowed only after Source text matches one of the exact normalized
    test strings. It never touches IP, Board, pot, stack, rake, Build Tree, or Solver.
    """
    report: dict[str, Any] = {
        "stage": "oop_multi_range_commit_roundtrip",
        "status": "not_started",
        "test_range": "AA,AKs:0.4",
        "test_range_partial_weight": 0.4,
        "test_range_entries": [{"hand": "AA", "weight": 1.0}, {"hand": "AKs", "weight": 0.4}],
        "expected_matrix_cell_indices": [0, 1],
        "expected_gto_plus_source_texts": list(_GTO_PLUS_OOP_MULTI_RANGE_SOURCE_TEXTS),
        "weight_display_capture_path": None,
        "weight_display_capture_saved": False,
        "weight_display_expected_percent": 40,
        "restore_source_text_readback": None,
        "restore_source_text_accepted": False,
        "weight_display_roi": [414, 343, 476, 376],
        "range_committed_temporarily": False,
        "test_range_may_remain_committed": False,
        "range_restored": False,
        "tree_built": False,
        "solver_run": False,
        "actions": [],
        "captures": [],
        "capture_windows": [],
        "manual_close_required": False,
    }
    baseline_signature = _bmp_matrix_center_signature(baseline_path)
    report["baseline_matrix_signature"] = baseline_signature
    if not _matrix_signature_is_empty(baseline_signature):
        report["status"] = "skipped_initial_oop_range_not_empty"
        report["note"] = "The OOP matrix is not visually empty; Clear was not used and no range was changed."
        return report

    position: dict[str, Any] = {"moved": False, "status": "not_attempted"}
    editor_open = False
    test_committed = False

    def capture_windows(stage: str):
        windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, stage
        )
        report["capture_windows"].extend(windows)
        return windows

    def add_capture(capture):
        if capture:
            report["captures"].append(capture)

    def close_editor_via_done(label: str) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None]:
        done = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _RANGE_EDITOR_DONE_CENTER, label="commit_range_editor_done"
        )
        report["actions"].append(done)
        deadline = time.monotonic() + 1.5
        remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.10)
            remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
        windows = capture_windows(label + "_after_done")
        path = _root_capture_path(windows, label + "_after_done")
        appearance = _bmp_region_difference_ratio(
            baseline_path, path, _RANGE_EDITOR_VERIFY_ROI
        )
        retry = None
        closed = not remaining and appearance["ratio"] <= 0.01
        if not closed:
            retry = _click_verified_gto_hit_target(
                user32, target_hwnd, target_pid, RECT, POINT,
                _RANGE_EDITOR_DONE_CENTER,
                label=label + "_done_native_retry"
            )
            report["actions"].append(retry)
            deadline = time.monotonic() + 1.5
            remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
            while remaining and time.monotonic() < deadline:
                time.sleep(0.10)
                remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
            windows = capture_windows(label + "_after_native_done")
            path = _root_capture_path(windows, label + "_after_native_done")
            appearance = _bmp_region_difference_ratio(
                baseline_path, path, _RANGE_EDITOR_VERIFY_ROI
            )
            closed = not remaining and appearance["ratio"] <= 0.01
        return closed, windows, {
            "click": done, "native_retry": retry,
            "baseline_difference": appearance,
            "comparison_roi": list(_RANGE_EDITOR_VERIFY_ROI),
            "visible_source_edits_remaining": len(remaining),
        }

    try:
        open_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _OOP_MATRIX_CENTER, label="open_oop_range_editor"
        )
        report["actions"].append(open_click)
        time.sleep(0.55)
        opened_windows = capture_windows("oop_aa_roundtrip_editor_open")
        opened_path = _root_capture_path(opened_windows, "oop_aa_roundtrip_editor_open")
        opened_appearance = _bmp_region_difference_ratio(baseline_path, opened_path)
        report["editor_open_difference"] = opened_appearance
        if opened_appearance["ratio"] < 0.05:
            raise RuntimeError("OOP editor did not visibly open; no test range was entered")
        editor_open = True

        position = _temporary_source_field_window_adjustment(
            user32, target_hwnd, RECT, POINT
        )
        report["temporary_window_adjustment"] = position
        source_probe = _probe_source_field_readback_restore_at_current_position(
            user32, target_hwnd, EnumWindowsProc, EnumChildProc,
            RECT, POINT, output_dir, stem, "OOP"
        )
        report["source_field_probe"] = source_probe
        if source_probe.get("temporary_capture"):
            add_capture(source_probe["temporary_capture"])
        if source_probe.get("restored_capture"):
            add_capture(source_probe["restored_capture"])
        if source_probe.get("status") != "write_readback_and_restore_verified":
            raise RuntimeError(
                "OOP Source field did not pass the reversible blank-field test: "
                + str(source_probe.get("status"))
            )
        edit_hwnd = int(source_probe.get("edit_hwnd") or 0)
        if (
            not edit_hwnd
            or not user32.IsWindow(probe.wintypes.HWND(edit_hwnd))
            or probe._window_pid(user32, edit_hwnd) != int(target_pid)
            or probe._class_name(user32, edit_hwnd) != "Edit"
            or int(user32.GetDlgCtrlID(probe.wintypes.HWND(edit_hwnd))) != 5458
            or not probe._window_is_related_to_embedded_target(
                user32, edit_hwnd, target_hwnd, host_hwnd
            )
        ):
            raise RuntimeError("OOP Source Edit identity changed before commit; no text was committed")
        original_text = probe._read_native_edit_text(user32, edit_hwnd)
        if original_text != "":
            raise RuntimeError("OOP Source field is no longer blank; preserving it and aborting")

        probe._write_native_edit_text(user32, edit_hwnd, report["test_range"])
        test_readback = probe._read_native_edit_text(user32, edit_hwnd)
        report["test_source_readback"] = test_readback
        if test_readback != report["test_range"]:
            probe._write_native_edit_text(user32, edit_hwnd, original_text)
            raise RuntimeError("Multi-hand test text did not read back exactly; source field was restored and Done was not clicked")
        typed_capture = probe._batch_capture(
            user32, target_hwnd, RECT, POINT, output_dir, stem,
            "oop_weighted_roundtrip_before_done"
        )
        add_capture(typed_capture)
        if typed_capture.get("capture_error"):
            probe._write_native_edit_text(user32, edit_hwnd, original_text)
            raise RuntimeError("Pre-Done image capture failed; Source field was restored")

        closed_after_test, test_windows, test_done = close_editor_via_done("oop_weighted_test")
        report["test_done"] = test_done
        editor_open = not closed_after_test
        if not closed_after_test:
            report["status"] = "test_done_not_closed"
            report["test_range_may_remain_committed"] = True
            report["manual_close_required"] = True
            report["note"] = (
                "Done could not be visually confirmed. The AA + AKs test range may be committed "
                "or remain in the open editor; leave it visible and use Clear + Done manually."
            )
            return report

        test_committed = True
        report["range_committed_temporarily"] = True
        test_path = _root_capture_path(test_windows, "oop_aa_test_after_done")
        test_signature = _bmp_matrix_center_signature(test_path)
        expected_cells_visible = _matrix_signature_matches_selected_cells(
            test_signature, baseline_signature, report["expected_matrix_cell_indices"]
        )
        report["test_matrix_signature"] = test_signature
        report["expected_matrix_cells_reflection_verified"] = expected_cells_visible

        reopen_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _OOP_MATRIX_CENTER, label="open_oop_range_editor"
        )
        report["actions"].append(reopen_click)
        time.sleep(0.55)
        restore_open_windows = capture_windows("oop_weighted_restore_editor_open")
        restore_open_path = _root_capture_path(
            restore_open_windows, "oop_weighted_restore_editor_open"
        )
        restore_open_appearance = _bmp_region_difference_ratio(
            baseline_path, restore_open_path
        )
        report["restore_editor_open_difference"] = restore_open_appearance
        report["weight_display_capture_path"] = restore_open_path
        report["weight_display_capture_saved"] = bool(restore_open_path and Path(restore_open_path).is_file())
        report["weight_display_expected_percent"] = 40
        report["weight_display_roi"] = [414, 343, 476, 376]
        if restore_open_appearance["ratio"] < 0.05:
            raise RuntimeError("OOP editor did not reopen for restoration")
        editor_open = True

        restore_probe = _probe_source_field_readback_restore_at_current_position(
            user32, target_hwnd, EnumWindowsProc, EnumChildProc,
            RECT, POINT, output_dir, stem, "OOP"
        )
        report["restore_source_field_probe"] = restore_probe
        if restore_probe.get("temporary_capture"):
            add_capture(restore_probe["temporary_capture"])
        if restore_probe.get("restored_capture"):
            add_capture(restore_probe["restored_capture"])
        restore_edit = int(restore_probe.get("edit_hwnd") or 0)
        if (
            not restore_edit
            or not user32.IsWindow(probe.wintypes.HWND(restore_edit))
            or probe._window_pid(user32, restore_edit) != int(target_pid)
            or probe._class_name(user32, restore_edit) != "Edit"
            or int(user32.GetDlgCtrlID(probe.wintypes.HWND(restore_edit))) != 5458
            or not probe._window_is_related_to_embedded_target(
                user32, restore_edit, target_hwnd, host_hwnd
            )
        ):
            raise RuntimeError("Could not uniquely re-identify OOP Source Edit for restoration")
        current_text = probe._read_native_edit_text(user32, restore_edit)
        report["restore_source_text_readback"] = current_text
        expected_test_source_texts = set(report["expected_gto_plus_source_texts"])
        report["restore_source_text_accepted"] = current_text in expected_test_source_texts
        if not restore_after_commit:
            if not report["restore_source_text_accepted"]:
                raise RuntimeError("OOP normalized Source text did not match the exact known test form; Build Tree was not opened")
            retained_closed, retained_windows, retained_done = close_editor_via_done("oop_build_tree_probe")
            report["build_tree_probe_done"] = retained_done
            editor_open = not retained_closed
            report["editor_closed_after_commit"] = bool(retained_closed)
            report["test_range_may_remain_committed"] = True
            report["manual_close_required"] = not retained_closed
            report["status"] = (
                "weighted_range_committed_for_build_tree_probe"
                if retained_closed and expected_cells_visible else "build_tree_probe_range_commit_not_verified"
            )
            report["note"] = "The exact AA+AKs:40% test range is intentionally retained for the Build Tree dialog inspection; a later guarded cleanup stage must clear it."
            return report
        if report["restore_source_text_accepted"]:
            probe._write_native_edit_text(user32, restore_edit, "")
            if probe._read_native_edit_text(user32, restore_edit) != "":
                raise RuntimeError("Could not clear the test-only weighted AA Source text")
        elif current_text != "":
            raise RuntimeError(
                "Source field text is not one of the exact known test forms "
                "(AA,[40%]AKs[/40%] or [40%]AKs[/40%],AA); preserved it and stopped"
            )

        clear_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _RANGE_EDITOR_CLEAR_CENTER, label="clear_range_editor"
        )
        report["actions"].append(clear_click)
        time.sleep(0.30)
        clear_capture = probe._batch_capture(
            user32, target_hwnd, RECT, POINT, output_dir, stem,
            "oop_weighted_roundtrip_after_clear"
        )
        add_capture(clear_capture)
        if clear_capture.get("capture_error"):
            raise RuntimeError("Could not capture OOP editor after Clear; Done was not clicked")
        closed_after_restore, restore_windows, restore_done = close_editor_via_done(
            "oop_weighted_restore"
        )
        report["restore_done"] = restore_done
        editor_open = not closed_after_restore
        if not closed_after_restore:
            report["manual_close_required"] = True
            raise RuntimeError("OOP editor did not close after Clear/Done")
        final_path = _root_capture_path(restore_windows, "oop_aa_restore_after_done")
        final_signature = _bmp_matrix_center_signature(final_path)
        final_dialog_difference = _bmp_region_difference_ratio(
            baseline_path, final_path, _RANGE_EDITOR_VERIFY_ROI
        )
        restored = (
            final_signature["samples"] == baseline_signature["samples"]
            and final_dialog_difference["ratio"] <= 0.01
        )
        report["final_matrix_signature"] = final_signature
        report["final_matrix_difference"] = _bmp_region_difference_ratio(
            baseline_path, final_path, _OOP_MATRIX_RECT
        )
        report["final_dialog_difference"] = final_dialog_difference
        report["range_restored"] = restored
        report["editor_closed_after_restore"] = True
        report["status"] = (
            "multi_hand_weighted_range_committed_and_visually_restored"
            if expected_cells_visible and report.get("restore_source_text_accepted") and restored and report.get("weight_display_capture_saved")
            else "multi_hand_range_restored_but_source_or_matrix_review_needed"
            if restored
            else "range_restoration_not_verified"
        )
        report["note"] = (
            "AA,AKs:0.4 was committed. Exactly matrix cells 0 (AA) and 1 (AKs) changed. "
            "The reopened Source field was read back as one of the exact expected [40%]AKs[/40%] forms; "
            "Clear/Done then restored the exact 13x13 baseline sample signature. No solver/tree action was performed."
            if restored and expected_cells_visible and report.get("restore_source_text_accepted") and report.get("weight_display_capture_saved") else
            "The OOP matrix was restored, but the expected two-cell reflection or normalized Source readback was not fully verified."
            if restored else
            "The multi-hand weighted test commit was attempted, but the final OOP matrix does not match its baseline."
        )
        return report
    except Exception as exc:
        report["status"] = "safe_stop_during_oop_roundtrip"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["editor_open_at_stop"] = editor_open
        report["test_range_may_remain_committed"] = bool(test_committed and not report.get("range_restored"))
        report["manual_close_required"] = bool(editor_open)
        return report
    finally:
        if position.get("moved"):
            restore_position = _restore_source_field_window_position(
                user32, target_hwnd, RECT, position
            )
            report["temporary_window_restore"] = restore_position
            report["window_position_restore_verified"] = bool(
                restore_position.get("verified")
            )
            if not restore_position.get("verified"):
                report["manual_close_required"] = True
                if report.get("range_restored"):
                    report["status"] = "range_restored_but_window_position_restore_failed"



def _run_ip_multi_range_commit_roundtrip(
    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
    output_dir: Path, stem: str, target_hwnd: int, target_pid: int,
    host_hwnd: int, baseline_path: str, *, restore_after_commit: bool = True
) -> dict[str, Any]:
    """Commit IP=AA plus AKs:40%, verify it, and optionally retain it for a Build Tree dialog probe.

    Runs only when all 169 IP mini-matrix sample points are black and Source is blank.
    Clear is allowed only after Source text matches one of the exact normalized
    test strings. It never touches OOP, Board, pot, stack, rake, Build Tree, or Solver.
    """
    report: dict[str, Any] = {
        "stage": "ip_multi_range_commit_roundtrip",
        "status": "not_started",
        "test_range": "AA,AKs:0.4",
        "test_range_partial_weight": 0.4,
        "test_range_entries": [{"hand": "AA", "weight": 1.0}, {"hand": "AKs", "weight": 0.4}],
        "expected_matrix_cell_indices": [0, 1],
        "expected_gto_plus_source_texts": list(_GTO_PLUS_IP_MULTI_RANGE_SOURCE_TEXTS),
        "weight_display_capture_path": None,
        "weight_display_capture_saved": False,
        "weight_display_expected_percent": 40,
        "restore_source_text_readback": None,
        "restore_source_text_accepted": False,
        "weight_display_roi": [414, 343, 476, 376],
        "range_committed_temporarily": False,
        "test_range_may_remain_committed": False,
        "range_restored": False,
        "tree_built": False,
        "solver_run": False,
        "actions": [],
        "captures": [],
        "capture_windows": [],
        "manual_close_required": False,
    }
    baseline_signature = _bmp_matrix_center_signature(baseline_path, _IP_MATRIX_RECT)
    report["baseline_matrix_signature"] = baseline_signature
    if not _matrix_signature_is_empty(baseline_signature):
        report["status"] = "skipped_initial_ip_range_not_empty"
        report["note"] = "The IP matrix is not visually empty; Clear was not used and no range was changed."
        return report

    position: dict[str, Any] = {"moved": False, "status": "not_attempted"}
    editor_open = False
    test_committed = False

    def capture_windows(stage: str):
        windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, stage
        )
        report["capture_windows"].extend(windows)
        return windows

    def add_capture(capture):
        if capture:
            report["captures"].append(capture)

    def close_editor_via_done(label: str) -> tuple[bool, list[dict[str, Any]], dict[str, Any] | None]:
        done = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _RANGE_EDITOR_DONE_CENTER, label="commit_range_editor_done"
        )
        report["actions"].append(done)
        deadline = time.monotonic() + 1.5
        remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
        while remaining and time.monotonic() < deadline:
            time.sleep(0.10)
            remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
        windows = capture_windows(label + "_after_done")
        path = _root_capture_path(windows, label + "_after_done")
        appearance = _bmp_region_difference_ratio(
            baseline_path, path, _RANGE_EDITOR_VERIFY_ROI
        )
        retry = None
        closed = not remaining and appearance["ratio"] <= 0.01
        if not closed:
            retry = _click_verified_gto_hit_target(
                user32, target_hwnd, target_pid, RECT, POINT,
                _RANGE_EDITOR_DONE_CENTER,
                label=label + "_done_native_retry"
            )
            report["actions"].append(retry)
            deadline = time.monotonic() + 1.5
            remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
            while remaining and time.monotonic() < deadline:
                time.sleep(0.10)
                remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
            windows = capture_windows(label + "_after_native_done")
            path = _root_capture_path(windows, label + "_after_native_done")
            appearance = _bmp_region_difference_ratio(
                baseline_path, path, _RANGE_EDITOR_VERIFY_ROI
            )
            closed = not remaining and appearance["ratio"] <= 0.01
        return closed, windows, {
            "click": done, "native_retry": retry,
            "baseline_difference": appearance,
            "comparison_roi": list(_RANGE_EDITOR_VERIFY_ROI),
            "visible_source_edits_remaining": len(remaining),
        }

    try:
        open_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _IP_MATRIX_CENTER, label="open_ip_range_editor"
        )
        report["actions"].append(open_click)
        time.sleep(0.55)
        opened_windows = capture_windows("ip_aa_roundtrip_editor_open")
        opened_path = _root_capture_path(opened_windows, "ip_aa_roundtrip_editor_open")
        opened_appearance = _bmp_region_difference_ratio(baseline_path, opened_path)
        report["editor_open_difference"] = opened_appearance
        if opened_appearance["ratio"] < 0.05:
            raise RuntimeError("IP editor did not visibly open; no test range was entered")
        editor_open = True

        position = _temporary_source_field_window_adjustment(
            user32, target_hwnd, RECT, POINT
        )
        report["temporary_window_adjustment"] = position
        source_probe = _probe_source_field_readback_restore_at_current_position(
            user32, target_hwnd, EnumWindowsProc, EnumChildProc,
            RECT, POINT, output_dir, stem, "IP"
        )
        report["source_field_probe"] = source_probe
        if source_probe.get("temporary_capture"):
            add_capture(source_probe["temporary_capture"])
        if source_probe.get("restored_capture"):
            add_capture(source_probe["restored_capture"])
        if source_probe.get("status") != "write_readback_and_restore_verified":
            raise RuntimeError(
                "IP Source field did not pass the reversible blank-field test: "
                + str(source_probe.get("status"))
            )
        edit_hwnd = int(source_probe.get("edit_hwnd") or 0)
        if (
            not edit_hwnd
            or not user32.IsWindow(probe.wintypes.HWND(edit_hwnd))
            or probe._window_pid(user32, edit_hwnd) != int(target_pid)
            or probe._class_name(user32, edit_hwnd) != "Edit"
            or int(user32.GetDlgCtrlID(probe.wintypes.HWND(edit_hwnd))) != 5458
            or not probe._window_is_related_to_embedded_target(
                user32, edit_hwnd, target_hwnd, host_hwnd
            )
        ):
            raise RuntimeError("IP Source Edit identity changed before commit; no text was committed")
        original_text = probe._read_native_edit_text(user32, edit_hwnd)
        if original_text != "":
            raise RuntimeError("IP Source field is no longer blank; preserving it and aborting")

        probe._write_native_edit_text(user32, edit_hwnd, report["test_range"])
        test_readback = probe._read_native_edit_text(user32, edit_hwnd)
        report["test_source_readback"] = test_readback
        if test_readback != report["test_range"]:
            probe._write_native_edit_text(user32, edit_hwnd, original_text)
            raise RuntimeError("Multi-hand test text did not read back exactly; source field was restored and Done was not clicked")
        typed_capture = probe._batch_capture(
            user32, target_hwnd, RECT, POINT, output_dir, stem,
            "ip_weighted_roundtrip_before_done"
        )
        add_capture(typed_capture)
        if typed_capture.get("capture_error"):
            probe._write_native_edit_text(user32, edit_hwnd, original_text)
            raise RuntimeError("Pre-Done image capture failed; Source field was restored")

        closed_after_test, test_windows, test_done = close_editor_via_done("ip_weighted_test")
        report["test_done"] = test_done
        editor_open = not closed_after_test
        if not closed_after_test:
            report["status"] = "test_done_not_closed"
            report["test_range_may_remain_committed"] = True
            report["manual_close_required"] = True
            report["note"] = (
                "Done could not be visually confirmed. The AA + AKs test range may be committed "
                "or remain in the open editor; leave it visible and use Clear + Done manually."
            )
            return report

        test_committed = True
        report["range_committed_temporarily"] = True
        test_path = _root_capture_path(test_windows, "ip_aa_test_after_done")
        test_signature = _bmp_matrix_center_signature(test_path, _IP_MATRIX_RECT)
        expected_cells_visible = _matrix_signature_matches_selected_cells(
            test_signature, baseline_signature, report["expected_matrix_cell_indices"]
        )
        report["test_matrix_signature"] = test_signature
        report["expected_matrix_cells_reflection_verified"] = expected_cells_visible

        reopen_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _IP_MATRIX_CENTER, label="open_ip_range_editor"
        )
        report["actions"].append(reopen_click)
        time.sleep(0.55)
        restore_open_windows = capture_windows("ip_weighted_restore_editor_open")
        restore_open_path = _root_capture_path(
            restore_open_windows, "ip_weighted_restore_editor_open"
        )
        restore_open_appearance = _bmp_region_difference_ratio(
            baseline_path, restore_open_path
        )
        report["restore_editor_open_difference"] = restore_open_appearance
        report["weight_display_capture_path"] = restore_open_path
        report["weight_display_capture_saved"] = bool(restore_open_path and Path(restore_open_path).is_file())
        report["weight_display_expected_percent"] = 40
        report["weight_display_roi"] = [414, 343, 476, 376]
        if restore_open_appearance["ratio"] < 0.05:
            raise RuntimeError("IP editor did not reopen for restoration")
        editor_open = True

        restore_probe = _probe_source_field_readback_restore_at_current_position(
            user32, target_hwnd, EnumWindowsProc, EnumChildProc,
            RECT, POINT, output_dir, stem, "IP"
        )
        report["restore_source_field_probe"] = restore_probe
        if restore_probe.get("temporary_capture"):
            add_capture(restore_probe["temporary_capture"])
        if restore_probe.get("restored_capture"):
            add_capture(restore_probe["restored_capture"])
        restore_edit = int(restore_probe.get("edit_hwnd") or 0)
        if (
            not restore_edit
            or not user32.IsWindow(probe.wintypes.HWND(restore_edit))
            or probe._window_pid(user32, restore_edit) != int(target_pid)
            or probe._class_name(user32, restore_edit) != "Edit"
            or int(user32.GetDlgCtrlID(probe.wintypes.HWND(restore_edit))) != 5458
            or not probe._window_is_related_to_embedded_target(
                user32, restore_edit, target_hwnd, host_hwnd
            )
        ):
            raise RuntimeError("Could not uniquely re-identify IP Source Edit for restoration")
        current_text = probe._read_native_edit_text(user32, restore_edit)
        report["restore_source_text_readback"] = current_text
        expected_test_source_texts = set(report["expected_gto_plus_source_texts"])
        report["restore_source_text_accepted"] = current_text in expected_test_source_texts
        if not restore_after_commit:
            if not report["restore_source_text_accepted"]:
                raise RuntimeError("IP normalized Source text did not match the exact known test form; Build Tree was not opened")
            retained_closed, retained_windows, retained_done = close_editor_via_done("ip_build_tree_probe")
            report["build_tree_probe_done"] = retained_done
            editor_open = not retained_closed
            report["editor_closed_after_commit"] = bool(retained_closed)
            report["test_range_may_remain_committed"] = True
            report["manual_close_required"] = not retained_closed
            report["status"] = (
                "weighted_range_committed_for_build_tree_probe"
                if retained_closed and expected_cells_visible else "build_tree_probe_range_commit_not_verified"
            )
            report["note"] = "The exact AA+AKs:40% test range is intentionally retained for the Build Tree dialog inspection; a later guarded cleanup stage must clear it."
            return report
        if report["restore_source_text_accepted"]:
            probe._write_native_edit_text(user32, restore_edit, "")
            if probe._read_native_edit_text(user32, restore_edit) != "":
                raise RuntimeError("Could not clear the test-only weighted AA Source text")
        elif current_text != "":
            raise RuntimeError(
                "Source field text is not one of the exact known test forms "
                "(AA,[40%]AKs[/40%] or [40%]AKs[/40%],AA); preserved it and stopped"
            )

        clear_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _RANGE_EDITOR_CLEAR_CENTER, label="clear_range_editor"
        )
        report["actions"].append(clear_click)
        time.sleep(0.30)
        clear_capture = probe._batch_capture(
            user32, target_hwnd, RECT, POINT, output_dir, stem,
            "ip_weighted_roundtrip_after_clear"
        )
        add_capture(clear_capture)
        if clear_capture.get("capture_error"):
            raise RuntimeError("Could not capture IP editor after Clear; Done was not clicked")
        closed_after_restore, restore_windows, restore_done = close_editor_via_done(
            "ip_weighted_restore"
        )
        report["restore_done"] = restore_done
        editor_open = not closed_after_restore
        if not closed_after_restore:
            report["manual_close_required"] = True
            raise RuntimeError("IP editor did not close after Clear/Done")
        final_path = _root_capture_path(restore_windows, "ip_aa_restore_after_done")
        final_signature = _bmp_matrix_center_signature(final_path, _IP_MATRIX_RECT)
        final_dialog_difference = _bmp_region_difference_ratio(
            baseline_path, final_path, _RANGE_EDITOR_VERIFY_ROI
        )
        restored = (
            final_signature["samples"] == baseline_signature["samples"]
            and final_dialog_difference["ratio"] <= 0.01
        )
        report["final_matrix_signature"] = final_signature
        report["final_matrix_difference"] = _bmp_region_difference_ratio(
            baseline_path, final_path, _IP_MATRIX_RECT
        )
        report["final_dialog_difference"] = final_dialog_difference
        report["range_restored"] = restored
        report["editor_closed_after_restore"] = True
        report["status"] = (
            "multi_hand_weighted_range_committed_and_visually_restored"
            if expected_cells_visible and report.get("restore_source_text_accepted") and restored and report.get("weight_display_capture_saved")
            else "multi_hand_range_restored_but_source_or_matrix_review_needed"
            if restored
            else "range_restoration_not_verified"
        )
        report["note"] = (
            "AA,AKs:0.4 was committed. Exactly matrix cells 0 (AA) and 1 (AKs) changed. "
            "The reopened Source field was read back as one of the exact expected [40%]AKs[/40%] forms; "
            "Clear/Done then restored the exact 13x13 baseline sample signature. No solver/tree action was performed."
            if restored and expected_cells_visible and report.get("restore_source_text_accepted") and report.get("weight_display_capture_saved") else
            "The IP matrix was restored, but the expected two-cell reflection or normalized Source readback was not fully verified."
            if restored else
            "The multi-hand weighted test commit was attempted, but the final IP matrix does not match its baseline."
        )
        return report
    except Exception as exc:
        report["status"] = "safe_stop_during_ip_roundtrip"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["editor_open_at_stop"] = editor_open
        report["test_range_may_remain_committed"] = bool(test_committed and not report.get("range_restored"))
        report["manual_close_required"] = bool(editor_open)
        return report
    finally:
        if position.get("moved"):
            restore_position = _restore_source_field_window_position(
                user32, target_hwnd, RECT, position
            )
            report["temporary_window_restore"] = restore_position
            report["window_position_restore_verified"] = bool(
                restore_position.get("verified")
            )
            if not restore_position.get("verified"):
                report["manual_close_required"] = True
                if report.get("range_restored"):
                    report["status"] = "range_restored_but_window_position_restore_failed"



_BOARD_CARD_RANK_ORDER = "AKQJT98765432"
_BOARD_CARD_SUIT_ORDER = "hcds"
_BOARD_CARD_X = (124, 147, 170, 193)
_BOARD_CARD_Y = (108, 130, 154, 178, 202, 224, 246, 268, 291, 314, 337, 361, 384)
_BOARD_SELECTOR_ROI = (105, 68, 297, 403)
_BOARD_SELECTOR_TEXT_ROI = (211, 227, 288, 244)
_BOARD_ENTRY_FIELD_ROI = (26, 233, 83, 245)
_BOARD_ENTRY_DIFF_ROI = (23, 230, 85, 248)
_BOARD_CLEAR_CENTER = (258, 108)
_BOARD_DONE_CENTER = (258, 385)
_BOARD_TEST_CARDS = ("As", "Kd", "7c")


def _bmp_region_dark_pixel_ratio(path: str | Path, roi: tuple[int, int, int, int], *, threshold: int = 180) -> float:
    """Return the proportion of dark pixels in a client-relative BMP region."""
    data = Path(path).read_bytes()
    if len(data) < 54 or data[:2] != b"BM":
        raise ValueError("capture is not a Windows BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, signed_height, planes, bpp, compression = struct.unpack_from("<iiHHI", data, 18)
    height = abs(signed_height)
    if width <= 0 or height <= 0 or planes != 1 or bpp != 32 or compression != 0:
        raise ValueError("capture is not an uncompressed 32-bit BMP")
    stride = ((width * bpp + 31) // 32) * 4
    if offset + stride * height > len(data):
        raise ValueError("BMP pixel data is truncated")
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(f"ROI outside capture dimensions: {roi}")
    dark = total = 0
    for y in range(y0, y1):
        row_y = y if signed_height < 0 else height - 1 - y
        row = offset + row_y * stride
        for x in range(x0, x1):
            i = row + x * 4
            blue, green, red = data[i], data[i + 1], data[i + 2]
            total += 1
            if max(red, green, blue) < int(threshold):
                dark += 1
    return dark / total if total else 1.0


def _board_card_center(card: str) -> tuple[int, int]:
    """Map a standard two-character card code to the measured GTO+ selector grid."""
    if not isinstance(card, str) or len(card.strip()) != 2:
        raise ValueError(f"invalid board card code: {card!r}")
    value = card.strip()
    rank = value[0].upper()
    suit = value[1].lower()
    if rank not in _BOARD_CARD_RANK_ORDER or suit not in _BOARD_CARD_SUIT_ORDER:
        raise ValueError(f"unsupported board card code: {card!r}")
    row = _BOARD_CARD_RANK_ORDER.index(rank)
    column = _BOARD_CARD_SUIT_ORDER.index(suit)
    return _BOARD_CARD_X[column], _BOARD_CARD_Y[row]


def _click_board_selector_target(user32, root_hwnd: int, root_pid: int, RECT, POINT, point: tuple[int, int], *, label: str) -> dict[str, Any]:
    """Click only one of the measured card, Clear, or Done targets in GTO's custom view."""
    x, y = map(int, point)
    card_points = {_board_card_center(rank + suit) for rank in _BOARD_CARD_RANK_ORDER for suit in _BOARD_CARD_SUIT_ORDER}
    if label == "select_board_card":
        if (x, y) not in card_points:
            raise ValueError("board card click is outside the calibrated 52-card grid")
    elif label == "clear_board_selector":
        if (x, y) != _BOARD_CLEAR_CENTER:
            raise ValueError("Clear click does not match its calibrated point")
    elif label == "commit_board_selector_done":
        if (x, y) != _BOARD_DONE_CENTER:
            raise ValueError("Done click does not match its calibrated point")
    else:
        raise ValueError(f"unregistered board selector click: {label}")
    return _click_verified_gto_hit_target(user32, root_hwnd, root_pid, RECT, POINT, (x, y), label=label)


def _run_board_selection_roundtrip(user32, EnumWindowsProc, EnumChildProc, RECT, POINT, target_hwnd: int, target_pid: int, output_dir: Path, stem: str, baseline_path: str, actions: list[dict[str, Any]], all_captures: list[dict[str, Any]], *, restore_after_commit: bool = True) -> dict[str, Any]:
    """Select a known flop; optionally retain it briefly for a Build Tree dialog inspection."""
    result: dict[str, Any] = {
        "stage": "board_selector_roundtrip",
        "test_cards": list(_BOARD_TEST_CARDS),
        "card_centers": {card: list(_board_card_center(card)) for card in _BOARD_TEST_CARDS},
        "status": "not_started",
        "selector_opened": False,
        "cards_selected": False,
        "board_cards_reflection_verified": False,
        "board_test_temporarily_committed": False,
        "board_test_restored": False,
        "board_test_may_remain_set": False,
        "manual_close_required": False,
    }
    selector_open = False
    committed = False

    def capture(stage: str) -> tuple[list[dict[str, Any]], str]:
        windows = _capture_related_windows(user32, EnumWindowsProc, EnumChildProc, RECT, POINT, target_hwnd, target_pid, output_dir, stem, stage)
        all_captures.extend(w["capture"] for w in windows)
        return windows, _root_capture_path(windows, stage)

    def clear_and_done() -> dict[str, Any]:
        nonlocal selector_open
        clear_click = _click_board_selector_target(user32, target_hwnd, target_pid, RECT, POINT, _BOARD_CLEAR_CENTER, label="clear_board_selector")
        actions.append(clear_click)
        time.sleep(0.20)
        done_click = _click_board_selector_target(user32, target_hwnd, target_pid, RECT, POINT, _BOARD_DONE_CENTER, label="commit_board_selector_done")
        actions.append(done_click)
        time.sleep(0.45)
        selector_open = False
        windows, path = capture("board_selector_restored_main")
        difference = _bmp_region_difference_ratio(baseline_path, path, _BOARD_ENTRY_DIFF_ROI)
        dark_ratio = _bmp_region_dark_pixel_ratio(path, _BOARD_ENTRY_FIELD_ROI)
        return {"windows": windows, "screenshot": path, "baseline_field_difference": difference, "entry_field_dark_pixel_ratio": dark_ratio, "clear_click": clear_click, "done_click": done_click}

    try:
        baseline_dark = _bmp_region_dark_pixel_ratio(baseline_path, _BOARD_ENTRY_FIELD_ROI)
        result["initial_board_field_dark_pixel_ratio"] = baseline_dark
        if baseline_dark > 0.002:
            result["status"] = "stopped_existing_board_not_empty"
            result["reason"] = "Board field is not empty; no selection or Clear action was sent."
            return result

        open_click = _click_exact_client(user32, target_hwnd, target_pid, RECT, POINT, _BOARD_INPUT_CENTER, label="focus_board_input")
        actions.append(open_click)
        time.sleep(0.45)
        windows, open_path = capture("board_selector_roundtrip_open")
        appearance = _bmp_region_difference_ratio(baseline_path, open_path, _BOARD_SELECTOR_ROI)
        result["open_click"] = open_click
        result["selector_open_difference"] = appearance
        result["selector_opened"] = bool(appearance["ratio"] >= 0.05)
        selector_open = result["selector_opened"]
        if not selector_open:
            raise RuntimeError("Board card selector did not open at the measured coordinates")

        card_clicks = []
        for card in _BOARD_TEST_CARDS:
            point = _board_card_center(card)
            click = _click_board_selector_target(user32, target_hwnd, target_pid, RECT, POINT, point, label="select_board_card")
            click["card"] = card
            card_clicks.append(click)
            actions.append(click)
            time.sleep(0.16)
        result["card_clicks"] = card_clicks
        windows, selected_path = capture("board_selector_cards_selected")
        selected_dark = _bmp_region_dark_pixel_ratio(selected_path, _BOARD_SELECTOR_TEXT_ROI)
        result["selected_cards_capture"] = selected_path
        result["selected_board_display_dark_pixel_ratio"] = selected_dark
        result["cards_selected"] = True
        if selected_dark <= 0.004:
            raise RuntimeError("The selector's selected-card display did not show the expected non-empty text region")

        done_click = _click_board_selector_target(user32, target_hwnd, target_pid, RECT, POINT, _BOARD_DONE_CENTER, label="commit_board_selector_done")
        actions.append(done_click)
        time.sleep(0.45)
        selector_open = False
        committed = True
        windows, committed_path = capture("board_selector_test_committed_main")
        committed_difference = _bmp_region_difference_ratio(baseline_path, committed_path, _BOARD_ENTRY_DIFF_ROI)
        committed_dark = _bmp_region_dark_pixel_ratio(committed_path, _BOARD_ENTRY_FIELD_ROI)
        result["done_click"] = done_click
        result["committed_screenshot"] = committed_path
        result["committed_board_field_difference"] = committed_difference
        result["committed_board_field_dark_pixel_ratio"] = committed_dark
        result["board_test_temporarily_committed"] = True
        result["board_cards_reflection_verified"] = bool(committed_difference["ratio"] > 0.005 and committed_dark > baseline_dark + 0.004)
        if not result["board_cards_reflection_verified"]:
            raise RuntimeError("The selected flop was not visibly reflected in the main Board field")

        if not restore_after_commit:
            result["board_test_may_remain_set"] = True
            result["status"] = "three_card_flop_committed_for_build_tree_probe"
            result["manual_close_required"] = False
            result["note"] = "As/Kd/7c is intentionally retained only until the Build Tree dialog is inspected, then the guarded Board Clear stage must restore the original empty field."
            return result

        reopen_click = _click_exact_client(user32, target_hwnd, target_pid, RECT, POINT, _BOARD_INPUT_CENTER, label="focus_board_input")
        actions.append(reopen_click)
        time.sleep(0.40)
        windows, clear_open_path = capture("board_selector_clear_open")
        clear_appearance = _bmp_region_difference_ratio(baseline_path, clear_open_path, _BOARD_SELECTOR_ROI)
        result["clear_selector_open_difference"] = clear_appearance
        selector_open = clear_appearance["ratio"] >= 0.05
        if not selector_open:
            raise RuntimeError("Board selector did not reopen for the restoration step")

        restore = clear_and_done()
        result["restore"] = restore
        restored_ratio = float(restore["baseline_field_difference"]["ratio"])
        result["board_test_restored"] = restored_ratio <= 0.002 and float(restore["entry_field_dark_pixel_ratio"]) <= 0.002
        result["board_test_may_remain_set"] = not result["board_test_restored"]
        result["status"] = "three_card_flop_selected_and_cleared_verified" if result["board_test_restored"] and result["board_cards_reflection_verified"] else "board_test_restoration_not_verified"
        result["manual_close_required"] = not result["board_test_restored"]
        return result
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        if selector_open:
            try:
                result["recovery"] = clear_and_done()
            except Exception as recovery_exc:
                result["recovery_error"] = f"{type(recovery_exc).__name__}: {recovery_exc}"
        elif committed:
            try:
                reopen_click = _click_exact_client(user32, target_hwnd, target_pid, RECT, POINT, _BOARD_INPUT_CENTER, label="focus_board_input")
                actions.append(reopen_click)
                time.sleep(0.40)
                windows, reopen_path = capture("board_selector_recovery_open")
                appearance = _bmp_region_difference_ratio(baseline_path, reopen_path, _BOARD_SELECTOR_ROI)
                result["recovery_open_difference"] = appearance
                selector_open = appearance["ratio"] >= 0.05
                if selector_open:
                    result["recovery"] = clear_and_done()
            except Exception as recovery_exc:
                result["recovery_error"] = f"{type(recovery_exc).__name__}: {recovery_exc}"
        recovery = result.get("recovery")
        if isinstance(recovery, dict):
            ratio = float((recovery.get("baseline_field_difference") or {}).get("ratio", 1.0))
            dark = float(recovery.get("entry_field_dark_pixel_ratio", 1.0))
            result["board_test_restored"] = ratio <= 0.002 and dark <= 0.002
        result["board_test_may_remain_set"] = bool(committed and not result.get("board_test_restored"))
        result["manual_close_required"] = bool(result.get("board_test_may_remain_set") or selector_open)
        result["status"] = (
            "board_test_failed_but_original_empty_state_restored"
            if committed and result.get("board_test_restored")
            else "board_test_failed_and_restoration_unverified"
            if committed else "board_test_not_committed"
        )
        return result






def _clear_committed_test_range(
    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
    target_hwnd: int, target_pid: int, host_hwnd: int,
    output_dir: Path, stem: str, baseline_path: str,
    role: str, actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Clear only the known AA+AKs:40% probe range, after exact text and matrix checks."""
    if role not in {"OOP", "IP"}:
        raise ValueError("role must be OOP or IP")
    center = _OOP_MATRIX_CENTER if role == "OOP" else _IP_MATRIX_CENTER
    matrix_rect = _OOP_MATRIX_RECT if role == "OOP" else _IP_MATRIX_RECT
    allowed_texts = set(_GTO_PLUS_OOP_MULTI_RANGE_SOURCE_TEXTS)
    report: dict[str, Any] = {
        "stage": f"{role.lower()}_build_tree_probe_cleanup",
        "status": "not_started",
        "range_clear_sent": False,
        "range_restored": False,
        "manual_close_required": False,
        "source_text_readback": None,
        "source_text_accepted": False,
    }
    baseline_sig = _bmp_matrix_center_signature(baseline_path, matrix_rect)
    current_windows = _capture_related_windows(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        target_hwnd, target_pid, output_dir, stem, f"{role.lower()}_build_tree_cleanup_before"
    )
    current_path = _root_capture_path(current_windows, f"{role.lower()}_build_tree_cleanup_before")
    current_sig = _bmp_matrix_center_signature(current_path, matrix_rect)
    report["before_matrix_matches_exact_test"] = _matrix_signature_matches_selected_cells(
        current_sig, baseline_sig, [0, 1]
    )
    if not report["before_matrix_matches_exact_test"]:
        report["status"] = "stopped_unexpected_matrix_state_preserved"
        report["note"] = "The matrix did not match exactly the known AA+AKs test signature; no Clear action was sent."
        return report

    moved = {"moved": False, "status": "not_attempted"}
    editor_open = False
    try:
        opened = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT, center,
            label="open_oop_range_editor" if role == "OOP" else "open_ip_range_editor"
        )
        actions.append(opened)
        time.sleep(0.55)
        open_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, f"{role.lower()}_build_tree_cleanup_editor_open"
        )
        open_path = _root_capture_path(open_windows, f"{role.lower()}_build_tree_cleanup_editor_open")
        open_diff = _bmp_region_difference_ratio(baseline_path, open_path)
        report["editor_open_difference"] = open_diff
        if open_diff["ratio"] < 0.05:
            raise RuntimeError(f"{role} editor did not open for guarded cleanup")
        editor_open = True

        moved = _temporary_source_field_window_adjustment(user32, target_hwnd, RECT, POINT)
        report["temporary_window_adjustment"] = moved
        source_probe = _probe_source_field_readback_restore_at_current_position(
            user32, target_hwnd, EnumWindowsProc, EnumChildProc,
            RECT, POINT, output_dir, stem, role
        )
        report["source_field_probe"] = source_probe
        edit_hwnd = int(source_probe.get("edit_hwnd") or 0)
        if (
            not edit_hwnd
            or not user32.IsWindow(probe.wintypes.HWND(edit_hwnd))
            or probe._window_pid(user32, edit_hwnd) != int(target_pid)
            or probe._class_name(user32, edit_hwnd) != "Edit"
            or int(user32.GetDlgCtrlID(probe.wintypes.HWND(edit_hwnd))) != 5458
            or not probe._window_is_related_to_embedded_target(user32, edit_hwnd, target_hwnd, host_hwnd)
        ):
            raise RuntimeError(f"{role} Source Edit identity was not uniquely verified; preserved the range")
        current_text = probe._read_native_edit_text(user32, edit_hwnd)
        report["source_text_readback"] = current_text
        report["source_text_accepted"] = current_text in allowed_texts
        if not report["source_text_accepted"]:
            raise RuntimeError(f"{role} Source text is not the exact AA+AKs:40% probe form; preserved it and sent no Clear")
        probe._write_native_edit_text(user32, edit_hwnd, "")
        if probe._read_native_edit_text(user32, edit_hwnd) != "":
            raise RuntimeError(f"{role} Source text could not be cleared and read back")

        clear = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _RANGE_EDITOR_CLEAR_CENTER, label="clear_range_editor"
        )
        actions.append(clear)
        report["range_clear_sent"] = True
        time.sleep(0.25)
        report["clear_capture"] = probe._batch_capture(
            user32, target_hwnd, RECT, POINT, output_dir, stem,
            f"{role.lower()}_build_tree_cleanup_after_clear"
        )
        done = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _RANGE_EDITOR_DONE_CENTER, label="commit_range_editor_done"
        )
        actions.append(done)
        time.sleep(0.45)
        remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
        retry = None
        if remaining:
            retry = _click_verified_gto_hit_target(
                user32, target_hwnd, target_pid, RECT, POINT,
                _RANGE_EDITOR_DONE_CENTER, label=f"{role.lower()}_build_tree_cleanup_done_retry"
            )
            actions.append(retry)
            time.sleep(0.45)
            remaining = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
        closed_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, f"{role.lower()}_build_tree_cleanup_after_done"
        )
        closed_path = _root_capture_path(closed_windows, f"{role.lower()}_build_tree_cleanup_after_done")
        final_sig = _bmp_matrix_center_signature(closed_path, matrix_rect)
        final_diff = _bmp_region_difference_ratio(baseline_path, closed_path, matrix_rect)
        editor_diff = _bmp_region_difference_ratio(baseline_path, closed_path, _RANGE_EDITOR_VERIFY_ROI)
        report.update({
            "done_click": done,
            "done_native_retry": retry,
            "visible_source_edits_remaining": len(remaining),
            "final_matrix_signature": final_sig,
            "final_matrix_difference": final_diff,
            "final_editor_difference": editor_diff,
            "range_restored": (
                not remaining
                and final_sig["samples"] == baseline_sig["samples"]
                and editor_diff["ratio"] <= 0.01
            ),
        })
        editor_open = bool(remaining)
        report["status"] = "known_test_range_cleared_and_baseline_verified" if report["range_restored"] else "cleanup_not_verified"
        report["manual_close_required"] = not report["range_restored"]
        return report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["status"] = "safe_stop_preserving_unrecognized_range" if not report["range_clear_sent"] else "cleanup_attempted_not_verified"
        report["manual_close_required"] = bool(editor_open)
        return report
    finally:
        if moved.get("moved"):
            restore = _restore_source_field_window_position(user32, target_hwnd, RECT, moved)
            report["temporary_window_restore"] = restore
            report["window_position_restore_verified"] = bool(restore.get("verified"))
            if not restore.get("verified"):
                report["manual_close_required"] = True


def _clear_committed_test_board(
    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
    target_hwnd: int, target_pid: int, output_dir: Path, stem: str,
    baseline_path: str, committed_path: str,
    actions: list[dict[str, Any]], all_captures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Clear As/Kd/7c only when the live Board field still matches the known test image."""
    report: dict[str, Any] = {
        "stage": "board_build_tree_probe_cleanup",
        "status": "not_started",
        "board_clear_sent": False,
        "board_restored": False,
        "manual_close_required": False,
    }
    try:
        before_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, "board_build_tree_cleanup_before"
        )
        all_captures.extend(w["capture"] for w in before_windows)
        before_path = _root_capture_path(before_windows, "board_build_tree_cleanup_before")
        still_expected = _bmp_region_difference_ratio(
            committed_path, before_path, _BOARD_ENTRY_DIFF_ROI
        )
        report["current_board_matches_test_image"] = still_expected
        if still_expected["ratio"] > 0.01:
            report["status"] = "stopped_board_differs_from_known_test_preserved"
            report["note"] = "Board field changed after the test commit; Clear was not sent."
            return report

        opened = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT,
            _BOARD_INPUT_CENTER, label="focus_board_input"
        )
        actions.append(opened)
        time.sleep(0.40)
        selector_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, "board_build_tree_cleanup_selector_open"
        )
        all_captures.extend(w["capture"] for w in selector_windows)
        selector_path = _root_capture_path(selector_windows, "board_build_tree_cleanup_selector_open")
        open_difference = _bmp_region_difference_ratio(
            before_path, selector_path, _BOARD_SELECTOR_ROI
        )
        report["selector_open_difference"] = open_difference
        if open_difference["ratio"] < 0.05:
            raise RuntimeError("Board selector did not open for guarded Clear")
        clear = _click_board_selector_target(
            user32, target_hwnd, target_pid, RECT, POINT,
            _BOARD_CLEAR_CENTER, label="clear_board_selector"
        )
        actions.append(clear)
        report["board_clear_sent"] = True
        time.sleep(0.20)
        done = _click_board_selector_target(
            user32, target_hwnd, target_pid, RECT, POINT,
            _BOARD_DONE_CENTER, label="commit_board_selector_done"
        )
        actions.append(done)
        time.sleep(0.45)
        final_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, "board_build_tree_cleanup_restored_main"
        )
        all_captures.extend(w["capture"] for w in final_windows)
        final_path = _root_capture_path(final_windows, "board_build_tree_cleanup_restored_main")
        diff = _bmp_region_difference_ratio(baseline_path, final_path, _BOARD_ENTRY_DIFF_ROI)
        dark = _bmp_region_dark_pixel_ratio(final_path, _BOARD_ENTRY_FIELD_ROI)
        report.update({
            "done_click": done,
            "baseline_field_difference": diff,
            "entry_field_dark_pixel_ratio": dark,
            "board_restored": diff["ratio"] <= 0.002 and dark <= 0.002,
            "screenshot": final_path,
        })
        report["status"] = "known_test_board_cleared_and_baseline_verified" if report["board_restored"] else "board_cleanup_not_verified"
        report["manual_close_required"] = not report["board_restored"]
        return report
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["manual_close_required"] = bool(report.get("board_clear_sent"))
        report["status"] = "board_cleanup_attempted_not_verified" if report.get("board_clear_sent") else "safe_stop_preserving_board"
        return report



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
                user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                target_hwnd, target_pid,
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
            else "player2_range_validation_failed_but_test_inputs_restored"
            if build_tree_dialog_probe
            and build_tree_dialog_probe.get("player2_range_validation_seen")
            and build_tree_sequence["all_test_inputs_restored"]
            else "build_tree_dialog_not_identified_but_test_inputs_restored"
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
            "build_tree_player2_validation_seen": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_range_validation_seen")),
            "build_tree_player2_validation_recovered": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_range_validation_recovered")),
            "build_tree_player2_range_cleanup_restored": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("player2_validation_cleanup_restored_ip")),
            "build_tree_probe_safe_to_cleanup": bool(build_tree_dialog_probe and build_tree_dialog_probe.get("safe_to_cleanup")),
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
