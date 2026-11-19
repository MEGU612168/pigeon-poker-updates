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

    # Stage 2 is permitted only after pixel-level confirmation that the OOP
    # editor is gone. Otherwise stop here instead of clicking beneath a modal.
    build_tree_result = None
    manual_close_required = False
    if oop_closed_ok:
        build_click = _click_exact_client(
            user32, target_hwnd, target_pid, RECT, POINT, _BUILD_TREE_CENTER,
            label="open_build_tree_setup"
        )
        actions.append(build_click)
        time.sleep(0.75)
        build_windows = _capture_related_windows(
            user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
            target_hwnd, target_pid, output_dir, stem, "build_tree_open"
        )
        build_open_path = _root_capture_path(build_windows, "build_tree_open")
        build_appearance = _bmp_region_difference_ratio(baseline_path, build_open_path)
        all_captures.extend(w["capture"] for w in build_windows)
        build_focus = probe._gui_thread_focus_snapshot(user32, RECT, POINT, target_hwnd, host)
        escape_result = _send_escape_only_to_gto_focused_thread(
            user32, RECT, POINT, target_hwnd, target_pid
        )
        build_closed_check = None
        build_closed_windows = []
        if escape_result["escape_sent"]:
            build_closed_windows = _capture_related_windows(
                user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                target_hwnd, target_pid, output_dir, stem, "build_tree_after_gto_escape"
            )
            build_closed_path = _root_capture_path(build_closed_windows, "build_tree_after_gto_escape")
            build_closed_check = _bmp_region_difference_ratio(baseline_path, build_closed_path)
            all_captures.extend(w["capture"] for w in build_closed_windows)
        build_closed_ok = bool(build_closed_check and build_closed_check["ratio"] <= 0.01)
        manual_close_required = not build_closed_ok
        build_tree_result = {
            "stage": "build_tree_setup",
            "status": "opened_and_visually_closed" if build_closed_ok else "opened_captured_manual_close_required",
            "open_click": build_click,
            "open_windows": build_windows,
            "visible_overlay_difference": build_appearance,
            "focus_before_escape": build_focus,
            "escape_attempt": escape_result,
            "after_escape_windows": build_closed_windows,
            "baseline_difference_after_escape": build_closed_check,
            "visually_closed": build_closed_ok,
            "manual_close_required": manual_close_required,
            "settings_changed": False,
            "tree_built": False,
            "solver_run": False,
        }
        stages.append(build_tree_result)
    else:
        manual_close_required = True

    report = {
        "schema_version": 2,
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
            "Build Tree dialog is captured without entering settings or building a tree. If it cannot be closed with verified GTO keyboard focus, the report marks manual_close_required and stops.",
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
        f"Build Tree dialog captured: {build_tree_result is not None}",
        f"Build Tree dialog visually closed: {bool(build_tree_result and build_tree_result['visually_closed'])}",
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
