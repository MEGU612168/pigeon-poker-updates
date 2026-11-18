"""One-click, fail-safe updater for Pigeon Poker.

Only application Python source files and VERSION.txt are ever replaced. Local
wallets, history databases, strategy databases, GTO+ trees and settings remain
outside the update allow-list.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Any

PRODUCT = "pigeon-poker"
CHANNEL = "stable"
MANIFEST_URL = (
    "https://raw.githubusercontent.com/MEGU612168/"
    "pigeon-poker-updates/main/stable.json"
)
EXPECTED_PAYLOAD_PREFIX = (
    "https://raw.githubusercontent.com/MEGU612168/"
    "pigeon-poker-updates/main/releases/"
)
EXPECTED_CODELOAD_PREFIX = "https://codeload.github.com/MEGU612168/pigeon-poker-updates/zip/"
MAX_COMPRESSED_BYTES = 18 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 18 * 1024 * 1024
MAX_FILES = 500
_ALLOWED_ROOT = {"PigeonPoker.pyw", "pigeon_updater.py", "VERSION.txt"}
_ALLOWED_PACKAGES = {"pigeon_poker", "pigeon_gto_plus"}
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
StatusCallback = Callable[[str], None]


def _version_tuple(value: str) -> tuple[int, int, int]:
    value = str(value).strip()
    if not _VERSION_RE.fullmatch(value):
        raise ValueError(f"Invalid version string: {value!r}")
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _user_data_root() -> Path:
    appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".local" / "share"
    target = base / "PigeonPoker" / "updater"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _read_current_version(app_root: Path) -> str:
    try:
        value = (app_root / "VERSION.txt").read_text(encoding="utf-8").strip()
        _version_tuple(value)
        return value
    except (OSError, ValueError):
        return "0.0.0"


def _https_get(url: str, *, max_bytes: int, timeout: int = 30) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Only HTTPS update URLs are accepted.")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "PigeonPoker-Updater/1.0", "Accept": "application/json, application/zip, */*"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https":
            raise ValueError("The update server redirected away from HTTPS.")
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > max_bytes:
            raise ValueError("The update file exceeds the size limit.")
        chunks, total = [], 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ValueError("The update file exceeds the size limit.")
            chunks.append(chunk)
    return b"".join(chunks)


def _fetch_manifest() -> dict[str, Any]:
    raw = _https_get(MANIFEST_URL, max_bytes=64 * 1024, timeout=15)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The update manifest is not valid UTF-8 JSON.") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("product") != PRODUCT or data.get("channel") != CHANNEL:
        raise ValueError("The update manifest is for an unsupported product or channel.")
    _version_tuple(str(data.get("version", "")).strip())
    url = str(data.get("payload_url", ""))
    is_raw = url.startswith(EXPECTED_PAYLOAD_PREFIX)
    is_codeload = url.startswith(EXPECTED_CODELOAD_PREFIX)
    if not (is_raw or is_codeload):
        raise ValueError("The update package URL is not on the trusted Pigeon Poker update channel.")
    parsed = urllib.parse.urlparse(url)
    host = "raw.githubusercontent.com" if is_raw else "codeload.github.com"
    if parsed.scheme != "https" or parsed.hostname != host:
        raise ValueError("The update package must be served from the trusted HTTPS host.")
    if is_codeload:
        commit_sha = url[len(EXPECTED_CODELOAD_PREFIX):].strip("/")
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise ValueError("The codeload package must be pinned to an immutable commit SHA.")
        if data.get("package_mode") != "updater-only":
            raise ValueError("The codeload package must explicitly declare updater-only mode.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data.get("payload_sha256", "")).lower()):
        raise ValueError("The update manifest has an invalid SHA-256 digest.")
    try:
        size = int(data.get("payload_size", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("The update manifest has an invalid payload size.") from exc
    if size <= 0 or size > MAX_COMPRESSED_BYTES:
        raise ValueError("The update package size is invalid or too large.")
    return data


def _is_allowed_member(name: str) -> bool:
    if not name or "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(p in {"", ".", ".."} for p in path.parts):
        return False
    if name in _ALLOWED_ROOT:
        return True
    return (
        len(path.parts) >= 2
        and path.parts[0] in _ALLOWED_PACKAGES
        and path.suffix.lower() == ".py"
        and not any(part.startswith(".") or part == "__pycache__" for part in path.parts)
    )


def _normalised_archive_members(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, str]]:
    """Validate archive members and strip only a single GitHub codeload root."""
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if not infos or len(infos) > MAX_FILES:
        raise ValueError("The update contains an invalid number of files.")
    raw_names = [info.filename for info in infos]
    if all(_is_allowed_member(name) for name in raw_names):
        members = [(info, info.filename) for info in infos]
    else:
        parts_list = [PurePosixPath(name).parts for name in raw_names]
        roots = {parts[0] for parts in parts_list if parts}
        if len(roots) == 1 and all(len(parts) >= 2 for parts in parts_list):
            members = [
                (info, PurePosixPath(*parts[1:]).as_posix())
                for info, parts in zip(infos, parts_list)
            ]
        else:
            members = [(info, info.filename) for info in infos]
    seen: set[str] = set()
    for _, relative in members:
        if not _is_allowed_member(relative):
            raise ValueError(f"The update contains a disallowed file: {relative}")
        folded = relative.casefold()
        if folded in seen:
            raise ValueError(f"The update contains a duplicate file path: {relative}")
        seen.add(folded)
    return members


def _validate_and_extract(payload: bytes, manifest: dict[str, Any], destination: Path) -> list[str]:
    if len(payload) != int(manifest["payload_size"]):
        raise ValueError("The downloaded update size does not match the manifest.")
    if hashlib.sha256(payload).hexdigest() != str(manifest["payload_sha256"]).lower():
        raise ValueError("SHA-256 verification failed. No application files were changed.")
    destination.mkdir(parents=True, exist_ok=True)
    extracted, total = [], 0
    try:
        from io import BytesIO
        with zipfile.ZipFile(BytesIO(payload), "r") as archive:
            if archive.testzip() is not None:
                raise ValueError("The update ZIP failed its integrity check.")
            members = _normalised_archive_members(archive)
            for info, relative in members:
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("The uncompressed update exceeds the size limit.")
                target = destination.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info, "r") as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=64 * 1024)
                if PurePosixPath(relative).suffix.lower() in {".py", ".pyw"}:
                    ast.parse(target.read_text(encoding="utf-8"), filename=relative)
                extracted.append(relative)
        required = {"pigeon_updater.py", "VERSION.txt"} if manifest.get("package_mode") == "updater-only" else _ALLOWED_ROOT
        if not required.issubset(set(extracted)):
            raise ValueError("The update is missing one or more required application files.")
        bundled_version = (destination / "VERSION.txt").read_text(encoding="utf-8").strip()
        if bundled_version != str(manifest["version"]):
            raise ValueError("The package version does not match the update manifest.")
        return sorted(extracted)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _apply_staged_files(app_root: Path, staged_root: Path, relative_files: list[str], *, restart: bool = True) -> Path:
    app_root = app_root.resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version = (staged_root / "VERSION.txt").read_text(encoding="utf-8").strip()
    backup_root = _user_data_root() / "backups" / f"v{version}_{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=False)
    replaced, created = [], []
    try:
        for relative in sorted(relative_files):
            if not _is_allowed_member(relative):
                raise ValueError(f"Refusing to replace a non-application path: {relative}")
            source = staged_root.joinpath(*PurePosixPath(relative).parts)
            target = app_root.joinpath(*PurePosixPath(relative).parts)
            if not target.resolve().is_relative_to(app_root):
                raise ValueError(f"Update destination escapes the application folder: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = backup_root.joinpath(*PurePosixPath(relative).parts)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
                replaced.append(relative)
            else:
                created.append(relative)
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".update", dir=str(target.parent))
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                shutil.copy2(source, temp_path)
                os.replace(temp_path, target)
            finally:
                temp_path.unlink(missing_ok=True)
    except Exception:
        for relative in reversed(replaced):
            backup = backup_root.joinpath(*PurePosixPath(relative).parts)
            target = app_root.joinpath(*PurePosixPath(relative).parts)
            if backup.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(backup, target)
        for relative in created:
            app_root.joinpath(*PurePosixPath(relative).parts).unlink(missing_ok=True)
        raise
    if restart:
        kwargs: dict[str, Any] = {"cwd": str(app_root), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([sys.executable, str(app_root / "PigeonPoker.pyw")], **kwargs)
    return backup_root


def _apply_helper(zip_path: Path, app_root: Path, parent_pid: int, expected_sha256: str) -> int:
    log_path = _user_data_root() / "update-helper.log"
    def log(message: str) -> None:
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\\n")
        except OSError:
            pass
    parent_closed = False
    try:
        deadline = time.monotonic() + 90
        while _pid_is_running(parent_pid) and time.monotonic() < deadline:
            time.sleep(0.25)
        if _pid_is_running(parent_pid):
            raise TimeoutError("Pigeon Poker did not close in time; no files were changed.")
        parent_closed = True
        if hashlib.sha256(zip_path.read_bytes()).hexdigest() != expected_sha256:
            raise ValueError("The staged update ZIP changed after verification; no files were changed.")
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = _normalised_archive_members(archive)
        names = [relative for _, relative in members]
        staging = Path(tempfile.mkdtemp(prefix="pigeon-update-stage-", dir=str(_user_data_root())))
        try:
            with zipfile.ZipFile(zip_path, "r") as archive:
                for info, relative in _normalised_archive_members(archive):
                    target = staging.joinpath(*PurePosixPath(relative).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info, "r") as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output, length=64 * 1024)
            backup = _apply_staged_files(app_root, staging, sorted(names), restart=False)
            log(f"Applied update. Backup: {backup}")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        kwargs: dict[str, Any] = {"cwd": str(app_root), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen([sys.executable, str(app_root / "PigeonPoker.pyw")], **kwargs)
        log("Restart launched successfully.")
        return 0
    except Exception as exc:
        log(f"UPDATE FAILED: {type(exc).__name__}: {exc}")
        if parent_closed and (app_root / "PigeonPoker.pyw").is_file():
            try:
                kwargs: dict[str, Any] = {"cwd": str(app_root), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
                if os.name == "nt":
                    kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                subprocess.Popen([sys.executable, str(app_root / "PigeonPoker.pyw")], **kwargs)
                log("Original/current app restarted after update failure.")
            except Exception as restart_exc:
                log(f"RESTART FAILED: {type(restart_exc).__name__}: {restart_exc}")
        return 1


def _helper_main(argv: list[str]) -> int:
    if len(argv) != 6 or argv[1] != "--apply-update":
        return 2
    zip_path, app_root = Path(argv[2]).expanduser(), Path(argv[3]).expanduser()
    try:
        parent_pid = int(argv[4])
    except ValueError:
        return 2
    expected = argv[5].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return 2
    return _apply_helper(zip_path, app_root, parent_pid, expected)


def start_update_check(app_root: Path, app_pid: int, on_status: StatusCallback,
                       on_apply: Callable[[], None], on_error: Callable[[str], None]) -> None:
    root = Path(app_root).resolve()
    def worker() -> None:
        try:
            on_status("Checking for updates…")
            manifest = _fetch_manifest()
            current, available = _read_current_version(root), str(manifest["version"])
            if _version_tuple(available) <= _version_tuple(current):
                on_status(f"Pigeon Poker is up to date ({current}).")
                return
            on_status(f"Downloading update {available}…")
            payload = _https_get(str(manifest["payload_url"]), max_bytes=MAX_COMPRESSED_BYTES, timeout=60)
            on_status("Verifying update package…")
            cache = _user_data_root() / "downloads"
            cache.mkdir(parents=True, exist_ok=True)
            zip_path = cache / f"pigeon-poker-v{available}.zip"
            zip_path.write_bytes(payload)
            stage = Path(tempfile.mkdtemp(prefix="pigeon-update-check-", dir=str(cache)))
            try:
                _validate_and_extract(payload, manifest, stage)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
            on_status("Update verified. Closing Pigeon Poker to apply it…")
            kwargs: dict[str, Any] = {"cwd": str(root), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--apply-update",
                              str(zip_path), str(root), str(app_pid), str(manifest["payload_sha256"]).lower()], **kwargs)
            on_apply()
        except Exception as exc:
            on_error(f"Update could not be completed: {exc}")
    threading.Thread(target=worker, name="PigeonPokerUpdateCheck", daemon=True).start()


if __name__ == "__main__":
    raise SystemExit(_helper_main(sys.argv))

# Release trigger: v1.3.4

# GitHub Actions release trigger for v1.3.4
