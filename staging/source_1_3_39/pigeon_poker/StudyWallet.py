from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pigeon_poker.study_wallet_core import StudyWalletStore, read_study_snapshot, allowance_cents

BG = "#08111f"
PANEL = "#101d2e"
PANEL2 = "#17263a"
TEXT = "#f1f5fa"
MUTED = "#91a3b8"
GOLD = "#e6bd63"
GREEN = "#26c281"
RED = "#ef6262"
WHITE = "#ffffff"
BORDER = "#2a405b"


class StudyWalletApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.store = StudyWalletStore()
        # When this app is launched from the Pigeon package folder, import its
        # previous local cashier ledger before any Study hours can be redeemed.
        legacy_db = ROOT / "data" / "pigeon_cashier.sqlite3"
        if legacy_db.is_file():
            legacy_balance = 0
            legacy_config = ROOT / "pigeon_config.json"
            if legacy_config.is_file():
                try:
                    import json
                    old_config = json.loads(legacy_config.read_text(encoding="utf-8"))
                    if "wallet_initialized" in old_config:
                        legacy_balance = max(0, int(round(float(old_config.get("balance", 0)) * 100)))
                except Exception:
                    legacy_balance = 0
            self.store.import_legacy_once(legacy_db, legacy_balance)
        self.title("Study Wallet")
        self.geometry("1080x700")
        self.minsize(900, 650)
        self.configure(bg=BG)
        self._style()
        self._build()
        self.refresh()
        self.after(2000, self._poll)

    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure("TFrame", background=BG)
        s.configure("Panel.TFrame", background=PANEL)
        s.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        s.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 10))
        s.configure("TEntry", fieldbackground=PANEL2, foreground=TEXT, insertcolor=TEXT)
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                    rowheight=28, bordercolor=BORDER, font=("Segoe UI", 9))
        s.configure("Treeview.Heading", background=PANEL2, foreground=GOLD,
                    font=("Segoe UI", 9, "bold"))
        s.map("Treeview", background=[("selected", "#24486a")])
        s.configure("Accent.TButton", background="#1d9b70", foreground="white",
                    font=("Segoe UI", 10, "bold"), padding=(16, 9))
        s.map("Accent.TButton", background=[("active", "#27b986")])
        s.configure("TButton", padding=(12, 7), font=("Segoe UI", 9, "bold"))

    def _card(self, parent, title, variable, colour=TEXT, large=True):
        frame = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tk.Label(frame, text=title, bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=17, pady=(13, 4))
        label = tk.Label(frame, textvariable=variable, bg=PANEL, fg=colour,
                         font=("Segoe UI", 25 if large else 20, "bold"))
        label.pack(anchor="w", padx=17, pady=(0, 13))
        return frame, label

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 14))
        tk.Label(header, text="STUDY WALLET", bg=BG, fg=GOLD,
                 font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(header, text="Study-time ledger shared with Pigeon Poker Cashier  •  poker cash balance is shown separately",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        self.study_total_var = tk.StringVar(value="--")
        self.depositable_var = tk.StringVar(value="$0")
        self.total_value_var = tk.StringVar(value="$0")
        self.redeemed_var = tk.StringVar(value="$0")
        self.cashier_balance_var = tk.StringVar(value="$0.00")
        cards = tk.Frame(self, bg=BG)
        cards.pack(fill="x", padx=28, pady=(0, 14))
        for c in range(5): cards.grid_columnconfigure(c, weight=1, uniform="studywallet")
        self._card(cards, "CUMULATIVE STUDY TIME", self.study_total_var)[0].grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._card(cards, "TOTAL STUDY VALUE", self.total_value_var, GREEN)[0].grid(row=0, column=1, sticky="nsew", padx=6)
        self._card(cards, "ALREADY DEPOSITED", self.redeemed_var, MUTED)[0].grid(row=0, column=2, sticky="nsew", padx=6)
        self._card(cards, "REMAINING TO DEPOSIT", self.depositable_var, GOLD)[0].grid(row=0, column=3, sticky="nsew", padx=6)
        self._card(cards, "POKER CASHIER BALANCE", self.cashier_balance_var, GREEN)[0].grid(row=0, column=4, sticky="nsew", padx=(6, 0))

        deposit = tk.Frame(self, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        deposit.pack(fill="x", padx=28, pady=(0, 14))
        top = tk.Frame(deposit, bg=PANEL)
        top.pack(fill="x", padx=18, pady=(15, 8))
        tk.Label(top, text="STUDY-TIME REDEMPTION TO PIGEON POKER", bg=PANEL, fg=GOLD,
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(top, text="REFRESH NOW", command=self.refresh).pack(side="right")
        form = tk.Frame(deposit, bg=PANEL)
        form.pack(fill="x", padx=18, pady=(0, 14))
        tk.Label(form, text="Amount (whole USD)", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left")
        self.amount_var = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.amount_var, width=12, font=("Segoe UI", 12)).pack(side="left", padx=(10, 12))
        ttk.Button(form, text="+$10", command=lambda: self.amount_var.set("10")).pack(side="left", padx=3)
        ttk.Button(form, text="+$50", command=lambda: self.amount_var.set("50")).pack(side="left", padx=3)
        ttk.Button(form, text="+$100", command=lambda: self.amount_var.set("100")).pack(side="left", padx=3)
        self.deposit_button = ttk.Button(form, text="DEPOSIT", style="Accent.TButton", command=self.deposit)
        self.deposit_button.pack(side="right")

        history_frame = tk.Frame(self, bg=BG)
        history_frame.pack(fill="both", expand=True, padx=28, pady=(0, 8))
        tk.Label(history_frame, text="STUDY-TIME REDEMPTION HISTORY", bg=BG, fg=GOLD,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(3, 8))
        cols = ("date", "amount", "study", "note")
        self.tree = ttk.Treeview(history_frame, columns=cols, show="headings", height=12)
        for key, label, width in [
            ("date", "DATE", 190), ("amount", "DEPOSITED TO PIGEON", 170),
            ("study", "CUMULATIVE STUDY AT REDEMPTION", 230), ("note", "DETAIL", 470),
        ]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor="w" if key in ("date", "note") else "center")
        self.tree.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="Waiting for Focus Timer…")
        tk.Label(self, textvariable=self.status_var, bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=30, pady=(0, 14))

    def refresh(self):
        try:
            snapshot = read_study_snapshot(self.store.snapshot_path)
            wallet_ready = self.store.is_initialized()
            self.deposit_button.configure(state=("normal" if wallet_ready and snapshot["connected"] else "disabled"))
            # This value is read from the exact same SQLite account used by
            # Pigeon Poker Cashier; it is intentionally separate from Study value.
            self.cashier_balance_var.set(f"${self.store.get_balance(0) / 100:,.2f}")
            if snapshot["connected"]:
                hours = snapshot["total_study_seconds"] / 3600
                self.study_total_var.set(f"{hours:,.2f} h")
                updated = snapshot["updated_at"].replace("T", " ")[:19]
                if not wallet_ready:
                    self.status_var.set("Open Pigeon Poker once to initialize the shared wallet ledger. Focus Timer history is preserved.")
                else:
                    self.status_var.set(f"Focus Timer connected ({snapshot.get('source', 'snapshot')})  •  Pigeon Cashier linked via {self.store.db_path.name}  •  Updated {updated}  •  1 cumulative Study hour = $1 allowance")
            else:
                self.study_total_var.set("NOT LINKED")
                self.status_var.set(f"Pigeon Cashier shared ledger: connected ({self.store.db_path})  •  Focus Timer data is being searched automatically. Start Focus Timer once if it is not running.")
            redeemed = self.store.redeemed_study_cents()
            if snapshot["connected"]:
                total_value = allowance_cents(snapshot["total_study_seconds"])
                available = max(0, total_value - redeemed)
                self.total_value_var.set(f"${total_value // 100:,}")
                self.redeemed_var.set(f"${redeemed // 100:,}")
                self.depositable_var.set(f"${available // 100:,}")
            else:
                self.total_value_var.set("—")
                self.redeemed_var.set(f"${redeemed // 100:,}")
                self.depositable_var.set("—")
            for item in self.tree.get_children(): self.tree.delete(item)
            for row in self.store.recent_study_redemptions(500):
                dt = row["redeemed_at"].replace("T", " ").replace("+00:00", " UTC")
                seconds = int(row.get("total_study_seconds", 0))
                study_at_redemption = f"{seconds / 3600:,.2f} h" if seconds else "Legacy redemption"
                self.tree.insert("", "end", values=(dt, f"${row['amount_cents']/100:,.0f}",
                                    study_at_redemption, row["note"]))
        except Exception as exc:
            self.status_var.set(f"Wallet refresh error: {exc}")

    def deposit(self):
        try:
            raw = self.amount_var.get().strip().replace(",", "").replace("$", "")
            if not raw.isdigit(): raise ValueError("Enter a whole-dollar amount, e.g. 50")
            amount = int(raw)
            result = self.store.deposit_study_time(amount)
            self.status_var.set(f"Deposited ${amount:,}. Remaining Study allowance: ${result['remaining_allowance_cents']//100:,}.")
            self.refresh()
        except Exception as exc:
            messagebox.showerror("Study Wallet", str(exc), parent=self)

    def _poll(self):
        try:
            if self.winfo_exists():
                self.refresh()
                self.after(2000, self._poll)
        except tk.TclError:
            pass


if __name__ == "__main__":
    app = StudyWalletApp()
    app.mainloop()