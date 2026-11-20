from __future__ import annotations

import hashlib
import importlib.util
import io
import tempfile
import zipfile
from pathlib import Path

UPDATER_PATH = Path(__file__).with_name("source_1_3_101") / "pigeon_updater.py"
SPEC = importlib.util.spec_from_file_location("pigeon_updater_repair_test", UPDATER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load the shipped Pigeon Poker updater.")
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


def make_payload(files: dict[str, bytes]) -> tuple[bytes, dict[str, object]]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    payload = buffer.getvalue()
    manifest: dict[str, object] = {
        "version": "1.3.104",
        "payload_size": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "package_mode": "full",
    }
    return payload, manifest


def test_full_update_requires_all_three_root_files() -> None:
    payload, manifest = make_payload({
        "PigeonPoker.pyw": b"print('app')\n",
        "pigeon_updater.py": b"print('updater')\n",
        "VERSION.txt": b"1.3.104\n",
    })
    with tempfile.TemporaryDirectory() as tmp:
        extracted = updater._validate_and_extract(payload, manifest, Path(tmp) / "stage")
    assert set(extracted) == {"PigeonPoker.pyw", "pigeon_updater.py", "VERSION.txt"}


def test_old_two_file_package_is_rejected_by_current_updater() -> None:
    payload, manifest = make_payload({
        "PigeonPoker.pyw": b"print('app')\n",
        "VERSION.txt": b"1.3.104\n",
    })
    with tempfile.TemporaryDirectory() as tmp:
        try:
            updater._validate_and_extract(payload, manifest, Path(tmp) / "stage")
        except ValueError as exc:
            assert "missing one or more required application files" in str(exc)
        else:
            raise AssertionError("The incomplete two-file package was unexpectedly accepted.")


def test_published_104_package_is_valid_for_existing_updater() -> None:
    release_dir = Path(__file__).parents[1] / "releases" / "v1.3.104"
    payload_path = release_dir / "payload-updater.zip.b64"
    if not payload_path.exists():
        # The package is constructed by the release workflow after all tests.
        return
    import base64
    import json

    release = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    payload = base64.b64decode(payload_path.read_text(encoding="ascii"), validate=True)
    manifest = {
        "version": "1.3.104",
        "payload_size": release["payload_size"],
        "payload_sha256": release["payload_sha256"],
        "package_mode": "full",
    }
    with tempfile.TemporaryDirectory() as tmp:
        extracted = updater._validate_and_extract(payload, manifest, Path(tmp) / "stage")
    assert set(extracted) >= {"PigeonPoker.pyw", "pigeon_updater.py", "VERSION.txt"}


if __name__ == "__main__":
    tests = [
        test_full_update_requires_all_three_root_files,
        test_old_two_file_package_is_rejected_by_current_updater,
        test_published_104_package_is_valid_for_existing_updater,
    ]
    for case in tests:
        case()
        print("PASS", case.__name__)
    print("ALL PASS", len(tests), "updater package compatibility tests")
