from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

from pigeon_poker.range_image_catalog import (  # noqa: E402
    RangeImageCatalogError,
    _load_catalog,
    _read_asset_bytes,
    range_catalog_summary,
    range_image_png,
    resolve_range_image_for_situation,
)


def _spot_for_entry(entry: dict) -> dict:
    return {
        "actor_position": entry["active_position"],
        "records": [
            {
                "position": item["position"],
                "action": item["action"],
                "amount_bb": item.get("size_bb"),
            }
            for item in entry.get("history", [])
        ],
    }


def test_packaged_fragments_reconstruct_the_expected_binary_and_scenarios():
    raw = _read_asset_bytes()
    assert raw.startswith(b"PPRIDX02")
    assert len(raw) == 495114
    assert range_catalog_summary()["asset_sha256"] == (
        "92d9d11583658e1cac675bbb9879894da61b18afb15fa7a04145f84e1785acf8"
    )


def test_all_174_bitmap_frames_and_scenario_entries_are_present():
    catalog = _load_catalog()
    assert len(catalog["frames"]) == 174
    assert len(catalog["entries"]) == 174
    assert set(catalog["frames"]) == set(range(128, 302))
    verified = [item for item in catalog["entries"] if item.get("verified")]
    unverified = [item for item in catalog["entries"] if not item.get("verified")]
    assert len(verified) == 173
    assert [item["source_id"] for item in unverified] == [146]


def test_every_verified_source_scenario_resolves_without_inference():
    for entry in _load_catalog()["entries"]:
        resolved = resolve_range_image_for_situation(_spot_for_entry(entry))
        if entry.get("verified"):
            assert resolved is not None, entry["source_id"]
            assert resolved["source_id"] in range(128, 302)
            assert resolved["actor_position"] == entry["active_position"]
            assert resolved["match_mode"] in {"exact", "suffix"}
        else:
            assert resolved is None, entry["source_id"]


def test_complete_history_requires_exact_match_and_uncovered_history_is_rejected():
    source = next(
        item for item in _load_catalog()["entries"]
        if item["source_id"] == 133
    )
    assert resolve_range_image_for_situation(_spot_for_entry(source)) is not None
    wrong = {
        "actor_position": "HJ",
        "records": [{"position": "UTG", "action": "raise", "amount_bb": 99.0}],
    }
    assert resolve_range_image_for_situation(wrong) is None
    assert resolve_range_image_for_situation({"actor_position": "CO", "records": []}) is None


def test_manually_reviewed_scenarios_match_the_original_action_headers():
    by_id = {item["source_id"]: item for item in _load_catalog()["entries"]}
    expected = {
        225: ("BB", [("UTG", "fold", None), ("HJ", "raise", 2.0), ("CO", "fold", None), ("BTN", "fold", None), ("SB", "raise", 11.0)]),
        226: ("HJ", [("UTG", "fold", None), ("HJ", "raise", 2.0), ("CO", "fold", None), ("BTN", "fold", None), ("SB", "raise", 11.0), ("BB", "fold", None)]),
        229: ("SB", [("UTG", "fold", None), ("HJ", "raise", 2.0), ("CO", "fold", None), ("BTN", "fold", None), ("SB", "raise", 11.0), ("BB", "fold", None), ("HJ", "allin", None)]),
        240: ("CO", [("UTG", "fold", None), ("HJ", "fold", None), ("CO", "raise", 2.3), ("BTN", "raise", 7.5), ("SB", "raise", 21.0), ("BB", "allin", None)]),
        258: ("CO", [("UTG", "fold", None), ("HJ", "fold", None), ("CO", "raise", 2.3), ("BTN", "fold", None), ("SB", "call", None), ("BB", "raise", 11.0)]),
    }
    for source_id, (actor, history) in expected.items():
        entry = by_id[source_id]
        actual = [
            (item["position"], item["action"], item.get("size_bb"))
            for item in entry["history"]
        ]
        assert entry["verified"] and entry["active_position"] == actor, source_id
        assert actual == history, (source_id, actual)


def test_png_bitmaps_are_loadable_and_keep_original_table_proportions():
    for source_id in (128, 146, 174, 225, 258, 286, 301):
        png = range_image_png(source_id)
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert png[12:16] == b"IHDR"
        width = int.from_bytes(png[16:20], "big")
        height = int.from_bytes(png[20:24], "big")
        assert (width, height) == (545, 345)
        assert len(png) > 1000


def test_unknown_image_id_fails_loudly():
    try:
        range_image_png(999)
    except RangeImageCatalogError:
        return
    raise AssertionError("Unknown image IDs must not return a blank image")


def run_tests():
    tests = [
        test_packaged_fragments_reconstruct_the_expected_binary_and_scenarios,
        test_all_174_bitmap_frames_and_scenario_entries_are_present,
        test_every_verified_source_scenario_resolves_without_inference,
        test_complete_history_requires_exact_match_and_uncovered_history_is_rejected,
        test_manually_reviewed_scenarios_match_the_original_action_headers,
        test_png_bitmaps_are_loadable_and_keep_original_table_proportions,
        test_unknown_image_id_fails_loudly,
    ]
    print("CATALOG", range_catalog_summary())
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "source range image catalogue tests")


if __name__ == "__main__":
    run_tests()
