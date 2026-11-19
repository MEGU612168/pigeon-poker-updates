"""Shared local Study Wallet storage used by Study Wallet and Pigeon Poker.

No real payment rails are connected. All amounts are integer USD cents.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any

SCHEMA_VERSION = 1
TEST_RESET_KEY = "pigeon_test_reset_v1_2_6_zero_balance_complete"
SNAPSHOT_FILENAME = "study_time_balance.json"
DB_FILENAME = "study_wallet.sqlite3"
TIMER_DATA_FILENAME = "simple_timer_data.json"
_DISCOVERY_CACHE: dict[str, Any] = {"key": "", "at": 0.0, "files": []}


def shared_wallet_dir(environ=None, home=None) -> Path:
    env = os.environ if environ is None else environ
    appdata = str(env.get("APPDATA", "")).strip()
    if appdata:
        return Path(appdata).expanduser() / "StudyWallet"
    return (home or Path.home()) / ".config" / "StudyWallet"


def shared_wallet_db_path(environ=None, home=None) -> Path:
    return shared_wallet_dir(environ, home) / DB_FILENAME


def shared_study_snapshot_path(environ=None, home=None) -> Path:
    return shared_wallet_dir(environ, home) / SNAPSHOT_FILENAME


def _nonnegative_seconds(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _timer_json_total(timer_path: Path) -> int:
    """Read only Study counters from the original Focus Timer data file."""
    if timer_path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError("Focus Timer data file is unexpectedly large")
    raw = json.loads(timer_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("Focus Timer data is not a JSON object")
    history = raw.get("history", {})
    if not isinstance(history, dict):
        history = {}
    historical = sum(_nonnegative_seconds(value) for value in history.values())
    current = raw.get("calendar_study") if "calendar_study" in raw else raw.get("study", 0)
    return historical + _nonnegative_seconds(current)


def _discovery_roots(target: Path) -> list[Path]:
    candidates = [target.parent, Path.cwd(), Path(__file__).resolve().parent,
                  Path(__file__).resolve().parent.parent, Path.home()]
    for key in ("USERPROFILE", "OneDrive", "OneDriveCommercial", "APPDATA", "LOCALAPPDATA"):
        value = str(os.environ.get(key, "")).strip()
        if value:
            candidates.append(Path(value).expanduser())
    roots, seen = [], set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            key = os.path.normcase(str(resolved))
            if key not in seen and resolved.is_dir():
                seen.add(key)
                roots.append(resolved)
        except (OSError, RuntimeError):
            continue
    return roots


def _timer_script_sibling(path: Path) -> bool:
    try:
        return (any(path.parent.glob("Focus_Timer_ULTIMATE_PRO*.pyw"))
                or any(path.parent.glob("FocusTimer*.pyw")))
    except OSError:
        return False


def _discover_timer_files(target: Path) -> list[Path]:
    """Find existing timer data without requiring the old manual-link button.

    A saved explicit path hint wins. Otherwise search common user folders with
    bounds and a short cache so the Cashier's live refresh remains inexpensive.
    """
    hint = target.parent / "focus_timer_data_path.txt"
    try:
        value = hint.read_text(encoding="utf-8-sig").strip()
        candidate = Path(value).expanduser() if value else None
        if candidate and candidate.is_file() and candidate.name.lower() == TIMER_DATA_FILENAME:
            return [candidate.resolve()]
    except (OSError, ValueError):
        pass

    roots = _discovery_roots(target)
    cache_key = "|".join(os.path.normcase(str(root)) for root in roots)
    now_mono = time.monotonic()
    if (_DISCOVERY_CACHE.get("key") == cache_key
            and now_mono - float(_DISCOVERY_CACHE.get("at", 0.0)) < 20):
        return [Path(item) for item in _DISCOVERY_CACHE.get("files", []) if Path(item).is_file()]

    found: dict[str, Path] = {}
    for root in roots:
        direct = root / TIMER_DATA_FILENAME
        try:
            if direct.is_file():
                resolved = direct.resolve()
                found[os.path.normcase(str(resolved))] = resolved
        except OSError:
            pass

    direct_nonzero = False
    for direct in found.values():
        try:
            if _timer_json_total(direct) > 0:
                direct_nonzero = True
                break
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
    if not direct_nonzero:
        try:
            home = Path.home().resolve()
        except OSError:
            home = None
        if home and home.is_dir():
            started, dirs_seen = time.monotonic(), 0
            skip_names = {".git", ".cache", "__pycache__", "node_modules", ".venv", "venv",
                          "temp", "tmp", "$recycle.bin", "system volume information",
                          "windows", "program files", "program files (x86)", "windowsapps"}
            skip_relative = {os.path.normcase("AppData/Local/Temp"),
                             os.path.normcase("AppData/Local/Packages"),
                             os.path.normcase("AppData/Local/Microsoft")}
            for current, dirs, files in os.walk(home, topdown=True, onerror=lambda _exc: None):
                dirs_seen += 1
                rel = os.path.relpath(current, home)
                dirs[:] = [name for name in dirs if name.lower() not in skip_names
                           and os.path.normcase(os.path.join(rel, name).replace("\\", "/")) not in skip_relative]
                if TIMER_DATA_FILENAME in files:
                    candidate = Path(current) / TIMER_DATA_FILENAME
                    try:
                        resolved = candidate.resolve()
                        found[os.path.normcase(str(resolved))] = resolved
                    except OSError:
                        pass
                if dirs_seen >= 12000 or time.monotonic() - started > 6.0:
                    break

    result = list(found.values())
    _DISCOVERY_CACHE.update({"key": cache_key, "at": now_mono, "files": [str(item) for item in result]})
    return result


def _read_timer_source_file(timer_path: Path) -> dict[str, Any]:
    total = _timer_json_total(timer_path)
    updated = datetime.fromtimestamp(timer_path.stat().st_mtime, timezone.utc).astimezone().isoformat(timespec="seconds")
    return {"connected": True, "total_study_seconds": total, "updated_at": updated,
            "source": "Focus Timer original data file", "error": "",
            "snapshot_path": str(timer_path), "direct_source": True}


def read_study_snapshot(path=None) -> dict[str, Any]:
    target = Path(path) if path is not None else shared_study_snapshot_path()
    last_error = None

    valid_timer_rows = []
    for timer_path in _discover_timer_files(target):
        try:
            total = _timer_json_total(timer_path)
            rank = (1 if total > 0 else 0, 1 if _timer_script_sibling(timer_path) else 0,
                    total, timer_path.stat().st_mtime)
            valid_timer_rows.append((rank, timer_path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
    if valid_timer_rows:
        _, best_path = max(valid_timer_rows, key=lambda row: row[0])
        try:
            return _read_timer_source_file(best_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc

    candidates = [target]
    if target.name == SNAPSHOT_FILENAME and target.parent.name == "StudyWallet":
        candidates.append(target.parent.parent / "PigeonPoker" / SNAPSHOT_FILENAME)
    for candidate in candidates:
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != SCHEMA_VERSION:
                raise ValueError("Unsupported Study Time snapshot format")
            seconds = int(raw.get("total_study_seconds", -1))
            if seconds < 0:
                raise ValueError("Negative Study seconds")
            return {"connected": True, "total_study_seconds": seconds,
                    "updated_at": str(raw.get("updated_at", "")),
                    "source": str(raw.get("source", "Focus Timer")), "error": "",
                    "snapshot_path": str(candidate)}
        except FileNotFoundError as exc:
            last_error = exc
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
    return {"connected": False, "total_study_seconds": 0, "updated_at": "",
            "source": "Focus Timer", "error":
            f"Focus Timer data/export not found or invalid after automatic search: {last_error or target}"}


def allowance_cents(total_study_seconds: int) -> int:
    return max(0, int(total_study_seconds)) // 3600 * 100


class StudyWalletStore:
    """SQLite-backed shared wallet. Safe for the Wallet and Pigeon to open together."""

    def __init__(self, db_path=None, snapshot_path=None):
        self.db_path = Path(db_path) if db_path else shared_wallet_db_path()
        self.db_path = self.db_path.expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.snapshot_path = Path(snapshot_path) if snapshot_path else shared_study_snapshot_path()
        self._initialize()

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=20, isolation_level=None)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA busy_timeout=20000")
            con.execute("PRAGMA foreign_keys=ON")
            yield con
        finally:
            con.close()

    def _initialize(self):
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""CREATE TABLE IF NOT EXISTS cashier_transactions (
                transaction_id TEXT PRIMARY KEY,
                played_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                delta_cents INTEGER NOT NULL,
                balance_after_cents INTEGER NOT NULL,
                recipient TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT ''
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_cashier_played ON cashier_transactions(played_at DESC)")
            con.execute("""CREATE TABLE IF NOT EXISTS study_redemptions (
                transaction_id TEXT PRIMARY KEY,
                redeemed_at TEXT NOT NULL,
                amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                balance_after_cents INTEGER NOT NULL DEFAULT 0,
                total_study_seconds INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT ''
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS wallet_account (
                account_id INTEGER PRIMARY KEY CHECK(account_id=1),
                balance_cents INTEGER NOT NULL DEFAULT 0,
                live_poker_stack_cents INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS wallet_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )""")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            latest = con.execute("SELECT balance_after_cents FROM cashier_transactions ORDER BY rowid DESC LIMIT 1").fetchone()
            seed = int(latest[0]) if latest else 0
            con.execute("INSERT OR IGNORE INTO wallet_account(account_id,balance_cents,live_poker_stack_cents,updated_at) VALUES(1,?,0,?)", (seed, now))
            con.execute("""INSERT OR IGNORE INTO study_redemptions
                (transaction_id,redeemed_at,amount_cents,balance_after_cents,total_study_seconds,note)
                SELECT transaction_id,played_at,delta_cents,balance_after_cents,0,note
                FROM cashier_transactions WHERE kind='study-time-deposit' AND delta_cents>0""")

    def is_test_reset_complete(self) -> bool:
        with self._connect() as con:
            return con.execute("SELECT 1 FROM wallet_meta WHERE key=?", (TEST_RESET_KEY,)).fetchone() is not None

    def reset_for_test_stage(self, initial_balance_cents: int = 0) -> bool:
        """One-time clean test reset: clear every wallet/poker ledger and start at $0.

        The Focus Timer snapshot is deliberately not modified. Since this is a
        fresh wallet, all cumulative Study hours are initially available to
        redeem; no previous test deposits are carried into the new ledger.
        """
        initial = max(0, int(initial_balance_cents))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM wallet_meta WHERE key=?", (TEST_RESET_KEY,)).fetchone():
                con.execute("ROLLBACK")
                return False
            # Reset all test-stage wallet activity, including old Study deposits.
            con.execute("DELETE FROM cashier_transactions")
            con.execute("DELETE FROM study_redemptions")
            con.execute(
                "UPDATE wallet_account SET balance_cents=?,live_poker_stack_cents=0,updated_at=? WHERE account_id=1",
                (initial, now),
            )
            con.execute("COMMIT")
            return True

    def mark_test_reset_complete(self):
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute("INSERT OR REPLACE INTO wallet_meta(key,value) VALUES(?,?)", (TEST_RESET_KEY, now))

    def redeemed_study_cents(self) -> int:
        with self._connect() as con:
            row = con.execute("SELECT COALESCE(SUM(amount_cents),0) FROM study_redemptions").fetchone()
        return max(0, int(row[0]))

    def import_legacy_once(self, legacy_db_path, initial_balance_cents=0):
        """Import the previous Pigeon-local Cashier ledger once, preserving history."""
        source = Path(legacy_db_path).expanduser().resolve()
        if source == self.db_path:
            return {"imported": 0, "balance_cents": self.get_balance(initial_balance_cents)}
        with self._connect() as con:
            marker = con.execute("SELECT value FROM wallet_meta WHERE key='legacy_pigeon_import_v1'").fetchone()
            if marker:
                return {"imported": 0, "balance_cents": self.get_balance(initial_balance_cents)}
            imported = 0
            latest_balance = None
            shared_had_activity = con.execute("SELECT COUNT(*) FROM cashier_transactions").fetchone()[0] > 0
            if source.is_file():
                old = sqlite3.connect(source)
                old.row_factory = sqlite3.Row
                try:
                    has_table = old.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cashier_transactions'").fetchone()
                    if has_table:
                        rows = old.execute("SELECT * FROM cashier_transactions ORDER BY rowid").fetchall()
                        for row in rows:
                            con.execute("""INSERT OR IGNORE INTO cashier_transactions
                                (transaction_id,played_at,kind,delta_cents,balance_after_cents,recipient,note)
                                VALUES(?,?,?,?,?,?,?)""",
                                (row["transaction_id"], row["played_at"], row["kind"], row["delta_cents"],
                                 row["balance_after_cents"], row["recipient"], row["note"]))
                            imported += 1
                        if rows:
                            latest_balance = int(rows[-1]["balance_after_cents"])
                finally:
                    old.close()
            current = con.execute("SELECT balance_cents FROM wallet_account WHERE account_id=1").fetchone()
            # Never overwrite a wallet that has already been used by Study Wallet.
            # On a fresh shared DB, migrate the last known Pigeon balance.
            if not shared_had_activity:
                seed = latest_balance if latest_balance is not None else max(0, int(initial_balance_cents))
                con.execute("UPDATE wallet_account SET balance_cents=?,updated_at=? WHERE account_id=1",
                            (seed, datetime.now(timezone.utc).isoformat(timespec="seconds")))
            else:
                seed = int(current[0]) if current else 0
            con.execute("INSERT INTO wallet_meta(key,value) VALUES('legacy_pigeon_import_v1',?)",
                        (json.dumps({"source": str(source), "imported": imported}),))
            return {"imported": imported, "balance_cents": seed}

    def is_initialized(self) -> bool:
        """True only after legacy migration and the zero-balance test reset finish."""
        with self._connect() as con:
            legacy = con.execute("SELECT 1 FROM wallet_meta WHERE key='legacy_pigeon_import_v1'").fetchone()
            reset = con.execute("SELECT 1 FROM wallet_meta WHERE key=?", (TEST_RESET_KEY,)).fetchone()
        return legacy is not None and reset is not None

    def get_balance(self, default=0) -> int:
        with self._connect() as con:
            row = con.execute("SELECT balance_cents FROM wallet_account WHERE account_id=1").fetchone()
            if row is None:
                return max(0, int(default))
            return int(row[0])

    def set_balance(self, balance_cents: int):
        balance = int(balance_cents)
        if balance < 0:
            raise ValueError("Wallet balance cannot be negative")
        with self._connect() as con:
            con.execute("UPDATE wallet_account SET balance_cents=?,updated_at=? WHERE account_id=1",
                        (balance, datetime.now(timezone.utc).isoformat(timespec="seconds")))

    def set_live_poker_stack(self, stack_cents: int):
        stack = max(0, int(stack_cents))
        with self._connect() as con:
            con.execute("UPDATE wallet_account SET live_poker_stack_cents=?,updated_at=? WHERE account_id=1",
                        (stack, datetime.now(timezone.utc).isoformat(timespec="seconds")))

    def get_live_poker_stack_cents(self) -> int:
        with self._connect() as con:
            row = con.execute("SELECT live_poker_stack_cents FROM wallet_account WHERE account_id=1").fetchone()
        return max(0, int(row[0])) if row else 0

    def record(self, kind: str, delta_cents: int, balance_after_cents: int,
               *, recipient="", note="", transaction_id=None):
        kind = str(kind).strip()
        delta, balance = int(delta_cents), int(balance_after_cents)
        if not kind or balance < 0:
            raise ValueError("Invalid wallet transaction")
        txid = transaction_id or uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("""INSERT INTO cashier_transactions
                (transaction_id,played_at,kind,delta_cents,balance_after_cents,recipient,note)
                VALUES(?,?,?,?,?,?,?)""", (txid, now, kind, delta, balance, str(recipient), str(note)))
            con.execute("UPDATE wallet_account SET balance_cents=?,updated_at=? WHERE account_id=1", (balance, now))
            con.execute("COMMIT")
        return txid

    def deposit_study_time(self, amount_dollars: int) -> dict[str, int]:
        amount = int(amount_dollars)
        if amount <= 0:
            raise ValueError("Deposit must be at least $1")
        amount_cents = amount * 100
        if not self.is_initialized():
            raise ValueError("共有ウォレット台帳が初期化されていません。Pigeon Pokerを一度起動してから、もう一度お試しください。Focus Timerの履歴は変更しません。")
        snapshot = read_study_snapshot(self.snapshot_path)
        if not snapshot["connected"]:
            raise ValueError("Focus Timer data was not found. Start Focus Timer once, then refresh; existing timer files are searched automatically.")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            # Re-read the snapshot immediately before committing, so live Study
            # updates and already-redeemed hours cannot be double-spent.
            snapshot = read_study_snapshot(self.snapshot_path)
            if not snapshot["connected"]:
                con.execute("ROLLBACK")
                raise ValueError("Focus Timer snapshot is unavailable")
            earned = allowance_cents(snapshot["total_study_seconds"])
            redeemed_row = con.execute("SELECT COALESCE(SUM(amount_cents),0) FROM study_redemptions").fetchone()
            redeemed = max(0, int(redeemed_row[0]))
            available = max(0, earned - redeemed)
            if amount_cents > available:
                con.execute("ROLLBACK")
                raise ValueError(f"Only ${available // 100:,} is currently available")
            row = con.execute("SELECT balance_cents FROM wallet_account WHERE account_id=1").fetchone()
            balance = int(row[0]) + amount_cents
            txid = uuid.uuid4().hex
            con.execute("""INSERT INTO cashier_transactions
                (transaction_id,played_at,kind,delta_cents,balance_after_cents,recipient,note)
                VALUES(?,?,?,?,?,?,?)""",
                (txid, now, "study-time-deposit", amount_cents, balance, "",
                 f"Redeemed {amount} cumulative Study hours at $1/hour"))
            con.execute("""INSERT INTO study_redemptions
                (transaction_id,redeemed_at,amount_cents,balance_after_cents,total_study_seconds,note)
                VALUES(?,?,?,?,?,?)""",
                (txid, now, amount_cents, balance, snapshot["total_study_seconds"],
                 f"Redeemed {amount} cumulative Study hours at $1/hour"))
            con.execute("UPDATE wallet_account SET balance_cents=?,updated_at=? WHERE account_id=1", (balance, now))
            con.execute("COMMIT")
            return {"deposited_cents": amount_cents, "balance_cents": balance,
                    "remaining_allowance_cents": available - amount_cents,
                    "total_study_seconds": snapshot["total_study_seconds"]}

    def depositable_cents(self) -> int:
        snapshot = read_study_snapshot(self.snapshot_path)
        if not snapshot["connected"]:
            return 0
        with self._connect() as con:
            redeemed = int(con.execute("SELECT COALESCE(SUM(amount_cents),0) FROM study_redemptions").fetchone()[0])
        return max(0, allowance_cents(snapshot["total_study_seconds"]) - redeemed)

    def poker_pnl_cents(self) -> int:
        with self._connect() as con:
            flows = int(con.execute("""SELECT COALESCE(SUM(delta_cents),0) FROM cashier_transactions
                WHERE kind IN ('buy-in','manual-rebuy','auto-rebuy','cash-out')""").fetchone()[0])
            live = int(con.execute("SELECT live_poker_stack_cents FROM wallet_account WHERE account_id=1").fetchone()[0])
        return flows + live

    def recent_study_redemptions(self, limit=500):
        limit = max(1, min(5000, int(limit)))
        with self._connect() as con:
            rows = con.execute("""SELECT transaction_id,redeemed_at,amount_cents,
                total_study_seconds,note FROM study_redemptions
                ORDER BY redeemed_at DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def recent(self, limit=500):
        limit = max(1, min(5000, int(limit)))
        with self._connect() as con:
            rows = [dict(row) for row in con.execute(
                "SELECT * FROM cashier_transactions ORDER BY played_at DESC,rowid DESC LIMIT ?", (limit,)).fetchall()]
            seen = {str(row["transaction_id"]) for row in rows}
            archived = con.execute("""SELECT transaction_id,redeemed_at,amount_cents,balance_after_cents,note
                FROM study_redemptions ORDER BY redeemed_at DESC LIMIT ?""", (limit,)).fetchall()
        for row in archived:
            item = dict(row)
            if str(item["transaction_id"]) in seen:
                continue
            rows.append({"transaction_id": item["transaction_id"], "played_at": item["redeemed_at"],
                         "kind": "study-time-deposit", "delta_cents": int(item["amount_cents"]),
                         "balance_after_cents": int(item["balance_after_cents"]), "recipient": "",
                         "note": item["note"]})
        rows.sort(key=lambda item: str(item.get("played_at", "")), reverse=True)
        return rows[:limit]

    def summary(self):
        with self._connect() as con:
            row = con.execute("""SELECT COUNT(*) count,
                COALESCE(SUM(CASE WHEN delta_cents>0 THEN delta_cents ELSE 0 END),0) credits,
                COALESCE(SUM(CASE WHEN delta_cents<0 THEN -delta_cents ELSE 0 END),0) debits
                FROM cashier_transactions""").fetchone()
            balance = con.execute("SELECT balance_cents FROM wallet_account WHERE account_id=1").fetchone()
        return {"count": int(row["count"]), "credits": int(row["credits"]),
                "debits": int(row["debits"]), "balance_cents": int(balance[0])}