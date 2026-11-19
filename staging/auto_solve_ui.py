"""Safe, read-only discovery of the embedded GTO+ 1.9.1 setup dialogs.

This probe only opens the already-calibrated OOP range editor and Build Tree
setup dialog, captures their actual UI, and dismisses them with Escape after
verifying keyboard focus belongs to the exact GTO+ process hosted by Pigeon.
It never enters text, commits a range, changes board/pot/stack/rake, builds a
tree, runs Solver, or selects another GTO.exe process.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ui_probe as probe

# Measured from the user's actual embedded GTO+ 1.9.1 client screenshot
# gto_plus_ui_20261119_174018_window_primary.bmp: 665 x 570 client pixels.
_REFERENCE_SIZE = (665, 570)
_OOP_MATRIX_RECT = (27, 88, 82, 144)
_OOP_MATRIX_CENTER = (54, 116)
_BUILD_TREE_RECT = (24, 253, 85, 276)
_BUILD_TREE_CENTER = (54, 265)


def _client_geometry(user32, hwnd: int, RECT) -> tuple[int, int]:
    client = RECT()
    if not user32.GetClientRect(probe.wintypes.HWND(hwnd), probe.ctypes.byref(client)):
        raise OSError(f"GetClientRect failed: {probe.ctypes.get_last_error()}")
    return int(client.right-client.left), int(client.bottom-client.top)


def _capture_related_windows(user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
                             root_hwnd: int, root_pid: int, output_dir: Path,
                             stem: str, stage: str) -> list[dict[str, Any]]:
    host = probe._top_level_ancestor(user32, root_hwnd)
    roots, _ = probe._all_hwnds(user32, EnumWindowsProc, EnumChildProc)
    # The embedded solver window is commonly a child of Pigeon's host and
    # therefore is NOT returned by EnumWindows. Always include that exact
    # integration HWND explicitly before enumerating GTO-owned top-level dialogs.
    candidates = [int(root_hwnd)] + [int(hwnd) for hwnd in roots if int(hwnd) != int(root_hwnd)]
    captured: list[dict[str, Any]] = []
    seen: set[int] = set()
    for hwnd in candidates:
        hwnd = int(hwnd)
        if hwnd in seen:
            continue
        seen.add(hwnd)
        if not hwnd or not user32.IsWindow(probe.wintypes.HWND(hwnd)):
            continue
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


def _click_exact_client(user32, root_hwnd: int, root_pid: int,
                        RECT, POINT, point: tuple[int, int], *,
                        label: str) -> dict[str, Any]:
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
    x0, y0, x1, y1 = (_OOP_MATRIX_RECT if label == "open_oop_range_editor"
                      else _BUILD_TREE_RECT)
    if not (x0 <= x <= x1 and y0 <= y <= y1 and 0 <= x < width and 0 <= y < height):
        raise RuntimeError(f"{label}: click point is outside its measured button/matrix; no click sent")

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


def _press_escape_if_exact_gto_focus(user32, RECT, POINT,
                                     root_hwnd: int, root_pid: int) -> dict[str, Any]:
    host = probe._top_level_ancestor(user32, root_hwnd)
    foreground = int(user32.GetForegroundWindow() or 0)
    focus = probe._gui_thread_focus_snapshot(
        user32, RECT, POINT, root_hwnd, host
    )
    focus_hwnds: list[int] = []
    for thread in focus.get("threads", []):
        handle = int((thread.get("handles") or {}).get("focus") or 0)
        if handle:
            focus_hwnds.append(handle)
    verified_focus = False
    for handle in focus_hwnds:
        if probe._window_pid(user32, handle) == int(root_pid):
            verified_focus = True
            break
        if probe._window_is_related_to_embedded_target(user32, handle, root_hwnd, host):
            verified_focus = True
            break
    foreground_related = (
        foreground == int(host)
        or foreground == int(root_hwnd)
        or probe._window_is_related_to_embedded_target(user32, foreground, root_hwnd, host)
    )
    if not (verified_focus and foreground_related):
        return {
            "status": "skipped_focus_not_proven",
            "foreground_hwnd": foreground,
            "focus_hwnds": focus_hwnds,
            "focus_snapshot": focus,
            "escape_sent": False,
        }
    user32.keybd_event(0x1B, 0, 0, 0)
    user32.keybd_event(0x1B, 0, 0x0002, 0)
    time.sleep(0.45)
    return {
        "status": "escape_sent_to_verified_gto_focus",
        "foreground_hwnd": foreground,
        "focus_hwnds": focus_hwnds,
        "focus_snapshot": focus,
        "escape_sent": True,
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
    initial_dialogs = _capture_related_windows(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        target_hwnd, target_pid, output_dir, stem, "initial"
    )
    extra_initial = [w for w in initial_dialogs if not w["is_embedded_root"]]
    preexisting_source_edits = probe._batch_visible_source_edits(user32, RECT, target_hwnd)
    if extra_initial or preexisting_source_edits:
        raise RuntimeError(
            "A related GTO+ popup or range editor is already open. "
            "The probe stopped without clicking to avoid disturbing the user's current dialog."
        )

    actions: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    all_captures: list[dict[str, Any]] = []
    baseline = probe._batch_capture(user32, target_hwnd, RECT, POINT, output_dir, stem, "baseline")
    all_captures.append(baseline)
    main_controls = probe._batch_child_controls(user32, RECT, target_hwnd)

    # Stage 1: open the OOP range editor only to inspect its real field/dialog.
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
    all_captures.extend(w["capture"] for w in oop_windows)
    oop_focus = probe._gui_thread_focus_snapshot(user32, RECT, POINT, target_hwnd, host)
    oop_escape = _press_escape_if_exact_gto_focus(user32, RECT, POINT, target_hwnd, target_pid)
    oop_closed = _capture_related_windows(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        target_hwnd, target_pid, output_dir, stem, "oop_editor_after_escape"
    )
    all_captures.extend(w["capture"] for w in oop_closed)
    if not oop_escape["escape_sent"]:
        raise RuntimeError(
            "The OOP editor was opened, but GTO+ keyboard focus could not be proven. "
            "No further clicks were sent; review the saved screenshot and close the dialog manually."
        )
    if any(not w["is_embedded_root"] for w in oop_closed):
        raise RuntimeError(
            "The OOP editor did not close after Escape. The probe stopped before opening Build Tree."
        )
    stages.append({
        "stage": "oop_range_editor",
        "status": "opened_captured_and_escape_closed",
        "click": oop_click,
        "windows_open": oop_windows,
        "focus_before_escape": oop_focus,
        "escape": oop_escape,
        "windows_after_escape": oop_closed,
        "range_text_changed": False,
        "range_committed": False,
    })

    # Stage 2: open the Build Tree setup dialog, capture its true controls,
    # and dismiss it. The Build Tree button itself is not pressed.
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
    all_captures.extend(w["capture"] for w in build_windows)
    build_focus = probe._gui_thread_focus_snapshot(user32, RECT, POINT, target_hwnd, host)
    build_escape = _press_escape_if_exact_gto_focus(user32, RECT, POINT, target_hwnd, target_pid)
    build_closed = _capture_related_windows(
        user32, EnumWindowsProc, EnumChildProc, RECT, POINT,
        target_hwnd, target_pid, output_dir, stem, "build_tree_after_escape"
    )
    all_captures.extend(w["capture"] for w in build_closed)
    if not build_escape["escape_sent"]:
        raise RuntimeError(
            "The Build Tree dialog was opened, but GTO+ focus could not be proven. "
            "No Solver or Build Tree action was sent; review the screenshot and close the dialog manually."
        )
    if any(not w["is_embedded_root"] for w in build_closed):
        raise RuntimeError("Build Tree setup did not close after Escape; no Build/Solver command was sent.")
    stages.append({
        "stage": "build_tree_setup",
        "status": "opened_captured_and_escape_closed",
        "click": build_click,
        "windows_open": build_windows,
        "focus_before_escape": build_focus,
        "escape": build_escape,
        "windows_after_escape": build_closed,
        "settings_changed": False,
        "tree_built": False,
        "solver_run": False,
    })

    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "probe": "read_only_gto_plus_setup_dialog_discovery",
        "target": {"pid": int(target_pid), "hwnd": int(target_hwnd), "host_hwnd": int(host)},
        "client_size": [width, height],
        "coordinate_reference": {
            "client_size": list(_REFERENCE_SIZE),
            "oop_matrix_rect": list(_OOP_MATRIX_RECT),
            "oop_matrix_center": list(_OOP_MATRIX_CENTER),
            "build_tree_button_rect": list(_BUILD_TREE_RECT),
            "build_tree_button_center": list(_BUILD_TREE_CENTER),
            "source": "user's 2026-11-19 17:40:18 embedded GTO+ screenshot",
        },
        "main_window_controls_before": main_controls,
        "initial_windows": initial_dialogs,
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
        },
        "notes": [
            "Only the exact Pigeon-embedded GTO+ HWND/PID was operated.",
            "OOP range editor and Build Tree setup were opened for screenshots, then dismissed with Escape.",
            "No input was typed, no range committed, and no board/pot/stack/rake/tree/Solver settings were changed.",
            "Every action was gated by the calibrated 665x570 client geometry and verified GTO+ keyboard focus.",
        ],
    }
    json_path = output_dir / f"{stem}.json"
    txt_path = output_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_path.write_text(
        "PIGEON POKER — SAFE GTO+ AUTO-SOLVE SETUP PROBE\n"
        f"Created: {report['created_at']}\n"
        f"Target: PID={target_pid} HWND={target_hwnd}\n"
        f"Client: {width}x{height}\n"
        "Range text changed: no\nBoard/pot/stack/rake changed: no\nTree built: no\nSolver run: no\n\n"
        + "\n".join(
            f"{stage['stage']}: {stage['status']}\n"
            f"open windows: {[{'title':w['title'],'rect':w['rect_screen'],'controls':w['controls']} for w in stage['windows_open']]}"
            for stage in stages
        ),
        encoding="utf-8",
    )
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
    parser = argparse.ArgumentParser(description="Safe read-only GTO+ 1.9.1 setup dialog discovery")
    parser.add_argument("--output", default=str(Path(__file__).resolve().parents[1] / "diagnostics"))
    parser.add_argument("--target-pid", type=int, required=True)
    parser.add_argument("--target-hwnd", type=int, required=True)
    args = parser.parse_args()
    try:
        path = run_setup_dialog_probe(
            Path(args.output), target_pid=int(args.target_pid), target_hwnd=int(args.target_hwnd)
        )
        print(f"Safe GTO+ setup diagnostic created: {path}")
        return 0
    except Exception as exc:
        print(f"Safe GTO+ setup diagnostic stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

# Build marker: read-only calibrated UI probe; no setup fields or solver commands are changed.
