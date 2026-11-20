from __future__ import annotations

import ast
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
METHOD = next(
    node for node in ast.walk(TREE)
    if isinstance(node, ast.FunctionDef)
    and node.name == "_apply_one_time_10_dollar_bonus"
)
namespace = {"datetime": datetime, "timezone": timezone}
exec(compile(ast.Module(body=[METHOD], type_ignores=[]), str(SOURCE), "exec"), namespace)
apply_bonus = namespace["_apply_one_time_10_dollar_bonus"]


def test_wallet_bonus_is_exactly_once_and_audited() -> None:
    with tempfile.TemporaryDirectory() as directory:
        db_path = Path(directory) / "wallet.sqlite3"
        with sqlite3.connect(db_path) as con:
            con.executescript("""
                CREATE TABLE wallet_account (
                    account_id INTEGER PRIMARY KEY,
                    balance_cents INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE wallet_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE cashier_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    played_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    delta_cents INTEGER NOT NULL,
                    balance_after_cents INTEGER NOT NULL,
                    recipient TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT ''
                );
                INSERT INTO wallet_account(account_id,balance_cents,updated_at)
                VALUES(1,2575,'initial');
            """)
        wallet_self = SimpleNamespace(
            wallet_store=SimpleNamespace(db_path=db_path),
            cash_balance_cents=2575,
            config_data={},
        )
        assert apply_bonus(wallet_self) is True
        assert wallet_self.cash_balance_cents == 3575
        assert wallet_self.config_data["balance"] == 35.75
        assert apply_bonus(wallet_self) is False
        with sqlite3.connect(db_path) as con:
            balance = con.execute(
                "SELECT balance_cents FROM wallet_account WHERE account_id=1"
            ).fetchone()[0]
            rows = con.execute(
                "SELECT kind,delta_cents,balance_after_cents,note FROM cashier_transactions"
            ).fetchall()
            marker = con.execute(
                "SELECT value FROM wallet_meta WHERE key='pigeon_poker_v1_3_106_bonus_10_usd'"
            ).fetchone()
        assert balance == 3575
        assert len(rows) == 1
        assert rows[0][0] == "bonus-credit"
        assert rows[0][1] == 1000
        assert rows[0][2] == 3575
        assert "+$10.00" in rows[0][3]
        assert marker is not None


if __name__ == "__main__":
    test_wallet_bonus_is_exactly_once_and_audited()
    print("PASS exact-once $10 wallet bonus and ledger transaction")
