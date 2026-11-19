"""Shared Focus Timer -> Study Wallet study-time contract.

Focus Timer writes cumulative Study seconds to %APPDATA%/StudyWallet.
Both the standalone Study Wallet app and Pigeon Poker read the same snapshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import time
from pathlib import Path
from typing import Mapping, Any


EXPORT_FILENAME = "study_time_balance.json"
EXPORT_SCHEMA_VERSION = 1


def shared_pigeon_data_dir(environ: Mapping[str, str] | None = None,
                           home: Path | None = None) -> Path:
    # Kept under the legacy function name for backward-compatible imports.
    env = os.environ if environ is None else environ
    appdata = str(env.get("APPDATA", "")).strip()
    if appdata:
        return Path(appdata).expanduser() / "StudyWallet"
    base = home or Path.home()
    return base / ".config" / "StudyWallet"


def shared_study_snapshot_path(environ: Mapping[str, str] | None = None,
                                home: Path | None = None) -> Path:
    return shared_pigeon_data_dir(environ, home) / EXPORT_FILENAME


@dataclass(frozen=True)
class StudyTimeSnapshot:
    total_seconds: int = 0
    updated_at: str = ""
    source: str = "Focus Timer"
    connected: bool = False
    error: str = ""

    @property
    def total_hours(self) -> float:
        return self.total_seconds / 3600.0

    @property
    def whole_dollar_allowance_cents(self) -> int:
        return (max(0, self.total_seconds) // 3600) * 100


def _read_timer_data_file(path: Path) -> StudyTimeSnapshot:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Focus Timer data must be a JSON object")
    history = raw.get("history", {})
    if not isinstance(history, dict):
        history = {}
    total = cumulative_study_seconds(history, raw.get("calendar_study", raw.get("study", 0)))
    updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds")
    return StudyTimeSnapshot(total, updated_at, "Focus Timer original data file", True, "")


_TIMER_DATA_FILENAME = "simple_timer_data.json"
_DISCOVERY_CACHE: dict[str, Any] = {"key": "", "at": 0.0, "files": []}


def _read_timer_data_file(path: Path) -> StudyTimeSnapshot:
    if path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("Focus Timer data file is unexpectedly large")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("Focus Timer data must be a JSON object")
    history = raw.get("history", {})
    if not isinstance(history, dict):
        history = {}
    total = cumulative_study_seconds(history, raw.get("calendar_study", raw.get("study", 0)))
    updated = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds")
    return StudyTimeSnapshot(total, updated, "Focus Timer original data file", True, "")


def _discover_timer_files(target: Path) -> list[Path]:
    hint = target.parent / "focus_timer_data_path.txt"
    try:
        value = hint.read_text(encoding="utf-8-sig").strip()
        hinted = Path(value).expanduser() if value else None
        if hinted and hinted.is_file() and hinted.name.lower() == _TIMER_DATA_FILENAME:
            return [hinted.resolve()]
    except (OSError, ValueError):
        pass
    roots = [target.parent, Path.cwd(), Path(__file__).resolve().parent,
             Path(__file__).resolve().parent.parent, Path.home()]
    for key in ("USERPROFILE", "OneDrive", "OneDriveCommercial", "APPDATA", "LOCALAPPDATA"):
        value = str(os.environ.get(key, "")).strip()
        if value:
            roots.append(Path(value).expanduser())
    unique, seen = [], set()
    for root in roots:
        try:
            root = root.resolve()
            key = os.path.normcase(str(root))
            if key not in seen and root.is_dir():
                seen.add(key)
                unique.append(root)
        except (OSError, RuntimeError):
            continue
    cache_key = "|".join(os.path.normcase(str(root)) for root in unique)
    now_mono = time.monotonic()
    if _DISCOVERY_CACHE.get("key") == cache_key and now_mono - float(_DISCOVERY_CACHE.get("at", 0)) < 20:
        return [Path(item) for item in _DISCOVERY_CACHE.get("files", []) if Path(item).is_file()]
    found: dict[str, Path] = {}
    for root in unique:
        candidate = root / _TIMER_DATA_FILENAME
        try:
            if candidate.is_file():
                resolved = candidate.resolve()
                found[os.path.normcase(str(resolved))] = resolved
        except OSError:
            pass
    nonzero = False
    for candidate in found.values():
        try:
            if _read_timer_data_file(candidate).total_seconds > 0:
                nonzero = True
                break
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    if not nonzero:
        try:
            home = Path.home().resolve()
        except OSError:
            home = None
        if home and home.is_dir():
            start, count = time.monotonic(), 0
            skip = {".git", ".cache", "__pycache__", "node_modules", ".venv", "venv", "temp", "tmp",
                    "$recycle.bin", "system volume information", "windows", "program files",
                    "program files (x86)", "windowsapps"}
            skip_relative = {os.path.normcase("AppData/Local/Temp"),
                             os.path.normcase("AppData/Local/Packages"),
                             os.path.normcase("AppData/Local/Microsoft")}
            for current, dirs, files in os.walk(home, topdown=True, onerror=lambda _exc: None):
                count += 1
                rel = os.path.relpath(current, home)
                dirs[:] = [name for name in dirs if name.lower() not in skip and
                           os.path.normcase(os.path.join(rel, name).replace("\\", "/")) not in skip_relative]
                if _TIMER_DATA_FILENAME in files:
                    candidate = Path(current) / _TIMER_DATA_FILENAME
                    try:
                        resolved = candidate.resolve()
                        found[os.path.normcase(str(resolved))] = resolved
                    except OSError:
                        pass
                if count >= 12000 or time.monotonic() - start > 6.0:
                    break
    result = list(found.values())
    _DISCOVERY_CACHE.update({"key": cache_key, "at": now_mono, "files": [str(item) for item in result]})
    return result


def read_study_time_snapshot(path: str | Path | None = None) -> StudyTimeSnapshot:
    target = Path(path) if path is not None else shared_study_snapshot_path()
    hint = target.parent / "focus_timer_data_path.txt"
    last_error = None
    timer_rows = []
    for timer_path in _discover_timer_files(target):
        try:
            snap = _read_timer_data_file(timer_path)
            sibling = (any(timer_path.parent.glob("Focus_Timer_ULTIMATE_PRO*.pyw"))
                       or any(timer_path.parent.glob("FocusTimer*.pyw")))
            timer_rows.append(((1 if snap.total_seconds > 0 else 0, 1 if sibling else 0,
                                snap.total_seconds, timer_path.stat().st_mtime), snap))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
    if timer_rows:
        return max(timer_rows, key=lambda row: row[0])[1]
    try:
        timer_path = Path(hint.read_text(encoding="utf-8").strip()).expanduser()
        if timer_path.is_file():
            try:
                return _read_timer_data_file(timer_path)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                last_error = exc
    except FileNotFoundError:
        pass
    except OSError as exc:
        last_error = exc
    candidates = [target]
    if target.name == EXPORT_FILENAME and target.parent.name == "StudyWallet":
        candidates.append(target.parent.parent / "PigeonPoker" / EXPORT_FILENAME)
    for candidate in candidates:
      try:
        raw = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("snapshot must be an object")
        version = int(raw.get("schema_version", 0))
        if version != EXPORT_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version: {version}")
        seconds = int(raw.get("total_study_seconds", -1))
        if seconds < 0:
            raise ValueError("total_study_seconds must be non-negative")
        updated_at = str(raw.get("updated_at", ""))
        return StudyTimeSnapshot(seconds, updated_at, str(raw.get("source", "Focus Timer")), True, "")
      except FileNotFoundError as exc:
        last_error = exc
        continue
      except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        last_error = exc
        continue
    return StudyTimeSnapshot(error=f"Focus Timer data/export not found or invalid: {last_error or target}")


def cumulative_study_seconds(history: Mapping[str, Any] | None, calendar_study_seconds: Any) -> int:
    """All-time Study seconds: completed calendar-day history plus today's counter.

    Timer-day ``study`` is intentionally not accepted here because it resets
    at the user-configured timer boundary. Rest and Sleep are never included.
    """
    total = 0
    if isinstance(history, Mapping):
        for value in history.values():
            try:
                total += max(0, int(value))
            except (TypeError, ValueError, OverflowError):
                continue
    try:
        current = max(0, int(calendar_study_seconds))
    except (TypeError, ValueError, OverflowError):
        current = 0
    return total + current


def available_deposit_cents(total_study_seconds: int, already_redeemed_cents: int) -> int:
    earned_cents = (max(0, int(total_study_seconds)) // 3600) * 100
    return max(0, earned_cents - max(0, int(already_redeemed_cents)))


def format_signed_usd(cents: int) -> str:
    value = int(cents)
    if value < 0:
        return f"-${abs(value) / 100:,.2f}"
    if value > 0:
        return f"+${value / 100:,.2f}"
    return "$0.00"


def snapshot_payload(total_study_seconds: int, *, updated_at: str | None = None) -> dict[str, Any]:
    seconds = max(0, int(total_study_seconds))
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "source": "Focus Timer ULTIMATE PRO",
        "total_study_seconds": seconds,
        "total_study_hours": seconds / 3600.0,
        "whole_dollar_allowance": seconds // 3600,
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }