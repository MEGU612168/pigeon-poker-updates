from __future__ import annotations

import base64
import bz2
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source_1_3_101" / "pigeon_poker" / "preflop_gto_strategy.py"
RANKS = "AKQJT98765432"
FREQUENCIES = [[100,100,100,100,100,100,100,100,100,100,100,100,43],[100,100,100,100,100,100,100,69,53,53,0,0,0],[100,100,100,100,100,100,7,0,0,0,0,0,0],[100,87,41,100,100,68,0,0,0,0,0,0,0],[100,0,0,0,100,100,0,0,0,0,0,0,0],[0,0,0,0,0,100,16,0,0,0,0,0,0],[0,0,0,0,0,0,100,8,0,0,0,0,0],[0,0,0,0,0,0,0,100,9,0,0,0,0],[0,0,0,0,0,0,0,0,100,11,0,0,0],[0,0,0,0,0,0,0,0,0,51,6,0,0],[0,0,0,0,0,0,0,0,0,0,18,0,0],[0,0,0,0,0,0,0,0,0,0,0,17,0],[0,0,0,0,0,0,0,0,0,0,0,0,17]]
EXPECTED_WEIGHTED_COMBOS = 233.26


def hand_order() -> list[str]:
    result = []
    for row, high in enumerate(RANKS):
        for column, low in enumerate(RANKS):
            if row == column:
                result.append(high * 2)
            elif row < column:
                result.append(high + low + "s")
            else:
                result.append(low + high + "o")
    return result


def combo_count(hand: str) -> int:
    if len(hand) == 2:
        return 6
    return 4 if hand.endswith("s") else 12


def replace_utg_open_range() -> dict:
    source = SOURCE.read_text(encoding="utf-8")
    match = re.search(r"_DATA_B64 = \(\n(.*?)\n\)", source, flags=re.S)
    if not match:
        raise RuntimeError("Could not locate the compressed preflop dataset")

    encoded = "".join(re.findall(r'"([A-Za-z0-9+/=]+)"', match.group(1)))
    compact = json.loads(bz2.decompress(base64.b64decode(encoded)))

    if len(FREQUENCIES) != 13 or any(len(row) != 13 for row in FREQUENCIES):
        raise AssertionError("UTG screenshot matrix must be 13 by 13")
    hands = hand_order()
    if len(hands) != 169 or len(set(hands)) != 169:
        raise AssertionError("Canonical hand order is not 169 unique classes")

    weighted = sum(
        combo_count(hand) * FREQUENCIES[index // 13][index % 13] / 100.0
        for index, hand in enumerate(hands)
    )
    if abs(weighted - EXPECTED_WEIGHTED_COMBOS) > 0.005:
        raise AssertionError(f"UTG weighted combos mismatch: {weighted}")

    utg_node = {
        "i": "01_UTG_OPEN",
        "d": "UTG first-in, 100 BB, open to 2.0 BB; exact screenshot-derived 169-hand matrix",
        "p": "スクリーンショット (303).png",
        "a": ["allin", "raise", "fold"],
        "z": {"allin": 100.0, "raise": 2.0},
        "t": {"allin": 0.0, "raise": 17.6, "fold": 82.4},
        "h": [
            [0, frequency * 100, (100 - frequency) * 100]
            for row in FREQUENCIES
            for frequency in row
        ],
    }

    nodes = compact.setdefault("nodes", [])
    existing = [node for node in nodes if node.get("i") == "01_UTG_OPEN"]
    if existing:
        nodes.remove(existing[0])
    nodes.insert(0, utg_node)

    new_encoded = base64.b64encode(
        bz2.compress(
            json.dumps(compact, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
            compresslevel=9,
        )
    ).decode("ascii")
    wrapped = "_DATA_B64 = (\n" + "".join(
        f'    "{new_encoded[i:i + 100]}"\n'
        for i in range(0, len(new_encoded), 100)
    ) + ")"

    source = source[:match.start()] + wrapped + source[match.end():]

    # The old UTG-only inferred-range construction is obsolete now that node 01
    # is present in the screenshot dataset. Remove that fallback entirely.
    old_inference = re.compile(
        r"\n    # UTG first-in is not separately shown in the screenshots\..*?\n    _CACHE = \{",
        flags=re.S,
    )
    source, removed = old_inference.subn("\n    _CACHE = {", source, count=1)
    if removed != 1:
        raise RuntimeError("Could not remove the obsolete inferred UTG range block")

    source = source.replace(
        "27 screenshot-derived core nodes; hand-class matrix calibrated to ",
        "28 screenshot-derived nodes, including the exact UTG first-in matrix; remaining missing branches use ",
    )
    SOURCE.write_text(source, encoding="utf-8")

    # Re-read the edited source data and verify the raw UTG node survived.
    verify_match = re.search(r"_DATA_B64 = \(\n(.*?)\n\)", source, flags=re.S)
    verify_encoded = "".join(re.findall(r'"([A-Za-z0-9+/=]+)"', verify_match.group(1)))
    verify_compact = json.loads(bz2.decompress(base64.b64decode(verify_encoded)))
    verify = next(node for node in verify_compact["nodes"] if node["i"] == "01_UTG_OPEN")
    if verify["p"] != "スクリーンショット (303).png" or len(verify["h"]) != 169:
        raise AssertionError("UTG screenshot node failed round-trip verification")
    if "UTG first-in is not separately shown" in source:
        raise AssertionError("Obsolete inferred UTG branch still remains")
    return {
        "nodes": len(verify_compact["nodes"]),
        "hand_classes": len(verify["h"]),
        "weighted_raise_combos": round(weighted, 2),
        "raise_frequency_pct": 17.6,
        "open_size_bb": 2.0,
        "source_image": verify["p"],
    }


if __name__ == "__main__":
    print(json.dumps(replace_utg_open_range(), ensure_ascii=False))
