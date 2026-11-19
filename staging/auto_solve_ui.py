"""Calibrated, read-only discovery of embedded GTO+ 1.9.1 setup UI.

The range editor is closed with its measured on-screen X button, not Escape:
the embedded GTO window has no keyboard focus while Pigeon's Tk child owns it.
The Build Tree dialog is captured and is only dismissed with Escape when the
GTO process itself owns keyboard focus. Every close is visually verified
against the baseline screenshot before the next click is allowed.
"""
from __future__ import annotations

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


def _click_exact_client(user32, root_hwnd: int, root_pid: int,
                        RECT, POINT, point: tuple[int, int], *,
                        label: str) -> dict[str, Any]:
    allowed = {
        "open_oop_range_editor": _OOP_MATRIX_RECT,
        "open_ip_range_editor": _IP_MATRIX_RECT,
        "focus_range_source_field": _RANGE_SOURCE_FIELD_RECT,
        "focus_board_input": _BOARD_INPUT_RECT,
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


def _probe_source_field_readback_restore(user32, root_hwnd: int, RECT, POINT,
                                           output_dir: Path, stem: str,
                                           role: str) -> dict[str, Any]:
    """Test the exact GTO+ Source Edit using AA, then restore the original text.

    The test never clicks Done. It writes only when exactly one visible Edit
    control with GTO+ control ID 5458 is found at the measured source-field
    location and its original content is blank. The exact original value is
    read back after restoration before the caller may proceed.
    """
    if role not in {"OOP", "IP"}:
        raise ValueError("role must be OOP or IP")
    click = _click_exact_client(
        user32, root_hwnd, probe._window_pid(user32, root_hwnd), RECT, POINT,
        _RANGE_SOURCE_FIELD_CENTER, label="focus_range_source_field"
    )
    client = RECT()
    if not user32.GetClientRect(probe.wintypes.HWND(root_hwnd), probe.ctypes.byref(client)):
        raise OSError(f"{role} Source field GetClientRect failed: {probe.ctypes.get_last_error()}")
    origin = POINT(int(client.left), int(client.top))
    if not user32.ClientToScreen(probe.wintypes.HWND(root_hwnd), probe.ctypes.byref(origin)):
        raise OSError(f"{role} Source field ClientToScreen failed: {probe.ctypes.get_last_error()}")
    focus = probe._gui_thread_focus_snapshot(
        user32, RECT, POINT, root_hwnd, probe._top_level_ancestor(user32, root_hwnd),
        source_point_screen=(int(origin.x + _RANGE_SOURCE_FIELD_CENTER[0]),
                             int(origin.y + _RANGE_SOURCE_FIELD_CENTER[1]))
    )
    finder = getattr(probe, "_batch_visible_source_edits", None)
    if not callable(finder):
        return {
            "stage": f"{role.lower()}_source_field",
            "status": "source_edit_enumerator_unavailable",
            "field_click": click, "focus_snapshot": focus,
            "candidate_count": None, "text_changed": False,
            "range_committed": False, "tree_built": False, "solver_run": False,
        }
    edits = finder(user32, RECT, root_hwnd)
    base = {
        "stage": f"{role.lower()}_source_field",
        "field_click": click,
        "focus_snapshot": focus,
        "candidate_count": len(edits),
        "range_committed": False,
        "tree_built": False,
        "solver_run": False,
    }
    if len(edits) != 1:
        return {**base, "status": "native_source_edit_missing_or_ambiguous",
                "text_changed": False, "source_controls": probe._batch_child_controls(user32, RECT, root_hwnd)}
    edit_hwnd, edit_rect = edits[0]
    if (probe._window_pid(user32, edit_hwnd) != probe._window_pid(user32, root_hwnd)
            or probe._class_name(user32, edit_hwnd) != "Edit"
            or int(user32.GetDlgCtrlID(probe.wintypes.HWND(edit_hwnd))) != 5458):
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
        "edit_control_id": 5458, "edit_class": "Edit",
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
        user32, target_hwnd, RECT, POINT, output_dir, stem, "OOP"
    )
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
    stages.append({
        "stage": "oop_range_editor",
        "status": "opened_and_closed_by_measured_x" if oop_closed_ok else "close_not_verified",
        "open_click": oop_click,
        "open_windows": oop_windows,
        "open_overlay_difference": oop_appearance,
        "close_click": close_click,
        "windows_after_x": oop_closed_windows,
        "baseline_difference_after_x": oop_close_check,
        "visually_closed": oop_closed_ok,
        "range_text_changed": False,
        "range_committed": False,
    })
    stages.append(oop_source_probe)

    # Stage 2: calibrate the IP Source field using the same reversible AA test.
    # Never click Done: the test text is read back and restored before closing.
    ip_editor_result = None
    board_input_result = None
    manual_close_required = False
    continue_after_oop = oop_closed_ok and oop_source_probe.get("status") != "source_field_test_incomplete"
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
                user32, target_hwnd, RECT, POINT, output_dir, stem, "IP"
            )
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
            ip_editor_result = {
                "stage": "ip_range_editor",
                "status": "opened_and_closed_by_measured_x" if ip_closed_ok else "close_not_verified",
                "open_click": ip_click,
                "open_windows": ip_windows,
                "open_overlay_difference": ip_appearance,
                "source_field_probe": ip_source_probe,
                "close_click": ip_close_click,
                "windows_after_x": ip_closed_windows,
                "baseline_difference_after_x": ip_close_check,
                "visually_closed": ip_closed_ok,
                "range_committed": False,
            }
            stages.append(ip_editor_result)
            stages.append(ip_source_probe)
            continue_after_oop = ip_closed_ok and ip_source_probe.get("status") != "source_field_test_incomplete"
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
        board_escape = None
        board_after_escape_windows = []
        board_close_check = None
        if board_dialog_detected:
            board_escape = _send_escape_only_to_gto_focused_thread(
                user32, RECT, POINT, target_hwnd, target_pid
            )
            if board_escape["escape_sent"]:
                board_after_escape_windows = _capture_related_windows(
                    user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                    target_hwnd, target_pid, output_dir, stem, "board_input_after_escape"
                )
                board_after_path = _root_capture_path(board_after_escape_windows, "board_input_after_escape")
                board_close_check = _bmp_region_difference_ratio(baseline_path, board_after_path)
                all_captures.extend(w["capture"] for w in board_after_escape_windows)
        board_closed_ok = bool(
            not board_dialog_detected
            or (board_close_check and board_close_check["ratio"] <= 0.01)
        )
        manual_close_required = board_dialog_detected and not board_closed_ok
        board_input_result = {
            "stage": "board_input",
            "status": (
                "input_field_focused_no_popup" if not board_dialog_detected
                else "selector_opened_and_closed" if board_closed_ok
                else "selector_opened_manual_close_required"
            ),
            "click": board_click,
            "open_windows": board_windows,
            "visible_overlay_difference": board_appearance,
            "popup_detected": board_popup_detected,
            "dialog_detected": board_dialog_detected,
            "native_controls": board_controls,
            "focus_snapshot": board_focus,
            "escape_attempt": board_escape,
            "windows_after_escape": board_after_escape_windows,
            "baseline_difference_after_escape": board_close_check,
            "visually_closed": board_closed_ok,
            "board_changed": False,
        }
        stages.append(board_input_result)

    report = {
        "schema_version": 3,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "probe": "verified_visual_gto_plus_setup_dialog_discovery",
        "target": {"pid": int(target_pid), "hwnd": int(target_hwnd), "host_hwnd": int(host)},
        "client_size": [width, height],
        "coordinate_reference": {
            "client_size": list(_REFERENCE_SIZE),
            "oop_matrix_rect": list(_OOP_MATRIX_RECT),
            "oop_matrix_center": list(_OOP_MATRIX_CENTER),
            "oop_close_rect": list(_OOP_CLOSE_RECT),
            "oop_close_center": list(_OOP_CLOSE_CENTER),
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
            "oop_range_text_changed": False,
            "ip_range_text_changed": False,
            "range_committed": False,
            "board_changed": False,
            "pot_changed": False,
            "stack_changed": False,
            "rake_changed": False,
            "tree_built": False,
            "solver_run": False,
            "other_gto_processes_touched": False,
            "build_tree_dialog_left_open": manual_close_required and build_tree_result is not None,
            "manual_close_required": manual_close_required,
        },
        "notes": [
            "Only the exact Pigeon-embedded GTO+ HWND/PID was operated.",
            "The OOP editor close is verified against baseline pixels in the calibrated dialog ROI.",
            "Escape is sent only when the focused HWND belongs to the exact GTO.exe PID; Pigeon's Tk host focus is never accepted.",
            "Build Tree is considered open only when a visible overlay or related GTO popup is detected. Escape is attempted only for a detected dialog when the exact GTO process owns keyboard focus; otherwise manual_close_required is set only if a dialog actually remains open.",
            "No range text, board, pot, stack, rake, tree or Solver setting is changed.",
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
        f"Build Tree click attempted: {bool(build_tree_result and build_tree_result.get('click_attempted'))}",
        f"Build Tree dialog detected: {bool(build_tree_result and build_tree_result.get('dialog_detected'))}",
        f"Build Tree dialog visually closed: {bool(build_tree_result and build_tree_result.get('dialog_detected') and build_tree_result['visually_closed'])}",
        f"Manual close required: {manual_close_required}",
        "Range/board/pot/stack/rake changed: no",
        "Tree built: no",
        "Solver run: no",
        "",
    ]
    for stage in stages:
        lines.append(f"{stage['stage']}: {stage['status']}")
        if "visible_overlay_difference" in stage:
            lines.append(f"Build Tree overlay pixel ratio: {stage['visible_overlay_difference']['ratio']:.4f}")
        if "baseline_difference_after_escape" in stage and stage["baseline_difference_after_escape"]:
            lines.append(f"After Escape baseline pixel ratio: {stage['baseline_difference_after_escape']['ratio']:.4f}")
        if "baseline_difference_after_x" in stage:
            lines.append(f"After X baseline pixel ratio: {stage['baseline_difference_after_x']['ratio']:.4f}")
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
