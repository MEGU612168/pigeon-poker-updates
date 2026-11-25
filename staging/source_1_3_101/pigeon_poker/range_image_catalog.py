from __future__ import annotations

import base64
import functools
import hashlib
import json
import lzma
import math
import struct
import zlib
from pathlib import Path
from typing import Any

_ASSET_PATH = Path(__file__).with_name("range_tables_v2.bin")
_EXPECTED_ASSET_SIZE = 848418
_EXPECTED_ASSET_SHA256 = "61e2ea29dade57077908b8db5c37be0cde9ade6a237f85b00770dd57a109f715"
_MAGIC = b"PPRIDX02"
_HEADER_SIZE = 18


def _read_asset_bytes() -> bytes:
    """Read the bitmap or its legacy-updater-compatible Python-embedded copy."""
    try:
        return _ASSET_PATH.read_bytes()
    except OSError as file_error:
        try:
            from .range_tables_v2_asset import RANGE_TABLES_V2_B64

            data = base64.b64decode(RANGE_TABLES_V2_B64, validate=True)
        except (ImportError, AttributeError, ValueError) as exc:
            raise RangeImageCatalogError(
                f"Range image asset is missing: {_ASSET_PATH.name}"
            ) from file_error
        if len(data) != _EXPECTED_ASSET_SIZE:
            raise RangeImageCatalogError("Embedded range image asset has an unexpected byte count")
        if hashlib.sha256(data).hexdigest() != _EXPECTED_ASSET_SHA256:
            raise RangeImageCatalogError("Embedded range image asset failed SHA-256 verification")
        return data


class RangeImageCatalogError(RuntimeError):
    """Raised when the original range-image catalogue is missing or corrupt."""


@functools.lru_cache(maxsize=1)
def _load_catalog() -> dict[str, Any]:
    data = _read_asset_bytes()
    if len(data) < _HEADER_SIZE or data[:8] != _MAGIC:
        raise RangeImageCatalogError("Range image asset has an unsupported header")

    width, height, count, raw_length = struct.unpack(">HHHI", data[8:18])
    if not (1 <= count <= 500 and 1 <= width <= 4096 and 1 <= height <= 4096):
        raise RangeImageCatalogError("Range image asset dimensions are invalid")
    expected = width * height * count
    if raw_length != expected:
        raise RangeImageCatalogError("Range image asset byte count is inconsistent")

    ids_end = _HEADER_SIZE + count * 2
    palette_end = ids_end + 768
    if len(data) <= palette_end:
        raise RangeImageCatalogError("Range image asset palette or payload is truncated")

    source_ids = struct.unpack(f">{count}H", data[_HEADER_SIZE:ids_end])
    palette = data[ids_end:palette_end]
    try:
        indexed_pixels = lzma.decompress(data[palette_end:])
    except lzma.LZMAError as exc:
        raise RangeImageCatalogError("Range image asset decompression failed") from exc
    if len(indexed_pixels) != expected:
        raise RangeImageCatalogError("Range image asset decompressed to the wrong size")
    if len(set(source_ids)) != count:
        raise RangeImageCatalogError("Range image asset contains duplicate screenshot IDs")

    frames = {}
    frame_size = width * height
    for i, source_id in enumerate(source_ids):
        frames[int(source_id)] = indexed_pixels[i * frame_size:(i + 1) * frame_size]

    try:
        # The authoritative action histories already live in the same embedded
        # 174-scenario dataset used by the CPU. A second JSON index went stale
        # or missing and could desynchronise source IDs from the bot's nodes.
        from .preflop_174_policy import _scenarios

        scenarios = tuple(_scenarios())
    except Exception as exc:
        raise RangeImageCatalogError("The embedded 174-scenario history index is unavailable") from exc
    entries = []
    for scenario in scenarios:
        source_id = int(scenario.get("id", -1))
        entries.append({
            "source_id": source_id,
            "source_file": f"screenshot_({source_id}).png",
            "active_position": str(scenario.get("position", "")).upper(),
            "history": list(scenario.get("history", []) or []),
            "verified": True,
            "prefix_complete": True,
        })
    if len(entries) != count:
        raise RangeImageCatalogError("The 174-scenario index does not cover all source images")
    entry_ids = {int(item["source_id"]) for item in entries}
    if entry_ids != set(frames):
        raise RangeImageCatalogError("Scenario IDs do not match the bitmap catalogue")
    duplicate_canonical = {}
    return {
        "width": width,
        "height": height,
        "palette": palette,
        "frames": frames,
        "entries": entries,
        "duplicate_canonical": duplicate_canonical,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _same_action(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if str(expected.get("position", "")).upper() != str(actual.get("position", "")).upper():
        return False
    action = str(expected.get("action", "")).lower()
    if action != str(actual.get("action", "")).lower():
        return False
    if action == "raise":
        try:
            expected_size = float(expected.get("size_bb"))
            actual_size = float(actual.get("amount_bb"))
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(expected_size) or not math.isfinite(actual_size):
            return False
        tolerance = max(0.12, abs(expected_size) * 0.04)
        return abs(expected_size - actual_size) <= tolerance
    return True


def _history_matches(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> bool:
    return len(expected) == len(actual) and all(
        _same_action(want, got) for want, got in zip(expected, actual)
    )


def resolve_range_image_for_situation(spot: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve only a unique, exact match among the 174 embedded histories."""
    if not isinstance(spot, dict):
        return None
    actor = str(spot.get("actor_position") or "").upper()
    records = list(spot.get("records", []) or [])
    actual = []
    for record in records:
        if not isinstance(record, dict):
            continue
        action = str(record.get("action", "")).lower()
        if action not in {"fold", "call", "check", "raise", "allin"}:
            continue
        actual.append({
            "position": str(record.get("position", "")).upper(),
            "action": action,
            "size_bb": record.get("amount_bb"),
        })
    from .preflop_174_policy import find_exact_preflop_174_scenario

    source_id = find_exact_preflop_174_scenario(actor, actual)
    if source_id is None:
        return None
    catalog = _load_catalog()
    metadata = next(
        (item for item in catalog["entries"] if int(item["source_id"]) == source_id),
        None,
    )
    if metadata is None or source_id not in catalog["frames"]:
        return None
    return {
        "source_id": source_id,
        "source_file": str(metadata.get("source_file", "")),
        "actor_position": actor,
        "match_mode": "exact",
        "matched_history_count": len(metadata.get("history", []) or []),
        "prefix_complete": True,
    }


def resolve_range_image_for_hand(table: Any, hand: Any, player_id: str) -> dict[str, Any] | None:
    """Resolve a live screenshot only for an exact, non-ambiguous source node."""
    from .preflop_174_policy import exact_preflop_174_source_image

    source_id = exact_preflop_174_source_image(table, hand, player_id)
    if source_id is None:
        return None
    catalog = _load_catalog()
    metadata = next(
        (item for item in catalog["entries"] if int(item["source_id"]) == source_id),
        None,
    )
    if metadata is None or source_id not in catalog["frames"]:
        return None
    return {
        "source_id": source_id,
        "source_file": str(metadata.get("source_file", "")),
        "actor_position": str(metadata.get("active_position", "")),
        "match_mode": "exact",
        "matched_history_count": len(metadata.get("history", []) or []),
        "prefix_complete": True,
    }

def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


@functools.lru_cache(maxsize=32)
def range_image_png(source_id: int) -> bytes:
    """Return a PNG bitmap of the selected original range table."""
    catalog = _load_catalog()
    source_id = int(source_id)
    indices = catalog["frames"].get(source_id)
    if indices is None:
        raise RangeImageCatalogError(f"Range screenshot #{source_id} is not in the image catalogue")

    width, height = catalog["width"], catalog["height"]
    palette = catalog["palette"]
    lookup = [bytes(palette[i:i + 3]) for i in range(0, 768, 3)]
    rows = []
    offset = 0
    for _ in range(height):
        index_row = indices[offset:offset + width]
        offset += width
        rgb_row = bytearray(width * 3)
        target = 0
        for index in index_row:
            rgb = lookup[index]
            rgb_row[target:target + 3] = rgb
            target += 3
        rows.append(b"\x00" + bytes(rgb_row))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    image_data = zlib.compress(b"".join(rows), level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", image_data)
        + _png_chunk(b"IEND", b"")
    )


def create_range_photo(master: Any, source_id: int):
    """Create a native Tk PhotoImage. Keep the returned object referenced by its window."""
    import tkinter as tk

    payload = base64.b64encode(range_image_png(int(source_id))).decode("ascii")
    try:
        image = tk.PhotoImage(master=master, data=payload, format="png")
        # Keep the original PNG in the source catalogue; only the Tk display is downscaled.
        # The source screenshots are 1092x707. Display the original bitmap at
        # half scale so the complete 13x13 matrix fits on ordinary Windows
        # work areas instead of being clipped by the monitor/taskbar bounds.
        if image.width() > 700 or image.height() > 550:
            image = image.subsample(2, 2)
        return image
    except tk.TclError as exc:
        raise RangeImageCatalogError(
            f"Windows could not load the source range image #{int(source_id)}: {exc}"
        ) from exc


def range_catalog_summary() -> dict[str, Any]:
    catalog = _load_catalog()
    return {
        "source_image_count": len(catalog["frames"]),
        "scenario_count": len(catalog["entries"]),
        "image_width": catalog["width"],
        "image_height": catalog["height"],
        "palette_entries": len(catalog["palette"]) // 3,
        "asset_sha256": catalog["sha256"],
    }
