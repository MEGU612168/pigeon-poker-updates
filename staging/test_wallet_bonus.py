from __future__ import annotations

import ast
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"
TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(TEXT, filename=str(SOURCE))
METHOD_NAMES = (
    "_apply_one_time_10_dollar_bonus",
    "_apply_one_time_270_dollar_casino_test_refund",
    "_apply_one_time_1100_dollar_user_balance_topup",
    "_apply_one_time_5000_dollar_update_loss_recovery",
)
namespace = {"datetime": datetime, "timezone": timezone}
for method_name in METHOD_NAMES:
    method_node = next(
        node for node in ast.walk(TREE)
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )
    exec(
        compile(ast.Module(body=[method_node], type_ignores=[]), str(SOURCE), "exec"),
        namespace,
    )
apply_10 = namespace[METHOD_NAMES[0]]
apply_270 = namespace[METHOD_NAMES[1]]
apply_1100 = namespace[METHOD_NAMES[2]]
apply_5000 = namespace[METHOD_NAMES[3]]


def test_existing_wallet_is_preserved_and_four_credits_are_exactly_once() -> None
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
        wallet = SimpleNamespace(
            wallet_store=SimpleNamespace(db_path=db_path),
            cash_balance_cents=2575,
            config_data={},
        )

        assert apply_10(wallet) is True
        assert wallet.cash_balance_cents == 3575
        assert apply_270(wallet) is True
        assert wallet.cash_balance_cents == 30575
        assert apply_1100(wallet) is True
        assert wallet.cash_balance_cents == 140575
        assert apply_5000(wallet) is True
        assert wallet.cash_balance_cents == 640575
        assert wallet.config_data["balance"] == 6405.75

        # Relaunch/re-entry cannot apply any of the same credits twice.
        assert apply_10(wallet) is False
        assert apply_270(wallet) is False
        assert apply_1100(wallet) is False
        assert apply_5000(wallet) is False

        with sqlite3.connect(db_path) as con:
            balance = con.execute(
                "SELECT balance_cents FROM wallet_account WHERE account_id=1"
            ).fetchone()[0]
            rows = con.execute(
                "SELECT transaction_id,kind,delta_cents,balance_after_cents,note "
                "FROM cashier_transactions"
            ).fetchall()
            markers = {
                row[0] for row in con.execute("SELECT key FROM wallet_meta")
            }

        assert balance == 140575
        assert len(rows) == 4
        by_id = {row[0]: row for row in rows}
        assert by_id["pigeon-poker-v1.3.106-bonus-10-usd"][1:4] == ("bonus-credit", 1000, 3575)
        assert by_id["pigeon-poker-v1.5.16-casino-test-refund-270-usd"][1:4] == ("casino-test-refund", 27000, 30575)
        topup = by_id["pigeon-poker-v1.5.19-user-balance-topup-1100-usd"]
        assert topup[1:4] == ("bonus-credit", 110000, 140575)
        assert "One-time +$1,100.00" in topup[4]
        recovery = by_id["pigeon-poker-v1.5.25-update-open-table-loss-recovery-5000-usd"]
        assert recovery[1:4] == ("update-recovery", 500000, 640575)
        assert "One-time +$5,000.00" in recovery[4]
        assert {
            "pigeon_poker_v1_3_106_bonus_10_usd",
            "pigeon_poker_v1_5_16_casino_test_refund_270_usd",
            "pigeon_poker_v1_5_19_user_balance_topup_1100_usd",
            "pigeon_poker_v1_5_25_update_open_table_loss_recovery_5000_usd",
        }.issubset(markers)


def test_startup_applies_topup_after_existing_wallet_refund() -> None:
    init_node = next(
        node for node in ast.walk(TREE)
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    init_source = ast.get_source_segment(TEXT, init_node) or ""
    assert (
        init_source.index("_apply_one_time_270_dollar_casino_test_refund()")
        < init_source.index("_apply_one_time_1100_dollar_user_balance_topup()")
        < init_source.index("_apply_one_time_5000_dollar_update_loss_recovery()")
        < init_source.index("self.cash_balance_cents = self.wallet_store.get_balance(self.cash_balance_cents)")
    )


if __name__ == "__main__":
    test_existing_wallet_is_preserved_and_three_credits_are_exactly_once()
    test_startup_applies_topup_after_existing_wallet_refund()
    print("PASS $10 bonus, $270 refund, $1,100 top-up, and one-time $5,000 update-loss recovery; no double credit")
