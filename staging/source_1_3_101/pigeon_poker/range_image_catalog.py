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



_RANGE_LOOKUP_EVENT_FIELDS = (
    "type", "street", "player_id", "player", "action", "decision",
    "position", "is_all_in", "all_in", "jam", "target", "raise_to",
    "to_amount", "total_contribution", "target_amount", "amount", "paid",
)


def live_range_lookup_signature(
    hand: Any,
    *,
    current_hand_key: str = "",
    cash_busy: bool = False,
    cash_deal_busy: bool = False,
    cash_sitting_out: bool = False,
    dealer_index: Any = None,
) -> tuple[Any, ...]:
    """Return every live input that can change paid-range eligibility or matching.

    The UI previously cached a failed lookup using only event count, street,
    and actor. A lookup made while dealing/busy could therefore stay cached as
    unavailable after the busy flag cleared. Event values can also be amended
    without changing the list length. Snapshot the lookup-relevant inputs.
    """
    if hand is None:
        return (
            None, str(current_hand_key), bool(cash_busy),
            bool(cash_deal_busy), bool(cash_sitting_out), repr(dealer_index),
        )

    events = list(getattr(hand, "events", ()) or ())
    event_state = []
    for event in events:
        if isinstance(event, dict):
            event_state.append(tuple(
                (field, repr(event.get(field))) for field in _RANGE_LOOKUP_EVENT_FIELDS
            ))
        else:
            event_state.append(("event", repr(event)))

    players = list(getattr(hand, "players", ()) or ())
    seat_by_id = getattr(hand, "seat_by_id", {}) or {}
    player_state = []
    for player in players:
        player_id = str(getattr(player, "player_id", "") or "")
        seat = seat_by_id.get(player_id) if isinstance(seat_by_id, dict) else None
        player_state.append((
            player_id,
            str(getattr(player, "position", "") or ""),
            repr(seat),
            bool(getattr(player, "all_in", False)),
            repr(getattr(player, "stack", None)),
        ))

    return (
        id(hand),
        str(current_hand_key),
        str(getattr(hand, "street", "") or ""),
        str(getattr(hand, "next_to_act", "") or ""),
        bool(getattr(hand, "finished", False)),
        tuple(event_state),
        tuple(player_state),
        repr(getattr(hand, "dealer_index", None)),
        repr(dealer_index),
        repr(getattr(hand, "big_blind", None)),
        bool(cash_busy),
        bool(cash_deal_busy),
        bool(cash_sitting_out),
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
    """Resolve a paid image from an exact history plus live decision-state evidence."""
    from .preflop_174_policy import (
        PAID_RANGE_ALL_IN_POSITION_REQUIREMENTS,
        _normalise_action,
        exact_preflop_174_source_candidates,
    )

    actor_position, positions, candidates = exact_preflop_174_source_candidates(
        table, hand, player_id
    )
    if not candidates:
        return None

    catalog = _load_catalog()
    match_mode = "exact"

    if len(candidates) > 1:
        # Action menu differences disambiguate nodes that share the same
        # action history but have different legal decisions (e.g. all-in
        # versus call/fold-only versions of a squeeze pot).
        try:
            legal = hand.legal_actions(player_id)
            legal_actions = {
                _normalise_action(value)
                for value in (legal.get("actions", ()) if isinstance(legal, dict) else ())
            }
        except Exception:
            legal_actions = set()

        if legal_actions:
            compatible = []
            for scenario in candidates:
                option_actions = {
                    _normalise_action(option[0])
                    for option in scenario.get("action_options", [])
                    if isinstance(option, (list, tuple)) and option
                }
                if option_actions and option_actions.issubset(legal_actions):
                    compatible.append(scenario)
            if not compatible:
                return None
            largest_menu = max(
                len({
                    _normalise_action(option[0])
                    for option in scenario.get("action_options", [])
                    if isinstance(option, (list, tuple)) and option
                })
                for scenario in compatible
            )
            candidates = [
                scenario for scenario in compatible
                if len({
                    _normalise_action(option[0])
                    for option in scenario.get("action_options", [])
                    if isinstance(option, (list, tuple)) and option
                }) == largest_menu
            ]
            if len(candidates) == 1:
                match_mode = "exact-live-actions"

    if len(candidates) > 1:
        # The chart descriptions for 252/253 specify whether BTN joined CO
        # as an all-in player. That state is not represented in the action
        # sequence, so read the hand's actual all-in flags.
        actual_all_in_positions = {
            positions.get(str(getattr(player, "player_id", "") or ""))
            for player in (getattr(hand, "players", ()) or ())
            if bool(getattr(player, "all_in", False))
        }
        actual_all_in_positions.discard(None)
        constrained = [
            scenario for scenario in candidates
            if int(scenario.get("id", -1)) in PAID_RANGE_ALL_IN_POSITION_REQUIREMENTS
        ]
        if constrained:
            compatible = [
                scenario for scenario in candidates
                if (
                    int(scenario.get("id", -1)) not in PAID_RANGE_ALL_IN_POSITION_REQUIREMENTS
                    or actual_all_in_positions
                    == set(PAID_RANGE_ALL_IN_POSITION_REQUIREMENTS[int(scenario["id"])])
                )
            ]
            if not compatible:
                return None
            if len(compatible) < len(candidates):
                candidates = compatible
                if len(candidates) == 1:
                    match_mode = "exact-live-state"

    if len(candidates) > 1:
        # Several source IDs are true duplicate screenshots. Permit an alias
        # only when their embedded pixel buffers are byte-for-byte identical.
        frame_values = [
            catalog["frames"].get(int(scenario["id"]))
            for scenario in candidates
        ]
        if not frame_values or frame_values[0] is None or any(
            frame != frame_values[0] for frame in frame_values[1:]
        ):
            return None

        def canonical_key(scenario):
            source = str(scenario.get("history_parse_source", ""))
            return (
                0 if source == "full_header_manual_verified" else 1,
                int(scenario.get("id", 10**9)),
            )

        candidates = [min(candidates, key=canonical_key)]
        match_mode = "exact-identical-source-image"

    try:
        source_id = int(candidates[0]["id"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    metadata = next(
        (item for item in catalog["entries"] if int(item["source_id"]) == source_id),
        None,
    )
    if metadata is None or source_id not in catalog["frames"]:
        return None
    return {
        "source_id": source_id,
        "source_file": str(metadata.get("source_file", "")),
        "actor_position": str(metadata.get("active_position", actor_position or "")),
        "match_mode": match_mode,
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


@functools.lru_cache(maxsize=174)
def range_image_ppm(source_id: int) -> bytes:
    """Return an ASCII PPM (P3) bitmap accepted by native Windows Tk PhotoImage."""
    catalog = _load_catalog()
    source_id = int(source_id)
    indices = catalog["frames"].get(source_id)
    if indices is None:
        raise RangeImageCatalogError(f"Range screenshot #{source_id} is not in the image catalogue")

    width, height = catalog["width"], catalog["height"]
    palette = catalog["palette"]
    lookup = [tuple(palette[i:i + 3]) for i in range(0, 768, 3)]
    rows = []
    offset = 0
    for _ in range(height):
        values = []
        for index in indices[offset:offset + width]:
            red, green, blue = lookup[index]
            values.extend((str(red), str(green), str(blue)))
        offset += width
        rows.append(" ".join(values))
    header = f"P3\n{width} {height}\n255\n"
    return (header + "\n".join(rows) + "\n").encode("ascii")


def create_range_photo(master: Any, source_id: int):
    """Create a native Tk PhotoImage from an ASCII PPM payload."""
    import tkinter as tk

    source_id = int(source_id)
    payload = range_image_ppm(source_id).decode("ascii")
    try:
        # P3 is deliberately passed as plain ASCII data. Windows Tk's PPM
        # decoder rejected a base64-encoded binary P6 payload in native tests;
        # P3 avoids the binary/base64 ambiguity in Tk's -data option.
        image = tk.PhotoImage(master=master, data=payload, format="PPM");
        if image.width() <= 0 or image.height() <= 0:
            raise tk.TclError("Tk created an empty PhotoImage")
        # The source screenshots are 1092x707. Display at half scale so the
        # complete 13x13 matrix fits on ordinary Windows work areas.
        if image.width() > 700 or image.height() > 550:
            image = image.subsample(2, 2)
        return image
    except tk.TclError as exc:
        raise RangeImageCatalogError(
            f"Windows could not render the source range image #{source_id}: {exc}"
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
