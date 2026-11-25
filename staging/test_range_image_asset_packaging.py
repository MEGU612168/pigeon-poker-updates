from __future__ import annotations

import hashlib
import importlib.util
import lzma
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

import pigeon_updater  # noqa: E402
from pigeon_poker import range_image_catalog  # noqa: E402


ASSET_MEMBER = "pigeon_poker/range_tables_v2.bin"


def _synthetic_bitmap_asset() -> bytes:
    width, height, count = 2, 2, 174
    source_ids = tuple(range(128, 302))
    raw_length = width * height * count
    header = b"PPRIDX02" + struct.pack(">HHHI", width, height, count, raw_length)
    ids = struct.pack(f">{count}H", *source_ids)
    palette = bytes(index % 256 for index in range(768))
    pixels = bytes(index % 256 for index in range(raw_length))
    return header + ids + palette + lzma.compress(pixels)


def _update_zip(asset: bytes) -> bytes:
    from io import BytesIO

    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("PigeonPoker.pyw", "from pigeon_poker.range_image_catalog import create_range_photo\n")
        archive.writestr("pigeon_updater.py", "# updater fixture\n")
        archive.writestr("VERSION.txt", "9.9.9\n")
        archive.writestr(ASSET_MEMBER, asset)
    return output.getvalue()


def test_runtime_catalog_loads_all_174_images_and_renders_146_147():
    asset = _synthetic_bitmap_asset()
    with tempfile.TemporaryDirectory() as tmp:
        asset_path = Path(tmp) / "range_tables_v2.bin"
        asset_path.write_bytes(asset)
        original_path = range_image_catalog._ASSET_PATH
        range_image_catalog._ASSET_PATH = asset_path
        range_image_catalog._load_catalog.cache_clear()
        range_image_catalog.range_image_png.cache_clear()
        try:
            summary = range_image_catalog.range_catalog_summary()
            assert summary["source_image_count"] == 174
            assert summary["scenario_count"] == 174
            assert summary["image_width"] == 2
            assert summary["image_height"] == 2
            assert set(range_image_catalog._load_catalog()["frames"]) == set(range(128, 302))
            for source_id in (128, 146, 147, 301):
                png = range_image_catalog.range_image_png(source_id)
                assert png.startswith(b"\x89PNG\r\n\x1a\n")
                assert png[12:16] == b"IHDR"
                assert int.from_bytes(png[16:20], "big") == 2
                assert int.from_bytes(png[20:24], "big") == 2
        finally:
            range_image_catalog._ASSET_PATH = original_path
            range_image_catalog._load_catalog.cache_clear()
            range_image_catalog.range_image_png.cache_clear()


def test_updater_allowlist_accepts_only_the_exact_bitmap_path():
    assert pigeon_updater._is_allowed_member(ASSET_MEMBER)
    assert not pigeon_updater._is_allowed_member("pigeon_poker/other.bin")
    assert not pigeon_updater._is_allowed_member("../pigeon_poker/range_tables_v2.bin")
    assert not pigeon_updater._is_allowed_member("pigeon_gto_plus/range_tables_v2.bin")


def test_updater_extracts_bitmap_and_verifies_its_independent_hash():
    asset = _synthetic_bitmap_asset()
    old_size = pigeon_updater.RANGE_IMAGE_ASSET_SIZE
    old_digest = pigeon_updater.RANGE_IMAGE_ASSET_SHA256
    pigeon_updater.RANGE_IMAGE_ASSET_SIZE = len(asset)
    pigeon_updater.RANGE_IMAGE_ASSET_SHA256 = hashlib.sha256(asset).hexdigest()
    payload = _update_zip(asset)
    manifest = {
        "version": "9.9.9",
        "payload_size": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "package_mode": "full",
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "extract"
            extracted = pigeon_updater._validate_and_extract(payload, manifest, destination)
            assert ASSET_MEMBER in extracted
            assert (destination / ASSET_MEMBER).read_bytes() == asset
    finally:
        pigeon_updater.RANGE_IMAGE_ASSET_SIZE = old_size
        pigeon_updater.RANGE_IMAGE_ASSET_SHA256 = old_digest


def test_updater_rejects_bitmap_with_wrong_hash_even_when_zip_hash_is_valid():
    expected = _synthetic_bitmap_asset()
    wrong = expected[:-1] + bytes([expected[-1] ^ 0x01])
    old_size = pigeon_updater.RANGE_IMAGE_ASSET_SIZE
    old_digest = pigeon_updater.RANGE_IMAGE_ASSET_SHA256
    pigeon_updater.RANGE_IMAGE_ASSET_SIZE = len(expected)
    pigeon_updater.RANGE_IMAGE_ASSET_SHA256 = hashlib.sha256(expected).hexdigest()
    payload = _update_zip(wrong)
    manifest = {
        "version": "9.9.9",
        "payload_size": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "package_mode": "full",
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "extract"
            try:
                pigeon_updater._validate_and_extract(payload, manifest, destination)
            except ValueError as exc:
                assert "174 range image asset" in str(exc)
            else:
                raise AssertionError("Updater accepted a bitmap with the wrong SHA-256")
            assert not destination.exists()
    finally:
        pigeon_updater.RANGE_IMAGE_ASSET_SIZE = old_size
        pigeon_updater.RANGE_IMAGE_ASSET_SHA256 = old_digest


def run_tests():
    tests = [
        test_runtime_catalog_loads_all_174_images_and_renders_146_147,
        test_updater_allowlist_accepts_only_the_exact_bitmap_path,
        test_updater_extracts_bitmap_and_verifies_its_independent_hash,
        test_updater_rejects_bitmap_with_wrong_hash_even_when_zip_hash_is_valid,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "174-range asset and update-packaging tests")


if __name__ == "__main__":
    run_tests()
