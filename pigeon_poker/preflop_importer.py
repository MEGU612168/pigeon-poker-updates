"""Import locally saved GTO Wizard preflop range exports into Pigeon Poker.

This module processes files the user has already saved/exported locally. It does
not log in to GTO Wizard, scrape the website, or send automated service requests.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html as html_lib
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

RANKS = "23456789TJQKA"
RANK_ORDER = "AKQJT98765432"
COLOR_ACTIONS = {
    "233,150,122": "raise",
    "143,188,139": "call",
    "109,162,192": "fold",
}


@dataclass(frozen=True)
class HandFrequency:
    hand: str
    raise_pct: float
    call_pct: float
    fold_pct: float


@dataclass
class ParseResult:
    source_format: str
    hands: dict[str, HandFrequency]
    warnings: list[str]


@dataclass
class ImportSummary:
    discovered: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    messages: list[str] | None = None

    def __post_init__(self) -> None:
        if self.messages is None:
            self.messages = []


def _normalise_hand(value: str) -> str:
    raw = re.sub(r"\s+", "", value)
    hand = raw[:2].upper() + raw[2:].lower()
    if len(hand) == 2 and hand[0] == hand[1] and hand[0] in RANKS:
        return hand
    if len(hand) == 3 and hand[0] != hand[1] and hand[2] in "so":
        if hand[0] not in RANKS or hand[1] not in RANKS:
            raise ValueError(f"Invalid hand class: {value!r}")
        if RANK_ORDER.index(hand[0]) > RANK_ORDER.index(hand[1]):
            hand = hand[1] + hand[0] + hand[2]
        return hand
    raise ValueError(f"Invalid hand class: {value!r}")


def _sort_key(hand: str) -> tuple[int, int, int]:
    if len(hand) == 2:
        return RANK_ORDER.index(hand[0]), RANK_ORDER.index(hand[1]), 0
    return RANK_ORDER.index(hand[0]), RANK_ORDER.index(hand[1]), 0 if hand.endswith("s") else 1


def _pct(value: Any) -> float:
    raw = str(value).strip().replace("%", "").replace(",", ".")
    result = float(raw or 0)
    if not 0 <= result <= 100:
        raise ValueError(f"Percentage outside 0..100: {value!r}")
    return result


def _rgb_key(value: str) -> str:
    nums = re.findall(r"\d+", value)
    return ",".join(str(int(x)) for x in nums[:3]) if len(nums) >= 3 else ""


def _css_layers(style: str) -> list[tuple[str, float]]:
    # Handles the nested rgb(...) parentheses inside linear-gradient(...).
    gradients = re.findall(r"linear-gradient\((?:[^()]|\([^()]*\))*\)", style, re.I)
    sizes = re.search(r"background-size\s*:\s*([^;]+)", style, re.I)
    if not gradients or not sizes:
        return []
    widths = []
    for size in sizes.group(1).split(","):
        match = re.search(r"([\d.]+)\s*%", size)
        if match:
            widths.append(float(match.group(1)))
    layers = []
    for gradient, width in zip(gradients, widths):
        color = re.search(r"rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)", gradient, re.I)
        if color:
            layers.append((_rgb_key(color.group(0)), width))
    return layers


class _RangeHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.cell_depth: int | None = None
        self.title_depth: int | None = None
        self.style = ""
        self.title_parts: list[str] = []
        self.cells: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "div":
            return
        values = {k.lower(): (v or "") for k, v in attrs}
        classes = set(values.get("class", "").split())
        if self.cell_depth is None and ({"rtc_strategy_range_normalized", "ra_table_cell"} & classes):
            self.cell_depth = self.depth
            self.style = values.get("style", "")
            self.title_parts = []
        elif self.cell_depth is not None and self.title_depth is None and "rtc_title" in classes:
            self.title_depth = self.depth
        self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "div":
            return
        level = self.depth - 1
        if self.title_depth == level:
            self.title_depth = None
        if self.cell_depth == level:
            title = re.sub(r"\s+", "", html_lib.unescape("".join(self.title_parts)))
            if title and self.style:
                self.cells.append((self.style, title))
            self.cell_depth = self.title_depth = None
            self.style = ""
            self.title_parts = []
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data: str) -> None:
        if self.title_depth is not None:
            self.title_parts.append(data)


def parse_gto_wizard_html(source: str) -> ParseResult:
    parser = _RangeHTMLParser()
    parser.feed(source)
    hands: dict[str, HandFrequency] = {}
    warnings: list[str] = []
    for style, raw_hand in parser.cells:
        try:
            hand = _normalise_hand(raw_hand)
        except ValueError:
            continue
        layers = _css_layers(style)
        if not layers:
            warnings.append(f"{hand}: no recognised CSS range layers")
            continue
        values = {"raise": 0.0, "call": 0.0, "fold": 0.0}
        previous = 0.0
        for color, boundary in layers:
            action = COLOR_ACTIONS.get(color)
            if action is None:
                raise ValueError(
                    f"{hand}: unrecognised action colour rgb({color}); "
                    "refusing to misclassify this frequency"
                )
            boundary = min(100.0, max(previous, boundary))
            values[action] += boundary - previous
            previous = boundary
        if previous < 99.5 and not any(COLOR_ACTIONS[c] == "fold" for c, _ in layers):
            values["fold"] += 100.0 - previous
        total = sum(values.values())
        if total and abs(total - 100.0) > 0.05:
            values = {key: value * 100.0 / total for key, value in values.items()}
        hands[hand] = HandFrequency(hand, values["raise"], values["call"], values["fold"])
    if not hands:
        raise ValueError("No GTO Wizard range cells were found in the HTML file.")
    if len(hands) != 169:
        warnings.append(
            f"Only {len(hands)} hand classes were parsed; a complete 169-class matrix was not confirmed."
        )
    if len(hands) != len(parser.cells):
        warnings.append(f"Parsed {len(hands)} hands from {len(parser.cells)} candidate cells.")
    return ParseResult("gtowizard_html", hands, warnings)


def parse_frequency_csv(source: str) -> ParseResult:
    reader = csv.DictReader(io.StringIO(source))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row.")
    headers = {name.strip().lower(): name for name in reader.fieldnames if name}
    if "hand" not in headers:
        raise ValueError("CSV must contain a Hand column.")
    columns = {name: headers.get(name) for name in ("raise", "call", "fold")}
    if not any(columns.values()):
        raise ValueError("CSV must contain Raise, Call, or Fold columns.")
    hands: dict[str, HandFrequency] = {}
    for row in reader:
        if not row.get(headers["hand"]):
            continue
        hand = _normalise_hand(row[headers["hand"]])
        values = {
            name: _pct(row[column]) if column and row.get(column) not in (None, "") else 0.0
            for name, column in columns.items()
        }
        present_total = sum(values[name] for name, column in columns.items() if column)
        missing = [name for name, column in columns.items() if not column]
        if missing and present_total <= 100.05:
            values[missing[0]] = max(0.0, 100.0 - present_total)
        total = sum(values.values())
        if total and abs(total - 100.0) > 0.15:
            raise ValueError(f"{hand}: action frequencies total {total:.3f}, not 100.")
        if total and total != 100:
            values = {key: value * 100.0 / total for key, value in values.items()}
        hands[hand] = HandFrequency(hand, values["raise"], values["call"], values["fold"])
    if not hands:
        raise ValueError("No hand rows were found in the CSV file.")
    warnings = [] if len(hands) == 169 else [
        f"Only {len(hands)} hand classes were parsed; a complete 169-class matrix was not confirmed."
    ]
    return ParseResult("frequency_csv", hands, warnings)


def parse_file(path: Path) -> ParseResult:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source = path.read_text(encoding="cp1252")
    if path.suffix.lower() == ".csv":
        return parse_frequency_csv(source)
    if any(marker in source for marker in (
        "rtc_strategy_range_normalized", "range_table_cell", "ra_table_cell"
    )):
        return parse_gto_wizard_html(source)
    raise ValueError(f"Unsupported file format: {path.name}")


def _load_metadata(path: Path, defaults: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(defaults)
    tokens = [token for token in re.split(r"[_-]+", path.stem.upper()) if token]
    players = re.search(r"(?:^|[_-])(\d+)\s*MAX(?:$|[_-])", path.stem, re.I)
    stack = re.search(r"(?:^|[_-])(\d+(?:\.\d+)?)\s*BB(?:$|[_-])", path.stem, re.I)
    positions = {"UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"}
    nodes = {"RFI", "OPEN", "VS_RFI", "VS_OPEN", "3BET", "VS_3BET", "4BET", "VS_4BET"}
    if players and "players" not in metadata:
        metadata["players"] = int(players.group(1))
    if stack and "stack_bb" not in metadata:
        metadata["stack_bb"] = float(stack.group(1))
    if "position" not in metadata:
        seat = next((token for token in tokens if token in positions), None)
        if seat:
            metadata["position"] = seat
    if "node" not in metadata:
        node = next((token for token in tokens if token in nodes), None)
        if node:
            metadata["node"] = node
    sidecar = path.with_suffix(".json")
    if sidecar.is_file():
        side = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(side, dict):
            raise ValueError(f"Metadata sidecar must be a JSON object: {sidecar.name}")
        metadata.update(side)
    for key in ("position", "node"):
        if metadata.get(key) is not None:
            metadata[key] = str(metadata[key]).strip().upper()
    for key in ("stack_bb", "ante_bb"):
        if metadata.get(key) not in (None, ""):
            metadata[key] = float(metadata[key])
    if metadata.get("players") not in (None, ""):
        metadata["players"] = int(metadata["players"])
    return metadata


def _context_key(metadata: dict[str, Any]) -> str:
    packed = json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def initialise_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS preflop_spots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_key TEXT NOT NULL UNIQUE,
            context_json TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_format TEXT NOT NULL,
            hand_count INTEGER NOT NULL,
            imported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS preflop_frequencies (
            spot_id INTEGER NOT NULL REFERENCES preflop_spots(id) ON DELETE CASCADE,
            hand TEXT NOT NULL,
            raise_pct REAL NOT NULL,
            call_pct REAL NOT NULL,
            fold_pct REAL NOT NULL,
            PRIMARY KEY (spot_id, hand)
        );
        CREATE INDEX IF NOT EXISTS idx_preflop_context ON preflop_spots(context_key);
        """)


def _store(db_path: Path, path: Path, parsed: ParseResult, metadata: dict[str, Any]) -> str:
    initialise_database(db_path)
    raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    context_key = _context_key(metadata)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        current = conn.execute(
            "SELECT id, source_sha256 FROM preflop_spots WHERE context_key=?", (context_key,)
        ).fetchone()
        if current and current[1] == raw_hash:
            return "skipped"
        if current:
            spot_id = current[0]
            conn.execute(
                """UPDATE preflop_spots SET context_json=?, source_name=?, source_sha256=?,
                   source_format=?, hand_count=?, imported_at=? WHERE id=?""",
                (json.dumps(metadata, ensure_ascii=False, sort_keys=True), path.name,
                 raw_hash, parsed.source_format, len(parsed.hands), now, spot_id),
            )
            conn.execute("DELETE FROM preflop_frequencies WHERE spot_id=?", (spot_id,))
            status = "updated"
        else:
            cur = conn.execute(
                """INSERT INTO preflop_spots
                   (context_key, context_json, source_name, source_sha256, source_format, hand_count, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (context_key, json.dumps(metadata, ensure_ascii=False, sort_keys=True), path.name,
                 raw_hash, parsed.source_format, len(parsed.hands), now),
            )
            spot_id = cur.lastrowid
            status = "imported"
        conn.executemany(
            "INSERT INTO preflop_frequencies VALUES (?, ?, ?, ?, ?)",
            [(spot_id, item.hand, item.raise_pct, item.call_pct, item.fold_pct)
             for item in sorted(parsed.hands.values(), key=lambda x: _sort_key(x.hand))],
        )
    return status


def import_folder(input_path: Path, db_path: Path,
                  defaults: dict[str, Any] | None = None) -> ImportSummary:
    defaults = defaults or {}
    if input_path.is_file():
        paths = [input_path]
    elif input_path.is_dir():
        paths = sorted(p for p in input_path.rglob("*")
                       if p.is_file() and p.suffix.lower() in {".html", ".htm", ".txt", ".csv"})
    else:
        raise FileNotFoundError(input_path)
    result = ImportSummary(discovered=len(paths))
    for path in paths:
        try:
            parsed = parse_file(path)
            metadata = _load_metadata(path, defaults)
            if not any(metadata.get(key) for key in ("position", "node", "tree")):
                metadata["unmapped_label"] = path.stem
            status = _store(db_path, path, parsed, metadata)
            setattr(result, status, getattr(result, status) + 1)
            result.messages.append(f"{status}: {path.name} ({len(parsed.hands)} hands)")
            result.messages.extend(f"warning: {note}" for note in parsed.warnings[:5])
        except Exception as exc:
            result.failed += 1
            result.messages.append(f"failed: {path.name}: {exc}")
    return result


def lookup_frequencies(db_path: Path, *, position: str, node: str, hand: str,
                       stack_bb: float | None = None, players: int | None = None) -> list[dict[str, Any]]:
    hand = _normalise_hand(hand)
    where = [
        "json_extract(s.context_json, '$.position')=?",
        "json_extract(s.context_json, '$.node')=?",
        "f.hand=?",
    ]
    params: list[Any] = [position.upper(), node.upper(), hand]
    if stack_bb is not None:
        where.append("json_extract(s.context_json, '$.stack_bb')=?")
        params.append(float(stack_bb))
    if players is not None:
        where.append("json_extract(s.context_json, '$.players')=?")
        params.append(int(players))
    query = """SELECT s.context_json, s.source_name, s.source_format,
                      f.raise_pct, f.call_pct, f.fold_pct
               FROM preflop_spots s JOIN preflop_frequencies f ON f.spot_id=s.id
               WHERE """ + " AND ".join(where)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def export_gto_plus(db_path: Path, *, spot_id: int, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT hand, raise_pct, call_pct, fold_pct FROM preflop_frequencies WHERE spot_id=? ORDER BY hand",
            (spot_id,),
        ).fetchall()
    if not rows:
        raise ValueError(f"No imported spot found with id {spot_id}")
    for index, action in enumerate(("raise", "call", "fold"), start=1):
        values = []
        for hand, raise_pct, call_pct, fold_pct in rows:
            pct = (raise_pct, call_pct, fold_pct)[index - 1]
            values.append(f"[{pct:.2f}]{hand}[/{pct:.2f}]")
        (output_dir / f"{action}_range.txt").write_text(",".join(values), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import saved GTO Wizard preflop HTML/CSV files into Pigeon Poker."
    )
    parser.add_argument("input", type=Path, help="Saved export file or folder")
    parser.add_argument("--db", type=Path, default=Path("pigeon_preflop.sqlite3"))
    parser.add_argument("--context", type=Path, help="JSON file with shared spot metadata")
    args = parser.parse_args(argv)
    defaults = json.loads(args.context.read_text(encoding="utf-8")) if args.context else {}
    summary = import_folder(args.input, args.db, defaults)
    print(json.dumps({
        "discovered": summary.discovered, "imported": summary.imported,
        "updated": summary.updated, "skipped": summary.skipped,
        "failed": summary.failed, "messages": summary.messages,
    }, ensure_ascii=False, indent=2))
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
