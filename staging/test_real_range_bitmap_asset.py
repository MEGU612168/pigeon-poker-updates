from __future__ import annotations

import base64
import hashlib
import struct
import sys
import types
import zlib
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

from pigeon_poker import range_image_catalog  # noqa: E402

ASSET = SOURCE_DIR / "pigeon_poker" / "range_tables_v2.bin"
EXPECTED_SIZE = 848418
EXPECTED_SHA256 = "61e2ea29dade57077908b8db5c37be0cde9ade6a237f85b00770dd57a109f715"
EXPECTED_IDS = set(range(128, 302))
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _validate_png(payload: bytes, expected_width: int, expected_height: int) -> None:
    assert payload.startswith(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while offset + 12 <= len(payload):
        length = struct.unpack_from(">I", payload, offset)[0]
        kind = payload[offset + 4:offset + 8]
        start = offset + 8
        end = start + length
        assert end + 4 <= len(payload), "truncated PNG chunk"
        body = kind + payload[start:end]
        expected_crc = struct.unpack_from(">I", payload, end)[0]
        assert (zlib.crc32(body) & 0xFFFFFFFF) == expected_crc, f"bad {kind!r} CRC"
        chunks.append((kind, payload[start:end]))
        offset = end + 4
        if kind == b"IEND":
            break

    assert offset == len(payload), "unexpected bytes after PNG IEND"
    assert chunks[0][0] == b"IHDR"
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", chunks[0][1]
    )
    assert (width, height) == (expected_width, expected_height)
    assert (bit_depth, color_type, compression, filtering, interlace) == (8, 2, 0, 0, 0)
    assert chunks[-1] == (b"IEND", b"")

    compressed = b"".join(data for kind, data in chunks if kind == b"IDAT")
    decoded = zlib.decompress(compressed)
    stride = 1 + width * 3
    assert len(decoded) == height * stride
    assert all(decoded[row * stride] <= 4 for row in range(height))


def test_embedded_python_carrier_loads_without_a_binary_file() -> None:
    data = ASSET.read_bytes()
    module_name = "pigeon_poker.range_tables_v2_asset"
    carrier = types.ModuleType(module_name)
    carrier.RANGE_TABLES_V2_B64 = base64.b64encode(data).decode("ascii")
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = carrier
    original_path = range_image_catalog._ASSET_PATH
    range_image_catalog._ASSET_PATH = ASSET.with_name("missing_range_tables_v2.bin")
    range_image_catalog._load_catalog.cache_clear()
    range_image_catalog.range_image_png.cache_clear()
    try:
        summary = range_image_catalog.range_catalog_summary()
        assert summary["source_image_count"] == 174
        assert summary["scenario_count"] == 174
        assert summary["asset_sha256"] == EXPECTED_SHA256
        for source_id in (128, 146, 147, 301):
            assert range_image_catalog.range_image_png(source_id).startswith(PNG_SIGNATURE)
    finally:
        range_image_catalog._ASSET_PATH = original_path
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
        range_image_catalog._load_catalog.cache_clear()
        range_image_catalog.range_image_png.cache_clear()


def test_real_174_bitmap_loads_and_every_source_image_renders() -> None:
    assert ASSET.is_file(), f"missing committed image asset: {ASSET}"
    data = ASSET.read_bytes()
    assert len(data) == EXPECTED_SIZE
    assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA256

    range_image_catalog._load_catalog.cache_clear()
    range_image_catalog.range_image_png.cache_clear()
    summary = range_image_catalog.range_catalog_summary()
    assert summary["source_image_count"] == 174
    assert summary["scenario_count"] == 174
    assert summary["asset_sha256"] == EXPECTED_SHA256

    frames = range_image_catalog._load_catalog()["frames"]
    assert set(frames) == EXPECTED_IDS
    for source_id in sorted(EXPECTED_IDS):
        png = range_image_catalog.range_image_png(source_id)
        _validate_png(png, summary["image_width"], summary["image_height"])


def test_create_range_photo_writes_real_rgb_pixels_into_native_tk_image() -> None:
    import tkinter as tk

    captured = {"writes": []}
    class FakePhotoImage:
        def __init__(self, *, master, width, height):
            captured["master"] = master
            self._width, self._height = width, height

        def width(self):
            return self._width

        def height(self):
            return self._height

        def put(self, data, to):
            captured["writes"].append((data, to))

        def subsample(self, x, y):
            self._width //= x
            self._height //= y
            return self

    original_photo_image = tk.PhotoImage
    tk.PhotoImage = FakePhotoImage
    try:
        photo = range_image_catalog.create_range_photo(object(), 136)
    finally:
        tk.PhotoImage = original_photo_image

    assert (photo.width(), photo.height()) == (546, 354)
    assert len(captured["writes"]) > 1
    assert captured["writes"][0][1] == (0, 0)
    assert all("#" in data for data, _to in captured["writes"])
    assert any(
        token not in {"#000000", "#ffffff"}
        for data, _to in captured["writes"]
        for token in data.replace("{", " ").replace("}", " ").split()
    )



if __name__ == "__main__":
    test_real_174_bitmap_loads_and_every_source_image_renders()
    test_embedded_python_carrier_loads_without_a_binary_file()
    test_create_range_photo_writes_real_rgb_pixels_into_native_tk_image()
    print("PASS: 174 PNG + PPM images, nonblack pixels, embedded asset and native Tk PhotoImage RGB writes")
