from __future__ import annotations

import json
import zipfile
import os
import math
import ctypes
import struct
import wave
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import queue
import random
import subprocess
import sys
import threading
import time
import uuid
import tkinter as tk
from pathlib import Path
# Retire the obsolete chart modules before importing the live preflop policy.
from pigeon_poker.preflop_cleanup import cleanup_retired_preflop_modules
cleanup_retired_preflop_modules()
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from pigeon_gto_plus import (PigeonGTOPlusIntegration, StrategyStore, GTOPlusIntegrationError,
                              GTOPlusAutoAnalyzer, WindowPermissionError)
from pigeon_poker.allin_ev import estimate_hero_allin_ev
from pigeon_poker.hand_display import current_hand_badge
from pigeon_poker.auto_fold_chart import (default_auto_fold_chart, normalize_auto_fold_chart,
    should_auto_fold, POSITIONS, RANKS_DESC, all_hand_classes)
from pigeon_poker.ev_cashout import calculate_ev_cashout_offer
from pigeon_poker.sound_design import write_sound_wav, SOUND_ASSETS, SOUND_VARIANT_COUNT, SOUND_FILE_VERSION
from pigeon_poker import (CashTable, CashGameCPU, GTOPlusLiveSession, LiveGTOError,
                          PokerRuleError, build_gto_plus_spot_table, HandHistoryStore,
                          is_gto_plus_supported_postflop_hand, CPUPoolStore, GGCareLedger, CashierLedger, bind_first_matching_tree)
from pigeon_poker.preflop_gto_strategy import (
    choose_preflop_action, preflop_gto_situation_size,
    estimate_preflop_opponent_ranges, preflop_gto_range_for_situation
)
from pigeon_poker.poker_reasoning import choose_range_aware_action
from pigeon_poker.cpu_learning import CPULearningStore
from pigeon_gto_plus.live_range_builder import build_live_hu_solver_setup
from pigeon_poker.multitable import MultiTableRegistry, next_big_blind_index_after_rotation
from pigeon_poker.betting_ui import (DEFAULT_POT_PRESETS, normalize_pot_presets, format_chip_amount,
                                      parse_chip_amount, pot_sized_target, bet_button_label)
from pigeon_poker.chip_visuals import (CHIP_DENOMINATIONS, CHIP_PALETTE, decompose_cents,
                                       draw_chip, draw_chip_stack, draw_chip_cluster)
from pigeon_poker.preferences import (FELT_THEMES, CARD_BACK_THEMES, CARD_FACE_THEMES,
                                       TABLE_BACKGROUND_THEMES, DEFAULT_HOTKEYS, SOUND_KEYS,
                                       SOUND_GROUP_LABELS, SOUND_GROUPS, sound_group_volumes,
                                       appearance_settings, card_face_palette, card_face_color,
                                       validate_hotkeys, format_hud_line, HUD_LABELS, SOUND_LABELS)
from pigeon_poker.pokercraft_graph import cumulative_comparison_values
from pigeon_poker.pokercraft_stats import calculate_player_statistics, filter_hand_results
from pigeon_poker.pokercraft_export import export_hand_history_csv
from pigeon_updater import (
    start_update_check, start_update_availability_check,
    UPDATE_CHECK_INTERVAL_MS,
)
from pigeon_poker.presentation import (
    ACTION_BADGE_MS, CHIP_TO_POT_MS, DEAL_FIRST_DELAY_MS, DEAL_FLIGHT_FRAMES,
    DEAL_FLIGHT_FRAME_MS, DEAL_BETWEEN_CARDS_MS, HOLE_REVEAL_PAUSE_MS,
    HOLE_REVEAL_FRAMES, HOLE_REVEAL_FRAME_MS, HOLE_REVEAL_CARD_GAP_MS,
    FLOP_REVEAL_FRAMES, FLOP_REVEAL_FRAME_MS, STREET_REVEAL_FRAMES,
    STREET_REVEAL_FRAME_MS, STREET_BETWEEN_CARDS_MS, POT_AWARD_MOVE_MS,
    POT_WIN_BANNER_MS, action_badge, action_paid_cents, ease_out_cubic,
    chip_flight_position, chip_flight_scale, hole_card_deal_sequence,
    payout_shares, hole_card_display_mode, staggered_progress,
    squeeze_card_pair_layout, squeeze_card_sweep_progress, squeeze_card_surface_point,
)
from pigeon_poker.hand_replay import build_replay_frames
from pigeon_poker.social_effects import (
    REACTION_TYPES, REACTION_LABELS, REACTION_DURATION_SECONDS,
    REACTION_COOLDOWN_SECONDS, MAX_REACTIONS_PER_HAND,
    BIG_POT_CELEBRATION_BB, BIG_POT_CELEBRATION_SECONDS,
    normalize_reaction, reaction_decision, reaction_progress,
    qualifies_for_big_pot, celebration_particle,
)
from pigeon_poker.table_modes import (
    RUSH_MODE, VIP_MODE, VIP_STAKE_KEY, VIP_SMALL_BLIND_CENTS, VIP_BIG_BLIND_CENTS,
    VIP_MIN_BUYIN_BB, VIP_MAX_BUYIN_BB, VIP_DEFAULT_BUYIN_BB,
    normalize_table_mode, is_rush_mode, is_vip_mode, table_mode_label,
)
from pigeon_poker.vip_ai import (
    assign_vip_cpu_roles, vip_cpu_role_label,
    validate_vip_cpu_roles, VIP_PURE_GTO_COUNT, VIP_NEAR_GTO_COUNT,
    PURE_GTO_ROLE, NEAR_GTO_ROLE,
)
from pigeon_poker.study_time import (
    read_study_time_snapshot, shared_study_snapshot_path,
    available_deposit_cents, format_signed_usd,
)
from pigeon_poker.study_wallet_core import StudyWalletStore
from pigeon_poker.table_control import (
    REGULAR_ACTION_SECONDS, FREE_TIMEBANK_SECONDS, PAID_TIMEBANK_SECONDS,
    DEFAULT_FREE_TIMEBANK_CARDS, normalize_table_pause_state,
    arm_free_timebank, arm_paid_timebank, consume_armed_timebank,
    reset_timebank_hand_state, clear_timebank_selection, action_seconds_for_street,
)

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "pigeon_config.json"
DEFAULT_GTO = Path(r"C:\Program Files\GTO\GTO.exe")

COLORS = {
    "bg": "#0b1220", "panel": "#111c2e", "panel2": "#17263a", "border": "#263b55",
    "text": "#f2f6fc", "muted": "#91a3b8", "green": "#19a974", "green2": "#0c6a4b",
    "gold": "#e6bd63", "red": "#d95757", "blue": "#3988d8", "felt": "#0c6849",
    "felt2": "#084d38", "seat": "#14243a", "white": "#ffffff",
}


def load_config() -> dict[str, Any]:
    data = {
        "gto_plus_executable": str(DEFAULT_GTO), "gto_plus_port": 55143,
        "rake_pct": 0.0, "balance": 0.0, "wallet_initialized": True,
        "database": "data/pigeon_strategies.sqlite3",
        "chip_display_unit": "USD", "bet_pot_percentages": list(DEFAULT_POT_PRESETS),
    }
    if CONFIG.exists():
        try:
            existing = json.loads(CONFIG.read_text(encoding="utf-8"))
            # Configurations from early alpha builds were seeded with $25,000.
            # Migrate that demo seed to $0 exactly once; keep later user deposits.
            if "wallet_initialized" not in existing:
                existing["balance"] = 0.0
                existing["wallet_initialized"] = True
            data.update(existing)
        except Exception:
            pass
    return data


def save_config(data: dict[str, Any]) -> None:
    CONFIG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class PigeonPokerApp(tk.Tk):
    """Pigeon Poker desktop alpha: table UI shell plus embedded GTO+ strategy bridge."""

    def __init__(self):
        super().__init__()
        self.title("Pigeon Poker | Cash & Rush")
        self.geometry("1480x900")
        self.minsize(1180, 720)
        self.configure(bg=COLORS["bg"])
        self.config_data = load_config()
        self.chip_display_unit = str(self.config_data.get("chip_display_unit", "USD")).upper()
        if self.chip_display_unit not in {"USD", "BB"}:
            self.chip_display_unit = "USD"
        self.bet_pot_percentages = normalize_pot_presets(self.config_data.get("bet_pot_percentages", DEFAULT_POT_PRESETS))
        self.appearance = appearance_settings(self.config_data)
        self.hotkeys = validate_hotkeys(self.config_data.get("hotkeys", DEFAULT_HOTKEYS))
        self.sound_settings = {key: bool(self.config_data.get("sounds", {}).get(key, True)) for key in SOUND_KEYS}
        self.sound_master = bool(self.config_data.get("sound_master", True))
        self.sound_volume = max(0, min(100, int(self.config_data.get("sound_volume", 50))))
        self.sound_group_levels = sound_group_volumes(self.config_data)
        self.hud_fields = {key: bool(self.config_data.get("hud_fields", {}).get(key, True))
                           for key in HUD_LABELS}
        self.auto_fold_chart = normalize_auto_fold_chart(self.config_data.get("auto_fold_chart", default_auto_fold_chart()))
        db_path = ROOT / self.config_data["database"]
        self.store = StrategyStore(db_path)
        self.integration = PigeonGTOPlusIntegration(
            self.config_data["gto_plus_executable"], self.store,
            port=int(self.config_data.get("gto_plus_port", 55143)),
            bridge_root=ROOT,
        )
        self.jobs: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.auto_collect_enabled_var = tk.BooleanVar(
            value=bool(self.config_data.get("gto_plus_auto_collect", True))
        )
        self.auto_scan_cancel_event = threading.Event()
        self.auto_scan_thread: threading.Thread | None = None
        self.integration.set_solver_status_callback(
            lambda busy, table_id=None: self.jobs.put(("gto_solver_status", {
                "busy": bool(busy), "table_id": table_id
            }))
        )
        self.sound_queue: queue.Queue[tuple[str, int, int] | None] = queue.Queue(maxsize=96)
        self.sound_last_variants: dict[str, int] = {}
        self.sound_worker_stop = threading.Event()
        self.sound_worker = threading.Thread(target=self._sound_worker_loop, daemon=True, name="PigeonWavSound")
        self.sound_worker.start()
        # Voice announcements use an independent SAPI/TTS worker. Speech must
        # never block Tk's action loop or delay the short physical table cues.
        self.action_voice_queue: queue.Queue[tuple[str, int] | None] = queue.Queue(maxsize=24)
        self.action_voice_stop = threading.Event()
        self.action_voice_worker = threading.Thread(
            target=self._action_voice_worker_loop, daemon=True, name="PigeonActionVoice")
        self.action_voice_worker.start()
        self.tree_files: list[Path] = [Path(x).expanduser() for x in self.config_data.get("gto_plus_tree_library", [])
                                       if str(x).strip()]
        self.tree_files = [path for path in self.tree_files if path.is_file()]
        preferred_tree = Path(self.config_data.get("gto_plus_preferred_tree", "")).expanduser()
        self.tree_file: Path | None = (
            preferred_tree if preferred_tree.is_file() else (self.tree_files[-1] if self.tree_files else None)
        )
        self.gto_embedded = False
        self.gto_owned_process_pid: int | None = None
        self._gto_auto_start_started = False
        self._gto_auto_connect_busy = False
        self._gto_handoff_in_progress = False
        self.cpu_last_action = tk.StringVar(value="CPUはまだGTO+の戦略を使っていません")
        self.status_var = tk.StringVar(value="GTO+ 未接続")
        self.hand_var = tk.StringVar(value="AUTO")
        self.human_hand_var = tk.StringVar(value="AUTO")
        self.side_var = tk.StringVar(value="IP")
        self.human_side_var = tk.StringVar(value="OOP")
        self.active_cpu_hand: str | None = None
        self.active_human_hand: str | None = None
        self.hand_finished = False
        self.rake_var = tk.StringVar(value=str(self.config_data.get("rake_pct", 0.0)))
        self.current_node_context: dict[str, Any] | None = None
        self.executable_var = tk.StringVar(value=self.config_data["gto_plus_executable"])
        self.port_var = tk.StringVar(value=str(self.config_data.get("gto_plus_port", 55143)))
        self.tree_var = tk.StringVar(value=(
            f"GTO+解析済みツリー {len(self.tree_files)} 本登録" if self.tree_files else "解析済みGTO+ファイル：未選択"
        ))
        self.node_var = tk.StringVar(value="現在ノード：未取得")
        self.balance_var = tk.StringVar(value=f"${float(self.config_data.get('balance', 0)):,.2f}")
        # Live cash-table state. A cash table is independent of the old GTO+
        # tree-training page; exact HU postflop matches can use GTO+ directly.
        self.cash_table: CashTable | None = None
        self.cash_cpus: dict[str, CashGameCPU] = {}
        self.cash_gto_session: GTOPlusLiveSession | None = None
        self.cash_gto_spot_mode = False
        self.cash_spot_side = "OOP"
        self.cash_busy = False
        self.cash_syncing_gto = False
        self.cash_rate = "NL10"
        self.cash_game_mode = RUSH_MODE
        self.cash_sb = 5
        self.cash_bb = 10
        self.cash_buyin = 1000
        self.cash_balance_cents = int(round(float(self.config_data.get("balance", 0)) * 100))
        self.cash_auto_rebuy_var = tk.BooleanVar(value=bool(self.config_data.get("cash_auto_rebuy", False)))
        # The BB-before-sit-out preference is per table slot, not global.
        # Temporary sit-out preserves that table and its stack/session.
        self.cash_sitout_before_bb_var = tk.BooleanVar(value=False)  # legacy migration only
        self.cash_bet_var = tk.StringVar(value="")
        self.card_squeeze_enabled_var = tk.BooleanVar(value=False)
        self.config_data["card_squeeze_enabled"] = False
        self.hero_squeeze_count = 0
        self.board_squeeze_count = 5
        self.cash_initial_flip: dict[str, Any] = {
            "active": False, "complete": False, "index": 0, "progress": 0.0
        }
        self.cash_board_squeeze: dict[str, Any] = {}
        self.cash_squeeze_deadline_at = 0.0
        self.cash_action_deadline_mode = ""
        self.cash_last_turn_sound_key = None
        self.auto_next_hand_jobs: set[str] = set()
        self.cash_status_var = tk.StringVar(value="テーブル未参加")
        self.cash_source_var = tk.StringVar(value="CPU strategy: waiting")
        self.cash_log_lines: list[str] = []
        self.cash_random = random.Random()
        self.cash_drop_pool_cents = max(0, int(self.config_data.get("cash_drop_pool_cents", 0)))
        self.cash_session_id = uuid.uuid4().hex
        self.cash_hand_instance = 0
        self.preflop_fold_pending = False
        self.postflop_auto_fold = False
        self.postflop_auto_fold_hand_token = None
        self.cash_current_hand_key: str | None = None
        self.history_store = HandHistoryStore(ROOT / "data" / "pigeon_hands.sqlite3")
        self.cpu_pool_store = CPUPoolStore(ROOT / "data" / "pigeon_cpu_pool.sqlite3",
                                                   stakes=("NL2", "NL5", "NL10", "NL25", "NL50", "NL100", "NL200", VIP_STAKE_KEY))
        self.cpu_learning_store = CPULearningStore(ROOT / "data" / "pigeon_cpu_learning.sqlite3")
        self.ggcare_ledger = GGCareLedger(ROOT / "data" / "pigeon_ggcare.sqlite3")
        self.ggcare_candidate = None
        # The independent Study Wallet is now the single balance/ledger source.
        # Import previous Pigeon-local Cashier records exactly once, then share
        # the same SQLite database with StudyWallet.pyw.
        legacy_cashier_db = ROOT / "data" / "pigeon_cashier.sqlite3"
        self.wallet_store = StudyWalletStore()
        self.wallet_migration = self.wallet_store.import_legacy_once(
            legacy_cashier_db, self.cash_balance_cents
        )
        # One-time fresh test reset: all poker accounting and old test deposits
        # are cleared. The new wallet starts at $0; Focus Timer history remains
        # untouched, so its full cumulative Study allowance becomes available.
        if not self.wallet_store.is_test_reset_complete():
            self.wallet_store.reset_for_test_stage(0)
            self.history_store.clear_all()
            self.ggcare_ledger.clear_all()
            self.cash_drop_pool_cents = 0
            self.config_data["cash_drop_pool_cents"] = 0
            self.config_data["balance"] = 0.0
            self.wallet_store.mark_test_reset_complete()
        self.cashier_ledger = CashierLedger(self.wallet_store.db_path)
        self._ensure_withdrawable_wallet_schema()
        # One-time $10 promotional balance credit. The SQLite marker and ledger
        # row are committed atomically so startup/relaunch cannot double-credit.
        self._apply_one_time_10_dollar_bonus()
        self.cash_balance_cents = self.wallet_store.get_balance(self.cash_balance_cents)
        self.balance_var.set(f"${self.cash_balance_cents / 100:,.2f}")
        self.config_data["balance"] = self.cash_balance_cents / 100
        save_config(self.config_data)
        self.cashier_amount_var = tk.StringVar(value="")
        self.cashier_withdraw_var = tk.StringVar(value="50.00")
        self.cashier_transfer_var = tk.StringVar(value="25.00")
        self.cashier_recipient_var = tk.StringVar(value="PigeonDemoUser")
        self.cashier_status_var = tk.StringVar(value="Study-time wallet • offline simulation only")
        self.study_depositable_var = tk.StringVar(value="$0")
        self.study_hours_detail_var = tk.StringVar(value="Searching for Focus Timer data automatically")
        self.poker_pnl_var = tk.StringVar(value="$0.00")
        self.study_depositable_cents = 0
        self.study_snapshot_connected = False
        self.study_snapshot_path = shared_study_snapshot_path()
        self.cashier_pnl_label = None
        self.cash_cpu_profiles: dict[str, Any] = {}
        self.vip_cpu_roles: dict[str, str] = {}
        self.multi_tables = MultiTableRegistry(max_tables=2)
        self.active_cash_table_id: str | None = None
        # CPU workers are cancellable so the bottom-bar "leave now" control can
        # cash out without waiting for the rest of a Rush & Cash hand to finish.
        self.cash_cpu_cancel_events: dict[str, threading.Event] = {}
        self.quick_leave_poll_jobs: set[str] = set()
        self.table_resume_retry_jobs: dict[str, str] = {}
        self.rush_fold_poll_jobs: set[str] = set()
        self.pending_table_action_jobs: dict[str, str] = {}
        # Independent, freely movable table windows mirror each open Rush & Cash table.
        self.table_windows: dict[str, dict[str, Any]] = {}
        self.cash_runout_dialogs: dict[str, dict[str, Any]] = {}
        # Per-table visual state: animated deals, board runouts and click-free squeeze popups.
        self.card_peel_drags: dict[str, dict[str, Any]] = {}
        self.squeeze_popups: dict[str, dict[str, Any]] = {}
        self.deal_animation_jobs: dict[str, dict[str, Any]] = {}
        self.hole_flip_jobs: dict[str, dict[str, Any]] = {}
        self.squeeze_deadline_jobs: dict[str, str] = {}
        self.board_squeeze_auto_jobs: dict[str, str] = {}
        self.board_animation_jobs: dict[str, dict[str, Any]] = {}
        self.cash_visible_board: list[str] = []
        self.cash_board_target: list[str] = []
        self.cash_board_reveal_count = 0
        self.cash_board_anim_index: int | None = None
        self.cash_board_anim_progress = 1.0
        self.cash_deal_counts: dict[str, int] = {}
        self.cash_deal_flying: dict[str, Any] | None = None
        self.cash_deal_busy = False
        self.cash_action_feed = "Waiting for the first hand"
        self.cash_thinking_player: str | None = None
        self.pending_gto_previous_table_id: str | None = None
        self.pending_gto_restart_table_id: str | None = None
        self._build_shell()
        self._build_lobby()
        self._build_cashier_page()
        self._build_table()
        self._build_placeholder_pages()
        self._build_pokercraft_page()
        self.show_page("lobby")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<KeyPress>", self._on_global_hotkey, add="+")
        self._job_drain_after_id = self.after(120, self._drain_jobs)
        self._study_cashier_refresh_id = self.after(2500, self._study_cashier_live_refresh)
        self._pokercraft_live_refresh_job = self.after(1800, self._tick_pokercraft_live_refresh)
        self.after(1200, self._refresh_update_button_state)
        self.after(UPDATE_CHECK_INTERVAL_MS, self._periodic_update_check)

    # ---------- Theme helpers ----------
    def _style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("Panel2.TFrame", background=COLORS["panel2"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Segoe UI", 9))
        style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 18, "bold"))
        style.configure("CardTitle.TLabel", background=COLORS["panel"], foreground=COLORS["text"], font=("Segoe UI", 12, "bold"))
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=(10, 8), background=COLORS["panel2"], foreground=COLORS["text"])
        style.map("TButton", background=[("active", "#28405e")], foreground=[("disabled", "#77879a")])
        style.configure("Accent.TButton", background=COLORS["green"], foreground="#071b14")
        style.map("Accent.TButton", background=[("active", "#35c78e")])
        style.configure("MutedUpdate.TButton", background="#354255", foreground="#aab5c5")
        style.map("MutedUpdate.TButton", background=[("disabled", "#354255")], foreground=[("disabled", "#8997aa")])
        style.configure("RetryUpdate.TButton", background="#64748b", foreground="#f2f6fc")
        style.configure("DrawerToggle.TButton", background="#22364d", foreground=COLORS["text"], font=("Segoe UI Symbol", 14, "bold"), padding=0)
        style.map("DrawerToggle.TButton", background=[("active", "#315276")])
        style.configure("Danger.TButton", background=COLORS["red"], foreground="white")
        style.configure("TEntry", fieldbackground="#0b1727", foreground=COLORS["text"], insertcolor=COLORS["text"], bordercolor=COLORS["border"])
        style.configure("TCombobox", fieldbackground="#0b1727", foreground=COLORS["text"])
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["panel2"], foreground=COLORS["muted"], padding=(14, 8))
        style.map("TNotebook.Tab", background=[("selected", COLORS["green2"])], foreground=[("selected", "white")])
        style.configure("Treeview", background=COLORS["panel"], fieldbackground=COLORS["panel"], foreground=COLORS["text"], rowheight=26)
        style.configure("Treeview.Heading", background=COLORS["panel2"], foreground=COLORS["text"])

    def _build_shell(self):
        self._style()
        header = tk.Frame(self, bg="#080e19", height=68)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="PIGEON", bg="#080e19", fg=COLORS["text"], font=("Segoe UI", 21, "bold")).pack(side="left", padx=(22, 2))
        tk.Label(header, text="POKER", bg="#080e19", fg=COLORS["green"], font=("Segoe UI", 21, "bold")).pack(side="left")
        version_label = "VERSION " + (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip() if (ROOT / "VERSION.txt").is_file() else "DESKTOP"
        tk.Label(header, text=f"DESKTOP ALPHA • {version_label}", bg="#080e19", fg=COLORS["gold"], font=("Segoe UI", 8, "bold")).pack(side="left", padx=14, pady=(12, 0))
        # The update action stays in the global header, visible on every page.
        # First-time/bootstrap installs can therefore be verified without
        # searching through the long Settings page.
        self.update_status_var = tk.StringVar(value="アップデート確認")
        self.update_button = ttk.Button(
            header, text="CHECK / UPDATE", style="Accent.TButton",
            command=self._begin_app_update, state="normal",
        )
        self.update_button.pack(side="right", padx=(12, 20), pady=12)
        tk.Label(header, text="SIMULATED BALANCE", bg="#080e19", fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(side="right", padx=(10, 8))
        tk.Label(header, textvariable=self.balance_var, bg="#080e19", fg=COLORS["text"], font=("Segoe UI", 13, "bold")).pack(side="right")
        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)
        self.sidebar = tk.Frame(body, bg="#0d1726", width=180)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Label(self.sidebar, text="MAIN MENU", bg="#0d1726", fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=17, pady=(24, 12))
        self.content = tk.Frame(body, bg=COLORS["bg"])
        self.content.pack(side="left", fill="both", expand=True)
        self.pages: dict[str, tk.Frame] = {}
        self.page_scroll_canvases: dict[str, tk.Canvas] = {}
        self.page_scroll_contents: dict[str, tk.Frame] = {}
        self.nested_page_scroll_canvases: set[tk.Canvas] = set()
        self._active_page_key: str | None = None
        self.bind_all("<MouseWheel>", self._scroll_active_page, add="+")
        nav = [("LOBBY", "lobby"), ("OPEN TABLES", "table"), ("CASHIER", "cashier"), ("POKERCRAFT", "poker_craft"), ("GG CARE", "gg_care"), ("SETTINGS", "settings")]
        for label, page in nav:
            ttk.Button(self.sidebar, text=label, command=lambda p=page: self.show_page(p)).pack(fill="x", padx=10, pady=3)
        tk.Frame(self.sidebar, bg=COLORS["border"], height=1).pack(fill="x", padx=14, pady=16)
        tk.Label(self.sidebar, text="SYSTEM STATUS", bg="#0d1726", fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=17)
        self.status_label = tk.Label(self.sidebar, textvariable=self.status_var, bg="#0d1726", fg=COLORS["gold"], justify="left", wraplength=145, font=("Segoe UI", 8))
        self.status_label.pack(anchor="w", padx=17, pady=7)

    def _new_page(self, key: str) -> tk.Frame:
        # Every main app page gets its own vertical scroll area. The returned
        # content frame keeps existing page builders unchanged.
        page = tk.Frame(self.content, bg=COLORS["bg"])
        if key == "gto":
            # Solver coordinates must not drift with a page scroll.
            # Keep GTO+ as a fixed viewport; the settings drawer has its own scroll.
            self.pages[key] = page
            return page
        canvas = tk.Canvas(
            page, bg=COLORS["bg"], highlightthickness=0, bd=0,
            yscrollincrement=24,
        )
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, bg=COLORS["bg"])
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def _sync_scroll_region(_event=None, target=canvas,
                                frame=content, item=window_id):
            # A canvas window otherwise keeps only the Frame's requested height.
            # Expanding child widgets such as Notebooks then collapse to their
            # natural request size, leaving a large unused area below them.
            # Fill the viewport when content is short, while preserving the
            # full requested height for pages that genuinely need scrolling.
            try:
                viewport_height = max(1, target.winfo_height())
                requested_height = max(1, frame.winfo_reqheight())
                target.itemconfigure(item, height=max(viewport_height, requested_height))
                target.configure(scrollregion=target.bbox("all"))
            except tk.TclError:
                return

        def _fit_content_width(event, target=canvas, item=window_id,
                               frame=content):
            try:
                target.itemconfigure(
                    item,
                    width=max(1, event.width),
                    height=max(1, event.height, frame.winfo_reqheight()),
                )
                target.after_idle(lambda: _sync_scroll_region(
                    target=target, frame=frame, item=item))
            except tk.TclError:
                return

        content.bind("<Configure>", _sync_scroll_region, add="+")
        canvas.bind("<Configure>", _fit_content_width, add="+")
        self.pages[key] = page
        self.page_scroll_canvases[key] = canvas
        self.page_scroll_contents[key] = content
        return content

    def _make_scrollable_tab(self, notebook, title: str, background: str):
        """Create a tab with its own vertical scroll canvas."""
        host = tk.Frame(notebook, bg=background)
        canvas = tk.Canvas(host, bg=background, highlightthickness=0, bd=0, yscrollincrement=24)
        scrollbar = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = tk.Frame(canvas, bg=background)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _e, c=canvas: c.configure(scrollregion=c.bbox("all")), add="+")
        canvas.bind("<Configure>", lambda ev, c=canvas, item=window_id: c.itemconfigure(item, width=ev.width), add="+")
        self.nested_page_scroll_canvases.add(canvas)
        notebook.add(host, text=title)
        return host, content

    def _scroll_active_page(self, event):
        key = self._active_page_key
        outer_canvas = self.page_scroll_canvases.get(key) if key else None
        if outer_canvas is None or not outer_canvas.winfo_exists():
            return None
        # Shift+wheel remains reserved for the PokerCraft session strip.
        if int(getattr(event, "state", 0) or 0) & 0x0001:
            return None
        delta = int(getattr(event, "delta", 0) or 0)
        if not delta:
            return None
        units = int(-delta / 120)
        if not units:
            units = -1 if delta > 0 else 1
        current = event.widget
        target = None
        while current is not None:
            if current is outer_canvas:
                target = outer_canvas
                break
            if current in self.nested_page_scroll_canvases:
                target = current
                break
            try:
                widget_class = current.winfo_class()
            except tk.TclError:
                widget_class = ""
            if widget_class in {"Canvas", "Treeview", "Text", "Listbox"}:
                try:
                    first, last = current.yview()
                    if (last - first) < 0.999:
                        # Let dedicated scrollable widgets and GTO canvases
                        # receive wheel input through their own bindings.
                        return None
                except (tk.TclError, AttributeError):
                    return None
            current = getattr(current, "master", None)
        if target is None:
            return None
        target.yview_scroll(units, "units")
        return "break"

    def show_page(self, key: str):
        for page in self.pages.values():
            page.pack_forget()
        if key not in self.pages:
            key = "lobby"
        self._active_page_key = key
        self.pages[key].pack(fill="both", expand=True)
        if key == "table":
            self._refresh_table_dashboard()
        if key == "cashier" and hasattr(self, "cashier_tree"):
            self._refresh_cashier()
        if key == "poker_craft" and hasattr(self, "history_tree"):
            self._refresh_pokercraft()

    def _page_header(self, parent, title: str, subtitle: str = ""):
        frame = tk.Frame(parent, bg=COLORS["bg"])
        frame.pack(fill="x", padx=22, pady=(20, 12))
        tk.Label(frame, text=title, bg=COLORS["bg"], fg=COLORS["text"], font=("Segoe UI", 19, "bold")).pack(anchor="w")
        if subtitle:
            tk.Label(frame, text=subtitle, bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))
        return frame

    def _panel(self, parent, title: str, padding: int = 12):
        outer = tk.Frame(parent, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        tk.Label(outer, text=title, bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=padding, pady=(padding, 7))
        inner = tk.Frame(outer, bg=COLORS["panel"])
        inner.pack(fill="both", expand=True, padx=padding, pady=(0, padding))
        return outer, inner

    # ---------- Lobby ----------
    def _build_lobby(self):
        page = self._new_page("lobby")
        self._page_header(page, "Poker Lobby", "Choose a game format. VIP is a separate 6-max NLH ring game, not fast-fold.")
        # Each Rush & Cash stake card is the direct entry point; no oversized shortcut sits above them.
        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True, padx=22, pady=(4, 14))

        rush_tab_host, rush_tab = self._make_scrollable_tab(notebook, "  RUSH & CASH  ", COLORS["bg"])
        vip_tab_host, vip_tab = self._make_scrollable_tab(notebook, "  VIP GAMES  ", COLORS["bg"])

        rush_wrap = tk.Frame(rush_tab, bg=COLORS["bg"])
        rush_wrap.pack(fill="both", expand=True, padx=4, pady=8)
        rates = [("NL2", "$0.01 / $0.02"), ("NL5", "$0.02 / $0.05"),
                 ("NL10", "$0.05 / $0.10"), ("NL25", "$0.10 / $0.25"),
                 ("NL50", "$0.25 / $0.50"), ("NL100", "$0.50 / $1.00"),
                 ("NL200", "$1.00 / $2.00")]
        for i, (name, blinds) in enumerate(rates):
            card = tk.Frame(rush_wrap, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
            card.grid(row=i // 3, column=i % 3, padx=9, pady=9, sticky="nsew")
            tk.Label(card, text=name, bg=COLORS["panel"], fg=COLORS["green"], font=("Segoe UI", 19, "bold")).pack(anchor="w", padx=16, pady=(16, 2))
            tk.Label(card, text=blinds, bg=COLORS["panel"], fg=COLORS["text"], font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16)
            tk.Label(card, text="FAST-FOLD • 6-max • CPU pool", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(4, 15))
            ttk.Button(card, text="OPEN TABLE", style="Accent.TButton", command=lambda r=name: self._join_table(r)).pack(anchor="w", padx=16, pady=(0, 16))
        for c in range(3):
            rush_wrap.grid_columnconfigure(c, weight=1)
        for r in range(3):
            rush_wrap.grid_rowconfigure(r, weight=1)
        tk.Label(rush_tab, text="※ Rush & Cash opponents rotate after every hand. Local CPU tables; no live player counts.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", padx=12, pady=(0, 10))

        vip_outer = tk.Frame(vip_tab, bg=COLORS["bg"])
        vip_outer.pack(fill="both", expand=True, padx=18, pady=18)
        vip_card = tk.Frame(vip_outer, bg="#171d2b", highlightbackground="#a98647", highlightthickness=2)
        vip_card.pack(fill="x", anchor="n")
        ribbon = tk.Frame(vip_card, bg="#3a2b18")
        ribbon.pack(fill="x")
        tk.Label(ribbon, text="PRIVATE TABLE  •  EXCLUSIVE STYLE", bg="#3a2b18", fg="#f1cf86",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=7)
        tk.Label(vip_card, text="VIP NLH", bg="#171d2b", fg="#f1cf86",
                 font=("Segoe UI", 26, "bold")).pack(anchor="w", padx=20, pady=(17, 2))
        tk.Label(vip_card, text="$25 / $50", bg="#171d2b", fg=COLORS["text"],
                 font=("Segoe UI", 18, "bold")).pack(anchor="w", padx=20)
        tk.Label(vip_card, text="NO-LIMIT HOLD’EM  •  6-MAX RING GAME  •  NO RUSH FOLD  •  SAME OPPONENTS BETWEEN HANDS",
                 bg="#171d2b", fg="#b7c6d8", font=("Segoe UI", 9, "bold"), wraplength=980,
                 justify="left").pack(anchor="w", padx=20, pady=(9, 5))
        tk.Label(vip_card, text="Buy-in: 20–100 BB ($1,000–$5,000)  •  Default: 100 BB ($5,000)  •  No ante",
                 bg="#171d2b", fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(0, 7))
        tk.Label(vip_card, text="Separate from Rush & Cash. The button rotates and CPU seats keep their identities and remaining stacks.",
                 bg="#171d2b", fg=COLORS["muted"], font=("Segoe UI", 9), wraplength=980,
                 justify="left").pack(anchor="w", padx=20, pady=(0, 16))
        ttk.Button(vip_card, text="OPEN VIP TABLE", style="Accent.TButton",
                   command=self._open_vip_buyin_dialog).pack(anchor="w", padx=20, pady=(0, 20))
        tk.Label(vip_tab, text="GGPOKERのVIP / Exclusive系高額ゲームを参考にしたローカル専用テーブルです。実際のGGPOKERへの接続や招待機能はありません。",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=980,
                 justify="left").pack(anchor="w", padx=22, pady=(0, 10))

    def _open_vip_buyin_dialog(self):
        """Choose a standard VIP stack in the 20–100 BB range before seating."""
        window = tk.Toplevel(self)
        window.title("VIP NLH • Buy-in")
        window.geometry("420x260")
        window.resizable(False, False)
        window.configure(bg=COLORS["panel"])
        window.transient(self)
        window.grab_set()
        tk.Label(window, text="VIP NLH  •  $25 / $50", bg=COLORS["panel"], fg="#f1cf86",
                 font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=20, pady=(18, 5))
        tk.Label(window, text="Choose your starting stack (20–100 BB)", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=20)
        buyin_var = tk.StringVar(value=str(VIP_DEFAULT_BUYIN_BB))
        row = tk.Frame(window, bg=COLORS["panel"])
        row.pack(fill="x", padx=20, pady=15)
        ttk.Combobox(row, textvariable=buyin_var, state="readonly", width=10,
                     values=("20", "40", "60", "80", "100")).pack(side="left")
        amount_label = tk.StringVar(value="$5,000.00")
        tk.Label(row, textvariable=amount_label, bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=14)
        def update_amount(*_):
            try:
                bb = int(buyin_var.get())
                amount_label.set(f"${bb * VIP_BIG_BLIND_CENTS / 100:,.2f}")
            except (TypeError, ValueError):
                amount_label.set("—")
        buyin_var.trace_add("write", update_amount)
        buttons = tk.Frame(window, bg=COLORS["panel"])
        buttons.pack(fill="x", padx=20, pady=(4, 18))
        ttk.Button(buttons, text="CANCEL", command=window.destroy).pack(side="right", padx=(6, 0))
        def join():
            try:
                bb = int(buyin_var.get())
                if not VIP_MIN_BUYIN_BB <= bb <= VIP_MAX_BUYIN_BB:
                    raise ValueError("VIP buy-in must be between 20 and 100 BB")
            except (TypeError, ValueError) as exc:
                messagebox.showerror("VIP buy-in", str(exc), parent=window)
                return
            window.destroy()
            self._join_table(VIP_STAKE_KEY, table_mode=VIP_MODE, buyin_bb=bb)
        ttk.Button(buttons, text="TAKE A SEAT", style="Accent.TButton", command=join).pack(side="right")


    def _cash_state_snapshot(self) -> dict[str, Any]:
        """Capture the active table's mutable state; wallet and stores are shared."""
        active_slot = self.multi_tables.get(self.active_cash_table_id) if getattr(self, "active_cash_table_id", None) else None
        slot_state = active_slot.state if active_slot else {}
        return {
            "cash_game_mode": normalize_table_mode(getattr(self, "cash_game_mode", RUSH_MODE)),
            "cash_table": self.cash_table,
            "cash_cpus": self.cash_cpus,
            "cash_gto_session": self.cash_gto_session,
            "cash_gto_spot_mode": self.cash_gto_spot_mode,
            "cash_spot_side": self.cash_spot_side,
            "cash_busy": self.cash_busy,
            "cash_syncing_gto": self.cash_syncing_gto,
            "cash_gto_waiting": bool(slot_state.get("cash_gto_waiting", False)),
            "cash_rate": self.cash_rate,
            "cash_sb": self.cash_sb,
            "cash_bb": self.cash_bb,
            "cash_buyin": self.cash_buyin,
            "cash_bet_value": self.cash_bet_var.get(),
            "hero_squeeze_count": self.hero_squeeze_count,
            "board_squeeze_count": self.board_squeeze_count,
            "cash_status": self.cash_status_var.get(),
            "cash_source": self.cash_source_var.get(),
            "cash_sitout_before_bb": bool(slot_state.get("cash_sitout_before_bb", False)),
            "cash_run_it_preference": slot_state.get("cash_run_it_preference", "ask"),
            "cash_sitting_out": bool(slot_state.get("cash_sitting_out", False)),
            "cash_sitout_pending": bool(slot_state.get("cash_sitout_pending", False)),
            "cash_timebank_cards_remaining": int(slot_state.get("cash_timebank_cards_remaining", DEFAULT_FREE_TIMEBANK_CARDS)),
            "cash_timebank_armed": bool(slot_state.get("cash_timebank_armed", False)),
            "cash_timebank_paid_armed": bool(slot_state.get("cash_timebank_paid_armed", False)),
            "cash_timebank_paid_used_this_hand": bool(slot_state.get("cash_timebank_paid_used_this_hand", False)),
            "cash_timebank_fee_due": int(slot_state.get("cash_timebank_fee_due", 0)),
            "cash_timebank_active_until": float(slot_state.get("cash_timebank_active_until", 0.0)),
            "cash_timebank_last_kind": str(slot_state.get("cash_timebank_last_kind", "")),
            "cash_resume_requested": bool(slot_state.get("cash_resume_requested", False)),
            "preflop_fold_pending": bool(getattr(self, "preflop_fold_pending", False)),
            "cash_rush_fold_pending": bool(slot_state.get("cash_rush_fold_pending", False)),
            "postflop_auto_fold": bool(getattr(self, "postflop_auto_fold", False)),
            "postflop_auto_fold_hand_token": getattr(self, "postflop_auto_fold_hand_token", None),
            "cash_log_lines": list(self.cash_log_lines),
            "cash_random": self.cash_random,
            "cash_session_id": self.cash_session_id,
            "cash_hand_instance": self.cash_hand_instance,
            "cash_current_hand_key": self.cash_current_hand_key,
            "range_paid_hand_key": slot_state.get("range_paid_hand_key"),
            "range_paid_chart": slot_state.get("range_paid_chart"),
            "cash_cpu_profiles": dict(self.cash_cpu_profiles),
            "vip_cpu_roles": dict(self.vip_cpu_roles),
            "cash_visible_board": list(self.cash_visible_board),
            "cash_board_target": list(self.cash_board_target),
            "cash_board_reveal_count": int(self.cash_board_reveal_count),
            "cash_board_anim_index": self.cash_board_anim_index,
            "cash_board_anim_progress": float(self.cash_board_anim_progress),
            "cash_board_anim_indices": list(slot_state.get("cash_board_anim_indices", [])),
            "cash_action_flash": dict(slot_state.get("cash_action_flash", {})) if slot_state.get("cash_action_flash") else None,
            "cash_deal_counts": dict(self.cash_deal_counts),
            "cash_initial_flip": dict(getattr(self, "cash_initial_flip", {})),
            "cash_board_squeeze": dict(getattr(self, "cash_board_squeeze", {})) if getattr(self, "cash_board_squeeze", None) else None,
            "cash_squeeze_deadline_at": float(getattr(self, "cash_squeeze_deadline_at", 0.0)),
            "cash_action_deadline_mode": str(getattr(self, "cash_action_deadline_mode", "") or ""),
            "cash_last_turn_sound_key": getattr(self, "cash_last_turn_sound_key", None),
            "cash_deal_flying": dict(self.cash_deal_flying) if self.cash_deal_flying else None,
            "cash_deal_busy": bool(self.cash_deal_busy),
            "cash_action_feed": self.cash_action_feed,
            "cash_thinking_player": self.cash_thinking_player,
            "ggcare_candidate": self.ggcare_candidate,
        }

    def _save_active_cash_slot(self):
        if self.active_cash_table_id and self.cash_table is not None:
            try:
                self.multi_tables.update_active(self._cash_state_snapshot(), self.cash_rate)
            except Exception:
                pass

    def _restore_cash_slot(self, table_id: str):
        slot = self.multi_tables.activate(table_id)
        state = slot.state
        self.cash_table = state.get("cash_table")
        self.cash_cpus = state.get("cash_cpus", {})
        self.cash_gto_session = None  # Discard legacy GTO+ sessions after engine removal.
        self.cash_gto_spot_mode = False  # GTO+ spot mode is no longer available.
        self.cash_spot_side = state.get("cash_spot_side", "OOP")
        self.cash_busy = bool(state.get("cash_busy", False))
        self.cash_syncing_gto = False
        state["cash_gto_waiting"] = bool(state.get("cash_gto_waiting", False))
        self.cash_rate = state.get("cash_rate", slot.rate)
        self.cash_game_mode = normalize_table_mode(state.get("cash_game_mode", RUSH_MODE))
        self.cash_sb = int(state.get("cash_sb", 0))
        self.cash_bb = int(state.get("cash_bb", 0))
        self.cash_buyin = int(state.get("cash_buyin", self.cash_bb * 100))
        self.cash_bet_var.set(str(state.get("cash_bet_value", "0.50")))
        self.hero_squeeze_count = int(state.get("hero_squeeze_count", 0))
        self.board_squeeze_count = int(state.get("board_squeeze_count", 5))
        self.cash_status_var.set(state.get("cash_status", "Table ready"))
        self.cash_source_var.set(state.get("cash_source", "CPU strategy: waiting"))
        normalize_table_pause_state(state)
        self.cash_sitout_before_bb_var.set(bool(state.get("cash_sitout_before_bb", False)))
        self.preflop_fold_pending = bool(state.get("preflop_fold_pending", False))
        self.postflop_auto_fold = bool(state.get("postflop_auto_fold", False))
        self.postflop_auto_fold_hand_token = state.get("postflop_auto_fold_hand_token")
        self.cash_log_lines = list(state.get("cash_log_lines", []))
        self.cash_random = state.get("cash_random", random.Random())
        self.cash_session_id = state.get("cash_session_id", uuid.uuid4().hex)
        self.cash_hand_instance = int(state.get("cash_hand_instance", 0))
        self.cash_current_hand_key = state.get("cash_current_hand_key")
        state["range_paid_hand_key"] = state.get("range_paid_hand_key")
        self.cash_cpu_profiles = dict(state.get("cash_cpu_profiles", {}))
        self.vip_cpu_roles = dict(state.get("vip_cpu_roles", {}))
        self.cash_visible_board = list(state.get("cash_visible_board", []))
        self.cash_board_target = list(state.get("cash_board_target", []))
        self.cash_board_reveal_count = int(state.get("cash_board_reveal_count", len(self.cash_visible_board)))
        self.cash_board_anim_index = state.get("cash_board_anim_index")
        self.cash_board_anim_progress = float(state.get("cash_board_anim_progress", 1.0))
        self.cash_deal_counts = dict(state.get("cash_deal_counts", {}))
        self.cash_initial_flip = dict(state.get("cash_initial_flip", {"complete": False, "progress": {}}))
        self.cash_board_squeeze = dict(state.get("cash_board_squeeze") or {})
        self.cash_squeeze_deadline_at = float(state.get("cash_squeeze_deadline_at", 0.0))
        self.cash_action_deadline_mode = str(state.get("cash_action_deadline_mode", "") or "")
        self.cash_last_turn_sound_key = state.get("cash_last_turn_sound_key")
        self.cash_deal_flying = state.get("cash_deal_flying")
        self.cash_deal_busy = bool(state.get("cash_deal_busy", False))
        self.cash_action_feed = str(state.get("cash_action_feed", ""))
        self.cash_thinking_player = state.get("cash_thinking_player")
        self.ggcare_candidate = state.get("ggcare_candidate")
        self.active_cash_table_id = table_id
        self.table_title_var.set(f"{table_mode_label(self.cash_game_mode)}  •  {self.cash_rate}")
        self._refresh_table_tabs()
        self._draw_table()
        self._render_cash_actions()
        self._refresh_cash_history()
        self._refresh_table_windows()

    def _switch_cash_table(self, table_id: str):
        if table_id == self.active_cash_table_id:
            return
        # A busy table keeps running independently; switching only changes the
        # currently focused table state, not that table's worker/animation.
        self._save_active_cash_slot()
        try:
            self._restore_cash_slot(table_id)
        except KeyError:
            return

    def _refresh_table_tabs(self):
        """Show only the open-window count; game control stays inside each table window."""
        if not hasattr(self, "table_tabs_frame"):
            return
        for child in self.table_tabs_frame.winfo_children():
            child.destroy()
        tk.Label(self.table_tabs_frame, text="TABLE WINDOWS", bg=COLORS["bg"],
                 fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(self.table_tabs_frame, text=f"{len(self.multi_tables)}/2 OPEN",
                 bg=COLORS["bg"], fg=COLORS["green"],
                 font=("Segoe UI", 9, "bold")).pack(side="right")
        self._refresh_table_dashboard()

    def _join_table(self, rate: str, *, table_mode: str = RUSH_MODE, buyin_bb: int | None = None):
        self._sync_external_wallet_balance()
        table_mode = normalize_table_mode(table_mode)
        rates = {
            "NL2": (1, 2), "NL5": (2, 5), "NL10": (5, 10),
            "NL25": (10, 25), "NL50": (25, 50), "NL100": (50, 100),
            "NL200": (100, 200),
            VIP_STAKE_KEY: (VIP_SMALL_BLIND_CENTS, VIP_BIG_BLIND_CENTS),
        }
        if rate not in rates or (is_vip_mode(table_mode) and rate != VIP_STAKE_KEY):
            messagebox.showerror("Poker Lobby", f"Unknown game/stake: {rate}")
            return
        # Each table owns its own action/deal lock. Joining another table does
        # not need to wait for the currently open table's CPU animation.
        if self.multi_tables.full:
            messagebox.showwarning("Table limit", "同時に開けるテーブルは最大2卓です。先にいずれかの卓を閉じてください。")
            return
        self._save_active_cash_slot()
        self.cash_rate = rate
        self.cash_game_mode = table_mode
        self.cash_session_id = uuid.uuid4().hex
        self.cash_hand_instance = 0
        self.preflop_fold_pending = False
        self.postflop_auto_fold = False
        self.postflop_auto_fold_hand_token = None
        self.cash_current_hand_key = None
        self.cash_sb, self.cash_bb = rates[rate]
        if is_vip_mode(table_mode):
            selected_buyin_bb = VIP_DEFAULT_BUYIN_BB if buyin_bb is None else int(buyin_bb)
            if not VIP_MIN_BUYIN_BB <= selected_buyin_bb <= VIP_MAX_BUYIN_BB:
                messagebox.showerror("VIP buy-in", "VIP buy-in must be between 20 and 100 BB")
                return
            self.cash_buyin = self.cash_bb * selected_buyin_bb
        else:
            self.cash_buyin = self.cash_bb * 100
        if self.cash_balance_cents < self.cash_buyin:
            required = self.cash_buyin / 100
            messagebox.showwarning(
                "Wallet balance too low",
                f"この卓には ${required:,.2f} の残高が必要です。Cashierでシミュレーション入金してください。"
            )
            self.show_page("cashier")
            return
        self.cash_balance_cents -= self.cash_buyin
        self._update_cash_balance()
        self._record_cash_transaction("buy-in", -self.cash_buyin,
                                       note=f"{rate} initial {self.cash_buyin // max(1, self.cash_bb)} BB")
        profiles = self.cpu_pool_store.sample_opponents(self.cash_rate, count=5, rng=self.cash_random)
        self.cash_cpu_profiles = {profile.cpu_id: profile for profile in profiles}
        self.vip_cpu_roles = (assign_vip_cpu_roles(
            [profile.cpu_id for profile in profiles], rng=self.cash_random
        ) if is_vip_mode(table_mode) else {})
        cpu_players = [(profile.cpu_id, profile.name, self.cash_buyin) for profile in profiles]
        players = cpu_players[:3] + [("hero", "YOU", self.cash_buyin)] + cpu_players[3:]
        if is_vip_mode(table_mode):
            # Reference profile: 5% rake with a $25 cap for the $25/$50
            # standard 6-max VIP listing found in public GGPoker stake tables.
            rake_bps, rake_cap = 500, 2_500
        else:
            rake_bps = int(round(float(self.config_data.get("cash_rake_pct", 0.0)) * 100))
            rake_cap = int(self.config_data.get("cash_rake_cap_cents", 0))
        self.cash_table = CashTable(players, self.cash_sb, self.cash_bb,
                                    dealer_index=self.cash_random.randrange(6),
                                    rng=self.cash_random, rake_bps=rake_bps, rake_cap=rake_cap)
        # Each Rush & Cash hand gets five distinct identities from the persistent
        # 100-player pool. Their level is independently assigned for this stake.
        self.cash_cpus = {
            profile.cpu_id: CashGameCPU(
                level=(5 if is_vip_mode(table_mode) else profile.level),
                rng=random.Random(self.cash_random.randrange(2**32)),
                simulations=48,
                archetype=("balanced" if is_vip_mode(table_mode) else profile.archetype),
                # VIP GTO/near-GTO roles are lineup specifications at this stage.
                # Do not apply a solver deviation to the level-5 fallback engine.
            )
            for profile in profiles
        }
        self.cash_gto_session = None
        self.cash_gto_spot_mode = False
        self.cash_busy = False
        self.ggcare_candidate = None
        self.cash_random = random.Random()
        self.cash_bet_var.set("")
        buyin_units = self.cash_buyin // max(1, self.cash_bb)
        mode_note = (f"VIP NLH $25/$50 • regular ring • persistent 6-max seats • buy-in {buyin_units} BB"
                     if is_vip_mode(table_mode) else f"Rush & Cash {rate} • buy-in 100 BB • rotating 6-max CPU pool")
        self.cash_log_lines = [f"Joined {mode_note}"]
        if is_vip_mode(table_mode):
            self.cash_log_lines.append(
                f"VIP lineup specification: {VIP_PURE_GTO_COUNT} PURE-GTO-role seats + "
                f"{VIP_NEAR_GTO_COUNT} NEAR-GTO-role seats. Strategy split is not fully implemented yet."
            )
            self.cash_log_lines.append(
                "CPU scope: HU postflop requires an exact GTO+ node match and pauses on a miss; preflop/multiway use the local level-5 policy (not GTO+)."
            )
        slot_state = self._cash_state_snapshot()
        slot_state.update({
            "cash_sitout_before_bb": False,
            "cash_sitting_out": False,
            "cash_sitout_pending": False,
            "cash_timebank_cards_remaining": max(0, int(self.config_data.get("cash_timebank_cards_per_session", DEFAULT_FREE_TIMEBANK_CARDS))),
            "cash_timebank_armed": False,
            "cash_timebank_paid_armed": False,
            "cash_timebank_paid_used_this_hand": False,
            "cash_timebank_fee_due": 0,
            "cash_timebank_active_until": 0.0,
            "cash_timebank_last_kind": "",
            "cash_resume_requested": False,
        })
        slot = self.multi_tables.add(rate, slot_state)
        self.active_cash_table_id = slot.table_id
        self.table_title_var.set(f"{table_mode_label(table_mode)}  •  {rate}")
        if is_vip_mode(table_mode):
            self._play_sound("vip_entry")
        self._create_table_window(slot.table_id)
        self._refresh_table_tabs()
        self._start_cash_hand(first=True)
        self._save_active_cash_slot()
        self.show_page("lobby")
        self._bring_table_front(slot.table_id)

    def _update_cash_balance(self):
        # The shared Study Wallet SQLite account is authoritative. All financial
        # actions commit through wallet_store.record/deposit_study_time; this
        # method only refreshes labels and the compatibility config cache.
        balance_text = f"${self.cash_balance_cents / 100:,.2f}"
        self.balance_var.set(balance_text)
        self.config_data["balance"] = self.cash_balance_cents / 100
        self._refresh_live_range_icons()
        for record in getattr(self, "table_windows", {}).values():
            try:
                record["wallet"].set(f"WALLET  {balance_text}")
            except (KeyError, tk.TclError):
                pass
        try:
            save_config(self.config_data)
        except Exception:
            pass

    def _build_cashier_page(self):
        page = self._new_page("cashier")
        self._page_header(page, "Cashier", "Study-time funded simulated wallet • no real payment processing")
        summary = tk.Frame(page, bg=COLORS["bg"])
        summary.pack(fill="x", padx=22, pady=(0, 10))
        self.cashier_summary_var = tk.StringVar(value="")
        tk.Label(summary, textvariable=self.cashier_summary_var, bg=COLORS["bg"], fg=COLORS["green"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(summary, text="OPEN STUDY WALLET", command=self._open_study_wallet).pack(side="right")
        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True, padx=22, pady=(0, 12))
        deposit_host, deposit = self._make_scrollable_tab(notebook, "Deposit", COLORS["panel"])
        withdraw_host, withdraw = self._make_scrollable_tab(notebook, "Withdraw", COLORS["panel"])
        history_host, history = self._make_scrollable_tab(notebook, "Transaction History", COLORS["panel"])
        transfer_host, transfer = self._make_scrollable_tab(notebook, "Transfer", COLORS["panel"])

        # Always-visible allowance and poker P&L directly above the deposit form.
        funding_panel = tk.Frame(deposit, bg=COLORS["panel2"],
                                 highlightbackground=COLORS["border"], highlightthickness=1)
        funding_panel.pack(fill="x", padx=28, pady=(20, 0))
        funding_top = tk.Frame(funding_panel, bg=COLORS["panel2"])
        funding_top.pack(fill="x", padx=18, pady=(14, 3))
        tk.Label(funding_top, text="AVAILABLE TO DEPOSIT", bg=COLORS["panel2"],
                 fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(funding_panel, textvariable=self.study_depositable_var, bg=COLORS["panel2"],
                 fg=COLORS["gold"], font=("Segoe UI", 23, "bold")).pack(anchor="w", padx=18, pady=(0, 2))
        tk.Label(funding_panel, textvariable=self.study_hours_detail_var, bg=COLORS["panel2"],
                 fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(0, 8))
        pnl_row = tk.Frame(funding_panel, bg=COLORS["panel2"])
        pnl_row.pack(fill="x", padx=18, pady=(0, 14))
        tk.Label(pnl_row, text="POKER PROFIT / LOSS", bg=COLORS["panel2"],
                 fg=COLORS["muted"], font=("Segoe UI", 9, "bold")).pack(side="left")
        self.cashier_pnl_label = tk.Label(pnl_row, textvariable=self.poker_pnl_var,
                 bg=COLORS["panel2"], fg=COLORS["white"],
                 font=("Segoe UI", 15, "bold"))
        self.cashier_pnl_label.pack(side="left", padx=(16, 0))

        self._cashier_form(deposit, "STUDY-TIME DEPOSIT", self.cashier_amount_var,
                           "Use previously withdrawn funds first, then remaining whole-dollar Study allowance. Withdrawn funds can be deposited back into your Pigeon Wallet.",
                           self._cashier_deposit, "DEPOSIT AVAILABLE FUNDS")
        self._cashier_form(withdraw, "MOVE TO WITHDRAWABLE", self.cashier_withdraw_var,
                           "Move funds from Wallet into Withdrawable Balance. The amount remains available in your local wallet ledger.",
                           self._cashier_withdraw, "MOVE TO WITHDRAWABLE")
        self._cashier_form(transfer, "SIMULATED TRANSFER", self.cashier_transfer_var,
                           "Record an offline demo transfer to a virtual recipient. No real player or external account receives funds.",
                           self._cashier_transfer, "SIMULATE TRANSFER", recipient=True)
        cols = ("date", "type", "amount", "balance", "recipient", "note")
        self.cashier_tree = ttk.Treeview(history, columns=cols, show="headings", height=18)
        headings = {"date": "DATE", "type": "TYPE", "amount": "AMOUNT", "balance": "BALANCE AFTER",
                    "recipient": "RECIPIENT", "note": "DETAIL"}
        widths = {"date": 155, "type": 135, "amount": 100, "balance": 120, "recipient": 150, "note": 380}
        for col in cols:
            self.cashier_tree.heading(col, text=headings[col])
            self.cashier_tree.column(col, width=widths[col], anchor="center" if col != "note" else "w")
        self.cashier_tree.pack(fill="both", expand=True, padx=12, pady=12)
        self.cashier_status_label = tk.Label(page, textvariable=self.cashier_status_var, bg=COLORS["bg"],
                                             fg=COLORS["muted"], font=("Segoe UI", 8))
        self.cashier_status_label.pack(anchor="w", padx=24, pady=(0, 8))
        self._refresh_cashier()

    def _cashier_form(self, parent, title: str, amount_var: tk.StringVar,
                      description: str, command, button_text: str, recipient: bool = False):
        frame = tk.Frame(parent, bg=COLORS["panel"])
        frame.pack(anchor="nw", padx=28, pady=28)
        tk.Label(frame, text=title, bg=COLORS["panel"], fg=COLORS["text"],
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(frame, text=description, bg=COLORS["panel"], fg=COLORS["muted"],
                 wraplength=720, justify="left", font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 14))
        tk.Label(frame, text="Amount (USD)", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w")
        ttk.Entry(frame, textvariable=amount_var, width=18).pack(anchor="w", pady=(3, 12))
        if recipient:
            tk.Label(frame, text="Virtual recipient ID", bg=COLORS["panel"], fg=COLORS["muted"],
                     font=("Segoe UI", 9)).pack(anchor="w")
            ttk.Entry(frame, textvariable=self.cashier_recipient_var, width=28).pack(anchor="w", pady=(3, 12))
        ttk.Button(frame, text=button_text, style="Accent.TButton", command=command).pack(anchor="w")

    @staticmethod
    def _parse_cashier_amount(text: str) -> int:
        amount = float(str(text).strip().replace(",", ""))
        if amount <= 0 or amount > 1_000_000:
            raise ValueError("金額は$0.01〜$1,000,000.00の範囲で入力してください。")
        return int(round(amount * 100))

    def _record_cash_transaction(self, kind: str, delta: int, *, recipient: str = "", note: str = ""):
        # Balance and transaction history are committed atomically to the same
        # SQLite account opened by the standalone Study Wallet.
        self.wallet_store.record(kind, delta, self.cash_balance_cents,
                                 recipient=recipient, note=note)
        self._refresh_cashier()

    @staticmethod
    def _parse_study_deposit_dollars(text: str) -> int:
        from decimal import Decimal, InvalidOperation
        raw = str(text).strip().replace(",", "").replace("$", "")
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError("入金額は整数のドルで入力してください。") from exc
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("Study時間の入金は整数ドルのみです（例：50）。")
        dollars = int(value)
        if dollars <= 0:
            raise ValueError("入金額は$1以上で入力してください。")
        return dollars * 100

    def _active_cash_table_stacks_cents(self) -> int:
        total = 0
        try:
            self._save_active_cash_slot()
        except Exception:
            pass
        for slot in self.multi_tables.list() if hasattr(self, "multi_tables") else []:
            state = slot.state
            table = state.get("cash_table")
            if table is None or state.get("cash_gto_spot_mode"):
                continue
            try:
                table.sync_external_hand_state()
                hero = next((seat for seat in table.seats if seat.get("id") == "hero"), None)
                if hero is not None:
                    total += max(0, int(hero.get("stack", 0)))
            except Exception:
                continue
        return total

    def _cashier_poker_pnl_cents(self) -> int:
        # Game P&L = realized table cash-outs - all buy-ins/rebuys + chips still
        # held at open tables. Study credits, GG CARE rewards, transfers and
        # wallet withdrawals are deliberately excluded from poker performance.
        flows = self.cashier_ledger.sum_delta_for_kinds(
            ("buy-in", "manual-rebuy", "auto-rebuy", "cash-out")
        )
        return int(flows + self._active_cash_table_stacks_cents())

    def _sync_external_wallet_balance(self):
        """Read the shared Wallet balance in both directions without writing it back."""
        try:
            external_balance = max(0, int(self.wallet_store.get_balance(0)))
            if external_balance == self.cash_balance_cents:
                return
            self.cash_balance_cents = external_balance
            balance_text = f"${external_balance / 100:,.2f}"
            self._refresh_live_range_icons()
            try:
                self.balance_var.set(balance_text)
            except (AttributeError, tk.TclError):
                pass
            self.config_data["balance"] = external_balance / 100
            for record in getattr(self, "table_windows", {}).values():
                try:
                    record["wallet"].set(f"WALLET  {balance_text}")
                except (KeyError, AttributeError, tk.TclError):
                    pass
            try:
                save_config(self.config_data)
            except Exception:
                pass
        except Exception as exc:
            # A transient SQLite lock is retried by the periodic refresh.
            self.cashier_link_error = str(exc)

    def _refresh_study_funding_panel(self):
        if not hasattr(self, "study_depositable_var"):
            return
        snapshot = read_study_time_snapshot()
        self.study_snapshot_connected = bool(snapshot.connected)
        redeemed = self.wallet_store.redeemed_study_cents()
        study_available = (
            available_deposit_cents(snapshot.total_seconds, redeemed)
            if snapshot.connected else 0
        )
        withdrawable = self._withdrawable_balance_cents()
        total_available = max(0, int(study_available) + int(withdrawable))
        self.study_depositable_cents = total_available
        dollar = chr(36)
        self.study_depositable_var.set(f"{dollar}{total_available / 100:,.2f}")
        if snapshot.connected:
            updated = snapshot.updated_at.replace("T", " ")[:19] if snapshot.updated_at else "unknown"
            self.study_hours_detail_var.set(
                f"Study allowance {dollar}{study_available / 100:,.2f} + "
                f"withdrawable {dollar}{withdrawable / 100:,.2f} • "
                f"Focus Timer {snapshot.total_hours:,.2f}h • Updated {updated}"
            )
        else:
            self.study_hours_detail_var.set(
                f"Focus Timer not linked • withdrawable {dollar}{withdrawable / 100:,.2f} "
                "remains available to deposit into Pigeon"
            )
        pnl = self._cashier_poker_pnl_cents()
        try:
            self.wallet_store.set_live_poker_stack(self._active_cash_table_stacks_cents())
        except Exception:
            pass
        self.poker_pnl_var.set(format_signed_usd(pnl))
        if self.cashier_pnl_label is not None:
            colour = COLORS["red"] if pnl < 0 else (COLORS["green"] if pnl > 0 else COLORS["white"])
            self.cashier_pnl_label.configure(fg=colour)
    def _study_cashier_live_refresh(self):
        try:
            self._sync_external_wallet_balance()
            # Keep the standalone Study Wallet's P&L current even while the
            # Cashier page is not visible and Pigeon is playing at other tables.
            try:
                self.wallet_store.set_live_poker_stack(self._active_cash_table_stacks_cents())
            except Exception:
                pass
            cashier_page = getattr(self, "pages", {}).get("cashier")
            if cashier_page is not None and cashier_page.winfo_exists() and cashier_page.winfo_ismapped():
                self._refresh_study_funding_panel()
        except tk.TclError:
            pass
        finally:
            try:
                self._study_cashier_refresh_id = self.after(2500, self._study_cashier_live_refresh)
            except tk.TclError:
                self._study_cashier_refresh_id = None

    def _redeposit_available_funds(self, amount_cents: int):
        import sqlite3
        amount = int(amount_cents)
        if amount <= 0:
            raise ValueError("入金額を入力してください。")
        snapshot = read_study_time_snapshot()
        connected = bool(getattr(snapshot, "connected", False))
        total_seconds = max(0, int(getattr(snapshot, "total_seconds", 0) or 0))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with sqlite3.connect(str(self.wallet_store.db_path), timeout=20) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=20000")
            con.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in con.execute("PRAGMA table_info(wallet_account)")}
            if "withdrawable_cents" not in columns:
                con.execute("ALTER TABLE wallet_account ADD COLUMN withdrawable_cents INTEGER NOT NULL DEFAULT 0")
            row = con.execute(
                "SELECT balance_cents,withdrawable_cents FROM wallet_account WHERE account_id=1"
            ).fetchone()
            if row is None:
                con.execute("ROLLBACK")
                raise ValueError("ウォレット口座が見つかりません。")
            balance = max(0, int(row["balance_cents"]))
            withdrawable = max(0, int(row["withdrawable_cents"]))
            withdrawn_part = min(amount, withdrawable)
            study_part = amount - withdrawn_part
            redeemed_row = con.execute(
                "SELECT COALESCE(SUM(amount_cents),0) FROM study_redemptions"
            ).fetchone()
            redeemed = max(0, int(redeemed_row[0] or 0))
            study_available = (
                max(0, (total_seconds // 3600) * 100 - redeemed)
                if connected else 0
            )
            if study_part > 0:
                if not connected:
                    con.execute("ROLLBACK")
                    raise ValueError(
                        "出金済み残高を超える入金にはFocus TimerのStudy時間が必要です。"
                    )
                if study_part % 100:
                    con.execute("ROLLBACK")
                    raise ValueError(
                        "Study時間分の入金は整数ドルです。セント単位の入金には出金済み残高をご利用ください。"
                    )
                if study_part > study_available:
                    con.execute("ROLLBACK")
                    combined = withdrawn_part + study_available
                    dollar = chr(36)
                    raise ValueError(
                        f"入金可能額は {dollar}{combined / 100:,.2f} です "
                        f"(出金済み {dollar}{withdrawn_part / 100:,.2f} + Study {dollar}{study_available / 100:,.2f})。"
                    )
            new_balance = balance
            if withdrawn_part > 0:
                new_balance += withdrawn_part
                con.execute(
                    "INSERT INTO cashier_transactions "
                    "(transaction_id,played_at,kind,delta_cents,balance_after_cents,recipient,note) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, now, "withdrawable-redeposit", withdrawn_part,
                     new_balance, "", "Returned from Withdrawable Balance to Pigeon Wallet"),
                )
            if study_part > 0:
                new_balance += study_part
                note = f"Redeemed {study_part // 100} cumulative Study hours at $1/hour"
                txid = uuid.uuid4().hex
                con.execute(
                    "INSERT INTO cashier_transactions "
                    "(transaction_id,played_at,kind,delta_cents,balance_after_cents,recipient,note) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (txid, now, "study-time-deposit", study_part, new_balance, "", note),
                )
                con.execute(
                    "INSERT INTO study_redemptions "
                    "(transaction_id,redeemed_at,amount_cents,balance_after_cents,total_study_seconds,note) "
                    "VALUES(?,?,?,?,?,?)",
                    (txid, now, study_part, new_balance, total_seconds, note),
                )
            new_withdrawable = withdrawable - withdrawn_part
            con.execute(
                "UPDATE wallet_account SET balance_cents=?,withdrawable_cents=?,updated_at=? "
                "WHERE account_id=1",
                (new_balance, new_withdrawable, now),
            )
            con.execute("COMMIT")
        remaining_study = max(0, study_available - study_part)
        return {
            "balance_cents": new_balance,
            "withdrawable_cents": new_withdrawable,
            "withdrawn_part_cents": withdrawn_part,
            "study_part_cents": study_part,
            "remaining_study_cents": remaining_study,
        }

    def _cashier_deposit(self):
        try:
            self._sync_external_wallet_balance()
            amount = self._parse_cashier_amount(self.cashier_amount_var.get())
            result = self._redeposit_available_funds(amount)
            self.cash_balance_cents = int(result["balance_cents"])
            self._update_cash_balance()
            self._refresh_study_funding_panel()
            self._refresh_cashier()
            dollar = chr(36)
            self.cashier_status_var.set(
                f"Deposit +{dollar}{amount / 100:.2f} • "
                f"withdrawn funds {dollar}{result['withdrawn_part_cents'] / 100:.2f} • "
                f"Study {dollar}{result['study_part_cents'] / 100:.2f}"
            )
            self.cashier_amount_var.set("")
        except Exception as exc:
            messagebox.showerror("Cashier deposit", str(exc), parent=self)
    def _open_study_wallet(self):
        wallet_script = ROOT / "pigeon_poker" / "StudyWallet.py"
        if not wallet_script.is_file():
            messagebox.showerror(
                "Study Wallet", "pigeon_poker/StudyWallet.py was not found.", parent=self
            )
            return
        try:
            subprocess.Popen([sys.executable, str(wallet_script)], cwd=str(ROOT), close_fds=True)
        except Exception as exc:
            messagebox.showerror("Study Wallet", str(exc), parent=self)


    def _apply_one_time_10_dollar_bonus(self) -> bool:
        """Atomically credit $10.00 to this local wallet once, with an audit row."""
        import sqlite3
        amount_cents = 1000
        marker_key = "pigeon_poker_v1_3_106_bonus_10_usd"
        transaction_id = "pigeon-poker-v1.3.106-bonus-10-usd"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with sqlite3.connect(str(self.wallet_store.db_path), timeout=20) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=20000")
            con.execute("BEGIN IMMEDIATE")
            already = con.execute(
                "SELECT value FROM wallet_meta WHERE key=?", (marker_key,)
            ).fetchone()
            if already is not None:
                con.execute("ROLLBACK")
                return False
            row = con.execute(
                "SELECT balance_cents FROM wallet_account WHERE account_id=1"
            ).fetchone()
            if row is None:
                con.execute("ROLLBACK")
                raise RuntimeError("Wallet account was not initialized; $10 bonus not applied.")
            new_balance = int(row["balance_cents"]) + amount_cents
            con.execute(
                "UPDATE wallet_account SET balance_cents=?,updated_at=? WHERE account_id=1",
                (new_balance, now),
            )
            con.execute(
                "INSERT INTO cashier_transactions "
                "(transaction_id,played_at,kind,delta_cents,balance_after_cents,recipient,note) "
                "VALUES(?,?,?,?,?,?,?)",
                (transaction_id, now, "bonus-credit", amount_cents, new_balance, "",
                 "One-time +$10.00 Pigeon Poker balance bonus (v1.3.106)"),
            )
            con.execute(
                "INSERT INTO wallet_meta(key,value) VALUES(?,?)",
                (marker_key, now),
            )
            con.execute("COMMIT")
        self.cash_balance_cents = new_balance
        self.config_data["balance"] = new_balance / 100
        return True

    def _ensure_withdrawable_wallet_schema(self):
        import sqlite3
        with sqlite3.connect(str(self.wallet_store.db_path), timeout=20) as con:
            con.execute("PRAGMA busy_timeout=20000")
            con.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in con.execute("PRAGMA table_info(wallet_account)")}
            if "withdrawable_cents" not in columns:
                con.execute("ALTER TABLE wallet_account ADD COLUMN withdrawable_cents INTEGER NOT NULL DEFAULT 0")
            marker = con.execute("SELECT 1 FROM wallet_meta WHERE key='withdrawable_migration_v1'").fetchone()
            if marker is None:
                old = con.execute(
                    "SELECT COALESCE(SUM(-delta_cents),0) FROM cashier_transactions "
                    "WHERE kind='withdrawal' AND delta_cents<0 AND note='Simulated wallet debit'"
                ).fetchone()
                restore = max(0, int(old[0] or 0))
                if restore:
                    con.execute(
                        "UPDATE wallet_account SET withdrawable_cents=withdrawable_cents+?,updated_at=? WHERE account_id=1",
                        (restore, datetime.now(timezone.utc).isoformat(timespec="seconds")),
                    )
                con.execute(
                    "INSERT INTO wallet_meta(key,value) VALUES('withdrawable_migration_v1',?)",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"),),
                )
            con.execute("COMMIT")

    def _withdrawable_balance_cents(self):
        import sqlite3
        with sqlite3.connect(str(self.wallet_store.db_path), timeout=20) as con:
            row = con.execute("SELECT withdrawable_cents FROM wallet_account WHERE account_id=1").fetchone()
        return max(0, int(row[0])) if row else 0

    def _move_wallet_to_withdrawable(self, amount_cents):
        import sqlite3
        amount = int(amount_cents)
        if amount <= 0:
            raise ValueError("出金可能額へ移す金額を入力してください。")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with sqlite3.connect(str(self.wallet_store.db_path), timeout=20) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=20000")
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT balance_cents,withdrawable_cents FROM wallet_account WHERE account_id=1"
            ).fetchone()
            if row is None:
                con.execute("ROLLBACK")
                raise ValueError("ウォレット口座が見つかりません。")
            balance = int(row["balance_cents"])
            available = int(row["withdrawable_cents"])
            if amount > balance:
                con.execute("ROLLBACK")
                raise ValueError("ウォレット残高が不足しています。")
            new_balance, new_available = balance - amount, available + amount
            con.execute(
                "UPDATE wallet_account SET balance_cents=?,withdrawable_cents=?,updated_at=? WHERE account_id=1",
                (new_balance, new_available, now),
            )
            con.execute(
                "INSERT INTO cashier_transactions "
                "(transaction_id,played_at,kind,delta_cents,balance_after_cents,recipient,note) "
                "VALUES(?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, now, "withdrawable-transfer", -amount, new_balance,
                 "withdrawable", "Moved from Wallet to Withdrawable Balance"),
            )
            con.execute("COMMIT")
        return {"balance_cents": new_balance, "withdrawable_cents": new_available}

    def _cashier_withdraw(self):
        try:
            self._sync_external_wallet_balance()
            amount = self._parse_cashier_amount(self.cashier_withdraw_var.get())
            result = self._move_wallet_to_withdrawable(amount)
            self.cash_balance_cents = result["balance_cents"]
            self._update_cash_balance()
            self._refresh_cashier()
            self.cashier_status_var.set(
                f"Withdrawable Balance +${amount/100:.2f} • "
                f"available ${result['withdrawable_cents']/100:,.2f}"
            )
            self.cashier_withdraw_var.set("")
        except Exception as exc:
            messagebox.showerror("Cashier", str(exc), parent=self)
    def _cashier_transfer(self):
        try:
            self._sync_external_wallet_balance()
            recipient = self.cashier_recipient_var.get().strip()
            if not recipient:
                raise ValueError("仮想送金先IDを入力してください。")
            amount = self._parse_cashier_amount(self.cashier_transfer_var.get())
            if amount > self.cash_balance_cents:
                raise ValueError("ウォレット残高が不足しています。")
            self.cash_balance_cents -= amount
            self._update_cash_balance()
            self._record_cash_transaction("transfer", -amount, recipient=recipient,
                                          note="Offline virtual transfer only")
            self.cashier_status_var.set(f"Simulated transfer recorded to {recipient}: -${amount/100:.2f}")
        except Exception as exc:
            messagebox.showerror("Cashier", str(exc))

    def _refresh_cashier(self):
        if not hasattr(self, "cashier_tree"):
            return
        self._sync_external_wallet_balance()
        self._refresh_study_funding_panel()
        summary = self.cashier_ledger.summary()
        withdrawable = self._withdrawable_balance_cents()
        self.cashier_summary_var.set(
            f"Wallet $" + f"{self.cash_balance_cents/100:,.2f} • Withdrawable $" + f"{withdrawable/100:,.2f} • "
            f"{summary['count']} transactions • Credits $" + f"{summary['credits']/100:,.2f} • "
            f"Debits $" + f"{summary['debits']/100:,.2f}"
        )
        for item in self.cashier_tree.get_children():
            self.cashier_tree.delete(item)
        for index, row in enumerate(self.cashier_ledger.recent(500)):
            date_text = row["played_at"].replace("T", " ").replace("+00:00", " UTC")
            self.cashier_tree.insert("", "end", iid=str(index), values=(
                date_text, row["kind"], f"{row['delta_cents']/100:+.2f}",
                f"${row['balance_after_cents']/100:,.2f}", row["recipient"], row["note"]))

    def _build_table(self):
        """Build only an open-table manager; actual play lives in one Toplevel per table."""
        page = self._new_page("table")
        self.table_title_var = tk.StringVar(value="OPEN TABLES")
        self._page_header(
            page,
            "Open Tables",
            "Each table is a separate window. Rush & Cash and VIP NLH run as independent game formats.",
        )
        top = tk.Frame(page, bg=COLORS["bg"])
        top.pack(fill="x", padx=22, pady=(0, 12))
        tk.Label(top, textvariable=self.table_title_var, bg=COLORS["bg"],
                 fg=COLORS["green"], font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(top, text="BACK TO LOBBY", command=lambda: self.show_page("lobby")).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="OPEN VIP TABLE", style="Accent.TButton",
                   command=self._open_vip_buyin_dialog).pack(side="right", padx=6)
        ttk.Button(top, text="OPEN RUSH & CASH TABLE", style="Accent.TButton",
                   command=self._open_rush_stake_dialog).pack(side="right", padx=6)
        self.table_tabs_frame = tk.Frame(page, bg=COLORS["bg"])
        self.table_tabs_frame.pack(fill="x", padx=22, pady=(0, 12))
        self.table_dashboard_frame = tk.Frame(page, bg=COLORS["bg"])
        self.table_dashboard_frame.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        self._refresh_table_dashboard()

    def _open_rush_stake_dialog(self):
        """Offer an explicit OPEN TABLE flow from the Open Tables manager."""
        choices = [
            ("NL2", "$0.01 / $0.02"), ("NL5", "$0.02 / $0.05"),
            ("NL10", "$0.05 / $0.10"), ("NL25", "$0.10 / $0.25"),
            ("NL50", "$0.25 / $0.50"), ("NL100", "$0.50 / $1.00"),
            ("NL200", "$1.00 / $2.00"),
        ]
        dialog = tk.Toplevel(self)
        dialog.title("OPEN RUSH & CASH TABLE")
        dialog.configure(bg=COLORS["panel"])
        dialog.resizable(False, False)
        dialog.transient(self)
        tk.Label(dialog, text="OPEN RUSH & CASH TABLE", bg=COLORS["panel"],
                 fg=COLORS["text"], font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=18, pady=(16, 4))
        tk.Label(dialog, text="Select a 6-max fast-fold stake. Each table opens in its own window.",
                 bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 12))
        grid = tk.Frame(dialog, bg=COLORS["panel"])
        grid.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        for index, (rate, blinds) in enumerate(choices):
            button = ttk.Button(
                grid, text=f"{rate}   •   {blinds}   •   OPEN TABLE",
                style="Accent.TButton",
                command=lambda r=rate, win=dialog: (win.destroy(), self._join_table(r)),
            )
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=4, pady=4)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        ttk.Button(dialog, text="CANCEL", command=dialog.destroy).pack(anchor="e", padx=18, pady=(0, 14))
        dialog.update_idletasks()
        dialog.geometry(f"{max(520, dialog.winfo_reqwidth())}x{dialog.winfo_reqheight()}")
        dialog.grab_set()
        dialog.focus_force()
        return dialog

    def _refresh_table_dashboard(self):
        """List windows that are already open; never render a second playable table here."""
        frame = getattr(self, "table_dashboard_frame", None)
        if frame is None or not frame.winfo_exists():
            return
        for child in frame.winfo_children():
            child.destroy()
        slots = self.multi_tables.list() if hasattr(self, "multi_tables") else []
        if not slots:
            empty = tk.Frame(frame, bg=COLORS["panel"],
                             highlightbackground=COLORS["border"], highlightthickness=1)
            empty.pack(fill="x", pady=8)
            tk.Label(empty, text="NO OPEN TABLES", bg=COLORS["panel"], fg=COLORS["text"],
                     font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=18, pady=(18, 5))
            tk.Label(empty, text="Join a stake from the lobby. Its table will open in a separate window.",
                     bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 10)).pack(
                         anchor="w", padx=18, pady=(0, 18))
            return
        for index, slot in enumerate(slots):
            state = slot.state
            table = state.get("cash_table")
            hand = table.hand if table is not None else None
            hero_stack = 0
            pot = 0
            hand_no = table.hand_number if table is not None else 0
            actor = "Ready"
            if hand is not None:
                hero = next((player for player in hand.players if player.player_id == "hero"), None)
                hero_stack = hero.stack if hero else 0
                pot = hand.pot
                actor = "Hand complete" if hand.finished else (
                    "Your action" if hand.next_to_act == "hero" else
                    (hand.player(hand.next_to_act).name + " to act" if hand.next_to_act else "In hand")
                )
            card = tk.Frame(frame, bg=COLORS["panel"],
                            highlightbackground=COLORS["border"], highlightthickness=1)
            card.pack(fill="x", pady=6)
            left = tk.Frame(card, bg=COLORS["panel"])
            left.pack(side="left", fill="both", expand=True, padx=16, pady=13)
            right = tk.Frame(card, bg=COLORS["panel"])
            right.pack(side="right", padx=16, pady=13)
            tk.Label(left, text=f"{table_mode_label(state.get('cash_game_mode'))}  •  {slot.rate}", bg=COLORS["panel"],
                     fg=COLORS["green"], font=("Segoe UI", 12, "bold")).pack(anchor="w")
            tk.Label(left,
                     text=f"Hand #{hand_no}   •   {actor}   •   Pot ${pot/100:.2f}   •   Your stack ${hero_stack/100:.2f}",
                     bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 0))
            ttk.Button(right, text="BRING TABLE TO FRONT", style="Accent.TButton",
                       command=lambda tid=slot.table_id: self._open_floating_table(tid)).pack(side="left", padx=4)
            ttk.Button(right, text="退出", style="Danger.TButton",
                       command=lambda tid=slot.table_id: self._leave_floating_table(tid)).pack(side="left", padx=4)

    def _toggle_sitout_before_bb_for_table(self, table_id: str, variable: tk.BooleanVar):
        """Queue/cancel a per-table sit-out immediately before HERO's next BB."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        requested = bool(variable.get())
        slot.state["cash_sitout_before_bb"] = requested
        if requested:
            # This is a future pause reservation, not a Resume command. If the
            # table is already temporarily paused, leave that state untouched.
            slot.state["cash_action_feed"] = "SIT OUT QUEUED • BEFORE YOUR NEXT BIG BLIND"
        else:
            slot.state["cash_action_feed"] = "SIT OUT BEFORE BB CANCELLED"
        if table_id == self.active_cash_table_id:
            self.cash_sitout_before_bb_var.set(requested)
            self.cash_log_lines.append(
                "SIT OUT: queued before next BB" if requested else "SIT OUT: next-BB request cancelled"
            )
            self._save_active_cash_slot()
        self._refresh_table_windows()

    def _request_table_sitout(self, table_id: str):
        """Pause after the current hand; never cash out or destroy the table."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        state = slot.state
        normalize_table_pause_state(state)
        if state.get("cash_sitting_out") or state.get("cash_sitout_pending"):
            return
        table = state.get("cash_table")
        hand = table.hand if table else None
        if hand is not None and not hand.finished:
            state["cash_sitout_pending"] = True
            state["cash_action_feed"] = "一時離席予約中 • このハンド終了後に休止"
            # Do not auto-fold. Keep playing this hand normally and pause only
            # after the hand reaches its natural end.
            self._refresh_table_windows()
            return
        state["cash_sitting_out"] = True
        state["cash_sitout_pending"] = False
        state["cash_action_feed"] = "SITTING OUT • TABLE AND STACK PRESERVED"
        if table_id in self.squeeze_deadline_jobs:
            self._cancel_squeeze_action_deadline(table_id)
        if table_id == self.active_cash_table_id:
            self.cash_status_var.set("SITTING OUT • press RESUME to return")
            self.cash_log_lines.append("SIT OUT: table preserved; stack remains seated")
            self._save_active_cash_slot()
        self._refresh_table_windows()

    def _cancel_table_sitout(self, table_id: str):
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        slot.state["cash_sitout_pending"] = False
        slot.state["cash_action_feed"] = "SIT OUT CANCELLED"
        self._save_active_cash_slot() if table_id == self.active_cash_table_id else None
        self._refresh_table_windows()

    def _resume_cash_table(self, table_id: str):
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        if table_id != self.active_cash_table_id:
            if self.cash_busy:
                slot.state["cash_resume_requested"] = True
                if table_id not in self.table_resume_retry_jobs:
                    self.table_resume_retry_jobs[table_id] = self.after(
                        150, lambda tid=table_id: self._retry_queued_table_resume(tid))
                self._refresh_table_windows()
                return
            self._save_active_cash_slot()
            self._restore_cash_slot(table_id)
            slot = self.multi_tables.get(table_id)
        state = slot.state
        state["cash_sitting_out"] = False
        state["cash_sitout_pending"] = False
        # Keep any future Sit Out Before Next BB reservation when resuming a
        # manually paused table. A BB-triggered pause already cleared its flag.
        state["cash_resume_requested"] = False
        record = self.table_windows.get(table_id)
        if record:
            try:
                record["sitout_before_bb_var"].set(bool(state.get("cash_sitout_before_bb", False)))
            except (KeyError, tk.TclError):
                pass
        self.cash_sitout_before_bb_var.set(bool(state.get("cash_sitout_before_bb", False)))
        self.cash_status_var.set("RESUMING TABLE…")
        self.cash_log_lines.append("RESUME: returning to preserved table and stack")
        if table_id == self.active_cash_table_id:
            self._save_active_cash_slot()
        self._refresh_table_windows()
        table = state.get("cash_table")
        if table is not None and (table.hand is None or table.hand.finished):
            self._start_cash_hand(first=table.hand is None)

    def _retry_queued_table_resume(self, table_id: str):
        self.table_resume_retry_jobs.pop(table_id, None)
        slot = self.multi_tables.get(table_id)
        if slot is None or not bool(slot.state.get("cash_resume_requested", False)):
            return
        if self.cash_busy:
            self.table_resume_retry_jobs[table_id] = self.after(
                150, lambda tid=table_id: self._retry_queued_table_resume(tid))
            return
        slot.state["cash_resume_requested"] = False
        self._resume_cash_table(table_id)

    def _hero_is_next_big_blind(self) -> bool:
        """Return whether hero is due to post the BB in the next Rush & Cash hand.

        Rush & Cash replaces the five CPU opponents for every new hand, so all
        five non-hero seats are treated as funded for the next hand. The dealer
        advances one seat before the next hand; in a six-max hand the BB is two
        seats left of that next button.
        """
        if self.cash_table is None or len(self.cash_table.seats) != 6:
            return False
        hero_index = next((i for i, seat in enumerate(self.cash_table.seats)
                           if seat["id"] == "hero"), None)
        if hero_index is None:
            return False
        next_big_blind = next_big_blind_index_after_rotation(
            self.cash_table.dealer_index, len(self.cash_table.seats))
        return hero_index == next_big_blind

    def _start_cash_hand(self, first: bool = False):
        if self.cash_gto_spot_mode and not first:
            self._start_gto_plus_spot(restart=True)
            return
        if self.cash_table is None:
            return
        active_slot = self.multi_tables.get(self.active_cash_table_id) if self.active_cash_table_id else None
        active_state = active_slot.state if active_slot else {}
        normalize_table_pause_state(active_state)
        if active_state.get("cash_sitting_out"):
            self.cash_status_var.set("SITTING OUT • table and stack preserved")
            self._refresh_table_windows()
            return
        try:
            if not self.cash_gto_spot_mode:
                self.ggcare_candidate = None
            hero_seat = next((seat for seat in self.cash_table.seats if seat["id"] == "hero"), None)
            if not self.cash_gto_spot_mode and hero_seat is not None and int(hero_seat["stack"]) <= 0:
                self.cash_status_var.set("Stack is empty — rebuy or leave before the next hand")
                self._render_cash_actions()
                return
            if first or self.cash_table.hand is None:
                self.cash_table.start_hand()
            else:
                if (not self.cash_gto_spot_mode
                        and bool(active_state.get("cash_sitout_before_bb", False))
                        and self._hero_is_next_big_blind()):
                    active_state["cash_sitting_out"] = True
                    active_state["cash_sitout_before_bb"] = False
                    active_state["cash_action_feed"] = "SIT OUT • NEXT BIG BLIND SKIPPED • TABLE PRESERVED"
                    record = self.table_windows.get(self.active_cash_table_id)
                    if record:
                        try:
                            record["sitout_before_bb_var"].set(False)
                        except (KeyError, tk.TclError):
                            pass
                    self.cash_sitout_before_bb_var.set(False)
                    self.cash_status_var.set("SITTING OUT BEFORE BIG BLIND • press RESUME")
                    self.cash_log_lines.append("SIT OUT: preserved table before posting next BB")
                    self._save_active_cash_slot()
                    self._refresh_table_windows()
                    return
                if is_vip_mode(self.cash_game_mode):
                    cpu_rebuys = {
                        str(seat["id"]): self.cash_buyin
                        for seat in self.cash_table.seats
                        if seat["id"] != "hero" and int(seat.get("stack", 0)) <= 0
                    }
                    self.cash_table.next_hand(rebuy_stacks=cpu_rebuys)
                else:
                    self._rotate_cash_opponents()
                    self.cash_table.start_hand()
            # Every live table hand may pause for an explicit Run It Multiple Times
            # decision after an all-in. GTO+ training spots keep their own flow.
            if not self.cash_gto_spot_mode and self.cash_table.hand is not None:
                self.cash_table.hand.defer_runout_choice = True
                if active_state:
                    active_state.setdefault("cash_run_it_preference", "ask")
            if self.active_cash_table_id:
                self._maybe_apply_cash_drop(self.active_cash_table_id)
            self.hero_squeeze_count = 0
            self.board_squeeze_count = 5
            self.cash_hand_instance += 1
            if self.active_cash_table_id and self.multi_tables.get(self.active_cash_table_id):
                reset_timebank_hand_state(self.multi_tables.get(self.active_cash_table_id).state)
            self.preflop_fold_pending = False
            self.postflop_auto_fold = False
            self.postflop_auto_fold_hand_token = None
            if self.active_cash_table_id and self.multi_tables.get(self.active_cash_table_id):
                active_state = self.multi_tables.get(self.active_cash_table_id).state
                active_state["preflop_fold_pending"] = False
                active_state["postflop_auto_fold"] = False
                active_state["postflop_auto_fold_hand_token"] = None
                record = self.table_windows.get(self.active_cash_table_id)
                if record:
                    try:
                        record["postflop_auto_fold_var"].set(False)
                    except (KeyError, tk.TclError):
                        pass
            self.cash_current_hand_key = f"{self.cash_session_id}-{self.cash_hand_instance}"
            self.cash_gto_session = None
            self.cash_visible_board = []
            self.cash_board_target = []
            self.cash_board_reveal_count = 0
            self.cash_board_anim_index = None
            self.cash_board_anim_progress = 1.0
            if self.active_cash_table_id and self.multi_tables.get(self.active_cash_table_id):
                self.multi_tables.get(self.active_cash_table_id).state["cash_board_anim_indices"] = []
                self.multi_tables.get(self.active_cash_table_id).state["cash_action_flash"] = None
            self.cash_deal_counts = {p.player_id: 0 for p in self.cash_table.hand.players}
            self.cash_initial_flip = {"active": False, "complete": False, "index": 0, "progress": 0.0}
            self.cash_board_squeeze = {}
            self.cash_squeeze_deadline_at = 0.0
            self.cash_deal_flying = None
            self.cash_deal_busy = True
            self.cash_action_feed = "Dealer is dealing the cards…"
            self.cash_thinking_player = None
            self.cash_busy = True
            self.cash_status_var.set(f"Hand #{self.cash_table.hand_number} • DEALING")
            self.cash_log_lines.append(f"\n--- HAND #{self.cash_table.hand_number} ---")
            self._save_active_cash_slot()
            self._draw_table()
            self._render_cash_actions()
            self._begin_deal_animation(self.active_cash_table_id)
        except Exception as exc:
            messagebox.showerror("Cash game", str(exc))
            self.cash_status_var.set(str(exc))

    def _maybe_apply_cash_drop(self, table_id: str):
        """Apply low-frequency 10/20/600BB Rush & Cash Drops from the pooled fund."""
        slot = self.multi_tables.get(table_id)
        table = slot.state.get("cash_table") if slot else None
        hand = table.hand if table else None
        if hand is None or hand.finished or not is_rush_mode(slot.state.get("cash_game_mode", RUSH_MODE)):
            return
        bb = int(hand.big_blind)
        # Approximate published Hold'em drop frequencies per 100,000 hands.
        # The pool must have enough real simulated credits before a drop is issued.
        candidates = ((600, 0.000003), (20, 0.00015), (10, 0.00360))
        chosen = None
        roll = self.cash_random.random()
        cumulative = 0.0
        for amount_bb, probability in candidates:
            cumulative += probability
            if roll < cumulative and self.cash_drop_pool_cents >= amount_bb * bb:
                chosen = amount_bb
                break
        if chosen is None:
            return
        total = int(chosen * bb)
        self.cash_drop_pool_cents -= total
        self.config_data["cash_drop_pool_cents"] = self.cash_drop_pool_cents
        save_config(self.config_data)
        players = [player for player in hand.players if player.hole_cards]
        if chosen == 600:
            # Large drop: split the total fund evenly across all dealt-in players.
            # The Cash Drop restriction applies even when the reward goes to stacks.
            hand.cash_drop_active = True
            shares = payout_shares(total, [player.player_id for player in players])
            for player in players:
                player.stack += int(shares.get(player.player_id, 0))
            table.sync_external_hand_state()
            detail = {"kind": "stack", "amount": total, "shares": shares}
            self.cash_log_lines.append(f"CASH DROP • {chosen}BB split across the table")
        else:
            hand.add_cash_drop_to_pot(total)
            detail = {"kind": "pot", "amount": total, "shares": {}}
            self.cash_log_lines.append(f"CASH DROP • +{chosen}BB added to the pot")
        slot.state["cash_drop_notice"] = {
            **detail, "started": time.monotonic(), "duration": 1.65,
            "token": uuid.uuid4().hex,
        }
        self._play_sound("cash_drop")
        self._tick_cash_drop_animation(table_id, slot.state["cash_drop_notice"]["token"])

    def _tick_cash_drop_animation(self, table_id: str, token: str):
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        notice = slot.state.get("cash_drop_notice") or {}
        if notice.get("token") != token:
            return
        elapsed = time.monotonic() - float(notice.get("started", 0.0))
        if elapsed >= float(notice.get("duration", 1.65)):
            slot.state["cash_drop_notice"] = None
            self._redraw_floating_table(table_id)
            return
        self._redraw_floating_table(table_id)
        self.after(55, lambda tid=table_id, key=token: self._tick_cash_drop_animation(tid, key))

    def _open_social_reactions(self, table_id: str):
        """Open a small, table-owned picker for sending a cosmetic reaction."""
        slot = self.multi_tables.get(table_id)
        record = self.table_windows.get(table_id)
        if slot is None or record is None:
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table is not None else None
        if hand is None or hand.finished or slot.state.get("cash_sitting_out", False):
            return
        targets = [player for player in hand.players if player.player_id != "hero"]
        if not targets:
            return
        window = tk.Toplevel(record["window"])
        window.title("TABLE REACTIONS")
        window.geometry("390x300")
        window.resizable(False, False)
        window.configure(bg=COLORS["panel"])
        try:
            window.transient(record["window"])
            window.attributes("-topmost", True)
            window.lift()
            window.focus_force()
        except tk.TclError:
            pass
        tk.Label(window, text="SEND A TABLE REACTION", bg=COLORS["panel"],
                 fg=COLORS["gold"], font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(window, text="Choose an opponent and a cosmetic effect. Reactions do not affect chips or hand results.",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=350,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", padx=16, pady=(0, 10))
        target_by_label = {f"{player.name}  •  {player.player_id}": player.player_id for player in targets}
        target_var = tk.StringVar(value=next(iter(target_by_label)))
        target_line = tk.Frame(window, bg=COLORS["panel"])
        target_line.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(target_line, text="TARGET", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        ttk.Combobox(target_line, textvariable=target_var, values=list(target_by_label),
                     state="readonly", width=31).pack(side="right")
        effects = tk.Frame(window, bg=COLORS["panel"])
        effects.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        buttons = (
            ("🥚  EGG SPLASH", "egg", "splash_egg"),
            ("💦  WATER BUCKET", "water", "splash_water"),
            ("☁  SMOKE", "smoke", "splash_smoke"),
            ("🥊  BOXING GLOVES", "gloves", "splash_gloves"),
        )
        for index, (label, effect, _sound) in enumerate(buttons):
            button = self._compact_action_button(
                effects, label,
                lambda tid=table_id, ef=effect, tv=target_var, mapping=target_by_label, win=window:
                    (self._send_social_reaction(tid, ef, mapping.get(tv.get(), "")), win.destroy()),
                "normal")
            button.pack(fill="x", padx=3, pady=3)
        tk.Label(window, text="LIMIT 4 PER HAND  •  SHORT COOLDOWN", bg=COLORS["panel"],
                 fg=COLORS["muted"], font=("Segoe UI", 7)).pack(anchor="e", padx=16, pady=(0, 10))

    def _send_social_reaction(self, table_id: str, effect: str, target_id: str) -> bool:
        """Validate and start one non-gameplay social reaction on a table."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return False
        state = slot.state
        table = state.get("cash_table")
        hand = table.hand if table is not None else None
        try:
            effect = normalize_reaction(effect)
        except ValueError:
            return False
        token = id(hand) if hand is not None else None
        if state.get("cash_social_reaction_hand_token") != token:
            state["cash_social_reaction_hand_token"] = token
            state["cash_social_reaction_count"] = 0
            state["cash_social_reaction_last_sent"] = 0.0
        now = time.monotonic()
        decision = reaction_decision(
            hand_active=bool(hand is not None and not hand.finished),
            target_id=target_id,
            player_ids=[player.player_id for player in hand.players] if hand else [],
            now=now,
            last_sent_at=float(state.get("cash_social_reaction_last_sent", 0.0)),
            sent_this_hand=int(state.get("cash_social_reaction_count", 0)),
        )
        if not decision.allowed:
            record = self.table_windows.get(table_id)
            if record:
                record["status"].set(decision.reason.upper())
            return False
        target = hand.player(target_id)
        state["cash_social_reaction_last_sent"] = now
        state["cash_social_reaction_count"] = int(state.get("cash_social_reaction_count", 0)) + 1
        state["cash_social_reaction"] = {
            "effect": effect, "target_id": target_id, "target_name": target.name,
            "started": now, "duration": REACTION_DURATION_SECONDS,
            "seed": int(getattr(table, "hand_number", 1) * 17 + len(hand.events) * 7 + state["cash_social_reaction_count"]),
        }
        self._play_sound({
            "egg": "splash_egg", "water": "splash_water",
            "smoke": "splash_smoke", "gloves": "splash_gloves",
        }[effect])
        self._animate_social_reaction_frame(table_id)
        return True

    def _animate_social_reaction_frame(self, table_id: str):
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        reaction = slot.state.get("cash_social_reaction")
        if not reaction:
            return
        elapsed = time.monotonic() - float(reaction.get("started", 0.0))
        if elapsed >= float(reaction.get("duration", REACTION_DURATION_SECONDS)):
            slot.state["cash_social_reaction"] = None
            self._redraw_floating_table(table_id)
            return
        self._redraw_floating_table(table_id)
        try:
            self.after(40, lambda tid=table_id: self._animate_social_reaction_frame(tid))
        except tk.TclError:
            pass

    def _draw_social_reaction_overlay(self, canvas, hand, width: int, height: int,
                                      hero_index: int, table):
        slot = self.multi_tables.get(getattr(table, "table_id", "")) if table is not None else None
        # Some table implementations do not carry their registry id; resolve the
        # active draw's table record by object identity instead.
        if slot is None:
            slot = next((item for item in self.multi_tables.list()
                         if item.state.get("cash_table") is table), None)
        if slot is None:
            return
        reaction = slot.state.get("cash_social_reaction")
        if not reaction:
            return
        now = time.monotonic()
        progress, opacity = reaction_progress(
            now, float(reaction.get("started", now)),
            float(reaction.get("duration", REACTION_DURATION_SECONDS)))
        if opacity <= 0:
            return
        target_id = str(reaction.get("target_id", ""))
        target_index = next((idx for idx, player in enumerate(hand.players)
                             if player.player_id == target_id), None)
        if target_index is None:
            return
        relative_positions = [
            (width*.50, height*.84), (width*.205, height*.69), (width*.205, height*.29),
            (width*.50, height*.125), (width*.795, height*.29), (width*.795, height*.69),
        ]
        if len(hand.players) == 2:
            relative_positions = [(width*.50, height*.83), (width*.50, height*.15)]
        px, py = relative_positions[(target_index - hero_index) % len(hand.players)]
        cx, cy = px, py - 63
        effect = str(reaction.get("effect", "egg"))
        seed = int(reaction.get("seed", 0))
        # Canvas has no per-item alpha; use stipple and carefully limited colors.
        if effect == "egg":
            flight = min(1.0, progress / .48)
            sx, sy = cx - 100 + 100 * (flight * flight * (3 - 2 * flight)), cy - 76 + 76 * flight
            if progress < .54:
                canvas.create_oval(sx-10, sy-15, sx+10, sy+15, fill="#f0e4c5",
                                   outline="#a98b5d", width=2, tags=("social_reaction",))
                canvas.create_line(sx-3, sy-5, sx+3, sy+5, fill="#b49b73", width=1,
                                   tags=("social_reaction",))
            burst = max(0.0, (progress - .40) / .60)
            radius = 9 + burst * 42
            for idx in range(8):
                angle = idx * math.tau / 8
                dx, dy = math.cos(angle) * radius, math.sin(angle) * radius * .55
                r = 5 + (idx % 3) * 2
                canvas.create_oval(cx+dx-r, cy+dy-r, cx+dx+r, cy+dy+r,
                                   fill=("#e8d2a0", "#d3b66d", "#b4c98d")[idx % 3],
                                   outline="", stipple="gray50", tags=("social_reaction",))
            canvas.create_text(cx, cy-52, text="SPLAT!", fill="#fff0c0",
                               font=("Segoe UI", 12, "bold"), tags=("social_reaction",))
        elif effect == "water":
            spread = 22 + progress * 78
            for idx in range(11):
                angle = (idx / 11) * math.tau
                dx = math.cos(angle) * spread
                dy = math.sin(angle) * spread * .60
                r = 3 + (idx % 4)
                y = cy - 8 + dy
                canvas.create_oval(cx+dx-r, y-r*1.7, cx+dx+r, y+r*1.7,
                                   fill=("#83d9ee", "#b6f0fa", "#399bc5")[idx % 3],
                                   outline="#d6f7ff", width=1, tags=("social_reaction",))
            canvas.create_arc(cx-62, cy-34, cx+62, cy+34, start=10, extent=160,
                              style="arc", outline="#8be2f2", width=5, tags=("social_reaction",))
            canvas.create_text(cx, cy-67, text="SPLASH!", fill="#bdf4ff",
                               font=("Segoe UI", 11, "bold"), tags=("social_reaction",))
        elif effect == "smoke":
            expand = 18 + progress * 58
            for idx in range(9):
                angle = idx * math.tau / 9
                dx, dy = math.cos(angle) * expand, math.sin(angle) * expand * .45
                r = 12 + (idx % 3) * 4
                canvas.create_oval(cx+dx-r, cy+dy-r, cx+dx+r, cy+dy+r,
                                   fill=("#8e9aa8", "#a9b2bc", "#657280")[idx % 3],
                                   outline="#c3cbd2", stipple="gray50", tags=("social_reaction",))
            canvas.create_text(cx, cy-62, text="POOF!", fill="#e0e6ed",
                               font=("Segoe UI", 11, "bold"), tags=("social_reaction",))
        elif effect == "gloves":
            swing = math.sin(progress * math.pi) * 23
            for side in (-1, 1):
                gx = cx + side * (28 + swing)
                gy = cy + (1-progress) * 24
                canvas.create_rectangle(gx-11, gy+10, gx+11, gy+28,
                                        fill="#f0c7a4", outline="#7a2933", width=2,
                                        tags=("social_reaction",))
                canvas.create_oval(gx-19, gy-11, gx+19, gy+19,
                                   fill="#c64552", outline="#711f2a", width=2,
                                   tags=("social_reaction",))
                canvas.create_arc(gx-12, gy-4, gx+12, gy+9, start=10, extent=160,
                                  style="arc", outline="#f6a7aa", width=2,
                                  tags=("social_reaction",))
            canvas.create_text(cx, cy-61, text="POW!", fill="#ffe1aa",
                               font=("Segoe UI", 15, "bold"), tags=("social_reaction",))
        if progress < .9:
            canvas.create_text(cx, cy+57, text=str(reaction.get("target_name", "")),
                               fill="#f8e8c4", font=("Segoe UI", 8, "bold"),
                               tags=("social_reaction",))

    def _trigger_big_pot_celebration(self, table_id: str):
        record = self.table_windows.get(table_id)
        if not record:
            return
        available = record.get("big_pot_celebration_available")
        if not available:
            return
        record["big_pot_celebration_available"] = None
        now = time.monotonic()
        record["big_pot_celebration"] = {
            "started": now, "duration": BIG_POT_CELEBRATION_SECONDS,
            "winners": list(available.get("winners", ["hero"])),
            "seed": int(available.get("seed", 1)),
        }
        self._play_sound("big_win")
        self._animate_big_pot_celebration_frame(table_id)
        self._refresh_table_windows()

    def _animate_big_pot_celebration_frame(self, table_id: str):
        record = self.table_windows.get(table_id)
        if not record or not record.get("big_pot_celebration"):
            return
        celebration = record["big_pot_celebration"]
        if time.monotonic() >= float(celebration["started"]) + float(celebration.get("duration", BIG_POT_CELEBRATION_SECONDS)):
            record["big_pot_celebration"] = None
            record["big_pot_celebration_available"] = None
            self._redraw_floating_table(table_id)
            self._refresh_table_windows()
            return
        self._redraw_floating_table(table_id)
        try:
            record["big_pot_celebration_job"] = self.after(
                34, lambda tid=table_id: self._animate_big_pot_celebration_frame(tid))
        except tk.TclError:
            record["big_pot_celebration_job"] = None

    def _draw_big_pot_celebration_overlay(self, canvas, hand, width: int, height: int,
                                          hero_index: int, table):
        slot = next((item for item in self.multi_tables.list()
                     if item.state.get("cash_table") is table), None)
        if slot is None:
            return
        record = self.table_windows.get(slot.table_id)
        celebration = record.get("big_pot_celebration") if record else None
        if not celebration:
            return
        now = time.monotonic()
        progress = max(0.0, min(1.0, (now - float(celebration.get("started", now))) /
                                max(.1, float(celebration.get("duration", BIG_POT_CELEBRATION_SECONDS)))))
        if progress >= 1:
            return
        # Gentle gold spotlight behind the winners, then restrained falling confetti.
        canvas.create_oval(width*.30, height*.20, width*.70, height*.72,
                           fill="#c89e45", outline="#f6d98d", width=2,
                           stipple="gray75", tags=("big_pot_celebration",))
        palette = ("#f3d37e", "#f6f0d7", "#76c9a7", "#7eadd7", "#d98875")
        for idx in range(28):
            x0, y0, vx, vy = celebration_particle(idx, int(celebration.get("seed", 1)))
            x = (x0 + vx * progress * .35) * width
            y = (y0 + vy * progress + .62 * progress * progress) * height
            size = 3 + (idx % 4)
            color = palette[idx % len(palette)]
            if idx % 2:
                canvas.create_rectangle(x-size, y-size*1.4, x+size, y+size*1.4,
                                        fill=color, outline="", tags=("big_pot_celebration",))
            else:
                canvas.create_oval(x-size, y-size, x+size, y+size,
                                   fill=color, outline="", tags=("big_pot_celebration",))
        if progress < .78:
            canvas.create_text(width/2, height*.24, text="HUGE POT!",
                               fill="#fff1bd", font=("Segoe UI", 19, "bold"),
                               tags=("big_pot_celebration",))

    def _show_rabbit_hunt(self, table_id: str):
        slot = self.multi_tables.get(table_id)
        table = slot.state.get("cash_table") if slot else None
        hand = table.hand if table else None
        if hand is None or not hand.finished or hand.winner_reason != "fold":
            return
        if slot.state.get("cash_rabbit_hunt_board"):
            slot.state["cash_rabbit_hunt_board"] = None
            self._redraw_floating_table(table_id)
            return
        board = hand.rabbit_hunt_board()
        if not board:
            return
        slot.state["cash_rabbit_hunt_board"] = list(board)
        self.cash_log_lines.append("RABBIT HUNT • hypothetical board only; hand result is unchanged")
        self._play_sound("rabbit_hunt")
        self._redraw_floating_table(table_id)

    def _rotate_cash_opponents(self):
        """Replace the five fast-fold opponents while preserving the hero stack."""
        if self.cash_table is None or self.cash_table.hand is None or not self.cash_table.hand.finished:
            raise PokerRuleError("Opponents can only rotate after a completed hand")
        self.cash_table.sync_external_hand_state()
        profiles = self.cpu_pool_store.sample_opponents(self.cash_rate, count=5, rng=self.cash_random)
        profile_iter = iter(profiles)
        for seat in self.cash_table.seats:
            if seat["id"] == "hero":
                continue
            profile = next(profile_iter)
            seat["id"] = profile.cpu_id
            seat["name"] = profile.name
            # Rush & Cash opponents enter each new hand with a fresh 100 BB stack.
            seat["stack"] = self.cash_buyin
        self.cash_cpu_profiles = {profile.cpu_id: profile for profile in profiles}
        self.vip_cpu_roles = {}
        self.cash_cpus = {
            profile.cpu_id: CashGameCPU(level=profile.level,
                                        rng=random.Random(self.cash_random.randrange(2**32)),
                                        simulations=48, archetype=profile.archetype)
            for profile in profiles
        }
        # Keep the six seat positions and rotate the button exactly one seat.
        self.cash_table.dealer_index = (self.cash_table.dealer_index + 1) % len(self.cash_table.seats)

    def _render_cash_actions(self):
        """Refresh the standalone table windows; the lobby never hosts action controls."""
        self._refresh_table_windows()

    def _preflop_gto_initial_raise_target(self, table, hand, actor_id: str,
                                      legal: dict[str, Any]) -> int | None:
        """Return an editable default raise-to size for this exact preflop node."""
        minimum = int(legal.get("min_target", 0) or 0)
        maximum = int(legal.get("max_target", 0) or 0)
        if maximum <= 0:
            return None
        if minimum <= 0 or minimum > maximum:
            minimum = maximum
        try:
            suggested = preflop_gto_situation_size(table, hand, actor_id)
            if suggested is not None:
                suggested = int(suggested)
                if minimum <= suggested <= maximum:
                    return suggested
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError, OverflowError):
            pass
        # Unsupported branches are still fully playable; use only an initial
        # legal minimum suggestion. The user can edit it freely before submit.
        return minimum

    def _apply_preflop_gto_size(self, table_id: str):
        """Apply a position/history-only GTO size suggestion and always report the outcome."""
        record = self.table_windows.get(table_id)
        if record is None:
            return

        def report(message: str):
            try:
                record["status"].set(str(message))
            except Exception:
                pass

        slot = self.multi_tables.get(table_id)
        if slot is None:
            report("GTO SIZE UNAVAILABLE • TABLE NOT FOUND")
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table is not None else None
        if hand is None or hand.finished:
            report("GTO SIZE UNAVAILABLE • NO LIVE HAND")
            return
        if str(hand.street).lower() != "preflop":
            report("GTO SIZE IS PRE-FLOP ONLY")
            return
        if bool(slot.state.get("cash_busy", False)):
            report("GTO SIZE UNAVAILABLE • TABLE BUSY")
            return
        if hand.next_to_act != "hero":
            report("GTO SIZE UNAVAILABLE • WAIT FOR YOUR TURN")
            return
        if bool(slot.state.get("cash_gto_spot_mode", False)):
            report("GTO SIZE UNAVAILABLE • GTO+ SPOT")
            return

        try:
            legal = hand.legal_actions("hero")
            legal_names = {
                str(value).lower().replace("_", "-")
                for value in legal.get("actions", ())
            }
            if not ({"bet", "raise"} & legal_names):
                report("GTO SIZE UNAVAILABLE • NO LEGAL BET/RAISE")
                return

            target = preflop_gto_situation_size(table, hand, "hero")
            if target is None:
                report("NO MATCHING GTO SIZE • POSITION / ACTION HISTORY NOT COVERED")
                return

            target = int(target)
            minimum = int(legal.get("min_target", 0) or 0)
            maximum = int(legal.get("max_target", 0) or 0)
            if minimum <= 0 or maximum < minimum:
                report("GTO SIZE UNAVAILABLE • INVALID LEGAL RANGE")
                return
            if not minimum <= target <= maximum:
                bb = max(1, int(getattr(table, "big_blind", 1)))
                wanted = format_chip_amount(
                    target, bb, self.chip_display_unit, include_unit=True
                )
                report(f"GTO SIZE NOT LEGAL • {wanted} OUTSIDE CURRENT STACK")
                return

            record["bet_min"], record["bet_max"] = minimum, maximum
            self._set_table_bet_target(table_id, target)
            bb = max(1, int(getattr(table, "big_blind", 1)))
            shown = format_chip_amount(
                target, bb, self.chip_display_unit, include_unit=True
            )
            report(f"GTO SIZE APPLIED • {shown} • POSITION + ACTION HISTORY")
        except Exception as exc:
            # The old handler swallowed every exception, making a dead button
            # indistinguishable from a policy miss. Surface the actual failure.
            report(f"GTO SIZE ERROR • {type(exc).__name__}: {str(exc)[:72]}")

    def _cash_human_action(self, action: str, amount: int | None = None):
        if self.cash_table is None or self.cash_table.hand is None or self.cash_busy:
            return
        hand = self.cash_table.hand
        if hand.next_to_act != "hero":
            return
        try:
            table_id = self.active_cash_table_id
            if table_id:
                self._cancel_squeeze_action_deadline(table_id)
                popup = self.squeeze_popups.get(table_id)
                if popup is not None:
                    # A folded hand stays hidden.  Any other completed action
                    # implicitly opens the cards before the action is applied.
                    self._complete_squeeze_popup(table_id, reveal_all=(action != "fold"))
            old_board = list(hand.board)
            if table_id:
                slot_for_bank = self.multi_tables.get(table_id)
                if slot_for_bank is not None:
                    clear_timebank_selection(slot_for_bank.state)
            if action != "fold":
                self.hero_squeeze_count = 2
            if self.cash_gto_session is not None and self.cash_gto_session.hand_token == id(hand):
                result = self.cash_gto_session.human_act(hand, "hero", action, amount)
                self.cash_table.sync_external_hand_state()
                if not result.get("gto_plus_synced"):
                    self.cash_log_lines.append("Human action was outside the GTO+ tree; solver sync ended for this hand.")
            else:
                self.cash_table.act("hero", action, amount)
            # Rush & Cash is fast-fold, not a six-player cash table where HERO
            # waits for the remaining CPUs to finish the hand. Once HERO folds,
            # the seat immediately leaves this virtual table. The already
            # committed chips stay in the abandoned pot; no winner/cards are
            # exposed, and the next hand gets a fresh opponent lineup.
            if action == "fold" and not self.cash_gto_spot_mode and is_rush_mode(self.cash_game_mode):
                hand.finished = True
                hand.winner_reason = "fast_fold"
                hand.next_to_act = None
                hand.pending.clear()
                hand.awards = []
                self.cash_table.sync_external_hand_state()
            action_text = self._describe_action("YOU", action, amount, hand.big_blind)
            self.cash_action_feed = (
                "YOU FOLDED • RUSHING TO NEXT HAND" if action == "fold" else action_text
            )
            self.cash_log_lines.append(action_text)
            if table_id:
                self._set_cash_action_flash(table_id, "hero", action, amount, actor_name="YOU")
            self.cash_thinking_player = None
            self._save_active_cash_slot()
            self._play_action_sound(action)
            if action in {"call", "bet", "raise", "all-in"} and self.active_cash_table_id:
                self._animate_action_chips(self.active_cash_table_id, "hero")
            if (not self.cash_gto_spot_mode and self.ggcare_candidate is None
                    and hand.player("hero").all_in):
                self.ggcare_candidate = self.ggcare_ledger.capture_hero_all_in(
                    self.cash_current_hand_key or f"{self.cash_session_id}-{self.cash_hand_instance}",
                    self.cash_rate, hand)
            if len(hand.board) > len(old_board):
                self.cash_busy = True
                self._render_cash_actions()
                squeeze_start = self._board_squeeze_start_index(hand, len(old_board))
                self._animate_board_reveal(
                    self.active_cash_table_id, list(hand.board),
                    squeeze_start_index=squeeze_start,
                    on_done=lambda tid=self.active_cash_table_id: self._finish_human_board_animation(tid)
                )
            else:
                self._update_cash_after_action()
        except Exception as exc:
            messagebox.showerror("Action rejected", str(exc))

    def _make_live_gto_scenario(self, hand, table, player_id: str, rake_pct: float,
                                table_id: str | None = None) -> dict[str, Any]:
        """Capture the exact observable HU postflop state for the GTO+ miss queue."""
        players = []
        active = [player for player in hand.players if player.eligible]
        dealer_index = int(getattr(hand, "dealer_index", 0))
        active_indices = [i for i, player in enumerate(hand.players) if player.eligible]
        if len(active_indices) == 2:
            if dealer_index in active_indices:
                ip_index = dealer_index
                oop_index = next(i for i in active_indices if i != dealer_index)
            else:
                clockwise = sorted(active_indices,
                    key=lambda i: ((i - dealer_index) % len(hand.players)) or len(hand.players))
                oop_index, ip_index = clockwise[0], clockwise[1]
        else:
            ip_index = dealer_index
            oop_index = next((i for i in active_indices if i != ip_index), ip_index)
        actor_index = hand.seat_by_id.get(player_id, 0)
        actor_position = "IP" if actor_index == ip_index else "OOP"
        for index, player in enumerate(hand.players):
            if not player.eligible:
                continue
            position = "IP" if index == ip_index else "OOP"
            item = {
                "seat_index": index,
                "position": position,
                "player_id": player.player_id,
                "stack_bb": round(player.stack / max(1, hand.big_blind), 6),
                "street_contribution_bb": round(player.street_contribution / max(1, hand.big_blind), 6),
                "total_contribution_bb": round(player.total_contribution / max(1, hand.big_blind), 6),
                "all_in": bool(player.all_in),
            }
            # Only disclose the acting CPU's own holding, never the opponent's hidden cards.
            if player.player_id == player_id:
                item["acting_hand"] = "".join(player.hole_cards)
            players.append(item)
        events = list(hand.events)
        flop_index = next((i for i, event in enumerate(events)
                           if event.get("type") == "street" and event.get("street") == "flop"), None)
        preflop_actions = []
        postflop_actions = []
        if flop_index is not None:
            for event in events[:flop_index]:
                if event.get("type") in {"blind", "action"}:
                    preflop_actions.append({k: event.get(k) for k in (
                        "type", "player", "blind", "action", "amount", "target", "paid",
                        "full_raise", "pot_before", "street_contribution_before",
                        "current_bet_before", "to_call_before") if k in event})
            for event in events[flop_index + 1:]:
                if event.get("type") == "action":
                    postflop_actions.append({k: event.get(k) for k in (
                        "player", "action", "target", "paid", "full_raise", "pot_before",
                        "street_contribution_before", "current_bet_before", "to_call_before")
                        if k in event})
                elif event.get("type") == "street":
                    postflop_actions.append({"type": "street", "street": event.get("street"),
                                             "board": event.get("board")})
        legal = hand.legal_actions(player_id)
        bb = max(1, int(hand.big_blind))
        strategic_state = {
            "schema": "pigeon-live-hu-postflop-v1",
            "game": "NLHE",
            "players": 2,
            "street": str(hand.street),
            "board": list(hand.board),
            "pot_bb": round(hand.pot / bb, 6),
            "effective_stack_bb": round(min(p.stack for p in active) / bb, 6) if active else 0,
            "rake_pct": round(float(rake_pct), 6),
            "dealer_position": "IP",
            "to_act": actor_position,
            "acting_hand": "".join(hand.player(player_id).hole_cards),
            "players_state": players,
            "preflop_action_history": preflop_actions,
            "postflop_action_history": postflop_actions,
            "legal_actions": list(legal.get("actions", [])),
            "minimum_target_bb": round(legal.get("min_target", 0) / bb, 6),
            "maximum_target_bb": round(legal.get("max_target", 0) / bb, 6),
        }
        return {
            "strategic_state": strategic_state,
            "occurrence": {
                "table_id": str(table_id or ""),
                "hand_number": int(getattr(table, "hand_number", 0) or 0),
                "acting_player_id": str(player_id),
            },
        }

    def _queue_live_gto_miss(self, hand, table, player_id: str, rake_pct: float,
                             table_id: str | None, reason: str) -> tuple[str, str]:
        scenario = self._make_live_gto_scenario(hand, table, player_id, rake_pct, table_id)
        try:
            from pigeon_poker.preflop_gto_strategy import _data as load_preflop_policy_data
            actual_rake_pct = float(getattr(table, "rake_bps", round(rake_pct * 100))) / 100.0
            actual_rake_cap_bb = (
                max(0.0, float(getattr(table, "rake_cap", 0)) / float(hand.big_blind))
                if int(getattr(hand, "big_blind", 0) or 0) > 0 else None
            )
            solver_setup = build_live_hu_solver_setup(
                hand, load_preflop_policy_data(), rake_pct=actual_rake_pct,
                rake_cap_bb=actual_rake_cap_bb)
        except Exception as setup_exc:
            solver_setup = {
                "supported": False,
                "schema": "pigeon-gto-plus-auto-solve-v1",
                "reason": f"{type(setup_exc).__name__}: {setup_exc}",
            }
        scenario["solver_setup"] = solver_setup
        key, path = self.integration.bridge.create_live_scenario_request(scenario, reason)
        return key, str(path)

    def _refresh_gto_pending_queue(self):
        if not hasattr(self, "gto_pending_tree"):
            return
        try:
            summary = self.store.unmatched_scenario_summary()
            self.gto_pending_summary_var.set(
                f"{summary['queued']:,} unresolved scenarios • {summary['queued_hits']:,} encounters • "
                f"{summary['by_status'].get('resolved', {}).get('scenarios', 0):,} resolved"
            )
            decisions = self.store.cpu_decision_summary()
            self.gto_cpu_decision_summary_var.set(
                f"CPU decisions recorded • GTO+: {decisions.get('gtoplus', 0):,} • "
                f"non-GTO scope: {decisions.get('fallback_unsupported', 0):,}"
            )
            for item in self.gto_pending_tree.get_children():
                self.gto_pending_tree.delete(item)
            for row in self.store.list_unmatched_scenarios(limit=100):
                scenario = row.get("scenario", {})
                state = scenario.get("scenario", {}).get("strategic_state", {})
                board = " ".join(state.get("board", [])) or "—"
                self.gto_pending_tree.insert("", "end", iid=str(row["scenario_key"]), values=(
                    str(state.get("street", "—")).upper(), board,
                    row.get("occurrences", 1), str(row.get("status", "queued")).upper()))
        except Exception as exc:
            self.gto_pending_summary_var.set(f"Queue read error: {exc}")

    def _export_gto_pending_queue(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="Export GTO+ missing-spot queue", defaultextension=".json",
            initialfile="pigeon_gto_plus_missing_spots.json",
            filetypes=[("JSON report", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            saved = self.store.export_unmatched_scenarios_json(path)
            messagebox.showinfo("GTO+ missing spots", f"Queue exported:\n{saved}", parent=self)
        except Exception as exc:
            messagebox.showerror("GTO+ missing spots", str(exc), parent=self)

    def _resume_waiting_gto_tables(self):
        """Retry paused CPU turns after a new GTO+ tree/node has been loaded."""
        waiting = [slot.table_id for slot in self.multi_tables.list()
                   if bool(slot.state.get("cash_gto_waiting", False))]
        for table_id in waiting:
            try:
                self._start_cash_cpu_chain_for_table(table_id)
            except Exception as exc:
                if table_id == self.active_cash_table_id:
                    self.cash_status_var.set(f"GTO+ retry failed: {exc}")

    def _start_cash_cpu_chain_if_needed(self):
        if self.cash_table is None or self.cash_table.hand is None or self.cash_table.hand.finished:
            self._render_cash_actions()
            return
        if self.cash_busy:
            self._render_cash_actions()
            return

        table = self.cash_table
        hand = table.hand
        table_id = self.active_cash_table_id
        is_cpu_turn = hand.next_to_act != "hero"
        slot_state = self.multi_tables.get(table_id).state if table_id and self.multi_tables.get(table_id) else {}
        if slot_state.get("cash_gto_waiting"):
            slot_state["cash_gto_waiting"] = False
        if (not is_cpu_turn and hand.street == "preflop" and not hand.finished
                and not bool(getattr(self, "cash_gto_spot_mode", False))
                and is_rush_mode(getattr(self, "cash_game_mode", RUSH_MODE))):
            try:
                chart_fold, chart_position, chart_combo = should_auto_fold(
                    hand, self.auto_fold_chart,
                    cash_drop_active=bool(getattr(hand, "cash_drop_active", False)))
            except Exception:
                chart_fold, chart_position, chart_combo = False, None, None
            if chart_fold:
                slot_state.setdefault("cash_log_lines", []).append(
                    f"AUTO-FOLD CHART • {chart_position} • {chart_combo}")
                self._request_preflop_fold(table_id)
                return
        if getattr(hand, "awaiting_runout_choice", False):
            self.cash_busy = False
            slot_state["cash_busy"] = False
            self._show_allin_decision(table_id)
            return
        client = getattr(self.integration, "_client", None)
        connected = bool(client is not None and client.connected)
        tree_files = [path for path in self.tree_files if path.is_file()]
        if self.tree_file is not None and self.tree_file.is_file() and self.tree_file not in tree_files:
            tree_files.insert(0, self.tree_file)
        # GTO+ scope is HU postflop. Even without a loaded tree/connection, keep
        # these decisions in the solver queue instead of silently using the pool CPU.
        gto_supported = False  # GTO+ ENGINE removed; use local CPU policy on every street.
        session_ready = bool(
            self.cash_gto_session is not None
            and self.cash_gto_session.hand_token == id(hand)
            and self.cash_gto_session.context is not None
        )
        # Crucial: bind at the first HU postflop node even when HERO acts first.
        # Otherwise the human's first check/bet is never sent to GTO+, and the
        # CPU cannot continue the same solver line on its turn.
        needs_bind = gto_supported and not session_ready
        if not is_cpu_turn and not needs_bind:
            if self._consume_queued_auto_fold(table_id):
                return
            self._ensure_squeeze_action_deadline(table_id)
            self._render_cash_actions()
            return

        self.cash_busy = True
        self.cash_syncing_gto = bool(needs_bind and not is_cpu_turn)
        self._save_active_cash_slot()
        self._render_cash_actions()
        self._refresh_table_windows()
        preferred_tree = self.tree_file
        candidate_trees = list(tree_files)
        big_blind = int(self.cash_bb)
        try:
            rake_pct = float(self.rake_var.get() or 0)
        except (TypeError, ValueError):
            rake_pct = 0.0
        cpus = dict(self.cash_cpus)
        profiles = dict(self.cash_cpu_profiles)
        # Stable CPU identities carry empirical action statistics between Rush hands.
        opponent_learning = self.cpu_learning_store.get_profiles(self.cash_rate, profiles.keys())
        vip_roles = dict(slot_state.get("vip_cpu_roles", self.vip_cpu_roles))
        active_mode = normalize_table_mode(slot_state.get("cash_game_mode", self.cash_game_mode))
        # GTO+ live CPU execution has been removed; always use the local range policy.
        existing_session = None
        timing_rng = self.cash_random
        cancel_event = threading.Event()
        self.cash_cpu_cancel_events[table_id] = cancel_event
        if gto_supported:
            self.jobs.put(("cash_gto_query_started", {
                "table_id": table_id,
                "player_id": hand.next_to_act,
                "name": (hand.player(hand.next_to_act).name
                         if hand.next_to_act in hand.seat_by_id else "CPU"),
            }))

        def work():
            decisions = []
            active_cpu_turn_timer = None
            active_cpu_turn_timed_out = None
            source_status = (
                "GTO+ exact HU postflop match required • CPU pauses on a miss"
                if gto_supported else
                "Local CPU policy • outside GTO+ HU postflop scope"
            )
            gto_reason = ""
            session = existing_session
            try:
                # Proactively bind on the first HU postflop state, independent of
                # whose turn it is. GTO+ stays the source for every exactly matched
                # decision node later in this hand.
                if needs_bind and not cancel_event.is_set():
                    try:
                        with self.integration.solver_status_context(table_id):
                            candidate, bound = bind_first_matching_tree(
                                self.integration, hand, candidate_trees, big_blind,
                                rake_pct=rake_pct, preferred_tree=preferred_tree,
                                allow_current_session=(len(self.multi_tables) <= 1),
                            )
                        session = candidate
                        try:
                            scenario_for_resolve = self._make_live_gto_scenario(
                                hand, table, hand.next_to_act if is_cpu_turn else "hero",
                                rake_pct, table_id)
                            miss_key = self.integration.bridge.scenario_fingerprint(scenario_for_resolve)
                            self.store.resolve_unmatched_scenario(
                                miss_key, str(bound.get("tree_file", "GTO+ current session")))
                        except Exception:
                            pass
                        source_status = (
                            f"GTO+ linked • {Path(bound['tree_file']).name if bound['tree_file'] != '<current GTO+ session>' else 'current session'} "
                            f"• {bound['tree_match_mode']} • {bound['imported_combos']} combo strategies cached"
                        )
                    except Exception as bind_exc:
                        session = None
                        gto_reason = str(bind_exc)

                if cancel_event.is_set():
                    self.jobs.put(("cash_cpu_done", {
                        "table_id": table_id, "decisions": decisions,
                        "snapshot": table.snapshot(), "gto_note": "leave requested",
                        "session": session, "source_status": source_status,
                        "cancelled": True,
                    }))
                    return

                if not is_cpu_turn:
                    # Deliver the prepared session to the UI so HERO's action
                    # buttons can be restricted to the exact solver tree actions.
                    self.jobs.put(("cash_gto_bind_done", {
                        "table_id": table_id, "session": session,
                        "source_status": source_status, "gto_reason": gto_reason,
                    }))
                    return

                safety = 0
                while (not cancel_event.is_set() and not hand.finished and not hand.awaiting_runout_choice
                       and hand.next_to_act != "hero"):
                    safety += 1
                    if safety > 200:
                        raise RuntimeError("CPU action loop safety stop (200 actions in one hand)")
                    pid = hand.next_to_act
                    cpu = cpus.get(pid)
                    if cpu is None:
                        raise RuntimeError(f"No CPU profile/runtime is registered for seat {pid}")

                    actor_name = hand.player(pid).name

                    action_timeout_seconds = float(action_seconds_for_street(hand.street))
                    turn_timed_out = threading.Event()
                    turn_committed = threading.Event()
                    turn_lock = threading.Lock()
                    turn_hand_token = id(hand)
                    turn_event_count = len(hand.events)
                    def expire_cpu_turn(
                        tid=table_id, player_id=pid, actor=actor_name,
                        hand_token=turn_hand_token, event_count=turn_event_count,
                        expired=turn_timed_out, committed=turn_committed, lock=turn_lock,
                        timeout_seconds=action_timeout_seconds
                    ):
                        with lock:
                            if committed.is_set():
                                return
                            expired.set()
                            cancel_event.set()
                        self.jobs.put(("cash_cpu_timeout", {
                            "table_id": tid, "player_id": player_id, "name": actor,
                            "hand_token": hand_token, "event_count": event_count,
                            "seconds": timeout_seconds,
                        }))
                    turn_timer = threading.Timer(action_timeout_seconds, expire_cpu_turn)
                    turn_timer.daemon = True
                    active_cpu_turn_timer = turn_timer
                    active_cpu_turn_timed_out = turn_timed_out
                    self.jobs.put(("cash_cpu_thinking", {
                        "table_id": table_id, "player_id": pid, "name": actor_name,
                        "seconds": action_timeout_seconds,
                    }))
                    turn_timer.start()
                    # Precompute fallback decisions so routine preflop folds can
                    # move almost immediately; postflop keeps natural thinking time.
                    fallback_decision = None
                    if hand.street == "preflop":
                        # Every preflop turn uses the screenshot-trained policy's exact nodes, explicit
                        # position/history/stack inference, or its safe legal-action
                        # fallback. Never route a custom human line into the postflop
                        # range policy.
                        fallback_decision = choose_preflop_action(table, hand, pid, cpu, None)
                    elif not (session is not None and session.hand_token == id(hand) and session.context is not None):
                        # The same opponent-range engine handles postflop decisions.
                        fallback_decision = choose_range_aware_action(
                            table, hand, pid, cpu,
                            range_estimator=lambda **kwargs: estimate_preflop_opponent_ranges(**kwargs, opponent_profiles=profiles, opponent_learning=opponent_learning),
                        )
                    if hand.street == "preflop":
                        if fallback_decision is not None and fallback_decision.action == "fold":
                            think_seconds = timing_rng.uniform(0.07, 0.16)
                        elif fallback_decision is not None:
                            think_seconds = timing_rng.uniform(0.38, 0.72)
                        else:
                            think_seconds = timing_rng.uniform(0.18, 0.38)
                    else:
                        think_seconds = timing_rng.uniform(0.9, 2.15)
                        if hand.street == "flop":
                            think_seconds += timing_rng.uniform(0.25, 0.85)
                        elif hand.street == "turn":
                            think_seconds += timing_rng.uniform(0.45, 1.0)
                        elif hand.street == "river":
                            think_seconds += timing_rng.uniform(0.65, 1.35)
                        if hand.pot >= hand.big_blind * 30:
                            think_seconds += timing_rng.uniform(0.25, 0.7)
                    self.jobs.put(("cash_cpu_thinking", {
                        "table_id": table_id, "player_id": pid, "name": actor_name,
                        "seconds": think_seconds,
                    }))
                    if cancel_event.wait(think_seconds):
                        break
                    if cancel_event.is_set():
                        break
                    old_board = list(hand.board)
                    action_label = ""
                    event_action = ""
                    event_amount = None
                    gto_used = False
                    screenshot_policy_used = False
                    inferred_preflop_policy_used = False
                    preflop_legal_fallback_used = False
                    preflop_gto_policy_used = False
                    range_policy_used = False

                    if session is not None and session.hand_token == id(hand) and session.context is not None:
                        try:
                            profile = profiles.get(pid)
                            vip_role = vip_roles.get(pid) if is_vip_mode(active_mode) else None
                            with self.integration.solver_status_context(table_id):
                                result = session.cpu_decide(
                                    hand, pid, rng=cpu.rng,
                                    level=(5 if is_vip_mode(active_mode) else cpu.level),
                                    archetype=("balanced" if is_vip_mode(active_mode) else
                                               (profile.archetype if profile else "balanced")),
                                )
                                with turn_lock:
                                    if not turn_timed_out.is_set() and not cancel_event.is_set():
                                        turn_committed.set()
                                        turn_timer.cancel()
                            table.sync_external_hand_state()
                            move = result["move"]
                            deviation_note = " • deviation" if result.get("deviated") else ""
                            if is_vip_mode(active_mode):
                                role_label = vip_cpu_role_label(vip_roles.get(pid))
                                line = (f"{actor_name}: {move.solver_label} "
                                        f"[{role_label} • matched GTO+ node]")
                            else:
                                line = f"{actor_name}: {move.solver_label} [GTO+ Lv.{cpu.level}{deviation_note}]"
                            decisions.append(line)
                            event_action = str(move.action)
                            event_amount = move.amount
                            action_label = self._describe_action(actor_name, move.action, move.amount, hand.big_blind)
                            source_status = "GTO+ exact solved-node strategy • node cached during play"
                            try:
                                self.store.record_cpu_decision(
                                    str(result.get("cache_key", "")), "gtoplus", event_action,
                                    table_id=str(table_id or ""),
                                    hand_number=int(getattr(table, "hand_number", 0) or 0),
                                    actor_id=str(pid),
                                    details={"street": hand.street, "board": list(hand.board),
                                             "solver_action": move.solver_label,
                                             "deviated": bool(result.get("deviated", False))})
                            except Exception:
                                pass
                            gto_used = True
                        except Exception as gto_exc:
                            gto_reason = str(gto_exc)
                            session = None

                    if cancel_event.is_set():
                        break
                    if gto_supported and not gto_used:
                        # A supported HU postflop state must not be played by the
                        # generic pool policy. Record the precise miss and pause the
                        # CPU turn until a matching GTO+ solved tree is loaded.
                        reason = gto_reason or "No exact GTO+ solved node was available for this HU postflop state."
                        scenario_key, request_path = self._queue_live_gto_miss(
                            hand, table, pid, rake_pct, table_id, reason)
                        self.jobs.put(("cash_gto_waiting", {
                            "table_id": table_id, "player_id": pid, "scenario_key": scenario_key,
                            "request_path": request_path, "reason": reason,
                            "snapshot": table.snapshot(), "session": None,
                        }))
                        return
                    if not gto_used:
                        decision = fallback_decision
                        if decision is None:
                            # If a preflop helper unexpectedly returns no decision,
                            # retry the screenshot-trained GTO policy rather than
                            # asking the postflop policy to invent a preflop line.
                            if hand.street == "preflop":
                                decision = choose_preflop_action(table, hand, pid, cpu, None)
                            else:
                                decision = choose_range_aware_action(
                                    table, hand, pid, cpu,
                                    range_estimator=lambda **kwargs: estimate_preflop_opponent_ranges(**kwargs, opponent_profiles=profiles, opponent_learning=opponent_learning),
                                )
                        if decision is None:
                            raise RuntimeError("No safe decision was available for this CPU turn.")
                        if cancel_event.is_set():
                            break
                        with turn_lock:
                            if turn_timed_out.is_set() or cancel_event.is_set():
                                break
                            table.act(pid, decision.action, decision.amount)
                            turn_committed.set()
                            turn_timer.cancel()
                        event_action = str(decision.action)
                        event_amount = decision.amount
                        decision_source = str(getattr(decision, "source", ""))
                        screenshot_policy_used = decision_source == "new-screenshot-gto"
                        inferred_preflop_policy_used = decision_source == "gto-rule-inference"
                        preflop_legal_fallback_used = decision_source == "gto-inferred-legal-fallback"
                        preflop_gto_policy_used = (
                            screenshot_policy_used or inferred_preflop_policy_used
                            or preflop_legal_fallback_used
                        )
                        range_policy_used = decision_source in {
                            "range-aware-policy", "range-aware-guardrail"
                        }
                        if screenshot_policy_used:
                            line = (
                                f"{actor_name}: {decision.action.upper()}"
                                + (f" ${decision.amount/100:.2f}" if decision.amount is not None else "")
                                + f" [screenshot GTO {decision.node_id}/{decision.hand_class} • {decision.action_frequency*100:.1f}%]"
                            )
                            source_status = f"Screenshot-trained GTO node • {decision.node_id}"
                        elif inferred_preflop_policy_used:
                            line = (
                                f"{actor_name}: {decision.action.upper()}"
                                + (f" ${decision.amount/100:.2f}" if decision.amount is not None else "")
                                + f" [GTO inference {decision.node_id}/{decision.hand_class} • {decision.action_frequency*100:.1f}%]"
                            )
                            source_status = (
                                f"GTO position/history/stack inference • {decision.node_id}"
                            )
                        elif preflop_legal_fallback_used:
                            line = (
                                f"{actor_name}: {decision.action.upper()}"
                                + " [GTO legal-action fallback]"
                            )
                            source_status = (
                                "No weighted GTO action was legal; a safe legal action was selected."
                            )
                        elif range_policy_used:
                            equity_pct = 100.0 * float(decision.equity_estimate or 0.0)
                            line = (
                                f"{actor_name}: {decision.action.upper()}"
                                + (f" ${decision.amount/100:.2f}" if decision.amount is not None else "")
                                + f" [range-aware • equity {equity_pct:.1f}%]"
                            )
                            source_status = str(getattr(decision, "note", "Range-aware decision"))
                        else:
                            line = (
                                f"{actor_name}: {decision.action.upper()}"
                                + (f" ${decision.amount/100:.2f}" if decision.amount is not None else "")
                                + f" [fallback, equity≈{decision.equity_estimate:.0%}]"
                            )
                            source_status = "Local fallback policy (not solver-exact)"
                        decisions.append(line)
                        action_label = self._describe_action(actor_name, decision.action, decision.amount, hand.big_blind)
                        try:
                            fallback_key = self.integration.bridge.scenario_fingerprint({
                                "street": hand.street, "board": list(hand.board),
                                "pot": hand.pot, "actor": pid,
                                "action_history": [e for e in hand.events if e.get("type") == "action"]})
                            self.store.record_cpu_decision(
                                fallback_key,
                                "preflop_screenshot_gto" if preflop_gto_policy_used else (
                                    "range_aware_guardrail" if getattr(decision, "source", "") == "range-aware-guardrail"
                                else "range_aware_policy" if range_policy_used else "fallback_unsupported"
                                ),
                                event_action,
                                table_id=str(table_id or ""),
                                hand_number=int(getattr(table, "hand_number", 0) or 0),
                                actor_id=str(pid), details={"street": hand.street,
                                    "board": list(hand.board), "reason": source_status,
                                    "range_node": getattr(decision, "node_id", ""),
                                    "range_hand": getattr(decision, "hand_class", ""),
                                    "range_frequency": getattr(decision, "action_frequency", None),
                                    "equity_estimate": getattr(decision, "equity_estimate", None),
                                    "decision_note": getattr(decision, "note", "")})
                        except Exception:
                            pass

                    self.jobs.put(("cash_cpu_action_event", {
                        "table_id": table_id, "player_id": pid, "name": actor_name,
                        "line": action_label, "action": event_action, "amount": event_amount,
                        "gto_used": gto_used,
                        "strategy_source": (
                            "preflop-screenshot-gto" if screenshot_policy_used else
                            "preflop-gto-inference" if inferred_preflop_policy_used else
                            "preflop-gto-legal-fallback" if preflop_legal_fallback_used else
                            "range-aware-guardrail" if getattr(fallback_decision, "source", "") == "range-aware-guardrail" else
                            "range-aware-policy" if range_policy_used else
                            ("gtoplus" if gto_used else "local-fallback")
                        ),
                        "street": hand.street, "pot": hand.pot,
                        "board_changed": len(hand.board) > len(old_board),
                    }))
                    if len(hand.board) > len(old_board):
                        animation_done = threading.Event()
                        board_squeeze_start = self._board_squeeze_start_index(hand, len(old_board))
                        self.jobs.put(("cash_board_animation", {
                            "table_id": table_id, "board": list(hand.board),
                            "squeeze_start_index": board_squeeze_start,
                            "ready_event": animation_done,
                        }))
                        # The CPU cannot make its next decision until the board
                        # has visibly run out on the table.
                        while not cancel_event.is_set() and not animation_done.wait(timeout=0.08):
                            pass
                    else:
                        # Leave the action banner and chip movement visible before
                        # the next opponent begins thinking; quick leave interrupts this wait.
                        if cancel_event.wait(timing_rng.uniform(0.65, 0.95)):
                            break

                if active_cpu_turn_timed_out is not None and active_cpu_turn_timed_out.is_set():
                    return
                if active_cpu_turn_timer is not None:
                    active_cpu_turn_timer.cancel()
                table.sync_external_hand_state()
                self.jobs.put(("cash_cpu_done", {
                    "table_id": table_id, "decisions": decisions,
                    "snapshot": table.snapshot(), "gto_note": gto_reason,
                    "session": session, "source_status": source_status,
                    "cancelled": cancel_event.is_set(),
                }))
            except Exception as exc:
                if active_cpu_turn_timer is not None:
                    active_cpu_turn_timer.cancel()
                if active_cpu_turn_timed_out is not None and active_cpu_turn_timed_out.is_set():
                    return
                self.jobs.put(("cash_cpu_error", {
                    "table_id": table_id, "error": str(exc),
                    "decisions": decisions, "session": session,
                    "cancelled": cancel_event.is_set(),
                }))

        threading.Thread(target=work, daemon=True, name="PigeonCashCPU").start()

    def _start_gto_plus_spot(self, restart: bool = False):
        """Start a genuinely solver-rooted HU postflop hand inside the Pigeon table UI."""
        if self.tree_file is None:
            messagebox.showinfo("GTO+ spot", "先にGTO+ ENGINEで接続し、解析済み .gto2 ツリーを読み込んでください。")
            self.show_page("lobby")
            return
        if not restart and self.multi_tables.full:
            messagebox.showwarning("Table limit", "GTO+ Spotを含めて同時に開けるテーブルは最大2卓です。")
            return
        if self.cash_busy:
            return
        if self.cash_table is not None:
            self._save_active_cash_slot()
        self.pending_gto_previous_table_id = self.active_cash_table_id if not restart else None
        self.pending_gto_restart_table_id = self.active_cash_table_id if restart else None
        self.cash_busy = True
        self.cash_gto_spot_mode = True
        if not restart:
            self.cash_session_id = uuid.uuid4().hex
            self.cash_hand_instance = 0
        self.cash_table = None
        self.cash_gto_session = None
        self.cash_status_var.set("GTO+の現在ノードを取得中…")
        self.cash_source_var.set("GTO+ solver • loading saved spot")
        self.show_page("table")
        self._render_cash_actions()

        tree = self.tree_file
        human_side = self.human_side_var.get().strip().lower()
        cpu_side = "ip" if human_side == "oop" else "oop"
        rake_pct = float(self.rake_var.get().strip() or "0")
        chooser = random.Random()

        def work():
            try:
                if self.integration.active_tree != str(tree.expanduser().resolve()):
                    self.integration.open_solved_tree(tree)
                context = self.integration.import_current_node(tree, rake_pct)
                dealt = self.integration.sample_private_hands(cpu_side, human_side,
                                                               cpu_hand="AUTO", human_hand="AUTO",
                                                               rng=chooser)
                node = context["node"]
                table = build_gto_plus_spot_table(context, dealt, human_side)
                bb_units = table.big_blind
                session = GTOPlusLiveSession(self.integration, str(tree), bb_units, rake_pct=rake_pct)
                # Bind the live adapter to the synthetic postflop hand built from
                # the exact selected GTO+ node (the old name `hand` was undefined).
                if table.hand is None:
                    raise RuntimeError("Pigeon could not build a hand from the selected GTO+ node")
                session.bind(table.hand)
                self.jobs.put(("cash_gto_spot_ready", {"table": table, "session": session,
                                                         "dealt": dealt, "context": context,
                                                         "human_side": human_side}))
            except Exception as exc:
                self.jobs.put(("cash_start_error", str(exc)))

        threading.Thread(target=work, daemon=True, name="PigeonGTOSpotLoad").start()

    def _update_cash_after_action(self):
        if self.cash_table is None or self.cash_table.hand is None:
            return
        hand = self.cash_table.hand
        if getattr(hand, "awaiting_runout_choice", False):
            self.cash_busy = False
            slot = self.multi_tables.get(self.active_cash_table_id) if self.active_cash_table_id else None
            if slot is not None:
                slot.state["cash_busy"] = False
            self._show_allin_decision(self.active_cash_table_id)
            return
        # If a human action caused the flop/turn/river to be dealt, animate the
        # community cards first and only then continue the hand state machine.
        if len(self.cash_board_target) < len(hand.board) or self.cash_board_target != list(hand.board):
            self.cash_busy = True
            self._render_cash_actions()
            squeeze_start = self._board_squeeze_start_index(hand, len(self.cash_board_target))
            self._animate_board_reveal(
                self.active_cash_table_id, list(hand.board),
                squeeze_start_index=squeeze_start,
                on_done=lambda tid=self.active_cash_table_id: self._finish_human_board_animation(tid)
            )
            return
        if hand.next_to_act == "hero" and self._consume_queued_auto_fold(self.active_cash_table_id):
            return
        board_squeeze_eligible = False
        self.cash_status_var.set(f"Hand #{self.cash_table.hand_number} • {hand.street.upper()} • Pot ${hand.pot/100:.2f}")
        self.cash_log_lines.append(f"{hand.street.upper()} | Board: {' '.join(hand.board) or '—'} | Pot ${hand.pot/100:.2f}")
        self._draw_table()
        self._render_cash_actions()
        if hand.finished:
            if self.active_cash_table_id:
                self._cancel_squeeze_action_deadline(self.active_cash_table_id)
            active_slot = self.multi_tables.get(self.active_cash_table_id) if self.active_cash_table_id else None
            active_state = active_slot.state if active_slot else {}
            if bool(active_state.get("cash_sitout_pending", False)):
                active_state["cash_sitout_pending"] = False
                active_state["cash_sitting_out"] = True
                active_state["cash_action_feed"] = "SITTING OUT • TABLE AND STACK PRESERVED"
                self.cash_status_var.set("SITTING OUT • press RESUME to return")
                self._save_active_cash_slot()
                self._refresh_table_windows()
            self.cash_table.sync_external_hand_state()
            # Cash Drop pool contribution is collected by the poker engine from
            # pots >= 30BB and accumulated across this local Rush & Cash client.
            cash_drop_fee = int(getattr(hand, "cash_drop_fund_fee", 0) or 0)
            if cash_drop_fee > 0:
                self.cash_drop_pool_cents += cash_drop_fee
                self.config_data["cash_drop_pool_cents"] = self.cash_drop_pool_cents
                save_config(self.config_data)
                self.cash_log_lines.append(
                    f"CASH DROP POOL • +{self._format_table_chips(cash_drop_fee, hand.big_blind)}")
            # A paid Time Bank Card is charged at hand end in Rush & Cash.
            fee_due = int(active_state.get("cash_timebank_fee_due", 0) or 0)
            if fee_due > 0:
                hero_for_fee = hand.player("hero")
                if hero_for_fee.stack >= fee_due:
                    hero_for_fee.stack -= fee_due
                    seat_for_fee = next((seat for seat in self.cash_table.seats if seat["id"] == "hero"), None)
                    if seat_for_fee is not None:
                        seat_for_fee["stack"] = hero_for_fee.stack
                    # Rush & Cash special handling: deduct from the buyer's stack
                    # at hand end; if the remaining stack is short, waive the fee.
                    # Do not send the fee to the simulated rotating opponents.
                    self.cash_log_lines.append(f"PAID TIME BANK • -{self._format_table_chips(fee_due, self.cash_table.big_blind)}")
                else:
                    self.cash_log_lines.append("PAID TIME BANK • fee waived (insufficient remaining stack)")
                active_state["cash_timebank_fee_due"] = 0
                self.cash_table.sync_external_hand_state()
            if self.cash_current_hand_key:
                try:
                    saved = self.history_store.save(
                        self.cash_current_hand_key, self.cash_rate, hand,
                        session_id=self.cash_session_id, table_id=self.active_cash_table_id or "",
                        compute_allin_ev=False)
                    if saved:
                        self.cash_log_lines.append("PokerCraft: hand history saved")
                        if getattr(self, "_active_page_key", "") == "poker_craft":
                            try:
                                self.after(80, self._refresh_pokercraft)
                            except tk.TclError:
                                pass
                        allin_snapshot = next((event for event in hand.events
                                                if event.get("type") == "allin_ev_snapshot"), None)
                        if allin_snapshot is not None:
                            hand_key_for_ev = str(self.cash_current_hand_key)
                            snapshot_for_ev = dict(allin_snapshot)
                            def calculate_allin_ev(key=hand_key_for_ev, snapshot=snapshot_for_ev):
                                try:
                                    estimate = estimate_hero_allin_ev(snapshot)
                                    self.history_store.update_allin_ev(key, estimate)
                                    self.jobs.put(("history_allin_ev_done", {"hand_key": key}))
                                except Exception as ev_exc:
                                    self.jobs.put(("history_allin_ev_error", str(ev_exc)))
                            threading.Thread(target=calculate_allin_ev, daemon=True,
                                             name="PigeonAllinEV").start()
                except Exception as history_exc:
                    self.cash_log_lines.append(f"PokerCraft save error: {history_exc}")
                if not self.cash_gto_spot_mode:
                    try:
                        if self.cpu_pool_store.record_hand(self.cash_current_hand_key, self.cash_rate, hand):
                            self.cash_log_lines.append("CPU pool: opponent statistics updated")
                        if self.cpu_learning_store.record_hand(
                            self.cash_current_hand_key, self.cash_rate, hand,
                            cpu_ids=self.cash_cpu_profiles.keys(),
                        ):
                            self.cash_log_lines.append("CPU learning: per-opponent behavior saved")
                    except Exception as cpu_stats_exc:
                        self.cash_log_lines.append(f"CPU statistics error: {cpu_stats_exc}")
            if not self.cash_gto_spot_mode and self.ggcare_candidate is not None:
                try:
                    care_result = self.ggcare_ledger.settle(self.ggcare_candidate, hand)
                    if care_result is not None:
                        if care_result.reward_cents > 0:
                            self.cash_balance_cents += care_result.reward_cents
                            self._update_cash_balance()
                            self._record_cash_transaction("gg-care", care_result.reward_cents,
                                                          note=f"{self.cash_rate} GG Care roll {care_result.roll}")
                        self.cash_log_lines.append(
                            f"GG CARE: roll {care_result.roll} • +${care_result.reward_cents/100:.2f} • {care_result.reason}"
                            if care_result.roll is not None else f"GG CARE: not qualified • {care_result.reason}"
                        )
                except Exception as care_exc:
                    self.cash_log_lines.append(f"GG Care error: {care_exc}")
                finally:
                    self.ggcare_candidate = None
            winners = []
            if hand.winner_reason == "showdown":
                for award in hand.awards:
                    winners.extend(award.winners)
                self.cash_log_lines.append("SHOWDOWN RESULT: " + (", ".join(dict.fromkeys(winners)) if winners else "split pot"))
            elif hand.winner_reason == "fast_fold":
                # Do not reveal the other players' cards or the result of the
                # abandoned pot. This is the defining fast-fold transition.
                self.cash_log_lines.append("RUSH: folded hand abandoned; moving to a new table")
            else:
                # A hand won by folds intentionally does not expose the winner
                # or anybody's cards; preserving the mystery is part of poker.
                self.cash_log_lines.append("HAND ENDED • no showdown")
            hero = hand.player("hero")
            if self.cash_auto_rebuy_var.get() and hero.stack < self.cash_buyin:
                self._sync_external_wallet_balance()
                top_up = self.cash_buyin - hero.stack
                if self.cash_balance_cents >= top_up:
                    hero.stack += top_up
                    seat = next(s for s in self.cash_table.seats if s["id"] == "hero")
                    seat["stack"] = hero.stack
                    self.cash_balance_cents -= top_up
                    self._update_cash_balance()
                    self._record_cash_transaction("auto-rebuy", -top_up, note=f"{self.cash_rate} to 100 BB")
                    self.cash_log_lines.append(f"AUTO REBUY: topped up by ${top_up/100:.2f} to 100 BB")
                else:
                    self.cash_log_lines.append("AUTO REBUY skipped: insufficient account balance")
            self._refresh_cash_history()
            self._refresh_ggcare()
            # Normal showdowns get a short result beat. A fast-fold immediately
            # deals a fresh hand, with no result screen or opponent wait.
            if (not self.cash_gto_spot_mode and hero.stack > 0
                    and self.active_cash_table_id is not None
                    and not bool(active_state.get("cash_sitting_out", False))):
                self._schedule_auto_next_hand(self.active_cash_table_id,
                                              delay_ms=(35 if hand.winner_reason == "fast_fold"
                                                        else (3600 if board_squeeze_eligible else 2700)))
        else:
            if self.active_cash_table_id and hand.next_to_act == "hero":
                self._ensure_squeeze_action_deadline(self.active_cash_table_id)
            elif self.active_cash_table_id:
                self._cancel_squeeze_action_deadline(self.active_cash_table_id)
            self._start_cash_cpu_chain_if_needed()

    def _schedule_auto_next_hand(self, table_id: str, delay_ms: int = 1100):
        if table_id in self.auto_next_hand_jobs:
            return
        self.auto_next_hand_jobs.add(table_id)
        self.after(delay_ms, lambda tid=table_id: self._auto_next_cash_hand(tid))

    def _auto_next_cash_hand(self, table_id: str):
        self.auto_next_hand_jobs.discard(table_id)
        if table_id not in {slot.table_id for slot in self.multi_tables.list()}:
            return
        if self.active_cash_table_id != table_id:
            if self.cash_busy:
                self._schedule_auto_next_hand(table_id, delay_ms=500)
                return
            self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
        if (self.cash_table is None or self.cash_table.hand is None
                or not self.cash_table.hand.finished or self.cash_busy
                or self.cash_gto_spot_mode):
            return
        slot = self.multi_tables.get(table_id)
        state = slot.state if slot else {}
        normalize_table_pause_state(state)
        if state.get("cash_sitting_out"):
            self._refresh_table_windows()
            return
        if state.get("cash_sitout_before_bb") and self._hero_is_next_big_blind():
            state["cash_sitting_out"] = True
            state["cash_sitout_before_bb"] = False
            state["cash_action_feed"] = "SIT OUT • BEFORE NEXT BIG BLIND • TABLE PRESERVED"
            record = self.table_windows.get(table_id)
            if record:
                record["sitout_before_bb_var"].set(False)
            self.cash_sitout_before_bb_var.set(False)
            self.cash_status_var.set("SITTING OUT BEFORE BIG BLIND • press RESUME")
            self.cash_log_lines.append("SIT OUT: skipped next BB; table preserved")
            self._save_active_cash_slot()
            self._refresh_table_windows()
            return
        hero = self.cash_table.hand.player("hero")
        if hero.stack <= 0:
            self.cash_status_var.set("Stack is empty • use REBUY or LEAVE TABLE")
            self._refresh_table_windows()
            return
        self._start_cash_hand(first=False)

    def _squeeze_hole_cards(self, table_id: str, *, open_all: bool = False):
        if table_id != self.active_cash_table_id:
            self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
        if self.cash_table is None or self.cash_table.hand is None:
            return
        hand = self.cash_table.hand
        if hand.finished or hand.next_to_act != "hero" or hand.player("hero").folded:
            return
        self.hero_squeeze_count = 2 if open_all else min(2, self.hero_squeeze_count + 1)
        self._save_active_cash_slot()
        self._draw_table()
        self._refresh_table_windows()

    def _squeeze_board(self, table_id: str, *, open_all: bool = False):
        if table_id != self.active_cash_table_id:
            self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
        if self.cash_table is None or self.cash_table.hand is None:
            return
        hand = self.cash_table.hand
        all_in = any(player.all_in for player in hand.players)
        threshold = 100 * self.cash_bb
        if not (hand.finished and all_in and hand.pot > threshold and len(hand.board) == 5):
            return
        self.board_squeeze_count = 5 if open_all else min(5, max(3, self.board_squeeze_count) + 1)
        self._save_active_cash_slot()
        self._draw_table()
        self._refresh_table_windows()

    def _save_squeeze_preference(self):
        self.config_data["card_squeeze_enabled"] = bool(self.card_squeeze_enabled_var.get())
        save_config(self.config_data)
        self._draw_table()
        self._refresh_table_windows()

    def _refresh_cash_history(self):
        if not hasattr(self, "cash_history_text"):
            return
        self.cash_history_text.configure(state="normal")
        self.cash_history_text.delete("1.0", "end")
        self.cash_history_text.insert("end", "\n".join(self.cash_log_lines[-80:]))
        self.cash_history_text.see("end")
        self.cash_history_text.configure(state="disabled")

    def _manual_cash_rebuy(self):
        if self.cash_table is None or self.cash_table.hand is None or not self.cash_table.hand.finished:
            return
        self._sync_external_wallet_balance()
        hero = self.cash_table.hand.player("hero")
        missing = max(0, self.cash_buyin - hero.stack)
        if missing <= 0:
            return
        if self.cash_balance_cents < missing:
            messagebox.showwarning("Insufficient balance", "100 BBまでの追加購入に残高が足りません。")
            return
        hero.stack += missing
        hero_seat = next(seat for seat in self.cash_table.seats if seat["id"] == "hero")
        hero_seat["stack"] = hero.stack
        self.cash_balance_cents -= missing
        self._update_cash_balance()
        self._record_cash_transaction("manual-rebuy", -missing, note=f"{self.cash_rate} to 100 BB")
        self.cash_log_lines.append(f"MANUAL REBUY: +${missing/100:.2f} to 100 BB")
        self._draw_table()
        self._render_cash_actions()
        self._refresh_cash_history()

    def _leave_cash_table(self, *, confirmed: bool = False):
        if self.cash_table is None or self.active_cash_table_id is None:
            return
        if self.cash_busy:
            messagebox.showinfo("Cash & Rush", "CPUの処理中です。テーブル退出の確認後、CPU処理の中断を待って退出します。",
                                parent=self.table_windows.get(self.active_cash_table_id, {}).get("window", self))
            return
        if not confirmed:
            if not self._ask_table_confirmation(
                    self.active_cash_table_id, "テーブル退出", "このテーブルから退出しますか？\n進行中のハンドがあればフォールドして、残りのスタックをウォレットへ戻します。"):
                return
        if self.cash_table.hand is not None and not self.cash_table.hand.finished:
            if not self.cash_gto_spot_mode:
                # Confirmed leave folds HERO; committed chips remain in the pot.
                leaving_hand = self.cash_table.hand
                leaving_hand.player("hero").folded = True
                leaving_hand.finished = True
                leaving_hand.winner_reason = "fast_fold"
                leaving_hand.next_to_act = None
                leaving_hand.pending.clear()
                leaving_hand.awards = []
                self.cash_log_lines.append("RUSH: folded and left the table immediately")
        self.cash_table.sync_external_hand_state()
        hero_seat = next((seat for seat in self.cash_table.seats if seat["id"] == "hero"), None)
        if hero_seat and not self.cash_gto_spot_mode:
            cash_out = int(hero_seat["stack"])
            self.cash_balance_cents += cash_out
            if cash_out:
                self._record_cash_transaction("cash-out", cash_out, note=f"{self.cash_rate} table exit")
        closing_id = self.active_cash_table_id
        pending_fold_job = self.pending_table_action_jobs.pop(closing_id, None)
        if pending_fold_job:
            try:
                self.after_cancel(pending_fold_job)
            except tk.TclError:
                pass
        self.cash_cpu_cancel_events.pop(closing_id, None)
        self.quick_leave_poll_jobs.discard(closing_id)
        self.rush_fold_poll_jobs.discard(closing_id)
        self._destroy_table_window(closing_id)
        self.multi_tables.remove(closing_id)
        still_pending = any(bool(slot.state.get("cash_sitout_before_bb")) for slot in self.multi_tables.list())
        self.cash_sitout_before_bb_var.set(still_pending)
        self.cash_table = None
        self.cash_gto_session = None
        self.cash_gto_spot_mode = False
        self.cash_cpus = {}
        self.cash_cpu_profiles = {}
        self.active_cash_table_id = self.multi_tables.active_id
        self._update_cash_balance()
        if self.active_cash_table_id:
            next_slot = self.multi_tables.get_active()
            self._restore_cash_slot(next_slot.table_id)
            self.show_page("lobby")
            self._open_floating_table(next_slot.table_id)
        else:
            self.cash_status_var.set("テーブル未参加")
            self.cash_source_var.set("CPU strategy: waiting")
            self._refresh_table_tabs()
            self.show_page("lobby")

    def _cycle_run_it_preference(self, table_id: str):
        """Cycle the table's default all-in resolution preference: Ask / 1x / 2x / 3x."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        values = ("ask", 1, 2, 3)
        current = slot.state.get("cash_run_it_preference", "ask")
        try:
            index = values.index(current)
        except ValueError:
            index = 0
        slot.state["cash_run_it_preference"] = values[(index + 1) % len(values)]
        if table_id == self.active_cash_table_id:
            self._save_active_cash_slot()
        self._refresh_table_windows()

    def _open_auto_fold_chart(self, table_id: str):
        """Open a 169-combo preflop fold chart, configured separately by position."""
        slot = self.multi_tables.get(table_id)
        parent_record = self.table_windows.get(table_id)
        if slot is None or parent_record is None:
            return
        working = normalize_auto_fold_chart(self.auto_fold_chart)
        dialog = tk.Toplevel(parent_record["window"])
        dialog.title("Pigeon Poker • Auto-Fold Hand Chart")
        dialog.geometry("950x700")
        dialog.minsize(850, 640)
        dialog.configure(bg=COLORS["bg"])
        try:
            dialog.transient(parent_record["window"])
            dialog.attributes("-topmost", True)
        except tk.TclError:
            pass

        title = tk.Label(dialog, text="AUTO-FOLD HAND CHART", bg=COLORS["bg"],
                         fg=COLORS["text"], font=("Segoe UI", 15, "bold"))
        title.pack(anchor="w", padx=18, pady=(14, 2))
        tk.Label(dialog,
                 text="Select the exact starting-hand classes to fast-fold before your action. Applies to this Rush & Cash Hold'em table.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", padx=18, pady=(0, 10))
        topbar = tk.Frame(dialog, bg=COLORS["panel"], padx=10, pady=8)
        topbar.pack(fill="x", padx=14)
        enabled_var = tk.BooleanVar(value=bool(working.get("enabled", False)))
        tk.Checkbutton(topbar, text="ENABLE AUTO-FOLD CHART", variable=enabled_var,
                       bg=COLORS["panel"], fg=COLORS["gold"], activebackground=COLORS["panel"],
                       activeforeground=COLORS["text"], selectcolor="#0b1727",
                       font=("Segoe UI", 9, "bold"), bd=0).pack(side="left", padx=(2, 16))
        tk.Label(topbar, text="POSITION", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        position_var = tk.StringVar(value="UTG")
        position_combo = ttk.Combobox(topbar, textvariable=position_var, values=list(POSITIONS),
                                      state="readonly", width=8)
        position_combo.pack(side="left", padx=(6, 14))
        apply_var = tk.BooleanVar(value=bool(working["positions"]["UTG"].get("apply", True)))
        def persist_apply_switch(*_args):
            current_position = position_var.get()
            working["positions"].setdefault(current_position, {"fold": [], "apply": False})
            working["positions"][current_position]["apply"] = bool(apply_var.get())
        apply_var.trace_add("write", persist_apply_switch)
        apply_check = tk.Checkbutton(topbar, text="APPLY AT THIS POSITION", variable=apply_var,
                                     bg=COLORS["panel"], fg=COLORS["text"], activebackground=COLORS["panel"],
                                     activeforeground=COLORS["text"], selectcolor="#0b1727",
                                     font=("Segoe UI", 8), bd=0)
        apply_check.pack(side="left")
        selected_label = tk.StringVar(value="0 / 169 hands selected")
        tk.Label(topbar, textvariable=selected_label, bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="right", padx=4)

        matrix_outer = tk.Frame(dialog, bg=COLORS["panel"], padx=10, pady=10)
        matrix_outer.pack(fill="both", expand=True, padx=14, pady=10)
        matrix = tk.Frame(matrix_outer, bg=COLORS["panel"])
        matrix.pack(anchor="center", expand=True)
        button_refs: dict[str, tk.Button] = {}

        def cell_hand(row: int, col: int) -> str:
            high, low = RANKS_DESC[row], RANKS_DESC[col]
            if row == col:
                return high + low
            if row < col:
                return high + low + "s"
            return low + high + "o"

        def save_current_position_apply():
            current_position = position_var.get()
            working["positions"].setdefault(current_position, {"fold": [], "apply": False})
            working["positions"][current_position]["apply"] = bool(apply_var.get())

        def refresh_matrix(*_args):
            position = position_var.get()
            current = working["positions"].get(position, {"fold": [], "apply": False})
            apply_var.set(bool(current.get("apply", False)))
            selected = set(current.get("fold", []))
            selected_label.set(f"{len(selected)} / 169 hands selected")
            for combo, button in button_refs.items():
                chosen = combo in selected
                button.configure(
                    bg="#a63f4b" if chosen else "#1a3045",
                    activebackground="#c65762" if chosen else "#2b4a65",
                    fg="#ffffff" if chosen else "#dbe8f4",
                    relief="sunken" if chosen else "flat")

        for j, rank in enumerate(RANKS_DESC):
            tk.Label(matrix, text=rank, width=5, bg=COLORS["panel"], fg=COLORS["gold"],
                     font=("Segoe UI", 8, "bold")).grid(row=0, column=j+1, padx=1, pady=1)
        for i, rank in enumerate(RANKS_DESC):
            tk.Label(matrix, text=rank, width=3, bg=COLORS["panel"], fg=COLORS["gold"],
                     font=("Segoe UI", 8, "bold")).grid(row=i+1, column=0, padx=1, pady=1)
            for j in range(13):
                combo = cell_hand(i, j)
                button = tk.Button(
                    matrix, text=combo, width=5, height=1, bd=0,
                    font=("Segoe UI", 7, "bold"), cursor="hand2",
                    command=lambda hand_class=combo: self._toggle_auto_fold_combo(
                        working, position_var, hand_class, refresh_matrix))
                button.grid(row=i+1, column=j+1, padx=1, pady=1, sticky="nsew")
                button_refs[combo] = button
        def change_position(_event=None):
            # The previous position's checkbox has already been persisted by
            # the BooleanVar trace; refresh only loads the newly selected one.
            refresh_matrix()

        position_combo.bind("<<ComboboxSelected>>", change_position)
        refresh_matrix()

        note = tk.Label(dialog,
                        text="Pairs on the diagonal • suited hands above the diagonal • offsuit hands below it. BTN / SB / BB require the position checkbox.",
                        bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8))
        note.pack(anchor="w", padx=18, pady=(0, 8))
        footer = tk.Frame(dialog, bg=COLORS["bg"])
        footer.pack(fill="x", padx=14, pady=(0, 14))

        def clear_position():
            working["positions"][position_var.get()]["fold"] = []
            refresh_matrix()

        def reset_all():
            fresh = default_auto_fold_chart()
            working["enabled"] = fresh["enabled"]
            working["positions"] = fresh["positions"]
            enabled_var.set(False)
            refresh_matrix()

        def apply_and_close():
            save_current_position_apply()
            working["enabled"] = bool(enabled_var.get())
            self.auto_fold_chart = normalize_auto_fold_chart(working)
            self.config_data["auto_fold_chart"] = self.auto_fold_chart
            save_config(self.config_data)
            self._refresh_table_windows()
            dialog.destroy()

        self._auto_fold_dialog_refs = getattr(self, "_auto_fold_dialog_refs", {})
        self._auto_fold_dialog_refs[table_id] = dialog
        dialog.bind("<Destroy>", lambda _event, tid=table_id, win=dialog:
                    self._auto_fold_dialog_refs.pop(tid, None)
                    if self._auto_fold_dialog_refs.get(tid) is win else None)
        ttk.Button(footer, text="CLEAR POSITION", command=clear_position).pack(side="left", padx=4)
        ttk.Button(footer, text="RESET ALL", command=reset_all).pack(side="left", padx=4)
        ttk.Button(footer, text="CANCEL", command=dialog.destroy).pack(side="right", padx=4)
        ttk.Button(footer, text="APPLY", style="Accent.TButton", command=apply_and_close).pack(side="right", padx=4)

    @staticmethod
    def _toggle_auto_fold_combo(working: dict[str, Any], position_var, combo: str, refresh):
        position = position_var.get()
        selected = set(working["positions"][position].get("fold", []))
        if combo in selected:
            selected.remove(combo)
        else:
            selected.add(combo)
        working["positions"][position]["fold"] = sorted(selected)
        refresh()

    def _show_allin_decision(self, table_id: str):
        """Offer Run It Once/Twice/Three Times and eligible local EV Cashout."""
        if not table_id:
            return
        slot = self.multi_tables.get(table_id)
        table = slot.state.get("cash_table") if slot else None
        hand = table.hand if table else None
        if hand is None or hand.finished or not getattr(hand, "awaiting_runout_choice", False):
            return
        existing = self.cash_runout_dialogs.get(table_id)
        if existing:
            try:
                existing["window"].lift()
                existing["window"].focus_force()
            except tk.TclError:
                pass
            return
        preference = slot.state.get("cash_run_it_preference", "ask")
        if preference in (1, 2, 3, "1", "2", "3"):
            self._resolve_allin_decision(table_id, count=int(preference))
            return
        record = self.table_windows.get(table_id)
        parent = record["window"] if record else self
        try:
            self._open_floating_table(table_id)
        except Exception:
            pass
        dialog = tk.Toplevel(parent)
        dialog.title("ALL-IN • RUN IT MULTIPLE TIMES")
        dialog.geometry("560x330")
        dialog.resizable(False, False)
        dialog.configure(bg=COLORS["bg"])
        try:
            dialog.transient(parent)
            dialog.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(dialog, text="ALL-IN", bg=COLORS["bg"], fg=COLORS["gold"],
                 font=("Segoe UI", 17, "bold")).pack(pady=(18, 2))
        tk.Label(dialog, text="Choose how many times to run the remaining board.",
                 bg=COLORS["bg"], fg=COLORS["text"], font=("Segoe UI", 9)).pack()
        status_var = tk.StringVar(value="Checking EV Cashout eligibility…")
        tk.Label(dialog, textvariable=status_var, bg=COLORS["bg"], fg=COLORS["muted"],
                 font=("Segoe UI", 8)).pack(pady=(8, 12))
        buttons = tk.Frame(dialog, bg=COLORS["bg"])
        buttons.pack(fill="x", padx=18, pady=4)
        for count, label in ((1, "RUN IT ONCE"), (2, "RUN IT TWICE"), (3, "RUN IT THREE TIMES")):
            ttk.Button(buttons, text=label, command=lambda n=count: self._resolve_allin_decision(
                table_id, count=n)).pack(fill="x", pady=3)
        cashout_button = ttk.Button(
            buttons, text="CHECKING EV CASHOUT…", state="disabled",
            command=lambda tid=table_id: self._resolve_allin_decision(
                tid, count=1, cashout_offer=self.cash_runout_dialogs.get(tid, {}).get("offer")))
        cashout_button.pack(fill="x", pady=(8, 3))
        tk.Label(dialog, text="No selection: Run It Once automatically after 18 seconds.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(pady=(4, 10))
        token = uuid.uuid4().hex
        auto_job = dialog.after(18000, lambda tid=table_id, key=token:
                                self._auto_resolve_runout(tid, key))
        self.cash_runout_dialogs[table_id] = {
            "window": dialog, "token": token, "auto_job": auto_job,
            "offer": None, "cashout_button": cashout_button,
            "status": status_var, "bb": int(hand.big_blind),
        }
        snapshot = next((dict(event) for event in reversed(hand.events)
                         if event.get("type") == "allin_ev_snapshot"), None)

        def calculate_offer():
            try:
                offer = calculate_ev_cashout_offer(snapshot, int(hand.big_blind), samples=1000) if snapshot else None
                self.jobs.put(("ev_cashout_offer_ready", {
                    "table_id": table_id, "token": token, "offer": offer}))
            except Exception as exc:
                self.jobs.put(("ev_cashout_offer_ready", {
                    "table_id": table_id, "token": token, "offer": None, "error": str(exc)}))
        threading.Thread(target=calculate_offer, daemon=True, name="PigeonEVCashoutOffer").start()
        try:
            dialog.grab_set()
            dialog.focus_force()
        except tk.TclError:
            pass

    def _auto_resolve_runout(self, table_id: str, token: str):
        dialog_state = self.cash_runout_dialogs.get(table_id)
        if dialog_state and dialog_state.get("token") == token:
            self._resolve_allin_decision(table_id, count=1)

    def _resolve_allin_decision(self, table_id: str, *, count: int = 1, cashout_offer=None):
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        previous_id = self.active_cash_table_id
        if previous_id != table_id:
            if previous_id and self.multi_tables.get(previous_id):
                self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
            slot = self.multi_tables.get(table_id)
        table = self.cash_table
        hand = table.hand if table else None
        if hand is None or hand.finished or not getattr(hand, "awaiting_runout_choice", False):
            self._close_allin_dialog(table_id)
            return
        self._close_allin_dialog(table_id)
        try:
            if cashout_offer is not None:
                hand.accept_ev_cashout(int(cashout_offer.payout))
                self.cash_log_lines.append(
                    f"EV CASHOUT • {cashout_offer.equity:.1%} equity • "
                    f"-{self._format_table_chips(cashout_offer.fee, hand.big_blind)} fee")
            else:
                selected = max(1, min(3, int(count)))
                hand.resolve_allin_runout(selected)
                self.cash_log_lines.append(f"RUN IT {selected}×")
            table.sync_external_hand_state()
            slot.state["cash_busy"] = False
            self.cash_busy = False
            if table_id == self.active_cash_table_id:
                # All boards are now final. Draw the runout rows together; no
                # stale one-board flip job may overwrite the additional boards.
                self.cash_board_target = list(hand.board)
                self.cash_visible_board = list(hand.board)
                self.cash_board_reveal_count = len(hand.board)
                self.cash_board_anim_indices = []
                self.cash_board_anim_index = None
                self.cash_board_anim_progress = 1.0
                self._draw_table()
                self._refresh_table_windows()
                self._update_cash_after_action()
            self._save_active_cash_slot()
        except Exception as exc:
            slot.state["cash_busy"] = False
            self.cash_busy = False
            messagebox.showerror("All-in decision", str(exc))
            if table_id == self.active_cash_table_id:
                self._refresh_table_windows()
        finally:
            if previous_id and previous_id != table_id and self.multi_tables.get(previous_id):
                self._restore_cash_slot(previous_id)

    def _close_allin_dialog(self, table_id: str):
        state = self.cash_runout_dialogs.pop(table_id, None)
        if not state:
            return
        try:
            if state.get("auto_job"):
                state["window"].after_cancel(state["auto_job"])
        except tk.TclError:
            pass
        try:
            state["window"].grab_release()
            state["window"].destroy()
        except tk.TclError:
            pass

    @staticmethod
    def _rotate_card_points(points, angle_degrees, center_x, center_y):
        import math
        angle = math.radians(float(angle_degrees))
        cosine, sine = math.cos(angle), math.sin(angle)
        rotated = []
        for x, y in points:
            dx, dy = float(x) - center_x, float(y) - center_y
            rotated.append((center_x + dx*cosine - dy*sine,
                            center_y + dx*sine + dy*cosine))
        return rotated

    def _draw_history_cards_icon(self, canvas: tk.Canvas):
        """Draw two real overlapping playing cards, rotated 10 degrees left."""
        canvas.delete("all")
        canvas.create_rectangle(0, 0, 40, 34, fill="#080e19", outline="")
        def card(x, y, rank, suit, foreground, front=False):
            width, height = 17.0, 24.0
            points = self._rotate_card_points(
                [(x, y), (x+width, y), (x+width, y+height), (x, y+height)],
                -10.0, x+width/2, y+height/2)
            flattened = [coordinate for point in points for coordinate in point]
            canvas.create_polygon(*flattened, fill="#ffffff", outline="#05080d",
                                  width=1.35, joinstyle="round")
            if front:
                canvas.create_text(x+4.5, y+6.2, text=rank, fill=foreground,
                                   font=("Georgia", 7, "bold"))
                canvas.create_text(x+4.5, y+12.2, text=suit, fill=foreground,
                                   font=("Segoe UI Symbol", 7, "bold"))
                canvas.create_text(x+12.2, y+20.0, text=suit, fill=foreground,
                                   font=("Segoe UI Symbol", 5, "bold"))
        card(15, 2, "K", "♠", "#111111", False)
        card(5, 5, "A", "♠", "#111111", True)
        canvas.create_rectangle(0, 0, 40, 34, outline="#080e19", width=1)

    def _draw_range_grid_icon(self, canvas: tk.Canvas, *, enabled: bool):
        canvas.delete("all")
        canvas.create_rectangle(0, 0, 34, 34, fill="#080e19", outline="")
        color = "#ffffff" if enabled else "#586575"
        canvas.create_rectangle(6, 5, 28, 29, outline=color, width=1.5)
        canvas.create_line(6, 10, 28, 10, fill=color, width=1.4)
        canvas.create_line(13.3, 10, 13.3, 29, fill=color, width=1.1)
        canvas.create_line(20.6, 10, 20.6, 29, fill=color, width=1.1)
        canvas.create_line(6, 16.3, 28, 16.3, fill=color, width=1.1)
        canvas.create_line(6, 22.6, 28, 22.6, fill=color, width=1.1)
        canvas.create_line(11, 3, 11, 7, fill=color, width=1.8)
        canvas.create_line(23, 3, 23, 7, fill=color, width=1.8)

    def _range_chart_for_table(self, slot, hand):
        if hand is None or bool(getattr(hand, "finished", False)):
            return None
        if bool(slot.state.get("cash_busy", False)) or bool(slot.state.get("cash_deal_busy", False)):
            return None
        if bool(slot.state.get("cash_sitting_out", False)):
            return None
        if str(getattr(hand, "street", "")).lower() not in {"preflop", "pre"}:
            return None
        if str(getattr(hand, "next_to_act", "") or "") != "hero":
            return None
        try:
            return preflop_gto_range_for_situation(slot.state.get("cash_table"), hand, "hero")
        except Exception:
            return None

    def _refresh_live_range_icons(self):
        for table_id, record in list(getattr(self, "table_windows", {}).items()):
            try:
                slot = self.multi_tables.get(table_id)
                if slot is None:
                    continue
                table = slot.state.get("cash_table")
                hand = table.hand if table is not None else None
                self._update_range_icon_state(slot, record, hand)
            except Exception:
                continue

    def _update_range_icon_state(self, slot, record, hand):
        canvas = record.get("range_icon")
        if canvas is None:
            return
        current_key = str(slot.state.get("cash_current_hand_key") or
                          (f"{slot.table_id}:{id(hand)}" if hand is not None else ""))
        signature = (
            id(hand) if hand is not None else None,
            len(getattr(hand, "events", ()) or ()) if hand is not None else 0,
            str(getattr(hand, "street", "")) if hand is not None else "",
            str(getattr(hand, "next_to_act", "")) if hand is not None else "",
            current_key,
        )
        paid = bool(current_key and slot.state.get("range_paid_hand_key") == current_key)
        if paid:
            # The same paid chart remains available through this hand even
            # after HERO acts or the board advances; reopening never charges again.
            chart = slot.state.get("range_paid_chart")
            record["range_chart_cache"] = chart
            record["range_chart_cache_key"] = signature
        else:
            if record.get("range_chart_cache_key") != signature:
                chart = self._range_chart_for_table(slot, hand)
                record["range_chart_cache"] = chart
                record["range_chart_cache_key"] = signature
            chart = record.get("range_chart_cache")
        # Use the already synchronized wallet cache during high-frequency table
        # refreshes. The click handler re-checks/debits SQLite atomically.
        balance = max(0, int(getattr(self, "cash_balance_cents", 0)))
        fee = int(getattr(hand, "big_blind", 0) or 0) if hand is not None else 0
        enabled = bool(chart and (paid or (fee > 0 and balance >= fee)))
        if record.get("range_icon_enabled") != enabled:
            self._draw_range_grid_icon(canvas, enabled=enabled)
            record["range_icon_enabled"] = enabled
        # Keep the icon clickable even when no exact chart is available.
        # The click handler explains the reason and never charges without a chart.
        try:
            canvas.configure(state="normal", cursor="hand2")
        except tk.TclError:
            pass
        record["range_paid_for_current_hand"] = paid
        record["range_current_hand_key"] = current_key

    def _debit_live_range_review(self, amount_cents: int, table_id: str, hand_key: str) -> bool:
        """Atomically debit the shared Wallet balance, never the poker stack."""
        import sqlite3
        amount = int(amount_cents)
        if amount <= 0:
            return False
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db_path = self.wallet_store.db_path
        with sqlite3.connect(str(db_path), timeout=20, isolation_level=None) as con:
            con.execute("PRAGMA busy_timeout=20000")
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT balance_cents FROM wallet_account WHERE account_id=1"
            ).fetchone()
            if row is None or int(row[0]) < amount:
                con.execute("ROLLBACK")
                return False
            before = int(row[0])
            after = before - amount
            txid = uuid.uuid4().hex
            con.execute(
                "UPDATE wallet_account SET balance_cents=?,updated_at=? WHERE account_id=1",
                (after, now),
            )
            con.execute(
                "INSERT INTO cashier_transactions "
                "(transaction_id,played_at,kind,delta_cents,balance_after_cents,recipient,note) "
                "VALUES(?,?,?,?,?,?,?)",
                (txid, now, "preflop-range-review", -amount, after, "",
                 f"Live preflop range review • table {table_id} • hand {hand_key}"),
            )
            con.execute("COMMIT")
        self.cash_balance_cents = after
        self._update_cash_balance()
        try:
            self._refresh_cashier()
        except Exception:
            pass
        return True

    def _open_realtime_preflop_range(self, table_id: str):
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table is not None else None
        hand_key = str(slot.state.get("cash_current_hand_key") or f"{table_id}:{id(hand)}")
        paid = str(slot.state.get("range_paid_hand_key") or "") == hand_key
        chart = slot.state.get("range_paid_chart") if paid else self._range_chart_for_table(slot, hand)
        if chart is None:
            self._update_range_icon_state(slot, self.table_windows.get(table_id, {}), hand)
            messagebox.showinfo(
                "Preflop range",
                "この状況に一致する画像由来レンジはありません。\n"
                "レンジ料金は発生していません。",
            )
            return
        if not paid:
            fee = int(getattr(hand, "big_blind", 0) or 0)
            if fee <= 0 or not self._debit_live_range_review(fee, table_id, hand_key):
                self._update_range_icon_state(slot, self.table_windows.get(table_id, {}), hand)
                messagebox.showwarning(
                    "Preflop range",
                    "ウォレット残高が不足しているか、料金を処理できませんでした。\n"
                    "テーブルスタックは変更していません。",
                )
                return
            slot.state["range_paid_hand_key"] = hand_key
            slot.state["range_paid_chart"] = chart
            try:
                if self.active_cash_table_id == table_id:
                    self._save_active_cash_slot()
            except Exception:
                pass
        record = self.table_windows.get(table_id)
        if record is not None:
            record["range_paid_for_current_hand"] = True
            self._update_range_icon_state(slot, record, hand)
        self._open_preflop_range_view(
            chart,
            title="LIVE PREFLOP RANGE",
            charge_label=("1 BB paid for this hand • re-open free" if not paid
                          else "Already paid this hand • re-open free"),
            table_id=table_id,
        )

    def _open_live_hand_flow(self, table_id: str):
        """Open the GGPOKER-style hand-history list for this table session."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return

        win = tk.Toplevel(self)
        win.title(f"PIGEON POKER • HAND HISTORY • {slot.rate}")
        win.geometry("760x690")
        win.minsize(560, 440)
        win.configure(bg="#080e19")
        try:
            win.transient(self)
            win.lift()
        except tk.TclError:
            pass

        header = tk.Frame(win, bg="#080e19", padx=14, pady=10)
        header.pack(fill="x")
        tk.Label(
            header, text="HAND HISTORY", bg="#080e19", fg="#f2f6fc",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header, text=f"{slot.rate}  •  newest hands first",
            bg="#080e19", fg="#91a3b8", font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(3, 0))

        columns = tk.Frame(win, bg="#111c2e", padx=12, pady=7)
        columns.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(columns, text="HOLE CARDS", width=19, anchor="w",
                 bg="#111c2e", fg="#aebed0",
                 font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Label(columns, text="WINNER", anchor="w",
                 bg="#111c2e", fg="#aebed0",
                 font=("Segoe UI", 8, "bold")).pack(side="left", fill="x", expand=True)
        tk.Label(columns, text="POT", width=13, anchor="e",
                 bg="#111c2e", fg="#aebed0",
                 font=("Segoe UI", 8, "bold")).pack(side="right")

        body = tk.Frame(win, bg="#080e19")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        list_canvas = tk.Canvas(body, bg="#080e19", highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=list_canvas.yview)
        list_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        list_canvas.pack(side="left", fill="both", expand=True)
        rows_host = tk.Frame(list_canvas, bg="#080e19")
        rows_window = list_canvas.create_window((0, 0), window=rows_host, anchor="nw")
        rows_host.bind(
            "<Configure>",
            lambda _e: list_canvas.configure(scrollregion=list_canvas.bbox("all")),
        )
        list_canvas.bind(
            "<Configure>",
            lambda event: list_canvas.itemconfigure(rows_window, width=event.width),
        )
        state = {"after_id": None, "closed": False, "signature": None}

        def winner_text(record):
            winners = []
            for event in list(record.get("events", []) or []):
                if not isinstance(event, dict):
                    continue
                kind = str(event.get("type", ""))
                if kind == "pot_award":
                    winners.extend(str(name) for name in (event.get("winners", []) or []))
                elif kind == "hand_won_by_fold" and event.get("winner"):
                    winners.append(str(event.get("winner")))
            if not winners:
                winners = [
                    str(player.get("name") or player.get("id") or "Player")
                    for player in (record.get("players", []) or [])
                    if int(player.get("net", 0) or 0) > 0
                ]
            return ", ".join(dict.fromkeys(winners)) or "—"

        def open_detail(record, is_live=False):
            detail = tk.Toplevel(win)
            detail.title("HAND DETAILS")
            detail.geometry("560x560")
            detail.minsize(420, 360)
            detail.configure(bg="#080e19")
            title = (
                f"HAND #{record.get('hand_number', '—')}  •  "
                f"{record.get('table_rate', slot.rate)}  •  "
                f"POT ${int(record.get('pot', 0) or 0)/100:.2f}"
            )
            tk.Label(detail, text=title, bg="#080e19", fg="#f2f6fc",
                     font=("Segoe UI", 10, "bold"), padx=12, pady=10).pack(anchor="w")
            hero_cards = str(record.get("hero_cards", "") or "—")
            board = str(record.get("board", "") or "—")
            tk.Label(
                detail, text=f"HOLE CARDS  {hero_cards}     BOARD  {board}",
                bg="#080e19", fg="#e6bd63", font=("Segoe UI", 9, "bold"),
                padx=12, pady=4,
            ).pack(anchor="w")
            flow = tk.Text(
                detail, bg="#0b1624", fg="#eaf1f9", insertbackground="#fff",
                relief="flat", wrap="word", font=("Consolas", 9), padx=10, pady=8,
            )
            flow.pack(fill="both", expand=True, padx=10, pady=8)
            names = {
                str(player.get("id") or ""): str(player.get("name") or player.get("id") or "Player")
                for player in (record.get("players", []) or [])
            }
            lines = []
            for event in list(record.get("events", []) or []):
                if not isinstance(event, dict):
                    continue
                kind = str(event.get("type", "action"))
                if kind == "street":
                    lines.append(f"\n── {str(event.get('street', '')).upper()} ──")
                    if event.get("board"):
                        lines.append("BOARD  " + " ".join(event.get("board") or []))
                elif kind == "action":
                    actor_id = str(event.get("player_id") or "")
                    actor = str(event.get("player") or names.get(actor_id, actor_id or "Player"))
                    if actor_id == "hero" or actor.casefold() in {"you", "hero"}:
                        actor = "YOU"
                    action = str(event.get("action", "")).upper().replace("_", " ")
                    target = event.get("target")
                    amount = f"  ${int(target)/100:.2f}" if target not in (None, "", 0) else ""
                    lines.append(f"{actor:<14} {action}{amount}")
                elif kind == "pot_award":
                    lines.append(
                        f"POT ${int(event.get('amount', 0) or 0)/100:.2f} → "
                        + ", ".join(event.get("winners", []) or [])
                    )
                elif kind == "hand_won_by_fold":
                    lines.append(
                        f"{event.get('winner', 'Player')} won by fold "
                        f"(${int(event.get('amount', 0) or 0)/100:.2f})"
                    )
            flow.insert("end", "\n".join(lines) or "No recorded actions.")
            flow.configure(state="disabled")
            if not is_live and record.get("events"):
                ttk.Button(
                    detail, text="▶  REPLAY HAND", style="Accent.TButton",
                    command=lambda row=record: (
                        setattr(self, "selected_history_record", row),
                        self._open_pokercraft_replay(),
                    ),
                ).pack(anchor="e", padx=12, pady=(0, 10))

        def render():
            if state["closed"] or not win.winfo_exists():
                return
            try:
                records = [
                    dict(row) for row in self.history_store.list_recent(5000)
                    if str(row.get("table_id") or "") == str(table_id)
                ]
            except Exception:
                records = []
            records.sort(
                key=lambda row: (str(row.get("played_at", "")), int(row.get("hand_number", 0) or 0)),
                reverse=True,
            )
            active_slot = self.multi_tables.get(table_id)
            active_table = active_slot.state.get("cash_table") if active_slot else None
            active_hand = active_table.hand if active_table is not None else None
            live_record = None
            if active_hand is not None and not bool(getattr(active_hand, "finished", False)):
                hero = next((player for player in active_hand.players if player.player_id == "hero"), None)
                live_record = {
                    "hand_number": getattr(active_hand, "hand_number", "—"),
                    "table_rate": slot.rate,
                    "hero_cards": " ".join(getattr(hero, "hole_cards", ()) or ()) if hero else "",
                    "board": " ".join(active_slot.state.get("cash_visible_board", []) or []),
                    "pot": int(getattr(active_hand, "pot", 0) or 0),
                    "players": [
                        {"id": player.player_id, "name": player.name,
                         "net": 0, "hole_cards": list(getattr(player, "hole_cards", ()) or [])}
                        for player in active_hand.players
                    ],
                    "events": list(getattr(active_hand, "events", []) or []),
                }
            items = ([live_record] if live_record is not None else []) + records
            signature = (
                tuple(str(row.get("hand_key") or row.get("hand_number") or id(row)) for row in items),
                len(getattr(active_hand, "events", []) or []) if active_hand is not None else 0,
            )
            if signature != state["signature"]:
                state["signature"] = signature
                for child in rows_host.winfo_children():
                    child.destroy()
                if not items:
                    tk.Label(
                        rows_host, text="No completed hands for this table yet.",
                        bg="#080e19", fg="#91a3b8", font=("Segoe UI", 10),
                        padx=14, pady=24,
                    ).pack(fill="x")
                for index, record in enumerate(items):
                    is_live = record is live_record
                    row_frame = tk.Frame(
                        rows_host, bg="#132033" if index % 2 == 0 else "#0e1928",
                        padx=10, pady=6,
                    )
                    row_frame.pack(fill="x", pady=1)
                    cards = str(record.get("hero_cards", "") or "").replace(",", " ").split()
                    card_canvas = tk.Canvas(
                        row_frame, width=92, height=54,
                        bg=row_frame.cget("bg"), highlightthickness=0, bd=0,
                    )
                    card_canvas.pack(side="left", padx=(0, 10))
                    if cards:
                        for card_index, card in enumerate(cards[:2]):
                            self._draw_card(
                                card_canvas, 3 + card_index * 39, 3, card,
                                width=34, height=48,
                            )
                    else:
                        card_canvas.create_text(
                            46, 27, text="—", fill="#91a3b8",
                            font=("Segoe UI", 11, "bold"),
                        )
                    winner = "LIVE" if is_live else winner_text(record)
                    winner_label = tk.Label(
                        row_frame, text=winner, bg=row_frame.cget("bg"),
                        fg="#f2f6fc", font=("Segoe UI", 9, "bold"),
                        anchor="w",
                    )
                    winner_label.pack(side="left", fill="x", expand=True)
                    pot = int(record.get("pot", 0) or 0)
                    pot_label = tk.Label(
                        row_frame, text=f"${pot/100:.2f}", width=11,
                        bg=row_frame.cget("bg"), fg="#e6bd63",
                        font=("Segoe UI", 10, "bold"), anchor="e",
                    )
                    pot_label.pack(side="right", padx=(8, 2))
                    open_row = lambda _e, row=record, live=is_live: open_detail(row, live)
                    for widget in (row_frame, card_canvas, winner_label, pot_label):
                        widget.bind("<Button-1>", open_row)
                        widget.bind("<Double-Button-1>", open_row)
            state["after_id"] = win.after(1800, render)

        def close():
            state["closed"] = True
            if state.get("after_id"):
                try:
                    win.after_cancel(state["after_id"])
                except tk.TclError:
                    pass
            try:
                win.destroy()
            except tk.TclError:
                pass

        win.protocol("WM_DELETE_WINDOW", close)
        render()
    def _create_table_window(self, table_id: str):
        """Create a compact, self-contained Rush & Cash table window."""
        if table_id in self.table_windows:
            return self.table_windows[table_id]["window"]
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return None

        window = tk.Toplevel(self)
        window.title(f"Pigeon Poker • {table_mode_label(slot.state.get('cash_game_mode'))} • {slot.rate}")
        screen_w, screen_h = window.winfo_screenwidth(), window.winfo_screenheight()
        # Reserve a visible strip above the Windows taskbar. A tall status
        # section below the felt used to push the action dock into the taskbar.
        width = max(760, min(1280, screen_w - 60))
        height = max(470, min(860, screen_h - 110))
        x = max(0, (screen_w - width) // 2)
        # Keep the table near the top while preserving a generous taskbar gap.
        y = max(12, min(60, (screen_h - height - 60) // 2))
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.minsize(760, 470)
        window.configure(bg=COLORS["bg"])

        # Compact top bar: table identity, turn state and wallet only.
        header = tk.Frame(window, bg="#080e19", height=38)
        header.pack(fill="x")
        header.pack_propagate(False)
        title_var = tk.StringVar(value=f"{table_mode_label(slot.state.get('cash_game_mode'))}  •  {slot.rate}")
        status_var = tk.StringVar(value="Waiting for hand")
        timer_var = tk.StringVar(value="")
        detail_var = tk.StringVar(value="HAND #1  •  PREFLOP  •  STACK $0.00")
        event_var = tk.StringVar(value="Cards will be dealt here • waiting for the first hand")
        wallet_var = tk.StringVar(value=f"WALLET  ${self.cash_balance_cents/100:,.2f}")
        tk.Label(header, text="PIGEON", bg="#080e19", fg=COLORS["text"],
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=(10, 1))
        tk.Label(header, text="POKER", bg="#080e19", fg=COLORS["green"],
                 font=("Segoe UI", 12, "bold")).pack(side="left")
        history_icon = tk.Canvas(header, width=40, height=34, bg="#080e19",
                                 highlightthickness=0, bd=0, cursor="hand2")
        history_icon.pack(side="left", padx=(9, 2))
        self._draw_history_cards_icon(history_icon)
        history_icon.bind("<Button-1>", lambda _e, tid=table_id: self._open_live_hand_flow(tid))
        range_icon = tk.Canvas(header, width=34, height=34, bg="#080e19",
                               highlightthickness=0, bd=0, cursor="hand2")
        range_icon.pack(side="left", padx=(1, 7))
        self._draw_range_grid_icon(range_icon, enabled=False)
        range_icon.configure(state="normal", cursor="hand2")
        range_icon.bind("<Button-1>", lambda _e, tid=table_id: self._open_realtime_preflop_range(tid))
        tk.Label(header, textvariable=title_var, bg="#080e19", fg=COLORS["gold"],
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=12)
        tk.Label(header, textvariable=status_var, bg="#080e19", fg=COLORS["text"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=4)
        event_label = tk.Label(header, textvariable=event_var, bg="#080e19", fg="#9fc6b7",
                               font=("Segoe UI", 8), anchor="w", width=34)
        event_label.pack(side="left", padx=(8, 2), fill="x", expand=True)
        timer_label = tk.Label(header, textvariable=timer_var, bg="#080e19", fg="#f6d982",
                               font=("Segoe UI", 10, "bold"), width=12, anchor="e")
        timer_label.pack_forget()  # The actionable clock is drawn beside HERO's hole cards.
        tk.Label(header, textvariable=wallet_var, bg="#080e19", fg=COLORS["green"],
                 font=("Segoe UI", 9, "bold")).pack(side="right", padx=10)
        self._compact_action_button(header, "LOBBY", lambda: (self.deiconify(), self.lift()), "normal").pack(side="right", padx=3)
        self._compact_action_button(header, "テーブル退出", lambda tid=table_id: self._leave_floating_table(tid), "danger").pack(side="right", padx=3)

        table_area = tk.Frame(window, bg=COLORS["bg"])
        table_area.pack(fill="both", expand=True, padx=4, pady=(2, 1))
        canvas = tk.Canvas(table_area, bg="#0a1220", highlightthickness=0,
                           cursor="arrow", bd=0)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Configure>", lambda _e, tid=table_id: self._redraw_floating_table(tid))
        canvas.bind("<Motion>", lambda event, tid=table_id: self._table_pointer_motion(tid, event))
        canvas.bind("<ButtonPress-1>", lambda event, tid=table_id: self._table_pointer_press(tid, event))
        canvas.bind("<ButtonRelease-1>", lambda event, tid=table_id: self._table_pointer_release(tid, event))
        # The old two-line HAND # / YOUR CARDS strip duplicated information
        # already visible on the felt and stole vertical space from the table.
        # Keep the StringVars internally for status diagnostics, but render
        # neither strip below the canvas.

        # Compact action dock. Utility toggles remain visible at all times.
        # Line 1: Fold / Check / Call / one contextual Bet-Raise-All-in submit button.
        # Line 2: slider + amount field + four pot-size buttons (selection only).
        action_outer = tk.Frame(window, bg=COLORS["panel"],
                                highlightbackground=COLORS["border"], highlightthickness=1)
        action_outer.pack(fill="x", padx=6, pady=(0, 5))
        actions = tk.Frame(action_outer, bg=COLORS["panel"])
        actions.pack(fill="x", padx=5, pady=(3, 1))
        fold_button = self._compact_action_button(
            actions, "FOLD",
            lambda tid=table_id: self._handle_table_fold(tid), "danger")
        fold_button.pack_forget()
        size_actions = tk.Frame(action_outer, bg=COLORS["panel"])
        size_actions.pack(fill="x", padx=5, pady=(0, 2))
        size_actions.configure(height=48)
        size_actions.pack_propagate(False)
        # Dedicated row keeps the situation-size control visible even when the
        # slider, amount entry and pot presets consume the full width.
        situation_actions = tk.Frame(action_outer, bg=COLORS["panel"])
        situation_actions.pack(fill="x", padx=5, pady=(0, 2))
        situation_actions.configure(height=30)
        situation_actions.pack_propagate(False)
        utility_actions = tk.Frame(action_outer, bg=COLORS["panel"])
        utility_actions.pack(fill="x", padx=6, pady=(1, 4))
        quick_leave_button = self._compact_action_button(
            utility_actions, "テーブル退出",
            lambda tid=table_id: self._leave_floating_table(tid), "danger")
        quick_leave_button.pack(side="left", padx=(1, 8))
        sitout_button = self._compact_action_button(
            utility_actions, "一時離席",
            lambda tid=table_id: self._request_table_sitout(tid), "normal")
        sitout_button.pack(side="left", padx=(0, 8))
        rabbit_hunt_button = self._compact_action_button(
            utility_actions, "RABBIT HUNT",
            lambda tid=table_id: self._show_rabbit_hunt(tid), "normal")
        rabbit_hunt_button.pack_forget()
        auto_rebuy_check = tk.Checkbutton(
            utility_actions, text="常に補充", variable=self.cash_auto_rebuy_var,
            command=self._save_auto_rebuy, bg=COLORS["panel"], fg=COLORS["muted"],
            activebackground=COLORS["panel"], activeforeground=COLORS["text"],
            selectcolor="#0b1727", font=("Segoe UI", 8), bd=0, padx=4,
            cursor="hand2")
        auto_rebuy_check.pack(side="left", padx=(1, 12))
        sitout_before_bb_var = tk.BooleanVar(value=bool(slot.state.get("cash_sitout_before_bb", False)))
        sitout_check = tk.Checkbutton(
            utility_actions, text="次のBB前に一時離席", variable=sitout_before_bb_var,
            command=lambda tid=table_id, var=sitout_before_bb_var:
                self._toggle_sitout_before_bb_for_table(tid, var),
            bg=COLORS["panel"], fg=COLORS["muted"],
            activebackground=COLORS["panel"], activeforeground=COLORS["text"],
            selectcolor="#0b1727", font=("Segoe UI", 8), bd=0, padx=4,
            cursor="hand2")
        sitout_check.pack(side="left")
        auto_fold_gto_size_button = self._compact_action_button(
            utility_actions, "AUTO-FOLD RANGE",
            lambda tid=table_id: self._open_auto_fold_chart(tid), "normal")
        auto_fold_gto_size_button.pack(side="left", padx=(10, 5))
        run_it_button = self._compact_action_button(
            utility_actions, "RUN IT: ASK",
            lambda tid=table_id: self._cycle_run_it_preference(tid), "normal")
        run_it_button.pack(side="left", padx=(0, 5))
        social_button = self._compact_action_button(
            utility_actions, "REACTIONS",
            lambda tid=table_id: self._open_social_reactions(tid), "normal")
        social_button.pack(side="left", padx=(0, 5))
        celebrate_button = self._compact_action_button(
            utility_actions, "CELEBRATE",
            lambda tid=table_id: self._trigger_big_pot_celebration(tid), "accent")
        celebrate_button.pack_forget()
        timebank_actions = tk.Frame(action_outer, bg=COLORS["panel"])
        timebank_actions.pack(fill="x", padx=6, pady=(0, 3))
        timebank_button = self._compact_action_button(
            timebank_actions, "TIME BANK CARD +30s",
            lambda tid=table_id: self._toggle_free_timebank(tid), "normal")
        timebank_button.pack(side="left", padx=(1, 5))
        paid_timebank_button = self._compact_action_button(
            timebank_actions, "BUY +30s • 1BB",
            lambda tid=table_id: self._toggle_paid_timebank(tid), "normal")
        paid_timebank_button.pack(side="left", padx=(1, 8))
        postflop_auto_fold_var = tk.BooleanVar(value=bool(slot.state.get("postflop_auto_fold", False)))
        postflop_auto_fold_check = tk.Checkbutton(
            timebank_actions, text="POSTFLOP AUTO-FOLD", variable=postflop_auto_fold_var,
            command=lambda tid=table_id, var=postflop_auto_fold_var:
                self._set_postflop_auto_fold(tid, bool(var.get())),
            bg=COLORS["panel"], fg=COLORS["gold"], activebackground=COLORS["panel"],
            activeforeground=COLORS["text"], selectcolor="#0b1727",
            font=("Segoe UI", 8, "bold"), bd=0, padx=5, cursor="hand2")
        bet_target_var = tk.StringVar(value="")
        bet_target_cents_var = tk.IntVar(value=0)
        bet_slider_var = tk.IntVar(value=0)
        record = {
            "window": window, "title": title_var, "status": status_var,
            "timer": timer_var, "timer_label": timer_label,
            "detail": detail_var, "event": event_var,
            "wallet": wallet_var, "canvas": canvas, "event_label": event_label,
            "history_icon": history_icon, "range_icon": range_icon,
            "range_chart_cache": None, "range_chart_cache_key": None,
            "actions": actions, "size_actions": size_actions,
            "situation_actions": situation_actions, "utility_actions": utility_actions,
            "fold_button": fold_button,
            "timebank_actions": timebank_actions,
            "quick_leave_button": quick_leave_button, "sitout_button": sitout_button,
            "rabbit_hunt_button": rabbit_hunt_button,
            "auto_fold_gto_size_button": auto_fold_gto_size_button,
            "run_it_button": run_it_button,
            "social_button": social_button, "celebrate_button": celebrate_button,
            "auto_rebuy_check": auto_rebuy_check, "sitout_check": sitout_check,
            "sitout_before_bb_var": sitout_before_bb_var,
            "timebank_button": timebank_button, "paid_timebank_button": paid_timebank_button,
            "timer_canvas_item": None,
            "postflop_auto_fold_var": postflop_auto_fold_var,
            "postflop_auto_fold_check": postflop_auto_fold_check,
            "bet_target": bet_target_var, "bet_target_cents": bet_target_cents_var,
            "bet_slider": bet_slider_var, "bet_action_button": None,
            "gto_size_button": None,
            "bet_min": 0, "bet_max": 0, "bet_verb": "bet", "bet_bb": 1,
            "bet_unit_label": None, "syncing_bet": False,
            "pot_animation": None, "pot_animation_key": None, "pot_animation_job": None,
        }
        self.table_windows[table_id] = record
        window.bind("<Return>", lambda _e, tid=table_id: self._submit_table_bet_enter(tid), add="+")
        window.bind("<KP_Enter>", lambda _e, tid=table_id: self._submit_table_bet_enter(tid), add="+")
        # Also bind the amount entry directly; Tk's Entry class may consume Return.
        for child in size_actions.winfo_children():
            child.bind("<Return>", lambda _e, tid=table_id: self._submit_table_bet_enter(tid), add="+")
        window.protocol("WM_DELETE_WINDOW", lambda tid=table_id: self._leave_floating_table(tid))
        self._redraw_floating_table(table_id)
        self._refresh_table_windows()
        return window

    def _describe_action(self, actor: str, action: str, amount: int | None, big_blind: int) -> str:
        key = str(action).lower().replace("_", "-")
        if key == "fold":
            verb = "folds"
        elif key == "check":
            verb = "checks"
        elif key in {"call", "all-in-call"}:
            verb = "calls"
        elif key == "bet":
            verb = "bets"
        elif key == "raise":
            verb = "raises to"
        elif key in {"all-in", "allin"}:
            verb = "is ALL-IN"
        else:
            verb = key.upper()
        if amount is not None and key in {"bet", "raise", "call", "all-in", "all-in-call"}:
            return f"{actor} {verb} {self._format_table_chips(int(amount), big_blind)}"
        return f"{actor} {verb}"

    def _toggle_table_chip_unit(self, table_id: str):
        """Clicking the BB/USD suffix beside YOU's stack toggles all table amounts."""
        self.chip_display_unit = "BB" if self.chip_display_unit == "USD" else "USD"
        self.config_data["chip_display_unit"] = self.chip_display_unit
        if hasattr(self, "chip_display_unit_var"):
            self.chip_display_unit_var.set(self.chip_display_unit)
        save_config(self.config_data)
        self._refresh_table_windows()
        return "break"

    def _submit_table_bet_enter(self, table_id: str):
        record = self.table_windows.get(table_id)
        if not record or not record.get("bet_action_button"):
            return "break"
        try:
            button = record["bet_action_button"]
            if str(button.cget("state")) != "disabled":
                button.invoke()
        except tk.TclError:
            pass
        return "break"

    def _set_cash_action_flash(self, table_id: str, player_id: str, action: str,
                               amount: int | None = None, *, actor_name: str | None = None):
        """Show a short action plaque beside the acting seat, synchronized to the event."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table else None
        if hand is None:
            return
        player = next((item for item in hand.players if item.player_id == player_id), None)
        name = actor_name or (player.name if player else ("YOU" if player_id == "hero" else player_id))
        amount_label = self._format_table_chips(int(amount), hand.big_blind) if amount is not None else None
        badge = action_badge(action, amount, amount_label)
        flash = {"player_id": str(player_id), "actor": str(name), "text": badge,
                 "expires_at": time.monotonic() + ACTION_BADGE_MS / 1000.0,
                 "token": uuid.uuid4().hex}
        slot.state["cash_action_flash"] = flash
        token = flash["token"]
        if table_id == self.active_cash_table_id:
            self._save_active_cash_slot()
        self._redraw_floating_table(table_id)
        self.after(ACTION_BADGE_MS, lambda tid=table_id, key=token: self._expire_cash_action_flash(tid, key))

    def _expire_cash_action_flash(self, table_id: str, token: str):
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        flash = slot.state.get("cash_action_flash") or {}
        if flash.get("token") != token:
            return
        slot.state["cash_action_flash"] = None
        self._redraw_floating_table(table_id)

    def _animate_action_chips(self, table_id: str, player_id: str):
        """Fly denomination-accurate chip stacks to the pot on curved paths."""
        record = self.table_windows.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not record or not slot:
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table else None
        if hand is None:
            return
        player = next((item for item in hand.players if item.player_id == player_id), None)
        if player is None:
            return
        # Animate only the chips committed by this action, not the player's
        # cumulative street contribution (which would visually double-count a
        # prior call when the same player later raises).
        action_paid = action_paid_cents(hand.events, player_id)
        if action_paid <= 0:
            return
        breakdown = decompose_cents(action_paid, int(table.big_blind))
        if not breakdown["counts"]:
            return
        canvas = record["canvas"]
        w, h = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        actor_index = next((i for i, p in enumerate(hand.players) if p.player_id == player_id), None)
        hero_index = next((i for i, p in enumerate(hand.players) if p.player_id == "hero"), 0)
        if actor_index is None:
            return
        seats = [(w*.50, h*.84), (w*.205, h*.69), (w*.205, h*.29),
                 (w*.50, h*.125), (w*.795, h*.29), (w*.795, h*.69)]
        if len(hand.players) == 2:
            seats = [(w*.50, h*.83), (w*.50, h*.15)]
        source = seats[(actor_index-hero_index) % len(hand.players)]
        start = (source[0], source[1] + (34 if source[1] < h*.5 else -25))
        target = (w*.50, h*.37)
        specs = [(d, count) for d, count in breakdown["counts"].items() if count]
        gap = 27.0
        total_width = (len(specs)-1)*gap
        groups = []
        for idx, (denomination, count) in enumerate(specs):
            ox = -total_width/2 + idx*gap
            tag = f"action_chip_flight_{uuid.uuid4().hex}_{idx}"
            x, y = start[0]+ox, start[1]
            draw_chip_stack(canvas, x, y, denomination, count, scale=.64,
                            tags=("chip_flight", tag), max_visible_layers=7, show_count=True)
            groups.append((tag, ox, idx))

        started = time.monotonic()
        duration = CHIP_TO_POT_MS / 1000.0
        completed = {"value": False}
        slide_cue = {"played": False}

        def frame():
            if not self.table_windows.get(table_id):
                return
            try:
                progress = min(1.0, max(0.0, (time.monotonic() - started) / duration))
                if progress >= .12 and not slide_cue["played"]:
                    slide_cue["played"] = True
                    self._play_sound("chip_slide")
                for tag, ox, order in groups:
                    local = max(0.0, min(1.0, (progress-order*.045)/.955))
                    lane = ox * (1.0 - .28*local)
                    sx, sy = start[0] + ox, start[1]
                    ex, ey = target[0] + ox*.24, target[1]
                    desired_x, desired_y = chip_flight_position(
                        (sx, sy), (ex, ey), local, lane=lane,
                        arc_height=min(42.0, math.hypot(ex-sx, ey-sy)*.085))
                    previous = record.setdefault("chip_flight_positions", {}).get(tag, (sx, sy))
                    canvas.move(tag, desired_x-previous[0], desired_y-previous[1])
                    desired_scale = chip_flight_scale(local)
                    scales = record.setdefault("chip_flight_scales", {})
                    previous_scale = float(scales.get(tag, 1.0))
                    if hasattr(canvas, "scale") and abs(desired_scale-previous_scale) > .0005:
                        ratio = desired_scale / max(.01, previous_scale)
                        bounds = canvas.bbox(tag) if hasattr(canvas, "bbox") else None
                        if bounds:
                            scale_cx = (bounds[0] + bounds[2]) / 2.0
                            scale_cy = (bounds[1] + bounds[3]) / 2.0
                        else:
                            scale_cx, scale_cy = desired_x, desired_y
                        canvas.scale(tag, scale_cx, scale_cy, ratio, ratio)
                    scales[tag] = desired_scale
                    record["chip_flight_positions"][tag] = (desired_x, desired_y)
                if progress < 1.0:
                    canvas.after(16, frame)
                else:
                    canvas.delete("chip_flight")
                    for tag, *_ in groups:
                        record.get("chip_flight_positions", {}).pop(tag, None)
                        record.get("chip_flight_scales", {}).pop(tag, None)
                    if not completed["value"]:
                        completed["value"] = True
                        self._play_sound("chip_settle")
            except tk.TclError:
                return
        frame()

    def _begin_deal_animation(self, table_id: str | None):
        """Deal each private card seat-by-seat with quick movement and a per-card sound."""
        if not table_id:
            self.cash_deal_busy=False
            self.cash_busy=False
            self._start_cash_cpu_chain_if_needed()
            return
        slot=self.multi_tables.get(table_id)
        if not slot:
            return
        table=slot.state.get("cash_table")
        hand=table.hand if table else None
        if hand is None:
            self._release_deal_lock(table_id)
            return
        # Deal one complete round clockwise from the SB (the button in heads-up),
        # then deal the second round in the same order.  This was previously tied
        # to list index zero and could make the visual deal disagree with the button.
        sequence = [
            item for item in hole_card_deal_sequence(
                [player.player_id for player in hand.players], table.dealer_index
            )
            if len(next((p.hole_cards for p in hand.players if p.player_id == item[0]), ())) > item[1]
        ]
        slot.state["cash_deal_busy"]=True
        slot.state["cash_busy"]=True
        if table_id==self.active_cash_table_id:
            self.cash_deal_busy=True
        slot.state["cash_deal_counts"]={p.player_id:0 for p in hand.players}
        slot.state["cash_deal_flying"]=None
        if table_id==self.active_cash_table_id:
            self.cash_busy=True
            self.cash_deal_counts=dict(slot.state["cash_deal_counts"])
            self.cash_deal_flying=None
        self.deal_animation_jobs[table_id]={"sequence":sequence,"cursor":0,"frame":0,"current":None,"after_id":None}
        self._redraw_floating_table(table_id)
        self.deal_animation_jobs[table_id]["after_id"] = self.after(1, lambda tid=table_id: self._deal_animation_tick(tid))

    def _deal_animation_tick(self, table_id: str):
        job=self.deal_animation_jobs.get(table_id)
        slot=self.multi_tables.get(table_id)
        if not job or not slot:
            self.deal_animation_jobs.pop(table_id,None)
            return
        table=slot.state.get("cash_table")
        hand=table.hand if table else None
        if hand is None:
            self.deal_animation_jobs.pop(table_id,None)
            self._release_deal_lock(table_id)
            return
        if job["cursor"] >= len(job["sequence"]):
            self.deal_animation_jobs.pop(table_id,None)
            slot.state["cash_deal_flying"]=None
            slot.state["cash_deal_busy"]=True
            slot.state["cash_action_feed"]="Your cards are on the table • move the cursor across each card to peel"
            if table_id==self.active_cash_table_id:
                self.cash_deal_flying=None
                self.cash_action_feed=slot.state["cash_action_feed"]
                self._save_active_cash_slot()
            self._redraw_floating_table(table_id)
            # Card Squeeze has been removed; reveal the two hole cards normally.
            self._begin_initial_hole_flip(table_id)
            return
        pid,card_index=job["sequence"][job["cursor"]]
        job["current"]={"player_id":pid,"card_index":card_index}
        job["frame"]=0
        slot.state["cash_deal_flying"]={"player_id":pid,"card_index":card_index,"progress":0.0}
        if table_id==self.active_cash_table_id:
            self.cash_deal_flying=dict(slot.state["cash_deal_flying"])
        self._play_sound("deal")
        self._deal_animation_frame(table_id)

    def _deal_animation_frame(self, table_id: str):
        job=self.deal_animation_jobs.get(table_id)
        slot=self.multi_tables.get(table_id)
        if not job or not slot:
            return
        job["after_id"] = None
        job["frame"]+=1
        progress=min(1.0,job["frame"]/2.0)
        current=job["current"] or {}
        slot.state["cash_deal_flying"]={**current,"progress":progress}
        if table_id==self.active_cash_table_id:
            self.cash_deal_flying=dict(slot.state["cash_deal_flying"])
        self._redraw_floating_table(table_id)
        if job["frame"]<2:
            job["after_id"] = self.after(1, lambda tid=table_id: self._deal_animation_frame(tid))
            return
        counts=slot.state.setdefault("cash_deal_counts",{})
        counts[current["player_id"]]=max(int(counts.get(current["player_id"],0)),int(current["card_index"])+1)
        self._play_sound("card_land")
        slot.state["cash_deal_flying"]=None
        if table_id==self.active_cash_table_id:
            self.cash_deal_counts=dict(counts)
            self.cash_deal_flying=None
            self._save_active_cash_slot()
        job["cursor"]+=1
        self._redraw_floating_table(table_id)
        job["after_id"] = self.after(1, lambda tid=table_id: self._deal_animation_tick(tid))

    def _begin_initial_hole_flip(self, table_id: str):
        """After both backs have landed, pause briefly and turn both hero cards face up."""
        slot = self.multi_tables.get(table_id)
        if not slot:
            return
        flip = {"active": True, "complete": False, "index": 0, "progress": 0.0}
        slot.state["cash_initial_flip"] = flip
        if table_id == self.active_cash_table_id:
            self.cash_initial_flip = dict(flip)
            self._save_active_cash_slot()
        self._redraw_floating_table(table_id)
        # One deliberate beat after the second card lands, as requested.
        self.hole_flip_jobs[table_id] = self.after(
            max(1, HOLE_REVEAL_PAUSE_MS // 4), lambda tid=table_id: self._initial_hole_flip_frame(tid))

    def _initial_hole_flip_frame(self, table_id: str):
        self.hole_flip_jobs.pop(table_id, None)
        slot = self.multi_tables.get(table_id)
        if not slot:
            self.hole_flip_jobs.pop(table_id, None)
            return
        hand = slot.state.get("cash_table").hand if slot.state.get("cash_table") else None
        if hand is None or hand.finished:
            self.hole_flip_jobs.pop(table_id, None)
            self._release_deal_lock(table_id)
            return
        flip = slot.state.setdefault("cash_initial_flip", {
            "active": True, "complete": False, "index": 0, "progress": 0.0
        })
        if flip.get("complete"):
            self.hole_flip_jobs.pop(table_id, None)
            return
        index = int(flip.get("index", 0))
        progress = float(flip.get("progress", 0.0))
        if progress <= 0.0:
            self._play_sound("card_swoosh")
        progress = min(1.0, progress + 0.5)
        flip["active"] = True
        flip["index"] = index
        flip["progress"] = progress
        if table_id == self.active_cash_table_id:
            self.cash_initial_flip = dict(flip)
        self._redraw_floating_table(table_id)
        if progress < 1.0:
            self.hole_flip_jobs[table_id] = self.after(
                1, lambda tid=table_id: self._initial_hole_flip_frame(tid))
            return
        if index == 0:
            flip["index"] = 1
            flip["progress"] = 0.0
            if table_id == self.active_cash_table_id:
                self.cash_initial_flip = dict(flip)
            self.hole_flip_jobs[table_id] = self.after(
                HOLE_REVEAL_CARD_GAP_MS, lambda tid=table_id: self._initial_hole_flip_frame(tid))
            return
        flip["active"] = False
        flip["complete"] = True
        flip["progress"] = 1.0
        slot.state["hero_squeeze_count"] = 2
        if table_id == self.active_cash_table_id:
            self.cash_initial_flip = dict(flip)
            self.hero_squeeze_count = 2
            self._save_active_cash_slot()
        self._redraw_floating_table(table_id)
        self._release_deal_lock(table_id)

    def _open_squeeze_popup(self, table_id: str):
        """Show two overlapping cards being physically flexed upward from their near edge."""
        slot = self.multi_tables.get(table_id)
        record = self.table_windows.get(table_id)
        if not slot or not record:
            self._release_deal_lock(table_id)
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table else None
        if hand is None:
            self._release_deal_lock(table_id)
            return
        hero = hand.player("hero")
        if len(hero.hole_cards) != 2 or hero.folded:
            self._release_deal_lock(table_id)
            return

        popup = tk.Toplevel(record["window"])
        popup.title("Card Squeeze")
        popup.configure(bg="#090b0d")
        popup.resizable(False, False)
        popup.transient(record["window"])
        # Premium close-up: two angled, overlapping cards; no hand illustration.
        # The dimensions leave a little breathing room around the tilted card edges.
        cw, canvas_h, footer_h = 690, 440, 50
        ch = canvas_h + footer_h
        popup.update_idletasks()
        parent = record["window"]
        px = parent.winfo_rootx() + max(8, (parent.winfo_width() - cw) // 2)
        py = parent.winfo_rooty() + max(8, (parent.winfo_height() - ch) // 2)
        popup.geometry(f"{cw}x{ch}+{px}+{py}")
        popup.attributes("-topmost", True)
        canvas = tk.Canvas(popup, width=cw, height=canvas_h, bg="#101214",
                           highlightthickness=0, bd=0, cursor="hand2")
        canvas.pack(side="top", fill="both", expand=False)
        footer = tk.Frame(popup, bg="#111417", height=footer_h)
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, text="伏せたカードの手前端を上へなぞって、しならせる",
                 bg="#111417", fg="#e6e0d3",
                 font=("Segoe UI", 8)).pack(side="left", padx=14)
        open_button = tk.Button(
            footer, text="OPEN", command=lambda tid=table_id:
            self._complete_squeeze_popup(tid, reveal_all=True),
            bg="#bd9d62", fg="#151719", activebackground="#dfc28a",
            activeforeground="#151719", relief="flat", bd=0,
            padx=18, pady=4, font=("Segoe UI", 9, "bold"), cursor="hand2")
        open_button.pack(side="right", padx=12, pady=5)
        card_width, card_height = 178, 246
        poses = squeeze_card_pair_layout(cw, card_width, top=86, overlap=.42,
                                         vertical_stagger=12, back_tilt=-7, front_tilt=6)
        state = {
            "window": popup, "canvas": canvas, "open_button": open_button,
            # One pointer sweep drives BOTH cards together. There is no
            # active-card/index state and no first-card/second-card sequence.
            "progress": [0.0, 0.0], "shared_progress": 0.0,
            "sweep_started": False, "sweep_anchor_y": None,
            "cards": list(hero.hole_cards), "table_id": table_id,
            "complete": False,
            "card_lefts": [pose[0] for pose in poses],
            "card_tops": [pose[1] for pose in poses],
            "card_tilts": [pose[2] for pose in poses],
            "card_width": card_width, "card_height": card_height,
            "swoosh_played": False, "land_played": False,
        }
        self.squeeze_popups[table_id] = state
        popup.protocol("WM_DELETE_WINDOW", lambda tid=table_id: self._complete_squeeze_popup(tid, reveal_all=True))
        canvas.bind("<Motion>", lambda event, tid=table_id: self._squeeze_popup_motion(tid, event))
        canvas.bind("<B1-Motion>", lambda event, tid=table_id: self._squeeze_popup_motion(tid, event))
        canvas.bind("<Enter>", lambda _e, c=canvas: c.configure(cursor="hand2"))
        self._draw_squeeze_popup(table_id)
        popup.lift()
        popup.focus_force()

    def _card_suit_ink(self, rank: str, suit: str) -> str:
        """Use a navy Spade and green Club even in a traditional two-colour deck."""
        suit = str(suit).lower()
        if suit == "s":
            return "#263f78"
        if suit == "c":
            return "#16814b"
        return card_face_color(str(rank) + suit, bool(self.appearance.get("four_color_deck", False)))

    def _draw_card_3d(self, canvas, x, y, value, width=52, height=70,
                      progress=1.0, tilt=0.0, tag="card_3d"):
        """Software-render a thin 3D card mesh with perspective, bevel and a Y-axis flip.

        `progress=0` shows the back; `progress=1` shows the face.  The card is
        a real 3D cuboid mesh projected through a perspective camera rather
        than a pre-skewed 2D rectangle.  It stays dependency-free for Windows.
        """
        from math import cos, sin, pi

        progress = max(0.0, min(1.0, float(progress)))
        angle = pi * (1.0 - progress)
        roll = float(tilt) * pi / 180.0
        focal = max(420.0, float(height) * 3.5)
        thickness = max(1.3, min(3.2, width * .025))
        cx, cy = x + width / 2.0, y + height / 2.0

        def project(u: float, v: float, z: float):
            lx = (u - .5) * width
            ly = (v - .5) * height
            # Rotate the card about its vertical axis, then add a slight roll.
            rx = lx * cos(angle) + z * sin(angle)
            rz = -lx * sin(angle) + z * cos(angle)
            px = rx * cos(roll) - ly * sin(roll)
            py = rx * sin(roll) + ly * cos(roll)
            scale = focal / max(80.0, focal + rz)
            return cx + px * scale, cy + py * scale

        def flat(points):
            return [coord for point in points for coord in point]

        front_z, back_z = thickness / 2.0, -thickness / 2.0
        front = [project(0, 0, front_z), project(1, 0, front_z),
                 project(1, 1, front_z), project(0, 1, front_z)]
        back = [project(0, 0, back_z), project(1, 0, back_z),
                project(1, 1, back_z), project(0, 1, back_z)]

        # The shadow and four side walls remain visible while the card turns.
        shadow = [(px + 5, py + 7) for px, py in (front if progress >= .5 else back)]
        canvas.create_polygon(*flat(shadow), fill="#03110d", outline="",
                              tags=(tag, "card_3d_shadow"))
        edge_colors = ("#f2e8d4", "#bca77f", "#e6dac0", "#aa956d")
        for i in range(4):
            j = (i + 1) % 4
            quad = [front[i], front[j], back[j], back[i]]
            canvas.create_polygon(*flat(quad), fill=edge_colors[i],
                                  outline="#927d59", width=1,
                                  tags=(tag, "card_3d_edge"))

        show_front = progress >= .5
        surface_z = front_z if show_front else back_z
        quad = front if show_front else back
        if show_front:
            face_fill, face_edge, face_inner, court_panel = card_face_palette(
                self.appearance.get("card_face_theme", "Classic"))
            canvas.create_polygon(*flat(quad), fill=face_fill,
                                  outline=face_edge, width=2,
                                  tags=(tag, "card_3d_face"))
            inner = [project(.025, .018, surface_z), project(.975, .018, surface_z),
                     project(.975, .982, surface_z), project(.025, .982, surface_z)]
            canvas.create_polygon(*flat(inner), fill="", outline=face_inner,
                                  width=1, tags=(tag, "card_3d_face"))

            code = str(value).strip()
            if code[:2].upper() == "10":
                rank, suit = "T", code[2].lower() if len(code) > 2 else "s"
            else:
                rank = code[0].upper() if code else "A"
                suit = code[1].lower() if len(code) > 1 else "s"
            suit_map = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
            symbol = suit_map.get(suit, "♠")
            rank_text = {"T": "10"}.get(rank, rank)
            color = self._card_suit_ink(rank, suit)

            def point(u, v):
                return project(u, v, surface_z)

            def text_at(u, v, text, size, *, angle=0, font="Georgia"):
                px, py = point(u, v)
                canvas.create_text(px, py, text=text, fill=color, angle=angle,
                                   font=(font, max(7, int(size)), "bold"),
                                   anchor="center", tags=(tag, "card_3d_face"))

            corner = max(8, int(width * .18))
            suit_size = max(7, int(width * .15))
            text_at(.12, .12, rank_text, corner)
            text_at(.13, .235, symbol, suit_size, font="Segoe UI Symbol")
            text_at(.88, .88, rank_text, corner, angle=180)
            text_at(.87, .765, symbol, suit_size, angle=180, font="Segoe UI Symbol")
            rank_value = 10 if rank == "T" else (int(rank) if rank.isdigit() else 0)
            if rank in {"J", "Q", "K"}:
                outline = [point(.25, .20), point(.75, .20), point(.80, .80), point(.20, .80)]
                canvas.create_polygon(*flat(outline), fill=court_panel,
                                      outline="#c8aa70", width=2,
                                      tags=(tag, "card_3d_face"))
                p0, p1 = point(.27, .50), point(.73, .50)
                canvas.create_line(*p0, *p1, fill="#ba9b61", width=2,
                                   tags=(tag, "card_3d_face"))
                for v in (.34, .66):
                    px, py = point(.50, v)
                    r = width * .10
                    canvas.create_oval(px-r, py-r, px+r, py+r,
                                       fill="#e4b996", outline="#9e785b",
                                       tags=(tag, "card_3d_face"))
                    text_at(.50, .34 if v < .5 else .66, symbol,
                            max(10, width * .14), font="Segoe UI Symbol")
                text_at(.50, .50, rank, max(13, width * .20))
            elif rank == "A":
                text_at(.50, .51, symbol, max(24, width * .42), font="Segoe UI Symbol")
            else:
                pip_patterns = {
                    2: [(0,.27),(0,.73)],
                    3: [(0,.22),(0,.50),(0,.78)],
                    4: [(-.18,.24),(.18,.24),(-.18,.76),(.18,.76)],
                    5: [(-.18,.24),(.18,.24),(0,.50),(-.18,.76),(.18,.76)],
                    6: [(-.18,.19),(.18,.19),(-.18,.50),(.18,.50),(-.18,.81),(.18,.81)],
                    7: [(-.18,.18),(.18,.18),(0,.34),(-.18,.50),(.18,.50),(-.18,.82),(.18,.82)],
                    8: [(-.18,.17),(.18,.17),(-.18,.39),(.18,.39),(-.18,.61),(.18,.61),(-.18,.83),(.18,.83)],
                    9: [(-.18,.15),(.18,.15),(-.18,.33),(.18,.33),(0,.50),(-.18,.67),(.18,.67),(-.18,.85),(.18,.85)],
                    10:[(-.18,.14),(.18,.14),(-.18,.32),(.18,.32),(-.18,.50),(.18,.50),(-.18,.68),(.18,.68),(-.18,.86),(.18,.86)],
                }
                for dx, v in pip_patterns.get(rank_value, pip_patterns[10]):
                    text_at(.50 + dx, v, symbol, max(12, width * .16),
                            angle=180 if v > .5 else 0, font="Segoe UI Symbol")
        else:
            back_name = str(self.appearance.get("card_back_theme", "Blue"))
            back_fill, back_line = CARD_BACK_THEMES.get(back_name, CARD_BACK_THEMES["Blue"])
            canvas.create_polygon(*flat(quad), fill=back_fill,
                                  outline="#d7b76e", width=2,
                                  tags=(tag, "card_3d_back"))
            inset = [project(.07, .055, surface_z), project(.93, .055, surface_z),
                     project(.93, .945, surface_z), project(.07, .945, surface_z)]
            canvas.create_polygon(*flat(inset), fill="", outline=back_line,
                                  width=2, tags=(tag, "card_3d_back"))
            for u in (.18, .34, .50, .66, .82):
                for v in (.18, .34, .50, .66, .82):
                    points = [project(u, v-.035, surface_z),
                              project(u+.035, v, surface_z),
                              project(u, v+.035, surface_z),
                              project(u-.035, v, surface_z)]
                    canvas.create_polygon(*flat(points), fill="",
                                          outline=back_line, width=1,
                                          tags=(tag, "card_3d_back"))

    def _draw_squeeze_card_perspective(self, canvas, x, y, value, width, height,
                                       progress=0.0, tilt=0):
        """Render a flexible hole card as a curved 3D sheet, not a flat mask.

        The cursor sweep raises the near edge.  The full sheet bends in both
        directions, passes naturally through an edge-on angle, then turns its
        face toward the player.  Mesh strips carry the back/face artwork along
        the same geometry, keeping the bend continuous from edge to edge.
        """
        from math import cos, sin, pi

        p = max(0.0, min(1.0, float(progress)))
        back_name = str(self.appearance.get("card_back_theme", "Blue"))
        back_fill, back_line = CARD_BACK_THEMES.get(back_name, CARD_BACK_THEMES["Blue"])
        face_fill, face_edge, face_inner, court_panel = card_face_palette(
            self.appearance.get("card_face_theme", "Classic"))

        def point(u, v, offset_y=0.0):
            px, py, depth, face, local_p = squeeze_card_surface_point(
                x, y, width, height, p, u, v, tilt)
            return px, py + offset_y, depth, face, local_p

        def xy(points):
            return [coord for point_ in points for coord in point_[:2]]

        # Projected shadow follows the same bowed silhouette, offset like a card
        # lifted a few millimetres above the felt.
        shadow = ([point(i/20, 0, 7) for i in range(21)] +
                  [point(1, i/20, 7) for i in range(21)] +
                  [point(1-i/20, 1, 7) for i in range(21)] +
                  [point(0, 1-i/20, 7) for i in range(21)])
        canvas.create_polygon(*xy(shadow), fill="#03090a", outline="",
                              tags=("squeeze_card", "squeeze_bow_shadow"))

        # A 2D mesh (x and y subdivisions) keeps the card's surface visibly curved.
        cols, rows = 12, 24
        for row in range(rows):
            v0, v1 = row / rows, (row + 1) / rows
            for col in range(cols):
                u0, u1 = col / cols, (col + 1) / cols
                quad = [point(u0, v0), point(u1, v0),
                        point(u1, v1), point(u0, v1)]
                front_votes = sum(1 for vertex in quad if vertex[3])
                edge_phase = any(.43 <= vertex[4] <= .57 for vertex in quad)
                if edge_phase:
                    fill = "#e5d8bf" if row % 2 else "#c9b894"
                    outline = "#8d7650"
                elif front_votes >= 2:
                    # The front face appears row-by-row from the lifted edge.
                    fill = face_fill
                    outline = ""
                else:
                    fill = back_fill
                    outline = ""
                canvas.create_polygon(*xy(quad), fill=fill, outline=outline,
                                      width=1 if outline else 0,
                                      tags=("squeeze_card", "squeeze_surface_mesh"))

        # Card silhouette and edge thickness.
        perimeter = ([point(i/40, 0) for i in range(41)] +
                     [point(1, i/40) for i in range(41)] +
                     [point(1-i/40, 1) for i in range(41)] +
                     [point(0, 1-i/40) for i in range(41)])
        canvas.create_line(*xy(perimeter), fill=face_edge, width=2.3,
                           smooth=True, tags=("squeeze_card", "squeeze_surface_edge"))
        left_edge = [point(0, i/32) for i in range(33)]
        right_edge = [point(1, i/32) for i in range(33)]
        for edge in (left_edge, right_edge):
            canvas.create_line(*xy(edge), fill="#fff0d2", width=1.2, smooth=True,
                               tags=("squeeze_card", "squeeze_surface_bevel"))

        # The back pattern remains only on rows that still face away from the
        # player. It disappears naturally behind the travelling curl line.
        for u in (.16, .33, .50, .67, .84):
            for v in (.15, .32, .50, .68, .85):
                if not point(u, v)[3]:
                    ru, rv = .022, .018
                    diamond = [point(u, v-rv), point(u+ru, v),
                               point(u, v+rv), point(u-ru, v)]
                    canvas.create_polygon(*xy(diamond), fill="", outline=back_line,
                                          width=1, tags=("squeeze_card", "squeeze_back_pattern"))

        rank, suit = str(value)[0], (str(value)[1].lower() if len(str(value)) > 1 else "s")
        suit_map = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
        symbol = suit_map.get(suit, "♠")
        rank_text = {"T": "10"}.get(rank, rank)
        ink = self._card_suit_ink(rank, suit)
        # The index is on the near corner, so it becomes visible early in the
        # sweep. The large centre pip follows later as the curl reaches it.
        rank_pt = point(.14, .86)
        suit_pt = point(.15, .73)
        center_pt = point(.52, .51)
        text_angle = float(tilt)
        if rank_pt[3]:
            canvas.create_text(rank_pt[0], rank_pt[1], text=rank_text, fill=ink,
                               font=("Georgia", max(13, int(width*.15)), "bold"),
                               angle=text_angle, tags=("squeeze_card", "squeeze_face_mark"))
        if suit_pt[3]:
            canvas.create_text(suit_pt[0], suit_pt[1], text=symbol, fill=ink,
                               font=("Segoe UI Symbol", max(13, int(width*.13)), "bold"),
                               angle=text_angle, tags=("squeeze_card", "squeeze_face_mark"))
        if center_pt[3]:
            canvas.create_text(center_pt[0], center_pt[1], text=symbol, fill=ink,
                               font=("Segoe UI Symbol", max(24, int(width*.36)), "bold"),
                               angle=text_angle, tags=("squeeze_card", "squeeze_face_mark"))

        # A long, soft specular highlight moves across the bowed plastic as it lifts.
        for ridge_v, ridge_color, ridge_width in ((.38, face_inner, 1.0),
                                                    (.50, "#fff7e8", 2.2),
                                                    (.62, face_inner, 1.0)):
            ridge = [point(i/40, ridge_v) for i in range(41)]
            canvas.create_line(*xy(ridge), fill=ridge_color, width=ridge_width,
                               smooth=True, tags=("squeeze_card", "squeeze_bend_ridge"))

    def _draw_squeeze_popup(self, table_id: str):
        state = self.squeeze_popups.get(table_id)
        if not state:
            return
        canvas = state["canvas"]
        canvas.delete("all")
        # Premium graphite mat with the restrained red piping shown in the
        # reference photo, while keeping the same premium card-table palette.
        canvas.create_rectangle(0, 0, 690, 440, fill="#090b0d", outline="")
        canvas.create_oval(8, 4, 682, 436, fill="#292c2f", outline="#8d2632", width=5)
        canvas.create_oval(16, 12, 674, 428, fill="#111518", outline="#b13c48", width=2)
        canvas.create_oval(24, 20, 666, 420, fill="#171c1f", outline="#343b3e", width=2)
        # Very low-contrast textile grain, clipped mathematically to the inner
        # felt oval so no stray stitches appear beyond the table rail.
        from math import sqrt
        felt_cx, felt_cy, felt_rx, felt_ry = 345.0, 220.0, 309.0, 188.0
        for yy in range(42, 414, 13):
            norm_y = (yy - felt_cy) / felt_ry
            remain = 1.0 - norm_y * norm_y
            if remain <= 0.0:
                continue
            half_span = felt_rx * sqrt(remain)
            x0 = int(felt_cx - half_span + 10)
            x1 = int(felt_cx + half_span - 10)
            shift = 7 if (yy // 13) % 2 else 0
            for xx in range(x0 + shift, x1, 18):
                canvas.create_line(xx, yy, xx + 4, yy + 1,
                                   fill="#22292c", width=1)
        canvas.create_oval(170, 54, 520, 385, fill="#1a2022", outline="#30383a", width=1)
        canvas.create_text(345, 30, text="CARD SQUEEZE", fill="#e6d3aa",
                           font=("Georgia", 15, "bold"))
        canvas.create_text(345, 54, text="伏せたカードの手前端を上へなぞって、しならせる",
                           fill="#c8c4b9", font=("Segoe UI", 9))

        lefts = state["card_lefts"]
        tops = state["card_tops"]
        tilts = state["card_tilts"]
        card_w = state["card_width"]
        card_h = state["card_height"]
        progress_values = state["progress"]
        # Rear card first, front card second: same angled overlap as the photo.
        for idx, card in enumerate(state["cards"]):
            x, top = lefts[idx], tops[idx]
            progress = float(progress_values[idx])
            self._draw_squeeze_card_perspective(
                canvas, x, top, card, card_w, card_h, progress, tilt=tilts[idx])
        if min(progress_values) >= .995:
            footer_copy = "YOUR HAND IS READY"
            footer_color = "#d7eee0"
        else:
            footer_copy = "2枚を重ねたまま、手前の下端から上へなぞる"
            footer_color = "#e3d4b2"
        canvas.create_text(345, 418, text=footer_copy, fill=footer_color,
                           font=("Segoe UI", 8, "bold"))

    def _squeeze_popup_motion(self, table_id: str, event):
        """Reveal both overlapping hole cards together with one bottom-to-top sweep."""
        state = self.squeeze_popups.get(table_id)
        if not state or state.get("complete"):
            return
        lefts = [float(value) for value in state["card_lefts"]]
        tops = [float(value) for value in state["card_tops"]]
        card_w = float(state["card_width"])
        card_h = float(state["card_height"])
        x, y = float(event.x), float(event.y)
        group_left = min(lefts) - 8.0
        group_right = max(left + card_w for left in lefts) + 8.0
        group_top = min(tops)
        group_bottom = max(top + card_h for top in tops)
        group_height = max(1.0, group_bottom - group_top)
        if not (group_left <= x <= group_right and group_top - 8 <= y <= group_bottom + 10):
            return

        if not state.get("sweep_started", False):
            # Start at the shared near edge of the two-card packet.
            # No press is required: simply enter at the lower edge and sweep up.
            if y < group_bottom - group_height * .13:
                return
            state["sweep_started"] = True
            state["sweep_anchor_y"] = min(group_bottom, max(group_bottom - group_height * .08, y))
            if not state.get("swoosh_played", False):
                self._play_sound("card_peel")
                state["swoosh_played"] = True

        anchor = state.get("sweep_anchor_y")
        if anchor is None or y > float(anchor) + 2.0:
            return
        new_value = squeeze_card_sweep_progress(float(anchor), y, group_top, group_height)
        old_value = float(state.get("shared_progress", 0.0))
        if new_value <= old_value + .001:
            return

        # Critical behaviour: the exact same progress is applied to both cards.
        # They flex and reveal simultaneously, maintaining the angled overlap.
        new_value = min(1.0, max(old_value, new_value))
        state["shared_progress"] = new_value
        state["progress"] = [new_value, new_value]
        self._draw_squeeze_popup(table_id)

        if new_value >= .995:
            state["shared_progress"] = 1.0
            state["progress"] = [1.0, 1.0]
            if not state.get("land_played", False):
                self._play_sound("card_land")
                state["land_played"] = True
            slot = self.multi_tables.get(table_id)
            if slot:
                slot.state["hero_squeeze_count"] = 2
                if table_id == self.active_cash_table_id:
                    self.hero_squeeze_count = 2
                    self._save_active_cash_slot()
                self._redraw_floating_table(table_id)
                self._ensure_squeeze_action_deadline(table_id)
            state["complete"] = True
            self._draw_squeeze_popup(table_id)
            self.after(260, lambda tid=table_id: self._complete_squeeze_popup(tid, reveal_all=False))

    def _complete_squeeze_popup(self, table_id: str, reveal_all: bool = False):
        state = self.squeeze_popups.pop(table_id, None)
        self._cancel_squeeze_action_deadline(table_id)
        release_deal_lock = True
        if state:
            release_deal_lock = not bool(state.get("deal_lock_released", False))
            if reveal_all:
                slot = self.multi_tables.get(table_id)
                if slot:
                    slot.state["hero_squeeze_count"] = 2
                    if table_id == self.active_cash_table_id:
                        self.hero_squeeze_count = 2
            try:
                state["window"].destroy()
            except tk.TclError:
                pass
        self._redraw_floating_table(table_id)
        if reveal_all:
            self._play_sound("card_swoosh")
            self._ensure_squeeze_action_deadline(table_id)
        if release_deal_lock:
            self._release_deal_lock(table_id)

    def _activate_table_for_control(self, table_id: str):
        if table_id == self.active_cash_table_id:
            return True
        if self.cash_busy:
            return False
        self._save_active_cash_slot()
        try:
            self._restore_cash_slot(table_id)
            return True
        except KeyError:
            return False

    def _sync_timebank_controls(self, table_id: str):
        slot = self.multi_tables.get(table_id)
        record = self.table_windows.get(table_id)
        if slot is None or record is None:
            return
        state = normalize_table_pause_state(slot.state)
        remaining = int(state.get("cash_timebank_cards_remaining", 0))
        armed = bool(state.get("cash_timebank_armed", False))
        paid_armed = bool(state.get("cash_timebank_paid_armed", False))
        paid_used = bool(state.get("cash_timebank_paid_used_this_hand", False))
        table = state.get("cash_table")
        hero = table.hand.player("hero") if table and table.hand else None
        bb = max(1, int(getattr(table, "big_blind", self.cash_bb or 1)))
        can_pay = bool(hero and int(hero.stack) >= bb)
        try:
            record["timebank_button"].configure(
                text=(f"FREE CARD SELECTED ✓" if armed else f"TIME BANK CARD ×{remaining} • +30s"),
                state=("normal" if remaining > 0 else "disabled"))
            if paid_used:
                paid_text, paid_state = "PAID CARD USED THIS HAND", "disabled"
            elif remaining > 0:
                paid_text, paid_state = "PAID +30s • 1BB (AFTER FREE)", "disabled"
            elif paid_armed:
                paid_text, paid_state = "PAID CARD SELECTED ✓", "normal"
            else:
                paid_text, paid_state = "BUY PAID CARD • +30s / 1BB", ("normal" if can_pay else "disabled")
            record["paid_timebank_button"].configure(text=paid_text, state=paid_state)
        except (KeyError, tk.TclError):
            pass

    def _toggle_free_timebank(self, table_id: str):
        if not self._activate_table_for_control(table_id):
            return
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        if slot.state.get("cash_sitting_out"):
            return
        armed = arm_free_timebank(slot.state)
        self.cash_log_lines.append("FREE TIME BANK CARD +30s: armed" if armed else "FREE TIME BANK CARD: disarmed / unavailable")
        self._save_active_cash_slot()
        self._sync_timebank_controls(table_id)

    def _toggle_paid_timebank(self, table_id: str):
        if not self._activate_table_for_control(table_id):
            return
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        if slot.state.get("cash_sitting_out"):
            return
        remaining = int(slot.state.get("cash_timebank_cards_remaining", 0))
        armed = arm_paid_timebank(slot.state)
        if remaining > 0:
            self.cash_log_lines.append("PAID TIME BANK is available after all free cards are used")
        elif not armed and slot.state.get("cash_timebank_paid_used_this_hand"):
            self.cash_log_lines.append("PAID TIME BANK: already used this hand")
        else:
            self.cash_log_lines.append("PAID TIME BANK 30s / 1BB: selected" if armed else "PAID TIME BANK: selection cancelled")
        self._save_active_cash_slot()
        self._sync_timebank_controls(table_id)

    def _ensure_squeeze_action_deadline(self, table_id: str):
        """Start the local Rush shot clock; card squeezing happens inside this clock."""
        slot = self.multi_tables.get(table_id)
        if not slot:
            return
        state = normalize_table_pause_state(slot.state)
        table = state.get("cash_table")
        hand = table.hand if table else None
        if (hand is None or hand.finished or hand.next_to_act != "hero"
                or state.get("cash_sitting_out")
                or bool(state.get("cash_gto_spot_mode", False))):
            self._cancel_squeeze_action_deadline(table_id)
            return
        if table_id in self.squeeze_deadline_jobs:
            # Do not reset the clock when Card Squeeze opens/closes or when the
            # player refreshes the table window.
            return
        duration = action_seconds_for_street(hand.street)
        deadline = time.monotonic() + duration
        state["cash_squeeze_deadline_at"] = deadline
        state["cash_action_deadline_mode"] = "action"
        state["squeeze_warning_played"] = False
        if table_id == self.active_cash_table_id:
            self.cash_squeeze_deadline_at = deadline
            self.cash_action_deadline_mode = "action"
            self.cash_action_feed = f"YOUR ACTION • {int(duration)}s"
            self._save_active_cash_slot()
        token = id(hand)
        turn_key = (token, len(hand.events))
        if state.get("cash_last_turn_sound_key") != turn_key:
            state["cash_last_turn_sound_key"] = turn_key
            if table_id == self.active_cash_table_id:
                self.cash_last_turn_sound_key = turn_key
            self._play_sound("your_turn")
        self._update_action_timer_display(table_id, duration, "action")
        # The clock is a felt-side visual beside HERO's hole cards. Redraw once
        # after establishing the deadline so the first frame is visible now,
        # rather than waiting for a later board or status repaint.
        self._redraw_floating_table(table_id)
        self._sync_timebank_controls(table_id)
        self.squeeze_deadline_jobs[table_id] = self.after(
            200, lambda tid=table_id, hand_token=token: self._tick_squeeze_action_deadline(tid, hand_token))
        self._refresh_table_windows()

    def _tick_squeeze_action_deadline(self, table_id: str, hand_token: int):
        self.squeeze_deadline_jobs.pop(table_id, None)
        slot = self.multi_tables.get(table_id)
        if not slot:
            return
        state = slot.state
        table = state.get("cash_table")
        hand = table.hand if table else None
        if (hand is None or id(hand) != hand_token or hand.finished or hand.next_to_act != "hero"
                or state.get("cash_sitting_out")):
            self._cancel_squeeze_action_deadline(table_id)
            return
        mode = str(state.get("cash_action_deadline_mode", "action"))
        remaining = float(state.get("cash_squeeze_deadline_at", 0.0)) - time.monotonic()
        if remaining <= 0:
            self._expire_squeeze_action_deadline(table_id, hand_token)
            return
        seconds_left = int(remaining + .999)
        if table_id == self.active_cash_table_id:
            prefix = "TIME BANK" if mode.startswith("timebank") else "YOUR ACTION"
            self.cash_action_feed = f"{prefix} • {seconds_left}s"
        self._update_action_timer_display(table_id, remaining, mode)
        if remaining <= 5.0 and not state.get("squeeze_warning_played", False):
            state["squeeze_warning_played"] = True
            self._play_sound("action_warning")
        self.squeeze_deadline_jobs[table_id] = self.after(
            200, lambda tid=table_id, token=hand_token: self._tick_squeeze_action_deadline(tid, token))

    def _update_action_timer_display(self, table_id: str, remaining: float | None = None,
                                     mode: str = "action"):
        record = self.table_windows.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not record:
            return
        if remaining is None:
            deadline = float(slot.state.get("cash_squeeze_deadline_at", 0.0)) if slot else 0.0
            remaining = max(0.0, deadline - time.monotonic()) if deadline else 0.0
        seconds = max(0, int(remaining + .999))
        label = f"{seconds:02d}s" if remaining > 0 else ""
        colour = "#ff7777" if remaining <= 5 else ("#74dcae" if mode.startswith("timebank") else "#f6d982")
        try:
            record["timer"].set(("TIME BANK " if mode.startswith("timebank") else "ACTION ") + label if label else "")
            # The live clock is drawn beside HERO's hole cards. Update canvas
            # items in place; never rebuild the action dock every 200ms.
            items = record.get("timer_canvas_item")
            canvas = record.get("canvas")
            if items and canvas and canvas.winfo_exists():
                bg_items, text_item = items
                for item in bg_items:
                    canvas.itemconfigure(item, fill=("#4d2630" if remaining <= 5 else "#102d28"),
                                         outline=colour)
                canvas.itemconfigure(text_item, text=label, fill=colour)
            record["timer_label"].configure(fg=colour)
        except (KeyError, tk.TclError, TypeError):
            pass

    def _cancel_squeeze_action_deadline(self, table_id: str):
        pending = self.squeeze_deadline_jobs.pop(table_id, None)
        if pending:
            try:
                self.after_cancel(pending)
            except tk.TclError:
                pass
        slot = self.multi_tables.get(table_id)
        if slot:
            slot.state["cash_squeeze_deadline_at"] = 0.0
            slot.state["cash_action_deadline_mode"] = ""
        if table_id == self.active_cash_table_id:
            self.cash_squeeze_deadline_at = 0.0
            self.cash_action_deadline_mode = ""
        record = self.table_windows.get(table_id)
        if record:
            try:
                record["timer"].set("")
            except (KeyError, tk.TclError):
                pass

    def _expire_squeeze_action_deadline(self, table_id: str, hand_token: int):
        """At shot-clock expiry, consume an armed Time Bank Card before acting."""
        self.squeeze_deadline_jobs.pop(table_id, None)
        slot = self.multi_tables.get(table_id)
        if not slot:
            return
        state = normalize_table_pause_state(slot.state)
        table = state.get("cash_table")
        hand = table.hand if table else None
        if (hand is None or id(hand) != hand_token or hand.finished or hand.next_to_act != "hero"
                or state.get("cash_sitting_out")):
            self._cancel_squeeze_action_deadline(table_id)
            return
        previous_id = self.active_cash_table_id
        if previous_id != table_id:
            if previous_id and self.multi_tables.get(previous_id):
                self._save_active_cash_slot()
            self._restore_cash_slot(table_id)
        try:
            mode, _ = (str(state.get("cash_action_deadline_mode") or "action"), 0)
            self._cancel_squeeze_action_deadline(table_id)
            timebank = consume_armed_timebank(state, int(getattr(table, "big_blind", 1)))
            if timebank is not None:
                bank_kind, extra_seconds = timebank
                deadline = time.monotonic() + float(extra_seconds)
                state["cash_squeeze_deadline_at"] = deadline
                state["cash_action_deadline_mode"] = f"timebank_{bank_kind}"
                state["squeeze_warning_played"] = False
                if table_id == self.active_cash_table_id:
                    self.cash_squeeze_deadline_at = deadline
                    self.cash_action_deadline_mode = f"timebank_{bank_kind}"
                    self.cash_action_feed = f"TIME BANK CARD • +{int(extra_seconds)}s"
                    self.cash_log_lines.append(f"TIME BANK: +{int(extra_seconds)} seconds activated ({bank_kind})")
                    self._save_active_cash_slot()
                self._play_sound("timebank")
                self._update_action_timer_display(table_id, extra_seconds, f"timebank_{bank_kind}")
                self.squeeze_deadline_jobs[table_id] = self.after(
                    200, lambda tid=table_id, token=hand_token: self._tick_squeeze_action_deadline(tid, token))
                self._sync_timebank_controls(table_id)
                return

            # If a Card Squeeze is still closed when the action clock ends,
            # reveal it now. Squeeze never receives its own extra 25-second clock.
            hidden_cards = (self.card_squeeze_enabled_var.get()
                            and int(state.get("hero_squeeze_count", 0)) < 2)
            if hidden_cards:
                state["hero_squeeze_count"] = 2
                if table_id == self.active_cash_table_id:
                    self.hero_squeeze_count = 2
                popup = self.squeeze_popups.pop(table_id, None)
                if popup:
                    try:
                        popup["window"].destroy()
                    except tk.TclError:
                        pass
                self._redraw_floating_table(table_id)
                self._play_sound("card_swoosh")
                if mode == "squeeze":
                    # The time spent revealing hidden cards is presentation time,
                    # not the player's decision time. Start the real action clock
                    # after the automatic reveal instead of folding/checking them.
                    duration = action_seconds_for_street(hand.street)
                    deadline = time.monotonic() + float(duration)
                    state["cash_squeeze_deadline_at"] = deadline
                    state["cash_action_deadline_mode"] = "action"
                    state["squeeze_warning_played"] = False
                    state["cash_action_feed"] = f"CARDS AUTO-REVEALED • YOUR ACTION • {int(duration)}s"
                    if table_id == self.active_cash_table_id:
                        self.hero_squeeze_count = 2
                        self.cash_squeeze_deadline_at = deadline
                        self.cash_action_deadline_mode = "action"
                        self.cash_action_feed = state["cash_action_feed"]
                        self.cash_log_lines.append("CARD SQUEEZE TIMEOUT • AUTO-REVEAL • ACTION CLOCK RESET")
                        self._save_active_cash_slot()
                    self._update_action_timer_display(table_id, duration, "action")
                    self.squeeze_deadline_jobs[table_id] = self.after(
                        200, lambda tid=table_id, token=hand_token: self._tick_squeeze_action_deadline(tid, token))
                    self._sync_timebank_controls(table_id)
                    return

            legal = hand.legal_actions("hero")
            actions = set(legal.get("actions", []))
            if "check" in actions:
                action = "check"
                note = "ACTION TIMEOUT • CHECKED (CHECK WAS AVAILABLE)"
            else:
                action = "fold"
                note = "ACTION TIMEOUT • FOLDED (CHECK WAS NOT AVAILABLE)"
            self.cash_log_lines.append(note)
            self.cash_action_feed = note
            self._cash_human_action(action)
        finally:
            if previous_id and previous_id != table_id and self.multi_tables.get(previous_id):
                self._restore_cash_slot(previous_id)

    def _release_deal_lock(self, table_id: str):
        slot = self.multi_tables.get(table_id)
        if slot:
            slot.state["cash_deal_busy"] = False
            slot.state["cash_busy"] = False
        if table_id == self.active_cash_table_id:
            self.cash_deal_busy = False
            self.cash_busy = False
            self._save_active_cash_slot()
            self._refresh_table_windows()
            self._start_cash_cpu_chain_if_needed()
        else:
            self._refresh_table_windows()
            self._start_cash_cpu_chain_for_table(table_id)

    def _start_cash_cpu_chain_for_table(self, table_id: str):
        """Start a table's CPU worker without leaving another table focused."""
        if not table_id or not self.multi_tables.get(table_id):
            return
        if table_id == self.active_cash_table_id:
            self._start_cash_cpu_chain_if_needed()
            return
        previous_id = self.active_cash_table_id
        self._save_active_cash_slot()
        try:
            self._restore_cash_slot(table_id)
            self._start_cash_cpu_chain_if_needed()
            self._save_active_cash_slot()
        finally:
            if previous_id and self.multi_tables.get(previous_id):
                self._restore_cash_slot(previous_id)

    def _finish_human_board_animation(self, table_id: str | None = None):
        """Continue the hand state machine after the board animation completes."""
        table_id = table_id or self.active_cash_table_id
        if not table_id or not self.multi_tables.get(table_id):
            return
        previous_id = self.active_cash_table_id
        if previous_id != table_id:
            self._save_active_cash_slot()
            self._restore_cash_slot(table_id)
        try:
            self.cash_busy = False
            self._save_active_cash_slot()
            self._update_cash_after_action()
            self._save_active_cash_slot()
        finally:
            if previous_id and previous_id != table_id and self.multi_tables.get(previous_id):
                self._restore_cash_slot(previous_id)

    def _board_squeeze_start_index(self, hand, previous_board_count: int) -> int | None:
        """Return the first turn/river card eligible for GG-style board squeeze.

        GGPoker's published Hold'em/Rush & Cash condition is an all-in showdown
        with a pot strictly larger than 100 BB.  The flop is never squeezed;
        only unrevealed turn/river cards are candidates.
        """
        # Board/Card Squeeze is disabled; use the normal community-card reveal.
        return None
        if hand is None or not hand.finished or len(hand.board) != 5:
            return None
        if not any(player.all_in for player in hand.players):
            return None
        if int(hand.pot) <= int(hand.big_blind) * 100:
            return None
        start = max(3, int(previous_board_count))
        return start if start < 5 else None

    def _animate_board_reveal(self, table_id: str | None, target_board: list[str],
                              ready_event: threading.Event | None=None,
                              on_done: Callable[[], None] | None=None,
                              squeeze_start_index: int | None=None):
        """Reveal flop/turn/river cards one-by-one with a short flip and sound."""
        if not table_id or not self.multi_tables.get(table_id):
            if ready_event: ready_event.set()
            if on_done: on_done()
            return
        slot=self.multi_tables.get(table_id)
        state=slot.state
        previous_target=list(state.get("cash_board_target", []))
        current=int(state.get("cash_board_reveal_count",0))
        # Collect committed chips into the main pot once per new street.  Use a
        # hand/street key so a redraw or duplicate worker event cannot replay it.
        table_for_collect = state.get("cash_table")
        hand_for_collect = table_for_collect.hand if table_for_collect else None
        collect_key = (id(hand_for_collect), len(target_board)) if hand_for_collect else None
        if (collect_key and int(getattr(hand_for_collect, "pot", 0)) > 0
                and len(target_board) > len(previous_target)
                and state.get("cash_pot_collect_sound_key") != collect_key):
            state["cash_pot_collect_sound_key"] = collect_key
            self._play_sound("pot_collect")
        # Compare against the previous runout before replacing the target.
        if current>len(target_board) or previous_target[:current] != list(target_board)[:current]:
            current=0
        state["cash_board_target"]=list(target_board)
        if table_id==self.active_cash_table_id:
            self.cash_board_target=list(target_board)
        job={"target":list(target_board),"index":current,"frame":0,
             "ready_event":ready_event,"on_done":on_done,
             "squeeze_start_index": squeeze_start_index,
             "squeezed_cards": set(), "waiting_squeeze": False}
        self.board_animation_jobs[table_id]=job
        self._board_reveal_next(table_id)

    def _board_reveal_next(self, table_id: str):
        job = self.board_animation_jobs.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not job or not slot:
            if job and job.get("ready_event"):
                job["ready_event"].set()
            self.board_animation_jobs.pop(table_id, None)
            return
        target = job["target"]
        state = slot.state
        index = int(job["index"])

        # GG-style flop presentation: three cards arrive as one spread, with a
        # tiny stagger, one continuous card-slide sound, and one shared reveal.
        # Turn and river remain independent single-card events.
        if (index < 3 and len(target) >= 3 and not job.get("flop_group_done")):
            group_start = max(0, index)
            indices = list(range(group_start, 3))
            job["group_mode"] = "flop"
            job["active_indices"] = indices
            job["frame"] = 0
            state["cash_board_anim_indices"] = indices
            state["cash_board_anim_index"] = None
            state["cash_board_anim_progress"] = 0.0
            state["cash_board_reveal_count"] = group_start
            if table_id == self.active_cash_table_id:
                self.cash_board_anim_index = None
                self.cash_board_anim_progress = 0.0
                self.cash_board_reveal_count = group_start
            self._play_sound("card_swoosh")
            self._redraw_floating_table(table_id)
            self._board_reveal_frame(table_id)
            return

        squeeze_start = job.get("squeeze_start_index")
        if (squeeze_start is not None and index >= int(squeeze_start)
                and index < len(target)
                and index not in job.get("squeezed_cards", set())):
            if job.get("waiting_squeeze"):
                return
            job["waiting_squeeze"] = True
            job["group_mode"] = None
            state["cash_board_anim_indices"] = []
            state["cash_board_squeeze"] = {
                "active": True, "index": index, "progress": 0.0,
                "start_index": int(squeeze_start),
            }
            state["cash_board_anim_index"] = index
            state["cash_board_anim_progress"] = 0.0
            state["cash_board_reveal_count"] = index
            if table_id == self.active_cash_table_id:
                self.cash_board_squeeze = dict(state["cash_board_squeeze"])
                self.cash_board_anim_index = index
                self.cash_board_anim_progress = 0.0
                self.cash_board_reveal_count = index
            self._redraw_floating_table(table_id)
            if table_id in self.board_squeeze_auto_jobs:
                try:
                    self.after_cancel(self.board_squeeze_auto_jobs.pop(table_id))
                except tk.TclError:
                    pass
            self.board_squeeze_auto_jobs[table_id] = self.after(
                12000, lambda tid=table_id: self._auto_finish_board_squeeze(tid))
            return

        if index >= len(target):
            auto_job = self.board_squeeze_auto_jobs.pop(table_id, None)
            if auto_job:
                try:
                    self.after_cancel(auto_job)
                except tk.TclError:
                    pass
            state["cash_board_squeeze"] = None
            state["cash_board_anim_indices"] = []
            state["cash_board_reveal_count"] = len(target)
            state["cash_board_anim_index"] = None
            state["cash_board_anim_progress"] = 1.0
            state["cash_visible_board"] = list(target)
            if table_id == self.active_cash_table_id:
                self.cash_board_target = list(target)
                self.cash_visible_board = list(target)
                self.cash_board_reveal_count = len(target)
                self.cash_board_anim_index = None
                self.cash_board_anim_progress = 1.0
            self._redraw_floating_table(table_id)
            self.board_animation_jobs.pop(table_id, None)
            if job.get("ready_event"):
                job["ready_event"].set()
            callback = job.get("on_done")
            if callback:
                callback()
            return

        job["frame"] = 0
        job["group_mode"] = None
        state["cash_board_anim_indices"] = []
        state["cash_board_anim_index"] = index
        state["cash_board_anim_progress"] = 0.0
        if table_id == self.active_cash_table_id:
            self.cash_board_anim_index = index
            self.cash_board_anim_progress = 0.0
        # Turn and river each get their own independent slide/flick cue.
        if index in {3, 4}:
            self._play_sound("card_swoosh")
        self._redraw_floating_table(table_id)
        self._board_reveal_frame(table_id)

    def _board_reveal_frame(self, table_id: str):
        job = self.board_animation_jobs.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not job or not slot:
            return
        state = slot.state
        job["frame"] += 1
        group_mode = job.get("group_mode")
        if group_mode == "flop":
            progress = min(1.0, job["frame"] / float(FLOP_REVEAL_FRAMES))
            state["cash_board_anim_progress"] = progress
            if table_id == self.active_cash_table_id:
                self.cash_board_anim_progress = progress
            self._redraw_floating_table(table_id)
            if job["frame"] < FLOP_REVEAL_FRAMES:
                self.after(FLOP_REVEAL_FRAME_MS, lambda tid=table_id: self._board_reveal_frame(tid))
                return
            indices = list(job.get("active_indices", [0, 1, 2]))
            reveal_count = max(indices, default=-1) + 1
            state["cash_board_reveal_count"] = reveal_count
            state["cash_visible_board"] = list(job["target"][:reveal_count])
            state["cash_board_anim_indices"] = []
            state["cash_board_anim_index"] = None
            state["cash_board_anim_progress"] = 1.0
            job["index"] = reveal_count
            job["flop_group_done"] = True
            job["group_mode"] = None
            self._play_sound("card_land")
            if table_id == self.active_cash_table_id:
                self.cash_board_reveal_count = reveal_count
                self.cash_visible_board = list(state["cash_visible_board"])
                self.cash_board_anim_index = None
                self.cash_board_anim_progress = 1.0
            self._redraw_floating_table(table_id)
            self.after(STREET_BETWEEN_CARDS_MS, lambda tid=table_id: self._board_reveal_next(tid))
            return

        progress = min(1.0, job["frame"] / float(STREET_REVEAL_FRAMES))
        state["cash_board_anim_progress"] = progress
        if table_id == self.active_cash_table_id:
            self.cash_board_anim_progress = progress
            self.cash_board_anim_index = job["index"]
        self._redraw_floating_table(table_id)
        if job["frame"] < STREET_REVEAL_FRAMES:
            self.after(STREET_REVEAL_FRAME_MS, lambda tid=table_id: self._board_reveal_frame(tid))
            return
        state["cash_board_reveal_count"] = job["index"] + 1
        state["cash_visible_board"] = list(job["target"][:job["index"] + 1])
        state["cash_board_anim_index"] = None
        state["cash_board_anim_progress"] = 1.0
        state["cash_board_anim_indices"] = []
        if table_id == self.active_cash_table_id:
            self.cash_board_target = list(job["target"])
            self.cash_board_reveal_count = job["index"] + 1
            self.cash_visible_board = list(state["cash_visible_board"])
            self.cash_board_anim_index = None
        self._redraw_floating_table(table_id)
        self._play_sound("card_land")
        job["index"] += 1
        self.after(STREET_BETWEEN_CARDS_MS, lambda tid=table_id: self._board_reveal_next(tid))

    def _board_squeeze_rect(self, table_id: str, card_index: int):
        """Rectangle for a board card, using the same layout math as _draw_table."""
        record = self.table_windows.get(table_id)
        if not record:
            return None
        canvas = record["canvas"]
        w = max(1, canvas.winfo_width())
        h = max(1, canvas.winfo_height())
        card_w = max(42, min(54, int(w * .043)))
        card_h = int(card_w * 1.38)
        card_gap = max(6, int(card_w * .15))
        start_x = w / 2 - (5 * card_w + 4 * card_gap) / 2
        left = start_x + int(card_index) * (card_w + card_gap)
        top = h * .395
        return left, top, left + card_w, top + card_h

    def _board_squeeze_pointer_motion(self, table_id: str, event) -> bool:
        slot = self.multi_tables.get(table_id)
        if not slot:
            return False
        squeeze = slot.state.get("cash_board_squeeze") or {}
        if not squeeze.get("active"):
            return False
        index = int(squeeze.get("index", -1))
        rect = self._board_squeeze_rect(table_id, index)
        if not rect:
            return False
        left, top, right, bottom = rect
        if not (left <= event.x <= right and top <= event.y <= bottom):
            return False
        progress = max(float(squeeze.get("progress", 0.0)),
                       min(1.0, max(0.0, (float(event.x) - left) / max(1.0, right-left))))
        squeeze["progress"] = progress
        slot.state["cash_board_squeeze"] = squeeze
        slot.state["cash_board_anim_index"] = index
        slot.state["cash_board_anim_progress"] = progress
        if table_id == self.active_cash_table_id:
            self.cash_board_squeeze = dict(squeeze)
            self.cash_board_anim_index = index
            self.cash_board_anim_progress = progress
        self._redraw_floating_table(table_id)
        if progress >= .97:
            self._complete_board_squeeze_card(table_id)
        return True

    def _complete_board_squeeze_card(self, table_id: str):
        job = self.board_animation_jobs.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not job or not slot or not job.get("waiting_squeeze"):
            return
        index = int(job["index"])
        job.setdefault("squeezed_cards", set()).add(index)
        job["waiting_squeeze"] = False
        job["index"] = index + 1
        state = slot.state
        target = job["target"]
        state["cash_board_reveal_count"] = index + 1
        state["cash_visible_board"] = list(target[:index+1])
        state["cash_board_anim_index"] = None
        state["cash_board_anim_progress"] = 1.0
        state["cash_board_squeeze"] = None
        if table_id == self.active_cash_table_id:
            self.cash_board_reveal_count = index + 1
            self.cash_visible_board = list(target[:index+1])
            self.cash_board_anim_index = None
            self.cash_board_anim_progress = 1.0
            self.cash_board_squeeze = {}
        self._play_sound("card_swoosh")
        self._redraw_floating_table(table_id)
        self.after(180, lambda tid=table_id: self._board_reveal_next(tid))

    def _auto_finish_board_squeeze(self, table_id: str):
        """Never hold an all-in showdown indefinitely if the player ignores the peel."""
        self.board_squeeze_auto_jobs.pop(table_id, None)
        job = self.board_animation_jobs.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not job or not slot:
            return
        target = list(job["target"])
        state = slot.state
        state["cash_board_reveal_count"] = len(target)
        state["cash_visible_board"] = target
        state["cash_board_anim_index"] = None
        state["cash_board_anim_progress"] = 1.0
        state["cash_board_squeeze"] = None
        job["index"] = len(target)
        job["waiting_squeeze"] = False
        if table_id == self.active_cash_table_id:
            self.cash_board_reveal_count = len(target)
            self.cash_visible_board = target
            self.cash_board_anim_index = None
            self.cash_board_anim_progress = 1.0
            self.cash_board_squeeze = {}
        self._redraw_floating_table(table_id)
        self._board_reveal_next(table_id)

    def _hero_card_rect(self, table_id: str, card_index: int):
        """Return the current hidden hero-card rectangle in its table canvas."""
        record = self.table_windows.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not record or not slot:
            return None
        table = slot.state.get("cash_table")
        hand = table.hand if table is not None else None
        if hand is None or hand.finished or hand.player("hero").folded:
            return None
        if card_index < int(slot.state.get("hero_squeeze_count", 0)) or card_index > 1:
            return None
        canvas = record["canvas"]
        w = max(1, canvas.winfo_width())
        h = max(1, canvas.winfo_height())
        # Hero is rotated to the bottom-centre seat in every table window.
        x = w * .50 - 52 + card_index * 56
        hero_y_ratio = .83 if len(hand.players) == 2 else .84
        y = h * hero_y_ratio - 112
        return (x, y, x + 48, y + 66)

    def _table_pointer_motion(self, table_id: str, event):
        record = self.table_windows.get(table_id)
        if not record:
            return
        if self._board_squeeze_pointer_motion(table_id, event):
            try:
                record["canvas"].configure(cursor="hand2")
            except tk.TclError:
                pass
            return
        drag = self.card_peel_drags.get(table_id)
        if drag:
            self._table_pointer_drag(table_id, event)
            return
        slot = self.multi_tables.get(table_id)
        if not slot:
            return
        reveal = int(slot.state.get("hero_squeeze_count", 0))
        rect = self._hero_card_rect(table_id, reveal) if reveal < 2 else None
        if rect and rect[0] <= event.x <= rect[2] and rect[1] <= event.y <= rect[3]:
            record["canvas"].configure(cursor="hand2")
        else:
            record["canvas"].configure(cursor="arrow")

    def _table_pointer_press(self, table_id: str, event):
        """Start peeling the next face-down hole card with the mouse."""
        slot = self.multi_tables.get(table_id)
        record = self.table_windows.get(table_id)
        if not slot or not record or not self.card_squeeze_enabled_var.get():
            return
        reveal = int(slot.state.get("hero_squeeze_count", 0))
        rect = self._hero_card_rect(table_id, reveal) if reveal < 2 else None
        if not rect or not (rect[0] <= event.x <= rect[2] and rect[1] <= event.y <= rect[3]):
            return
        top, bottom = float(rect[1]), float(rect[3])
        # Start the squeeze near the lower edge, then pull upward. A press in
        # the middle of the card is ignored so the action is deliberate.
        if float(event.y) < top + (bottom - top) * .72:
            return
        self.card_peel_drags[table_id] = {
            "index": reveal, "rect": rect,
            "start_y": min(bottom, float(event.y)),
            "progress": 0.0,
        }
        record["canvas"].configure(cursor="hand2")
        self._play_sound("card_peel")
        self._redraw_floating_table(table_id)
        return "break"

    def _table_pointer_drag(self, table_id: str, event):
        drag = self.card_peel_drags.get(table_id)
        if not drag:
            return
        left, top, right, bottom = drag["rect"]
        start_y = min(max(float(drag["start_y"]), top + 1), bottom)
        progress = squeeze_card_sweep_progress(start_y, float(event.y), top,
                                               max(1.0, bottom - top))
        drag["progress"] = max(float(drag.get("progress", 0.0)), progress)
        self._redraw_floating_table(table_id)
        return "break"

    def _table_pointer_release(self, table_id: str, event):
        drag = self.card_peel_drags.pop(table_id, None)
        if not drag:
            return
        slot = self.multi_tables.get(table_id)
        record = self.table_windows.get(table_id)
        if slot and drag["progress"] >= 0.58:
            state = slot.state
            current = int(state.get("hero_squeeze_count", 0))
            if current == int(drag["index"]):
                state["hero_squeeze_count"] = min(2, current + 1)
                self._play_sound("card_land")
                if table_id == self.active_cash_table_id:
                    self.hero_squeeze_count = int(state["hero_squeeze_count"])
                    self._save_active_cash_slot()
        if record:
            record["canvas"].configure(cursor="arrow")
            self._redraw_floating_table(table_id)
        return "break"

    def _redraw_floating_table(self, table_id: str):
        record = self.table_windows.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not record or not slot:
            return
        state = slot.state
        table = state.get("cash_table")
        drag = self.card_peel_drags.get(table_id, {})
        self._draw_table(canvas=record["canvas"], table=table, table_id=table_id,
                         profiles=state.get("cash_cpu_profiles", {}),
                         squeeze_count=int(state.get("hero_squeeze_count", 0)),
                         board_squeeze_count=5,
                         peel_index=drag.get("index"),
                         peel_progress=float(drag.get("progress", 0.0)),
                         visible_board=state.get("cash_board_target", getattr(table.hand, "board", []) if table and table.hand else []),
                         board_reveal_count=int(state.get("cash_board_reveal_count", len(getattr(table.hand, "board", [])) if table and table.hand else 0)),
                         board_anim_index=state.get("cash_board_anim_index"),
                         board_anim_indices=state.get("cash_board_anim_indices", []),
                         board_anim_progress=float(state.get("cash_board_anim_progress", 1.0)),
                         deal_counts=state.get("cash_deal_counts", {}),
                         deal_flying=state.get("cash_deal_flying"),
                         thinking_player=state.get("cash_thinking_player"),
                         hero_flip_state=state.get("cash_initial_flip", {}))
        # Hero's stack amount on the seat plaque is the $ / BB toggle target.
        record["canvas"].tag_bind(
            "hero_stack_toggle", "<Button-1>",
            lambda _event, tid=table_id: self._toggle_table_chip_unit(tid))
        record["canvas"].tag_bind(
            "hero_stack_toggle", "<Enter>",
            lambda _event, c=record["canvas"]: c.configure(cursor="hand2"))
        record["canvas"].tag_bind(
            "hero_stack_toggle", "<Leave>",
            lambda _event, c=record["canvas"]: c.configure(cursor="arrow"))

    def _destroy_table_window(self, table_id: str):
        self._cancel_squeeze_action_deadline(table_id)
        # A floating table can be closed while Card Squeeze or an all-in board
        # reveal is still active. Tear down every visual job before its Toplevel.
        popup = self.squeeze_popups.pop(table_id, None)
        if popup:
            try:
                popup["window"].destroy()
            except tk.TclError:
                pass
        board_job = self.board_animation_jobs.pop(table_id, None)
        if board_job and board_job.get("ready_event"):
            board_job["ready_event"].set()
        deal_job = self.deal_animation_jobs.pop(table_id, None)
        if deal_job and deal_job.get("after_id"):
            try:
                self.after_cancel(deal_job["after_id"])
            except tk.TclError:
                pass
        self.card_peel_drags.pop(table_id, None)
        board_auto = self.board_squeeze_auto_jobs.pop(table_id, None)
        if board_auto:
            try:
                self.after_cancel(board_auto)
            except tk.TclError:
                pass
        flip_job = self.hole_flip_jobs.pop(table_id, None)
        if flip_job:
            try:
                self.after_cancel(flip_job)
            except tk.TclError:
                pass
        record = self.table_windows.pop(table_id, None)
        if record:
            try:
                pending = record.get("raise_after_id")
                if pending:
                    record["window"].after_cancel(pending)
                record["window"].destroy()
            except tk.TclError:
                pass

    def _bring_table_front(self, table_id: str):
        record = self.table_windows.get(table_id)
        if not record:
            return
        window = record["window"]
        try:
            window.deiconify()
            window.lift()
            # A brief topmost pulse makes a newly opened table reliably surface
            # above the lobby on Windows; it is then returned to normal stacking.
            window.attributes("-topmost", True)
            old_after = record.get("raise_after_id")
            if old_after:
                try:
                    window.after_cancel(old_after)
                except tk.TclError:
                    pass
            def release_topmost(tid=table_id):
                current = self.table_windows.get(tid)
                if current:
                    try:
                        current["window"].attributes("-topmost", False)
                    except tk.TclError:
                        pass
                    current["raise_after_id"] = None
            record["raise_after_id"] = window.after(420, release_topmost)
            window.focus_force()
        except tk.TclError:
            pass

    def _open_floating_table(self, table_id: str):
        self._bring_table_front(table_id)

    def _request_quick_leave(self, table_id: str, confirmed: bool = False):
        """Confirm, then cash out from this seat while cancelling CPU waits."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        if not confirmed and not self._ask_table_confirmation(
                table_id, "テーブル退出", "現在のハンドをフォールドして、残りのスタックをウォレットへ戻します。テーブルから退出しますか？"):
            return
        self._cancel_squeeze_action_deadline(table_id)
        board_auto = self.board_squeeze_auto_jobs.pop(table_id, None)
        if board_auto:
            try:
                self.after_cancel(board_auto)
            except tk.TclError:
                pass
        flip_job = self.hole_flip_jobs.pop(table_id, None)
        if flip_job:
            try:
                self.after_cancel(flip_job)
            except tk.TclError:
                pass
        self.quick_leave_poll_jobs.add(table_id)
        cancel_event = self.cash_cpu_cancel_events.get(table_id)
        if cancel_event is not None:
            cancel_event.set()

        # Cancel visual work that would otherwise keep the hand marked busy.
        self.deal_animation_jobs.pop(table_id, None)
        popup = self.squeeze_popups.pop(table_id, None)
        if popup:
            try:
                popup["window"].destroy()
            except tk.TclError:
                pass
        board_job = self.board_animation_jobs.pop(table_id, None)
        if board_job and board_job.get("ready_event"):
            board_job["ready_event"].set()
        self.card_peel_drags.pop(table_id, None)
        slot.state["cash_deal_busy"] = False
        slot.state["cash_busy"] = bool(cancel_event is not None)
        slot.state["cash_action_feed"] = "LEAVING TABLE…"
        if table_id == self.active_cash_table_id:
            self.cash_deal_busy = False
            self.cash_action_feed = "LEAVING TABLE…"
            self._save_active_cash_slot()
        self._refresh_table_windows()
        self._poll_quick_leave(table_id)

    def _poll_quick_leave(self, table_id: str):
        """Wait only for an in-flight CPU calculation, never for the poker hand."""
        if table_id not in self.quick_leave_poll_jobs:
            return
        slot = self.multi_tables.get(table_id)
        if slot is None:
            self.quick_leave_poll_jobs.discard(table_id)
            self.cash_cpu_cancel_events.pop(table_id, None)
            return
        # A CPU worker owns the hand object until it posts cash_cpu_done/error.
        if table_id in self.cash_cpu_cancel_events:
            self.after(60, lambda tid=table_id: self._poll_quick_leave(tid))
            return

        previous_id = self.active_cash_table_id
        if previous_id != table_id:
            if previous_id and self.multi_tables.get(previous_id):
                self._save_active_cash_slot()
            self._restore_cash_slot(table_id)
        try:
            self.cash_busy = False
            self.cash_deal_busy = False
            self.cash_syncing_gto = False
            self.cash_thinking_player = None
            self.quick_leave_poll_jobs.discard(table_id)
            self._leave_cash_table(confirmed=True)
        finally:
            # _leave_cash_table activates the next remaining table itself.
            if (previous_id and previous_id != table_id
                    and self.active_cash_table_id == table_id
                    and self.multi_tables.get(previous_id)):
                self._restore_cash_slot(previous_id)

    def _ask_table_confirmation(self, table_id: str, title: str, message: str) -> bool:
        """Show a modal confirmation owned by the table window, always above it."""
        record = self.table_windows.get(table_id)
        parent = record["window"] if record else self
        dialog = tk.Toplevel(parent)
        dialog.title(title)
        dialog.transient(parent)
        dialog.resizable(False, False)
        dialog.configure(bg=COLORS["panel"])
        dialog.attributes("-topmost", True)
        self._active_confirmation_dialog = dialog
        dialog.geometry("430x176")
        dialog.update_idletasks()
        try:
            px = parent.winfo_rootx() + max(0, (parent.winfo_width() - 430) // 2)
            py = parent.winfo_rooty() + max(0, (parent.winfo_height() - 176) // 2)
            dialog.geometry(f"430x176+{px}+{py}")
        except tk.TclError:
            pass
        tk.Label(dialog, text=title, bg=COLORS["panel"], fg=COLORS["gold"],
                 font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=18, pady=(16, 7))
        tk.Label(dialog, text=message, bg=COLORS["panel"], fg=COLORS["text"],
                 wraplength=390, justify="left", font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(0, 12))
        result = {"value": False}
        buttons = tk.Frame(dialog, bg=COLORS["panel"])
        buttons.pack(fill="x", padx=14, pady=(0, 12))
        def finish(value: bool):
            result["value"] = bool(value)
            try:
                dialog.grab_release()
                dialog.destroy()
                self._active_confirmation_dialog = None
            except tk.TclError:
                self._active_confirmation_dialog = None
        cancel = tk.Button(buttons, text="キャンセル", command=lambda: finish(False),
                           bg="#25374c", fg="#f0f4fa", activebackground="#344d68",
                           relief="flat", bd=0, padx=16, pady=6, cursor="hand2")
        cancel.pack(side="right", padx=(6, 0))
        ok = tk.Button(buttons, text="退出する", command=lambda: finish(True),
                       bg="#c94e55", fg="#ffffff", activebackground="#e56b72",
                       relief="flat", bd=0, padx=18, pady=6, cursor="hand2")
        ok.pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        try:
            dialog.lift()
            dialog.focus_force()
            dialog.grab_set()
            dialog.wait_window()
        except tk.TclError:
            return False
        return bool(result["value"])

    def _leave_floating_table(self, table_id: str):
        if table_id != self.active_cash_table_id:
            self._switch_cash_table(table_id)
        if self.active_cash_table_id != table_id:
            return
        active_slot = self.multi_tables.get(table_id)
        already_sitting_out = bool(active_slot and active_slot.state.get("cash_sitting_out", False))
        if not already_sitting_out and not self._ask_table_confirmation(
                table_id, "テーブル退出", "このテーブルから退出しますか？\n進行中のハンドがあればフォールドして、残りのスタックをウォレットへ戻します。"):
            return
        if self.cash_busy:
            self._request_quick_leave(table_id, confirmed=True)
        else:
            self._leave_cash_table(confirmed=True)

    def _handle_table_fold(self, table_id: str):
        """Handle the visible Fold control without silently dropping Rush preflop folds."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table is not None else None
        if hand is None or hand.finished:
            return
        mode = normalize_table_mode(slot.state.get("cash_game_mode", RUSH_MODE))
        if is_rush_mode(mode) and hand.street == "preflop":
            # This is the fast-fold feature, not merely a standard in-turn action.
            # It intentionally works while a CPU is acting and for the BB when
            # CHECK is available, without waiting for the action to reach HERO.
            self._request_preflop_fold(table_id)
            return
        if hand.next_to_act != "hero":
            return
        if table_id != self.active_cash_table_id:
            if self.cash_busy:
                # Do not lose a click on another table just because the currently
                # focused table has a CPU worker. Retry once the shared controller
                # is free; the hand/turn is revalidated by this method.
                pending = self.pending_table_action_jobs.get(table_id)
                if pending:
                    return
                self.pending_table_action_jobs[table_id] = self.after(
                    80, lambda tid=table_id: self._retry_table_fold(tid))
                return
            self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
        if self.active_cash_table_id == table_id and not self.cash_busy:
            self._cash_human_action("fold")
            self._open_floating_table(table_id)

    def _retry_table_fold(self, table_id: str):
        self.pending_table_action_jobs.pop(table_id, None)
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        if self.cash_busy and table_id != self.active_cash_table_id:
            self.pending_table_action_jobs[table_id] = self.after(
                80, lambda tid=table_id: self._retry_table_fold(tid))
            return
        self._handle_table_fold(table_id)

    def _floating_table_action(self, table_id: str, action: str, amount: int | None = None):
        if table_id != self.active_cash_table_id:
            self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
        if self.active_cash_table_id == table_id and not self.cash_busy:
            self._cash_human_action(action, amount)
            self._open_floating_table(table_id)

    def _request_preflop_fold(self, table_id: str):
        """Rush-fold preflop immediately, including while another player is acting."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table else None
        if (hand is None or hand.finished or hand.street != "preflop"
                or not is_rush_mode(slot.state.get("cash_game_mode", RUSH_MODE))):
            return
        if table_id != self.active_cash_table_id:
            self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
            slot = self.multi_tables.get(table_id)
            table = slot.state.get("cash_table") if slot else None
            hand = table.hand if table else None
            if hand is None or hand.finished or hand.street != "preflop":
                return

        # Stop old card/reveal work so it cannot hold up the next hand.
        self._cancel_squeeze_action_deadline(table_id)
        for job_map in (self.deal_animation_jobs, self.hole_flip_jobs, self.board_squeeze_auto_jobs):
            pending = job_map.pop(table_id, None)
            if pending:
                after_id = pending.get("after_id") if isinstance(pending, dict) else pending
                if after_id:
                    try:
                        self.after_cancel(after_id)
                    except tk.TclError:
                        pass
        popup = self.squeeze_popups.pop(table_id, None)
        if popup:
            try:
                popup["window"].destroy()
            except tk.TclError:
                pass
        board_job = self.board_animation_jobs.pop(table_id, None)
        if board_job and board_job.get("ready_event"):
            board_job["ready_event"].set()
        self.card_peel_drags.pop(table_id, None)
        slot.state["cash_deal_flying"] = None
        slot.state["cash_deal_busy"] = False
        slot.state["cash_rush_fold_pending"] = True
        slot.state["cash_action_feed"] = "RUSH FOLD • MOVING TO A NEW HAND…"
        if table_id == self.active_cash_table_id:
            self.cash_deal_flying = None
            self.cash_deal_busy = False
            self.cash_action_feed = slot.state["cash_action_feed"]

        # A cancellable worker may still own the mutable hand object. Wait for its
        # cancellation message before marking the hand finished.
        cancel_event = self.cash_cpu_cancel_events.get(table_id)
        if cancel_event is not None:
            self.rush_fold_poll_jobs.add(table_id)
            cancel_event.set()
            slot.state["cash_busy"] = True
            self.cash_busy = True
            self._save_active_cash_slot()
            self._refresh_table_windows()
            self._poll_rush_fold(table_id)
            return
        self._finish_rush_fold(table_id)

    def _poll_rush_fold(self, table_id: str):
        if table_id not in self.rush_fold_poll_jobs:
            return
        if self.multi_tables.get(table_id) is None:
            self.rush_fold_poll_jobs.discard(table_id)
            self.cash_cpu_cancel_events.pop(table_id, None)
            return
        if table_id in self.cash_cpu_cancel_events:
            self.after(35, lambda tid=table_id: self._poll_rush_fold(tid))
            return
        self.rush_fold_poll_jobs.discard(table_id)
        self._finish_rush_fold(table_id)

    def _finish_rush_fold(self, table_id: str):
        """Finalize Rush Fold privately, then deal the player into the next hand."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        if table_id != self.active_cash_table_id:
            self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
        table = self.cash_table
        hand = table.hand if table else None
        if (hand is None or hand.finished or hand.street != "preflop"
                or not is_rush_mode(slot.state.get("cash_game_mode", RUSH_MODE))):
            slot.state["cash_rush_fold_pending"] = False
            return

        was_hero_turn = hand.next_to_act == "hero"
        hand.player("hero").folded = True
        hand.events.append({
            "type": "action", "player_id": "hero", "player": "YOU",
            "action": "fold", "street": hand.street, "fast_fold": True,
            "out_of_turn": not was_hero_turn,
        })
        hand.finished = True
        hand.winner_reason = "fast_fold"
        hand.next_to_act = None
        hand.pending.clear()
        hand.awards = []
        table.sync_external_hand_state()

        slot.state["cash_rush_fold_pending"] = False
        slot.state["preflop_fold_pending"] = False
        slot.state["cash_busy"] = False
        slot.state["cash_deal_busy"] = False
        slot.state["cash_thinking_player"] = None
        slot.state["cash_action_feed"] = "RUSH FOLD • NEXT HAND"
        slot.state["cash_action_flash"] = {
            "player_id": "hero", "actor": "YOU", "text": "RUSH FOLD",
            "expires_at": time.monotonic() + 1.0, "token": uuid.uuid4().hex,
        }
        self.preflop_fold_pending = False
        self.cash_busy = False
        self.cash_deal_busy = False
        self.cash_thinking_player = None
        self.cash_action_feed = "RUSH FOLD • NEXT HAND"
        self.cash_log_lines.append("YOU: RUSH FOLD (out of turn) • moved to the next hand")
        self._play_action_sound("fold")
        self._save_active_cash_slot()
        self._draw_table()
        self._refresh_table_windows()
        self._update_cash_after_action()

    def _set_postflop_auto_fold(self, table_id: str, enabled: bool):
        """Arm check-when-free / fold-when-facing-a-bet for this hand only."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table else None
        enabled = bool(enabled and hand is not None and not hand.finished
                       and hand.street != "preflop")
        slot.state["postflop_auto_fold"] = enabled
        slot.state["postflop_auto_fold_hand_token"] = id(hand) if enabled else None
        record = self.table_windows.get(table_id)
        if record is not None:
            try:
                record["postflop_auto_fold_var"].set(enabled)
            except (KeyError, tk.TclError):
                pass
        if table_id == self.active_cash_table_id:
            self.postflop_auto_fold = enabled
            self.postflop_auto_fold_hand_token = id(hand) if enabled else None
        table_busy = (self.cash_busy if table_id == self.active_cash_table_id
                      else bool(slot.state.get("cash_busy", False)))
        # Enabling while the hero already has the action means the action has arrived:
        # check if free, fold only when facing a wager.
        if (enabled and hand and hand.street != "preflop" and hand.next_to_act == "hero"
                and not hand.finished and not table_busy):
            self._consume_queued_auto_fold(table_id)
            return
        self._refresh_table_windows()

    def _clear_postflop_auto_fold(self, table_id: str):
        slot = self.multi_tables.get(table_id)
        if slot is not None:
            slot.state["postflop_auto_fold"] = False
            slot.state["postflop_auto_fold_hand_token"] = None
        record = self.table_windows.get(table_id)
        if record:
            try:
                record["postflop_auto_fold_var"].set(False)
            except (KeyError, tk.TclError):
                pass
        if table_id == self.active_cash_table_id:
            self.postflop_auto_fold = False
            self.postflop_auto_fold_hand_token = None

    def _consume_queued_auto_fold(self, table_id: str) -> bool:
        """Consume preflop fast-fold, or one postflop check/fold decision when HERO acts."""
        slot = self.multi_tables.get(table_id)
        if slot is None:
            return False
        table_busy = (self.cash_busy if table_id == self.active_cash_table_id
                      else bool(slot.state.get("cash_busy", False)))
        if table_busy:
            return False
        table = slot.state.get("cash_table")
        hand = table.hand if table else None
        if hand is None or hand.finished or hand.next_to_act != "hero":
            return False
        pending = bool(slot.state.get("preflop_fold_pending", False)) and hand.street == "preflop"
        armed_token = slot.state.get("postflop_auto_fold_hand_token")
        postflop = (bool(slot.state.get("postflop_auto_fold", False))
                    and hand.street != "preflop" and armed_token == id(hand))
        if not (pending or postflop):
            return False

        action = "fold"
        if postflop:
            legal = hand.legal_actions("hero")
            legal_actions = set(legal.get("actions", []))
            action = "check" if "check" in legal_actions else "fold"
            slot.state.setdefault("cash_log_lines", []).append(
                f"POSTFLOP AUTO • {hand.street.upper()} • {action.upper()}"
            )
        else:
            slot.state["preflop_fold_pending"] = False

        previous_id = self.active_cash_table_id
        if previous_id != table_id:
            if previous_id and self.multi_tables.get(previous_id):
                self._save_active_cash_slot()
            self._restore_cash_slot(table_id)
        try:
            if table_id == self.active_cash_table_id:
                if pending:
                    self.preflop_fold_pending = False
                    self.cash_log_lines.append("PRE-FOLD • queued before HERO's preflop action")
                else:
                    self.cash_log_lines.append(f"AUTO {action.upper()} • {hand.street.upper()}")
            self._cash_human_action(action)
        finally:
            if previous_id and previous_id != table_id and self.multi_tables.get(previous_id):
                self._restore_cash_slot(previous_id)
        return True

    def _compact_action_button(self, parent, text: str, command, kind: str = "normal"):
        """Small, flat controls that preserve canvas space for the cards and board."""
        palette = {
            "normal": ("#25374c", "#f0f4fa", "#344d68"),
            "accent": ("#1ca878", "#071b14", "#31c58b"),
            "danger": ("#c94e55", "#ffffff", "#e56b72"),
        }
        bg, fg, active = palette.get(kind, palette["normal"])
        return tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=active, activeforeground=fg,
            relief="flat", bd=0, highlightthickness=0,
            padx=8, pady=3, font=("Segoe UI", 8, "bold"),
            cursor="hand2", takefocus=True,
        )

    def _format_table_chips(self, cents: int, big_blind: int) -> str:
        return format_chip_amount(cents, big_blind, self.chip_display_unit)

    def _set_table_bet_target(self, table_id: str, cents: int):
        record = self.table_windows.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not record or not slot:
            return
        table = slot.state.get("cash_table")
        bb = max(1, int(getattr(table, "big_blind", 1)))
        cents = max(int(record.get("bet_min", 0)), min(int(record.get("bet_max", cents)), int(cents)))
        record["syncing_bet"] = True
        try:
            record["bet_target_cents"].set(cents)
            record["bet_slider"].set(cents)
            record["bet_target"].set(format_chip_amount(cents, bb, self.chip_display_unit, include_unit=False))
        finally:
            record["syncing_bet"] = False
        self._update_bet_submit_label(table_id)

    def _on_table_bet_slider(self, table_id: str, value: str):
        record = self.table_windows.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not record or not slot or record.get("syncing_bet"):
            return
        table = slot.state.get("cash_table")
        bb = max(1, int(getattr(table, "big_blind", 1)))
        cents = int(round(float(value)))
        record["bet_target_cents"].set(cents)
        record["bet_target"].set(format_chip_amount(cents, bb, self.chip_display_unit, include_unit=False))
        self._update_bet_submit_label(table_id)

    def _on_table_bet_entry_change(self, table_id: str, _event=None):
        record = self.table_windows.get(table_id)
        slot = self.multi_tables.get(table_id)
        if not record or not slot or record.get("syncing_bet"):
            return
        table = slot.state.get("cash_table")
        bb = max(1, int(getattr(table, "big_blind", 1)))
        try:
            cents = parse_chip_amount(record["bet_target"].get(), bb, self.chip_display_unit)
        except (ValueError, ArithmeticError):
            return
        record["bet_target_cents"].set(cents)
        slider_value = max(int(record.get("bet_min", 0)), min(int(record.get("bet_max", cents)), cents))
        record["syncing_bet"] = True
        try:
            record["bet_slider"].set(slider_value)
        finally:
            record["syncing_bet"] = False
        self._update_bet_submit_label(table_id)

    def _update_bet_submit_label(self, table_id: str):
        record = self.table_windows.get(table_id)
        if not record:
            return
        button = record.get("bet_action_button")
        if button is None:
            return
        target = int(record["bet_target_cents"].get())
        label = bet_button_label(record.get("bet_verb", "bet"), target, int(record.get("bet_max", 0)))
        button.configure(text=label)
        if label == "ALL-IN":
            button.configure(bg="#c94e55", fg="#ffffff", activebackground="#e56b72")
        else:
            button.configure(bg="#1ca878", fg="#071b14", activebackground="#31c58b")

    def _set_table_pot_preset(self, table_id: str, percentage: int):
        slot = self.multi_tables.get(table_id)
        record = self.table_windows.get(table_id)
        if not slot or not record:
            return
        table = slot.state.get("cash_table")
        hand = table.hand if table else None
        if hand is None or hand.finished or hand.next_to_act != "hero":
            return
        legal = hand.legal_actions("hero")
        if not ({"bet", "raise"} & set(legal.get("actions", []))):
            return
        verb = "bet" if "bet" in legal["actions"] else "raise"
        hero = hand.player("hero")
        target = pot_sized_target(hand, legal, hero, percentage, verb)
        # Preset buttons ONLY move the slider / amount selection. They never submit.
        self._set_table_bet_target(table_id, target)

    def _floating_table_bet_action(self, table_id: str, amount_var: tk.StringVar):
        if table_id != self.active_cash_table_id:
            self._save_active_cash_slot()
            try:
                self._restore_cash_slot(table_id)
            except KeyError:
                return
        if self.active_cash_table_id != table_id or self.cash_busy or self.cash_table is None or self.cash_table.hand is None:
            return
        try:
            hand = self.cash_table.hand
            legal = hand.legal_actions("hero")
            bb = max(1, int(self.cash_table.big_blind))
            raw_amount = str(amount_var.get()).strip()
            if not raw_amount:
                record = self.table_windows.get(table_id)
                if record:
                    record["status"].set("ENTER A BET SIZE OR CHOOSE A POT PRESET")
                return
            target = parse_chip_amount(raw_amount, bb, self.chip_display_unit)
            minimum = int(legal["min_target"])
            maximum = int(legal["max_target"])
            if target < minimum and target != maximum:
                raise ValueError(f"最小サイズは {format_chip_amount(minimum, bb, self.chip_display_unit)} です。")
            if target > maximum:
                raise ValueError(f"スタック上限は {format_chip_amount(maximum, bb, self.chip_display_unit)} です。")
            if target == maximum and "all-in" in legal["actions"]:
                # There is no separate ALL-IN button: selecting the full stack turns
                # the single Bet/Raise submit button into ALL-IN.
                self._floating_table_action(table_id, "all-in")
            else:
                verb = "bet" if "bet" in legal["actions"] else "raise"
                self._floating_table_action(table_id, verb, target)
        except Exception as exc:
            messagebox.showerror("Invalid bet size", str(exc))

    def _refresh_table_windows(self):
        """Refresh each standalone table with compact, contextual betting controls."""
        for slot in self.multi_tables.list():
            record = self.table_windows.get(slot.table_id)
            if record is None:
                try:
                    self._create_table_window(slot.table_id)
                    record = self.table_windows.get(slot.table_id)
                except tk.TclError:
                    continue
            if record is None:
                continue
            state = slot.state
            table = state.get("cash_table")
            hand = table.hand if table is not None else None
            current_hand_key = id(hand) if hand is not None else None
            self._update_range_icon_state(slot, record, hand)
            if hand is not None and not hand.finished:
                previous_effect_hand = record.get("social_effect_hand_key")
                if previous_effect_hand != current_hand_key:
                    record["big_pot_celebration_available"] = None
                    record["big_pot_celebration"] = None
                    state["cash_social_reaction"] = None
                    record["social_effect_hand_key"] = current_hand_key
            if hand is None or hand.finished:
                if bool(state.get("postflop_auto_fold", False)):
                    self._clear_postflop_auto_fold(slot.table_id)
                if hand is not None and not bool(state.get("cash_gto_spot_mode", False)):
                    self._ensure_pot_award_animation(slot.table_id, hand)
            elif (bool(state.get("postflop_auto_fold", False))
                  and state.get("postflop_auto_fold_hand_token") != id(hand)):
                self._clear_postflop_auto_fold(slot.table_id)
            bb = max(1, int(getattr(table, "big_blind", 1)))
            record["title"].set(f"{table_mode_label(state.get('cash_game_mode'))}  •  {slot.rate}")
            record["wallet"].set(f"WALLET  ${self.cash_balance_cents/100:,.2f}")
            record["event"].set(str(state.get("cash_action_feed", "")))
            try:
                if bool(state.get("cash_sitting_out", False)):
                    record["sitout_button"].configure(
                        text="再開", command=lambda tid=slot.table_id: self._resume_cash_table(tid),
                        state="normal")
                else:
                    if bool(state.get("cash_sitout_pending", False)):
                        record["sitout_button"].configure(
                            text="離席予約中", command=lambda tid=slot.table_id: self._cancel_table_sitout(tid),
                            state="normal")
                    else:
                        record["sitout_button"].configure(
                            text="一時離席", command=lambda tid=slot.table_id: self._request_table_sitout(tid),
                            state="normal")
            except (KeyError, tk.TclError):
                pass
            try:
                preference = state.get("cash_run_it_preference", "ask")
                run_it_label = "RUN IT: ASK" if preference == "ask" else f"RUN IT: {int(preference)}×"
                record["run_it_button"].configure(text=run_it_label)
                record["auto_fold_gto_size_button"].configure(
                    text=("AUTO-FOLD RANGE • ON" if self.auto_fold_chart.get("enabled") else "AUTO-FOLD RANGE"))
            except (KeyError, tk.TclError, ValueError, TypeError):
                pass
            try:
                reaction_live = bool(hand is not None and not hand.finished and not state.get("cash_sitting_out", False))
                record["social_button"].configure(state=("normal" if reaction_live else "disabled"))
                celebrate_ready = bool(record.get("big_pot_celebration_available"))
                celebrate_active = bool(record.get("big_pot_celebration"))
                if celebrate_ready and not celebrate_active:
                    record["celebrate_button"].pack(side="left", padx=(0, 5))
                else:
                    record["celebrate_button"].pack_forget()
            except (KeyError, tk.TclError):
                pass
            deadline = float(state.get("cash_squeeze_deadline_at", 0.0) or 0.0)
            mode = str(state.get("cash_action_deadline_mode", "action") or "action")
            self._update_action_timer_display(slot.table_id,
                max(0.0, deadline - time.monotonic()) if deadline else 0.0, mode)
            self._redraw_floating_table(slot.table_id)
            actions_frame = record["actions"]
            sizes_frame = record["size_actions"]
            situation_frame = record["situation_actions"]

            # Only reconstruct controls when the legal-action topology changes.
            # CPU thinking banners, event text and timer ticks must not destroy
            # an Entry while the player is typing or steal a button click.
            preview_legal = {}
            if (hand is not None and not hand.finished
                    and not bool(state.get("cash_busy", False))
                    and hand.next_to_act == "hero"):
                try:
                    preview_legal = hand.legal_actions("hero")
                except Exception:
                    preview_legal = {}
            legal_signature = (
                tuple(sorted(preview_legal.get("actions", []))),
                int(preview_legal.get("to_call", 0) or 0),
                int(preview_legal.get("min_target", 0) or 0),
                int(preview_legal.get("max_target", 0) or 0),
            )
            hero = next((p for p in hand.players if p.player_id == "hero"), None) if hand else None
            action_signature = (
                # A new hand may have identical legal actions/pot/stack to the
                # previous hand. Include identity so its GTO size default is reloaded.
                current_hand_key,
                int(getattr(table, "dealer_index", 0) or 0) if table is not None else None,
                tuple(getattr(hero, "hole_cards", ()) or ()) if hero else (),
                bool(hand is not None),
                bool(hand.finished) if hand else False,
                str(hand.winner_reason or "") if hand else "",
                str(hand.street) if hand else "",
                str(hand.next_to_act or "") if hand else "",
                len(hand.events) if hand else 0,
                int(hand.pot) if hand else 0,
                int(hero.stack) if hero else 0,
                bool(state.get("cash_busy", False)),
                bool(state.get("cash_deal_busy", False)),
                bool(state.get("cash_syncing_gto", False)),
                str(state.get("cash_thinking_player") or ""),
                bool(state.get("preflop_fold_pending", False)),
                bool(state.get("postflop_auto_fold", False)),
                bool(state.get("cash_sitting_out", False)),
                bool(state.get("cash_sitout_pending", False)),
                bool(state.get("cash_sitout_before_bb", False)),
                bool(state.get("cash_timebank_armed", False)),
                bool(state.get("cash_timebank_paid_armed", False)),
                bool(state.get("cash_gto_spot_mode", False)),
                str(state.get("cash_run_it_preference", "ask")),
                int(self.cash_balance_cents),
                str(self.chip_display_unit),
                legal_signature,
            )
            rebuild_actions = record.get("action_signature") != action_signature
            if rebuild_actions:
                for frame in (actions_frame, sizes_frame, situation_frame):
                    for child in frame.winfo_children():
                        if frame is actions_frame and child is record.get("fold_button"):
                            child.pack_forget()
                            continue
                        child.destroy()
                record["bet_action_button"] = None
                record["gto_size_button"] = None
                record["action_signature"] = action_signature
            else:
                # Keep existing action controls and focused widgets alive.
                if hand is None:
                    record["status"].set("TABLE READY")
                    record["detail"].set("WAITING FOR FIRST HAND")
                elif hand.finished:
                    if hand.winner_reason == "showdown":
                        record["status"].set("YOU WON" if hero and any("hero" in a.winners for a in hand.awards) else "SHOWDOWN COMPLETE")
                    elif hand.winner_reason == "fast_fold":
                        record["status"].set("RUSHING TO NEXT HAND…")
                    else:
                        record["status"].set("HAND COMPLETE")
                elif bool(state.get("cash_busy", False)):
                    thinker = state.get("cash_thinking_player")
                    if state.get("cash_deal_busy", False):
                        record["status"].set("DEALING / SQUEEZE")
                    elif thinker:
                        name = next((p.name for p in hand.players if p.player_id == thinker), "Opponent")
                        record["status"].set(f"{name} THINKING…")
                    else:
                        record["status"].set("GTO+ SYNC…" if state.get("cash_syncing_gto") else "CPU THINKING…")
                elif hand.next_to_act == "hero":
                    record["status"].set("YOUR TURN")
                    self._update_bet_submit_label(slot.table_id)
                    try:
                        record["window"].deiconify()
                    except tk.TclError:
                        pass
                else:
                    actor = hand.player(hand.next_to_act).name if hand.next_to_act else "CPU"
                    record["status"].set(f"{actor} TO ACT")
                continue

            rabbit_button = record.get("rabbit_hunt_button")
            if rabbit_button is not None:
                can_rabbit = bool(hand is not None and hand.finished and hand.winner_reason == "fold"
                                  and len(hand.board) < 5 and hand.rabbit_hunt_board())
                try:
                    rabbit_button.pack(side="left", padx=(0, 8)) if can_rabbit else rabbit_button.pack_forget()
                    rabbit_button.configure(text=("HIDE RABBIT HUNT" if state.get("cash_rabbit_hunt_board") else "RABBIT HUNT"))
                except tk.TclError:
                    pass
            auto_fold_check = record.get("postflop_auto_fold_check")
            if auto_fold_check is not None:
                try:
                    auto_fold_check.pack_forget()
                    record["postflop_auto_fold_var"].set(bool(state.get("postflop_auto_fold", False)))
                    if hand is not None and hand.street != "preflop" and not hand.finished:
                        auto_fold_check.pack(side="left", padx=(12, 0))
                except tk.TclError:
                    pass
            # Sit-out keeps the cash table, table ID, seat and remaining stack alive.
            if bool(state.get("cash_sitting_out", False)):
                record["status"].set("SITTING OUT • TABLE PRESERVED")
                record["detail"].set("YOUR SEAT AND STACK ARE PRESERVED • PRESS RESUME TO RETURN")
                record["sitout_button"].configure(text="再開", command=lambda tid=slot.table_id: self._resume_cash_table(tid), state="normal")
                # The persistent utility button changes to RESUME; avoid a
                # duplicate action-dock button stealing space from betting controls.
                self._sync_timebank_controls(slot.table_id)
                continue
            if bool(state.get("cash_sitout_pending", False)):
                record["sitout_button"].configure(text="離席予約中", command=lambda tid=slot.table_id: self._cancel_table_sitout(tid), state="normal")
            else:
                record["sitout_button"].configure(text="一時離席", command=lambda tid=slot.table_id: self._request_table_sitout(tid), state="normal")
            self._sync_timebank_controls(slot.table_id)
            if hand is None:
                record["status"].set("TABLE READY")
                record["detail"].set("WAITING FOR FIRST HAND")
                continue

            hero = next((p for p in hand.players if p.player_id == "hero"), None)
            hero_stack = hero.stack if hero else 0
            unit_hint = "CLICK STACK: $ ↔ BB"
            record["detail"].set(
                f"HAND #{table.hand_number}   •   {hand.street.upper()}   •   YOUR STACK {format_chip_amount(hero_stack, bb, self.chip_display_unit)}   •   {unit_hint}"
            )

            if hand.finished:
                if hand.winner_reason == "showdown":
                    winners = list(dict.fromkeys(w for award in hand.awards for w in award.winners))
                    result = "YOU WON" if hero and any("hero" in award.winners for award in hand.awards) else "SHOWDOWN COMPLETE"
                    record["status"].set(result + ("  •  " + ", ".join(winners) if winners else ""))
                elif hand.winner_reason == "fast_fold":
                    record["status"].set("RUSHING TO NEXT HAND…")
                else:
                    record["status"].set("HAND COMPLETE")
                if not bool(state.get("cash_gto_spot_mode", False)) and hero_stack > 0:
                    tk.Label(actions_frame, text="NEXT HAND…", bg=COLORS["panel"],
                             fg=COLORS["green"], font=("Segoe UI", 8, "bold")).pack(side="left", padx=5)
                elif hero_stack <= 0:
                    tk.Label(actions_frame, text="STACK EMPTY", bg=COLORS["panel"],
                             fg=COLORS["red"], font=("Segoe UI", 8, "bold")).pack(side="left", padx=5)
                    if self.cash_balance_cents > 0:
                        self._compact_action_button(actions_frame, "REBUY",
                            lambda tid=slot.table_id: self._floating_table_rebuy(tid), "accent").pack(side="left", padx=2)
                continue

            if bool(state.get("cash_busy", False)):
                board_target = list(state.get("cash_board_target", []))
                board_revealed = int(state.get("cash_board_reveal_count", 0))
                if board_target and board_revealed < len(board_target):
                    phase = {3: "FLOP", 4: "TURN", 5: "RIVER"}.get(len(board_target), "BOARD")
                    record["status"].set(f"{phase} DEALING…")
                    busy_text = f"{phase} • cards turning over…"
                elif state.get("cash_deal_busy", False):
                    record["status"].set("DEALING / SQUEEZE")
                    busy_text = "Cards are being dealt…"
                elif state.get("cash_thinking_player"):
                    thinker = next((p.name for p in hand.players if p.player_id == state.get("cash_thinking_player")), "Opponent")
                    record["status"].set(f"{thinker} THINKING…")
                    busy_text = f"{thinker} is thinking…"
                else:
                    record["status"].set("GTO+ SYNC…" if state.get("cash_syncing_gto") else "CPU THINKING…")
                    busy_text = "Opponent is deciding…"
                # Rush Fold remains visible throughout preflop, including while
                # HERO is the nominal actor but card/deal animation or a CPU
                # cancellation still marks the table busy. The handler owns the
                # fast-fold cancellation and safely stops the pending work.
                if (hand.street == "preflop"
                        and is_rush_mode(state.get("cash_game_mode", RUSH_MODE))):
                    queued = bool(state.get("cash_rush_fold_pending", False))
                    fold_button = record["fold_button"]
                    fold_button.configure(
                        text="FOLD" if not queued else "FOLD ✓",
                        command=lambda tid=slot.table_id: self._handle_table_fold(tid),
                        state="disabled" if queued else "normal")
                    fold_button.pack(side="left", padx=2)
                tk.Label(actions_frame, text=busy_text, bg=COLORS["panel"],
                         fg=COLORS["gold"], font=("Segoe UI", 8, "bold")).pack(side="left", padx=5)
                continue

            # All streets use the same live legal-action renderer. Do not
            # branch away from this path on a postflop HERO turn.
            if hand.next_to_act != "hero":
                actor = hand.player(hand.next_to_act).name if hand.next_to_act else "CPU"
                record["status"].set(f"{actor} TO ACT")
                continue
            try:
                legal = hand.legal_actions("hero")
                action_names = set(legal.get("actions", []))
                # Rush & Cash always exposes fast-fold preflop, including
                # the BB/check option where the engine may omit ordinary fold
                # from its in-turn legal-action list. VIP remains a regular ring.
                rush_preflop = (hand.street == "preflop"
                                and is_rush_mode(state.get("cash_game_mode", RUSH_MODE)))
                fold_button = record["fold_button"]
                if rush_preflop or "fold" in action_names:
                    fold_command = ((lambda tid=slot.table_id: self._handle_table_fold(tid))
                                    if rush_preflop or hand.street != "preflop" else
                                    (lambda tid=slot.table_id: self._floating_table_action(tid, "fold")))
                    fold_button.configure(text="FOLD", command=fold_command, state="normal")
                    fold_button.pack(side="left", padx=2)
                else:
                    fold_button.pack_forget()
                if "check" in action_names:
                    self._compact_action_button(actions_frame, "CHECK",
                        lambda tid=slot.table_id: self._floating_table_action(tid, "check"), "accent").pack(side="left", padx=2)
                elif "call" in action_names:
                    self._compact_action_button(actions_frame, f"CALL {format_chip_amount(legal['to_call'], bb, self.chip_display_unit)}",
                        lambda tid=slot.table_id: self._floating_table_action(tid, "call"), "accent").pack(side="left", padx=2)

                if "bet" in action_names or "raise" in action_names:
                    verb = "bet" if "bet" in action_names else "raise"
                    hero_state = hand.player("hero")
                    minimum = int(legal["min_target"])
                    maximum = int(legal["max_target"])
                    minimum = min(minimum, maximum)  # short all-in is a valid target too
                    record["bet_min"], record["bet_max"] = minimum, maximum
                    record["bet_verb"], record["bet_bb"] = verb, bb
                    # GTO size is only a suggested initial value for
                    # the preflop amount field. The entry, slider and presets
                    # remain editable; submit passes the user's chosen size as-is.
                    target = minimum
                    if hand.street == "preflop" and not bool(state.get("cash_gto_spot_mode", False)):
                        suggested = self._preflop_gto_initial_raise_target(
                            table, hand, "hero", legal
                        )
                        if suggested is not None and minimum <= suggested <= maximum:
                            target = int(suggested)
                    record["bet_target_cents"].set(target)
                    record["bet_slider"].set(target)
                    record["bet_target"].set(
                        format_chip_amount(
                            target, bb, self.chip_display_unit, include_unit=False
                        )
                    )
                    self._update_bet_submit_label(slot.table_id)

                    # A small amount field makes the slider precise; presets only select.
                    tk.Label(sizes_frame, text="BET TO" if verb == "bet" else "RAISE TO", bg=COLORS["panel"],
                             fg=COLORS["muted"], font=("Segoe UI", 7, "bold")).pack(side="left", padx=(2, 4))
                    scale = tk.Scale(
                        sizes_frame, from_=minimum, to=maximum, orient="horizontal",
                        resolution=1, showvalue=False, variable=record["bet_slider"],
                        command=lambda value, tid=slot.table_id: self._on_table_bet_slider(tid, value),
                        length=190, width=10, sliderlength=15, bd=0,
                        bg=COLORS["panel"], fg=COLORS["text"], troughcolor="#344d68",
                        activebackground=COLORS["green"], highlightthickness=0,
                        relief="flat", takefocus=True,
                    )
                    scale.pack(side="left", padx=(0, 4))
                    entry = ttk.Entry(sizes_frame, textvariable=record["bet_target"], width=7,
                                      font=("Segoe UI", 8), justify="right")
                    entry.pack(side="left", padx=(0, 2))
                    entry.bind("<KeyRelease>", lambda _e, tid=slot.table_id: self._on_table_bet_entry_change(tid))
                    entry.bind("<Return>", lambda _e, tid=slot.table_id: self._submit_table_bet_enter(tid), add="+")
                    entry.bind("<KP_Enter>", lambda _e, tid=slot.table_id: self._submit_table_bet_enter(tid), add="+")
                    unit_text = "BB" if self.chip_display_unit == "BB" else "USD"
                    tk.Label(sizes_frame, text=unit_text, bg=COLORS["panel"],
                             fg=COLORS["muted"], font=("Segoe UI", 7)).pack(side="left", padx=(0, 7))

                    # Always expose the preflop situation-size control when a
                    # raise is legal. It is not gated by the hero's hand class;
                    # the click resolves the size from position + action history.
                    record["gto_size_button"] = None
                    if hand.street == "preflop" and not bool(state.get("cash_gto_spot_mode", False)):
                        gto_size_button = self._compact_action_button(
                            situation_frame, "GTO SIZE",
                            lambda tid=slot.table_id: self._apply_preflop_gto_size(tid),
                            "normal")
                        gto_size_button.pack(side="left", padx=(2, 6))
                        tk.Label(
                            situation_frame,
                            text="SIZE = POSITION + PREFLOP RAISE HISTORY (NOT YOUR HAND)",
                            bg=COLORS["panel"], fg=COLORS["muted"],
                            font=("Segoe UI", 7, "bold"),
                        ).pack(side="left", padx=2)
                        record["gto_size_button"] = gto_size_button

                    for pct in self.bet_pot_percentages:
                        self._compact_action_button(
                            sizes_frame, f"{pct}%",
                            lambda tid=slot.table_id, p=pct: self._set_table_pot_preset(tid, p),
                            "normal").pack(side="left", padx=1)

                    submit = self._compact_action_button(
                        actions_frame, "BET" if verb == "bet" else "RAISE",
                        lambda tid=slot.table_id, var=record["bet_target"]:
                            self._floating_table_bet_action(tid, var), "accent")
                    submit.pack(side="left", padx=(7, 2))
                    record["bet_action_button"] = submit
                    self._update_bet_submit_label(slot.table_id)

                tk.Label(actions_frame, text=f"TO CALL {format_chip_amount(legal['to_call'], bb, self.chip_display_unit)}",
                         bg=COLORS["panel"], fg=COLORS["muted"],
                         font=("Segoe UI", 7, "bold")).pack(side="right", padx=6)
            except Exception as exc:
                record["status"].set(f"ACTION ERROR: {exc}")
            try:
                record["window"].deiconify()
            except tk.TclError:
                pass

    def _floating_table_rebuy(self, table_id: str):
        if table_id != self.active_cash_table_id:
            if self.cash_busy:
                return
            self._save_active_cash_slot()
            self._restore_cash_slot(table_id)
        self._manual_cash_rebuy()

    def _draw_table(self, canvas=None, table=None, table_id=None, profiles=None, squeeze_count=None,
                    board_squeeze_count=None, peel_index=None, peel_progress=0.0,
                    visible_board=None, board_reveal_count=None, board_anim_index=None,
                    board_anim_indices=None, board_anim_progress=1.0, deal_counts=None, deal_flying=None,
                    thinking_player=None, hero_flip_state=None):
        """Draw the horizontal six-max table; hero is always bottom-centre."""
        external = canvas is not None
        if canvas is None:
            if not hasattr(self, "table_canvas"):
                # There is deliberately no playable table inside the lobby root.
                # Persist the active state and redraw each independent table window.
                self._save_active_cash_slot()
                self._refresh_table_windows()
                return
            canvas = self.table_canvas
        if table is None:
            table = self.cash_table
        if profiles is None:
            profiles = self.cash_cpu_profiles
        if squeeze_count is None:
            squeeze_count = self.hero_squeeze_count
        if board_squeeze_count is None:
            board_squeeze_count = self.board_squeeze_count
        if hero_flip_state is None:
            hero_flip_state = self.cash_initial_flip
        if not external:
            self._save_active_cash_slot()
        w = max(700 if not external else 320, canvas.winfo_width())
        h = max(420 if not external else 260, canvas.winfo_height())
        canvas.delete("all")
        bg_name = str(self.appearance.get("table_background", "Midnight"))
        bg_base, bg_glow, bg_vignette = TABLE_BACKGROUND_THEMES.get(
            bg_name, TABLE_BACKGROUND_THEMES["Midnight"])
        canvas.create_rectangle(0, 0, w, h, fill=bg_base, outline="")
        # Stippled ambient pools create depth without the cost of a raster
        # background or reducing contrast behind player controls.
        canvas.create_oval(w*.08, h*.015, w*.92, h*.99, fill=bg_glow,
                           outline="", stipple="gray75", tags=("table_background",))
        canvas.create_oval(w*.18, h*.70, w*.82, h*1.10, fill=bg_vignette,
                           outline="", stipple="gray75", tags=("table_background",))
        slot_for_specials = self.multi_tables.get(table_id) if table_id else None
        special_state = slot_for_specials.state if slot_for_specials else {}
        drop_notice = special_state.get("cash_drop_notice") or {}
        drop_live = bool(drop_notice and time.monotonic() < float(drop_notice.get("started", 0.0)) + float(drop_notice.get("duration", 0.0)))
        # Layered premium rail: dark contact shadow, warm wood, brass piping and
        # a soft inner cushion.  The nested edges make the table feel recessed.
        canvas.create_oval(w * .024, h * .080, w * .976, h * .956,
                           fill="#020609", outline="#06090b", width=2)
        canvas.create_oval(w * .030, h * .086, w * .970, h * .948,
                           fill="#17130f", outline="#725a35", width=13)
        canvas.create_oval(w * .038, h * .098, w * .962, h * .936,
                           fill="#30271d", outline="#c8a45e", width=2)
        canvas.create_arc(w * .045, h * .105, w * .955, h * .928,
                          start=18, extent=145, style="arc", outline="#f1dba7",
                          width=2, tags=("table_rail_highlight",))
        canvas.create_oval(w * .048, h * .112, w * .952, h * .920,
                           fill="#12231e", outline="#6f5734", width=4)
        felt, felt_inner, felt_edge = FELT_THEMES.get(str(self.appearance.get("felt_theme", "Emerald")), FELT_THEMES["Emerald"])
        if drop_live:
            felt, felt_inner, felt_edge = ("#b75b1d", "#874014", "#e6a04d")
        canvas.create_oval(w * .056, h * .126, w * .944, h * .906,
                           fill=felt, outline=felt_edge, width=3)
        canvas.create_oval(w * .17, h * .24, w * .83, h * .77,
                           fill=felt_inner, outline=felt_edge, width=1)
        canvas.create_oval(w * .176, h * .248, w * .824, h * .762,
                           fill="", outline="#ffffff", width=1, stipple="gray75")
        # Fine inner pinstripe and a very low-contrast Pigeon Poker medallion
        # carry the visual-work branch's branding into the newer dynamic table.
        # These are painted beneath cards/chips, so live game information stays clear.
        canvas.create_oval(w * .075, h * .151, w * .925, h * .879,
                           fill="", outline="#b9a06a", width=1,
                           tags=("felt_pinstripe",))
        canvas.create_oval(w * .315, h * .445, w * .685, h * .655,
                           fill="", outline="#ffffff", width=1,
                           stipple="gray75", tags=("felt_medallion",))
        canvas.create_text(w * .5, h * .555, text="P I G E O N   P O K E R",
                           fill="#ffffff", stipple="gray50",
                           font=("Segoe UI", max(8, int(h * .018)), "bold"),
                           tags=("felt_wordmark",))
        # Short, evenly spaced rail stitches add detail without a noisy texture.
        stitch_color = "#d2b77c" if not drop_live else "#f1bf79"
        for stitch_i in range(36):
            angle = (2 * math.pi * stitch_i / 36) - math.pi / 2
            cx, cy = w * .5, h * .52
            rx, ry = w * .447, h * .365
            x1 = cx + math.cos(angle) * rx
            y1 = cy + math.sin(angle) * ry
            x2 = cx + math.cos(angle) * (rx - w * .006)
            y2 = cy + math.sin(angle) * (ry - h * .009)
            canvas.create_line(x1, y1, x2, y2, fill=stitch_color, width=1,
                               tags=("table_rail_stitch",))
        if bool(special_state.get("cash_sitting_out", False)):
            # A paused table is deliberately empty: HERO alone remains seated.
            paused_hand = table.hand if table is not None else None
            hero_player = next((p for p in paused_hand.players if p.player_id == "hero"), None) if paused_hand else None
            hero_seat = next((s for s in table.seats if s.get("id") == "hero"), None) if table is not None else None
            hero_stack = int(hero_player.stack if hero_player is not None else (hero_seat or {}).get("stack", 0))
            stack_text = self._format_table_chips(hero_stack, max(1, int(getattr(table, "big_blind", 1))), self.chip_display_unit) if table is not None else ""
            cx, cy = w * .50, h * .76
            radius = max(23, min(34, int(min(w, h) * .045)))
            canvas.create_oval(cx-radius, cy-radius, cx+radius, cy+radius,
                               fill="#172b3c", outline="#d6b977", width=2, tags=("sitout_hero",))
            canvas.create_text(cx, cy, text="YOU", fill="#f2dfae",
                               font=("Segoe UI", max(10, int(radius*.43)), "bold"), tags=("sitout_hero",))
            canvas.create_text(cx, cy+radius+18, text="SITTING OUT", fill="#f0d18a",
                               font=("Segoe UI", 10, "bold"), tags=("sitout_hero",))
            canvas.create_text(cx, cy+radius+38, text=f"STACK  {stack_text}", fill="#d8e2ea",
                               font=("Segoe UI", 9, "bold"), tags=("sitout_hero",))
            canvas.create_text(w*.5, h*.40, text="TEMPORARILY AWAY", fill="#b7c8cf",
                               font=("Segoe UI", 12, "bold"), tags=("sitout_status",))
            return
        # Sparse, theme-matched felt grain catches light without turning into
        # a noisy texture or adding hundreds of canvas objects per animation.
        grain = {"Emerald": "#176b50", "Blue": "#1b6b91",
                 "Red": "#873542", "Charcoal": "#4a5960"}.get(
                     str(self.appearance.get("felt_theme", "Emerald")), "#176b50")
        felt_cx, felt_cy = w * .50, h * .505
        felt_rx, felt_ry = w * .315, h * .255
        for row, v in enumerate((.30, .40, .60, .70)):
            norm_y = (v - .505) / .255
            span = felt_rx * math.sqrt(max(0.0, 1.0 - norm_y * norm_y))
            for col in range(9):
                u = (col + .5 + (.25 if row % 2 else 0.0)) / 9.5
                gx = felt_cx - span + 2.0 * span * u
                gy = felt_cy + (v - .505) * h
                canvas.create_line(gx, gy, gx + 2.2, gy + .8,
                                   fill=grain, width=1, tags=("felt_grain",))
        if table is None or table.hand is None:
            canvas.create_text(w/2, h/2, text="CASH & RUSH  •  WAITING FOR HAND", fill="white",
                               font=("Segoe UI", 16, "bold"))
            return
        hand = table.hand
        runout_boards_for_display = [list(row) for row in (getattr(hand, "runout_boards", []) or [])]
        multi_runout_display = bool(hand.finished and len(runout_boards_for_display) > 1)
        hero_index = next((i for i, player in enumerate(hand.players) if player.player_id == "hero"), 3)
        # Offset 0 is hero at bottom-centre; other seats progress clockwise around the oval.
        relative_positions = [
            (w*.50, h*.84), (w*.205, h*.69), (w*.205, h*.29),
            (w*.50, h*.125), (w*.795, h*.29), (w*.795, h*.69),
        ]
        if len(hand.players) == 2:
            relative_positions = [(w*.50, h*.83), (w*.50, h*.15)]
        positions = [relative_positions[(i-hero_index) % len(hand.players)] for i in range(len(hand.players))]

        # Board and pot occupy the middle, as on the reference client.
        # Pot is deliberately placed immediately above the community-card row,
        # not beneath the top player's cards or in the bottom action strip.
        pot_text = ("POT PAID" if hand.finished and hand.winner_reason in {"showdown", "fold"}
                    else f"POT  {self._format_table_chips(hand.pot, table.big_blind)}")
        pot_label_y = h*.145 if multi_runout_display else h*.315
        pot_plaque_w = max(112, min(206, len(pot_text) * 8.2 + 30))
        canvas.create_rectangle(w/2-pot_plaque_w/2, pot_label_y-13,
                                w/2+pot_plaque_w/2, pot_label_y+13,
                                fill="#101d19", outline="#9b7d48", width=1,
                                tags=("pot_plaque",))
        canvas.create_line(w/2-pot_plaque_w/2+8, pot_label_y-10,
                           w/2+pot_plaque_w/2-8, pot_label_y-10,
                           fill="#d8bf86", width=1, tags=("pot_plaque_sheen",))
        canvas.create_text(w/2+1, pot_label_y+1, text=pot_text, fill="#070c0a",
                           font=("Segoe UI", 11 if multi_runout_display else 12, "bold"), tags=("pot_label_shadow",))
        canvas.create_text(w/2, pot_label_y, text=pot_text, fill="#f7e2a3",
                           font=("Segoe UI", 11 if multi_runout_display else 12, "bold"), tags=("pot_label",))
        if drop_live:
            elapsed = max(0.0, time.monotonic() - float(drop_notice.get("started", 0.0)))
            progress = min(1.0, elapsed / max(.1, float(drop_notice.get("duration", 1.65))))
            drop_label = f"CASH DROP  •  {int(drop_notice.get('amount', 0) / max(1, table.big_blind))} BB"
            canvas.create_rectangle(w*.34, h*.205, w*.66, h*.255,
                                    fill="#5b2d13", outline="#f4b45d", width=2,
                                    tags=("cash_drop_banner",))
            canvas.create_text(w*.5, h*.23, text=drop_label, fill="#ffe7bd",
                               font=("Segoe UI", 11, "bold"), tags=("cash_drop_banner",))
            palette = ("#f2c55d", "#d9e2e7", "#b77d43")
            for idx in range(18):
                x = w*(.16 + ((idx*37) % 68)/100)
                phase = (progress + idx*.071) % 1.0
                y = h*(.12 + phase*.48)
                color = palette[idx % len(palette)]
                canvas.create_oval(x-6, y-3, x+6, y+3, fill=color,
                                   outline="#714f26", width=1, tags=("cash_drop_falling",))
        # Exact denomination stacks represent the live pot; chip colours always
        # remain BB-denominated even when the amount labels are shown in USD.
        pot_animation = None
        table_record = self.table_windows.get(table_id) if table_id else None
        if table_record:
            pot_animation = table_record.get("pot_animation")
        anim_active = bool(pot_animation and time.monotonic() < float(pot_animation.get("visible_until", 0.0)))
        if (not multi_runout_display
                and not (hand.finished and hand.winner_reason in {"showdown", "fold"} and anim_active)
                and int(hand.pot) > 0):
            draw_chip_cluster(canvas, w*.50, h*.351, int(hand.pot), int(table.big_blind),
                              scale=.84, max_width=128, tags=("pot_chips",),
                              max_visible_layers=8)
        board = list(hand.board)
        rabbit_board = special_state.get("cash_rabbit_hunt_board") if hand.finished else None
        rabbit_board = list(rabbit_board) if rabbit_board else None
        if rabbit_board and len(rabbit_board) == 5:
            canvas.create_text(w/2, h*.365, text="RABBIT HUNT  •  HYPOTHETICAL RUNOUT",
                               fill="#e2b96d", font=("Segoe UI", 8, "bold"), tags=("rabbit_hunt_label",))
        else:
            runout_boards_for_display = [list(row) for row in (getattr(hand, "runout_boards", []) or [])]
            if hand.finished and len(runout_boards_for_display) > 1:
                canvas.create_text(w/2, h*.255,
                                   text=f"RUN IT {len(runout_boards_for_display)}×  •  SPLIT RUNOUT",
                                   fill="#f0cf82", font=("Segoe UI", 9, "bold"),
                                   tags=("street_label",))
            else:
                canvas.create_text(w/2, h*.53, text=hand.street.upper(), fill="#c7e7d9",
                                   font=("Segoe UI", 8, "bold"), tags=("street_label",))
        # Multi-runout showdowns display one compact, clearly labelled row per
        # completed board. The normal one-board path retains its reveal animation.
        if multi_runout_display:
            run_card_w = max(34, min(43, int(w * .035)))
            run_card_h = int(run_card_w * 1.36)
            run_gap = 5
            row_gap = max(8, int(h * .015))
            total_rows_h = len(runout_boards_for_display) * (run_card_h + row_gap) - row_gap
            run_start_y = max(h * .29, (h - total_rows_h) / 2 - 8)
            for run_index, run_board in enumerate(runout_boards_for_display):
                row_y = run_start_y + run_index * (run_card_h + row_gap)
                canvas.create_text(w*.205, row_y + run_card_h/2,
                                   text=f"BOARD {run_index + 1}", anchor="e",
                                   fill="#e9cc87", font=("Segoe UI", 7, "bold"),
                                   tags=("runout_board_label",))
                row_start_x = w*.5 - (5*run_card_w + 4*run_gap)/2
                for card_index, run_card in enumerate(run_board[:5]):
                    self._draw_card(canvas, row_start_x + card_index*(run_card_w+run_gap),
                                    row_y, run_card, run_card_w, run_card_h)
            board_layout = []
        else:
            board_layout = list(rabbit_board or (board if visible_board is None else visible_board))
        reveal_count = len(board_layout) if board_reveal_count is None else max(0, min(len(board_layout), int(board_reveal_count)))
        board_anim_set = set(int(i) for i in (board_anim_indices or []))
        if deal_counts is None:
            deal_counts = {p.player_id: 2 for p in hand.players}
        card_w = max(42, min(54, int(w * .043)))
        card_h = int(card_w * 1.38)
        card_gap = max(6, int(card_w * .15))
        board_y = h*.395
        start_x = w/2 - (len(board_layout)*card_w + max(0, len(board_layout)-1)*card_gap)/2
        ordered_board_anim_indices = sorted(board_anim_set)
        for i, card in enumerate(board_layout):
            card_x = start_x + i*(card_w+card_gap)
            if i in board_anim_set or board_anim_index == i:
                reveal_progress = board_anim_progress
                if i in board_anim_set and len(ordered_board_anim_indices) > 1:
                    reveal_progress = staggered_progress(
                        board_anim_progress,
                        ordered_board_anim_indices.index(i),
                        len(ordered_board_anim_indices),
                        stagger_fraction=0.12,
                    )
                reveal_lift = math.sin(math.pi * max(0.0, min(1.0, reveal_progress))) * 6.5
                reveal_tilt = math.sin(math.pi * max(0.0, min(1.0, reveal_progress))) * 3.6
                self._draw_card_3d(canvas, card_x, board_y-reveal_lift, card, card_w, card_h,
                                   progress=reveal_progress, tilt=reveal_tilt, tag="board_card_3d")
            elif i < reveal_count or (rabbit_board is not None and i < len(rabbit_board)):
                self._draw_card(canvas, card_x, board_y, card, card_w, card_h)
                if rabbit_board is not None and i >= len(hand.board):
                    canvas.create_rectangle(card_x+1, board_y+1, card_x+card_w-1, board_y+card_h-1,
                                            fill="#1b2430", stipple="gray50", outline="#d6ad62",
                                            dash=(3, 2), tags=("rabbit_hunt_card",))
            else:
                self._draw_card_back(canvas, card_x, board_y, card_w, card_h)
        active_indices = [i for i, player in enumerate(hand.players) if player.hole_cards]
        if len(active_indices) == 2:
            sb_index = table.dealer_index
            bb_index = next((table.dealer_index + i) % 6 for i in range(1, 7)
                            if (table.dealer_index + i) % 6 in active_indices)
        else:
            sb_index = next((table.dealer_index + i) % 6 for i in range(1, 7)
                            if (table.dealer_index + i) % 6 in active_indices)
            bb_index = next((sb_index + i) % 6 for i in range(1, 7)
                            if (sb_index + i) % 6 in active_indices)
        for i, player in enumerate(hand.players):
            x, y = positions[i]
            is_hero = player.player_id == "hero"
            is_actor = hand.next_to_act == player.player_id
            is_dealer = i == table.dealer_index
            if not player.hole_cards:
                state = "SITTING OUT"
            elif player.folded:
                state = "FOLDED"
            elif player.all_in:
                state = "ALL-IN"
            elif is_actor:
                state = "YOUR TURN" if is_hero else ("THINKING…" if thinking_player == player.player_id else "TO ACT")
            else:
                state = "IN HAND"
            width = 174 if external else 138
            card_label = "YOU" if is_hero else player.name
            # Move the identity panel a little toward the felt centre, leaving
            # a clean outer lane for the two hole cards and preventing avatar
            # badges from being hidden behind card corners.
            panel_x = x
            panel_y = y
            box_top = panel_y - 32
            box_bottom = panel_y + 32
            fill = "#1d493d" if is_hero else ("#1d3b5b" if player.hole_cards and not player.folded else "#101a28")
            if is_actor and not is_hero:
                fill = "#254b59"
            outline = COLORS["gold"] if is_actor else ("#4b9a79" if is_hero else "#40566d")
            seat_tag = f"seat_{player.player_id}"
            # Rounded, layered seat frame from the visual branch.  Its geometry
            # changes only the panel silhouette; all current avatar/HUD/role
            # content below remains intact.
            sx1, sx2 = panel_x-width/2, panel_x+width/2
            sy1, sy2 = box_top, box_bottom
            radius = 10
            seat_shape = [sx1+radius, sy1, sx2-radius, sy1, sx2, sy1+radius,
                          sx2, sy2-radius, sx2-radius, sy2, sx1+radius, sy2,
                          sx1, sy2-radius, sx1, sy1+radius]
            shadow_shape = [sx1+radius+3, sy1+4, sx2-radius+3, sy1+4,
                            sx2+3, sy1+radius+4, sx2+3, sy2-radius+4,
                            sx2-radius+3, sy2+4, sx1+radius+3, sy2+4,
                            sx1+3, sy2-radius+4, sx1+3, sy1+radius+4]
            canvas.create_polygon(*shadow_shape, smooth=True, splinesteps=12,
                                  fill="#02080d", outline="",
                                  tags=("seat_shadow", seat_tag))
            if is_actor:
                outer = [sx1+radius, sy1-4, sx2-radius, sy1-4,
                         sx2+4, sy1+radius, sx2+4, sy2-radius,
                         sx2-radius, sy2+4, sx1+radius, sy2+4,
                         sx1-4, sy2-radius, sx1-4, sy1+radius]
                canvas.create_polygon(*outer, smooth=True, splinesteps=12,
                                      fill="#4b3a20", outline="#d8b96e", width=1,
                                      tags=("active_seat_glow", seat_tag))
                inner = [sx1+radius, sy1-1, sx2-radius, sy1-1,
                         sx2+1, sy1+radius, sx2+1, sy2-radius,
                         sx2-radius, sy2+1, sx1+radius, sy2+1,
                         sx1-1, sy2-radius, sx1-1, sy1+radius]
                canvas.create_polygon(*inner, smooth=True, splinesteps=12,
                                      fill="#193c36", outline="#f0d18b", width=1,
                                      tags=("active_seat_glow", seat_tag))
            canvas.create_polygon(*seat_shape, smooth=True, splinesteps=12,
                                  fill=fill, outline=outline, width=2 if is_actor else 1,
                                  tags=("seat", seat_tag))
            canvas.create_line(sx1+radius, box_top+2, sx2-radius, box_top+2,
                               fill="#ffffff" if is_actor else "#6d8294", width=1,
                               tags=("seat_top_sheen", seat_tag))
            # A compact identity medallion gives each seat a visual anchor. CPU
            # avatar IDs map deterministically to a restrained colour/suit pair,
            # while HERO has a dedicated green identity plate.
            profile_for_avatar = profiles.get(player.player_id) if not is_hero and profiles else None
            avatar_id = str(getattr(profile_for_avatar, "avatar", "avatar-01"))
            try:
                avatar_index = max(0, int(avatar_id.rsplit("-", 1)[-1]) - 1)
            except (TypeError, ValueError):
                avatar_index = sum(ord(ch) for ch in avatar_id) % 24
            avatar_palette = ("#315d7a", "#6b3f4c", "#4d6548", "#66533d",
                              "#4e4e79", "#2f6b69", "#78544d", "#596474")
            avatar_symbol = ("♠", "♥", "♦", "♣", "◆", "★")[avatar_index % 6]
            avatar_ink = ("#d9e9f4", "#f0c2c9", "#d9e9f4", "#c8ebd3", "#e0dcff", "#d5f2e9")[avatar_index % 6]
            avatar_x, avatar_y = panel_x-width/2+20, panel_y
            avatar_fill = "#1d5945" if is_hero else avatar_palette[avatar_index % len(avatar_palette)]
            avatar_outline = "#f0d18b" if is_actor or is_hero else "#8295a7"
            canvas.create_oval(avatar_x-15, avatar_y-15, avatar_x+15, avatar_y+15,
                               fill="#071018", outline="#05090d", width=2,
                               tags=("seat_avatar_shadow", seat_tag))
            canvas.create_oval(avatar_x-12, avatar_y-12, avatar_x+12, avatar_y+12,
                               fill=avatar_fill, outline=avatar_outline, width=2 if is_actor or is_hero else 1,
                               tags=("seat_avatar", seat_tag))
            canvas.create_text(avatar_x, avatar_y, text="Y" if is_hero else avatar_symbol,
                               fill="#f7f2e5" if is_hero else avatar_ink,
                               font=("Segoe UI Symbol", 13, "bold"),
                               tags=("seat_avatar", seat_tag))
            text_left = panel_x-width/2+39
            canvas.create_text(text_left, panel_y-19, text=card_label, anchor="w", fill="white",
                               font=("Segoe UI", 9, "bold"), tags=("seat", seat_tag))
            if not is_hero and is_vip_mode(special_state.get("cash_game_mode", self.cash_game_mode)):
                table_vip_roles = special_state.get("vip_cpu_roles", self.vip_cpu_roles)
                vip_role_text = vip_cpu_role_label(table_vip_roles.get(player.player_id))
                if vip_role_text:
                    canvas.create_text(text_left, panel_y-5, text=vip_role_text, anchor="w",
                                       fill="#f0d18a" if vip_role_text.startswith("PURE") else "#b8c8e5",
                                       font=("Segoe UI", 6, "bold"), tags=("seat", seat_tag))
            stack_tags = ("seat", seat_tag, "hero_stack_toggle") if is_hero else ("seat", seat_tag)
            stack_label = self._format_table_chips(player.stack, table.big_blind)
            stack_text_id = canvas.create_text(
                text_left, panel_y+5, text=stack_label, anchor="w",
                fill="#fff0ba" if is_hero else "#cbd8e6",
                font=("Segoe UI", 8, "bold" if is_hero else "normal"), tags=stack_tags)
            canvas.create_text(panel_x+width/2-7, panel_y+5, text=state, anchor="e",
                               fill="#cbd8e6", font=("Segoe UI", 7, "bold"), tags=("seat", seat_tag))
            if is_hero:
                canvas.create_text(panel_x-width/2+82, panel_y+5, text="↔", anchor="w",
                                   fill="#d4b875", font=("Segoe UI", 7, "bold"),
                                   tags=("seat", seat_tag, "hero_stack_toggle"))
                canvas.tag_bind("hero_stack_toggle", "<Enter>",
                                lambda _event, c=canvas: c.configure(cursor="hand2"))
                canvas.tag_bind("hero_stack_toggle", "<Leave>",
                                lambda _event, c=canvas: c.configure(cursor="arrow"))
                canvas.tag_bind("hero_stack_toggle", "<Button-1>",
                                lambda _event, tid=self.active_cash_table_id: self._toggle_table_chip_unit(tid))
            if not is_hero and player.player_id.startswith("cpu"):
                profile = profiles.get(player.player_id)
                if profile is not None:
                    hud = {"vpip": profile.vpip, "pfr": profile.pfr,
                           "three_bet": profile.three_bet, "af": profile.aggression_factor,
                           "hands": profile.hands}
                    hud_text = format_hud_line(hud, self.hud_fields)
                    if hud_text:
                        canvas.create_text(text_left, panel_y+22, text=hud_text, anchor="w",
                                           fill="#96b8ca", font=("Segoe UI", 7), tags=("seat_hud", seat_tag))
                canvas.tag_bind(seat_tag, "<Button-1>",
                                lambda _event, cpu_id=player.player_id: self._show_cpu_profile_popup(cpu_id))
                canvas.tag_bind(seat_tag, "<Enter>", lambda _event: canvas.configure(cursor="hand2"))
                canvas.tag_bind(seat_tag, "<Leave>", lambda _event: canvas.configure(cursor=""))
            role = "BTN" if is_dealer else ("SB" if i == sb_index else ("BB" if i == bb_index else ""))
            if role:
                badge_w = 34 if role == "BTN" else 24
                badge_x = panel_x + width/2 - badge_w/2 - 7
                badge_y = panel_y - 18
                badge_fill = "#e6c77d" if role == "BTN" else "#273c4b"
                badge_ink = "#241d12" if role == "BTN" else "#e9d39b"
                canvas.create_rectangle(badge_x-badge_w/2, badge_y-8,
                                        badge_x+badge_w/2, badge_y+8,
                                        fill=badge_fill, outline="#f5e1a7" if role == "BTN" else "#718596",
                                        width=1, tags=("position_badge", role.lower()))
                canvas.create_text(badge_x, badge_y, text=role, anchor="center",
                                   fill=badge_ink, font=("Segoe UI", 7, "bold"),
                                   tags=("position_badge", role.lower()))
            dealt_count = max(0, min(2, int(deal_counts.get(player.player_id, 2))))
            # Hole cards belong to the outer player lane; wagers move inward.
            away_x, away_y = x - w*.5, y - h*.53
            away_len = max(1.0, math.hypot(away_x, away_y))
            card_offset = max(104.0, min(172.0, h*.24))
            card_center_x = max(54.0, min(w-54.0, x + away_x/away_len*card_offset))
            card_center_y = max(36.0, min(h-36.0, y + away_y/away_len*card_offset))
            if is_hero and len(player.hole_cards) == 2 and not player.folded:
                squeeze_on = bool(self.card_squeeze_enabled_var.get())
                reveal = max(0, min(2, int(squeeze_count))) if squeeze_on else 2
                flip_index = int(hero_flip_state.get("index", 0)) if isinstance(hero_flip_state, dict) else 0
                flip_progress = float(hero_flip_state.get("progress", 0.0)) if isinstance(hero_flip_state, dict) else 0.0
                flip_complete = bool(hero_flip_state.get("complete", False)) if isinstance(hero_flip_state, dict) else False
                flip_active = bool(hero_flip_state.get("active", False)) if isinstance(hero_flip_state, dict) else False
                card_w_hole, card_h_hole = 48, 66
                card_y = card_center_y - card_h_hole/2
                for card_index, card in enumerate(player.hole_cards):
                    card_x = card_center_x - 52 + card_index*56
                    mode = hole_card_display_mode(
                        card_index, dealt_count,
                        squeeze_enabled=squeeze_on,
                        squeeze_count=reveal,
                        flip_state=hero_flip_state,
                        peel_index=peel_index,
                        peel_progress=peel_progress,
                    )
                    if mode == "hidden":
                        continue
                    if mode == "face":
                        self._draw_card(canvas, card_x, card_y, card, card_w_hole, card_h_hole)
                    elif mode == "flip":
                        # During the no-squeeze open, the first completed card
                        # remains face-up while only the second card flips.
                        self._draw_card_3d(canvas, card_x, card_y, card,
                                           card_w_hole, card_h_hole,
                                           progress=flip_progress, tag="hero_initial_flip")
                    elif mode == "peel":
                        self._draw_peel_card(canvas, card_x, card_y, card,
                                             card_w_hole, card_h_hole, peel_progress)
                    else:
                        self._draw_card_back(canvas, card_x, card_y, card_w_hole, card_h_hole)
                # Display the made hand under HERO's cards. Never leak the hand
                # while Card Squeeze is still closed or the normal flip is incomplete.
                cards_are_visible = (
                    (squeeze_on and reveal >= 2)
                    or (not squeeze_on and flip_complete)
                    or (hand.finished and hand.winner_reason == "showdown")
                )
                if cards_are_visible and len(hand.board) + len(player.hole_cards) >= 2:
                    rank_text = current_hand_badge(player.hole_cards + hand.board)
                    rank_y = card_center_y + card_h_hole / 2 + 12
                    rank_width = min(284, max(150, len(rank_text) * 8.2 + 22))
                    canvas.create_rectangle(card_center_x-rank_width/2, rank_y-9,
                                            card_center_x+rank_width/2, rank_y+10,
                                            fill="#0b211b", outline="#b99a58", width=1,
                                            tags=("hero_made_hand",))
                    canvas.create_text(card_center_x, rank_y, text=rank_text,
                                       fill="#f5e3ad", font=("Segoe UI", 8, "bold"),
                                       tags=("hero_made_hand",))
            elif (hand.finished and hand.winner_reason == "showdown"
                  and player.eligible and len(player.hole_cards) == 2):
                # Only an actual showdown may expose opponents' hole cards.
                self._draw_card(canvas, x-50, y+38, player.hole_cards[0], 42, 58)
                self._draw_card(canvas, x+4, y+38, player.hole_cards[1], 42, 58)
            elif player.hole_cards and not player.folded:
                for card_index in range(dealt_count):
                    card_x = card_center_x - 43 + card_index*48
                    self._draw_card_back(canvas, card_x, card_center_y-26, 38, 52)
            if player.street_contribution:
                # Project the wager inward from the outer seat band, so the chip
                # stack/amount do not overlap names, hole cards or player state.
                dx, dy = (w * .5 - x), (h * .53 - y)
                distance = max(1.0, math.hypot(dx, dy))
                inward = (90.0 if abs(dx) < w * .12 else max(112.0, min(128.0, h * .19)))
                chip_x = x + dx / distance * inward
                chip_y = y + dy / distance * inward
                draw_chip_cluster(canvas, chip_x, chip_y+2,
                                  int(player.street_contribution), int(table.big_blind),
                                  scale=.78, max_width=112, tags=("bet_chips",),
                                  max_visible_layers=7)
                bet_label = self._format_table_chips(player.street_contribution, table.big_blind)
                bet_label_width = max(34, len(bet_label) * 7.0 + 14)
                canvas.create_rectangle(chip_x-bet_label_width/2, chip_y-25,
                                        chip_x+bet_label_width/2, chip_y-10,
                                        fill="#101a18", outline="#8f7546", width=1,
                                        tags=("bet_amount",))
                canvas.create_text(chip_x, chip_y-17.5, text=bet_label,
                                   fill="#ffe5a1", font=("Segoe UI", 9, "bold"),
                                   tags=("bet_amount",))
        # Action clock sits beside HERO's hole cards so it is visible without
        # looking to a distant top-right header. The label is updated in-place.
        if table_id and table_id in self.table_windows:
            record_for_clock = self.table_windows[table_id]
            state_for_clock = self.multi_tables.get(table_id).state if self.multi_tables.get(table_id) else {}
            deadline_for_clock = float(state_for_clock.get("cash_squeeze_deadline_at", 0.0) or 0.0)
            if deadline_for_clock > time.monotonic() and hand.next_to_act == "hero" and not hand.finished:
                hero_x, hero_y = positions[hero_index]
                to_center_x, to_center_y = (w * .5 - hero_x), (h * .53 - hero_y)
                center_len = max(1.0, math.hypot(to_center_x, to_center_y))
                card_offset = max(50.0, min(78.0, h * .13))
                hole_x = hero_x + to_center_x / center_len * card_offset
                hole_y = hero_y + to_center_y / center_len * card_offset
                clock_x, clock_y = hole_x + 82, hole_y + 5
                state_mode = str(state_for_clock.get("cash_action_deadline_mode", "action"))
                remaining = max(0, int(deadline_for_clock - time.monotonic() + .999))
                clock_colour = "#ff7777" if remaining <= 5 else ("#74dcae" if state_mode.startswith("timebank") else "#f6d982")
                bg1 = canvas.create_oval(clock_x-23, clock_y-14, clock_x+23, clock_y+14,
                                         fill="#102d28", outline=clock_colour, width=1,
                                         tags=("hero_action_clock",))
                label_item = canvas.create_text(clock_x, clock_y, text=f"{remaining:02d}s",
                                                fill=clock_colour, font=("Segoe UI", 9, "bold"),
                                                tags=("hero_action_clock",))
                record_for_clock["timer_canvas_item"] = ([bg1], label_item)
            else:
                record_for_clock["timer_canvas_item"] = None

        # A compact action plaque appears on the inner lane beside the acting seat.
        if table_id and self.multi_tables.get(table_id):
            flash = self.multi_tables.get(table_id).state.get("cash_action_flash") or {}
            if flash and time.monotonic() < float(flash.get("expires_at", 0.0)):
                actor_index = next((idx for idx, item in enumerate(hand.players)
                                    if item.player_id == flash.get("player_id")), None)
                if actor_index is not None:
                    ax, ay = positions[actor_index]
                    cx, cy = w * .50, h * .53
                    bx = ax + (cx - ax) * .25
                    by = ay + (cy - ay) * .25
                    badge_text = str(flash.get("text", "ACTION"))
                    badge_width = max(68, min(176, 16 + len(badge_text) * 7.1))
                    canvas.create_rectangle(bx-badge_width/2, by-13, bx+badge_width/2, by+13,
                                            fill="#f1cf7a", outline="#fff0c0", width=1,
                                            tags=("action_flash",))
                    canvas.create_text(bx, by, text=badge_text, fill="#261f13",
                                       font=("Segoe UI", 8, "bold"), tags=("action_flash",))

        # A card visibly travels from the dealer area to each seat during the deal.
        if deal_flying:
            flying_pid = deal_flying.get("player_id")
            flying_index = int(deal_flying.get("card_index", 0))
            player_index = next((idx for idx, item in enumerate(hand.players)
                                 if item.player_id == flying_pid), None)
            if player_index is not None:
                relative = (player_index - hero_index) % len(hand.players)
                seat_x, seat_y = relative_positions[relative]
                is_flying_hero = flying_pid == "hero"
                away_x, away_y = seat_x - w*.5, seat_y - h*.53
                away_len = max(1.0, math.hypot(away_x, away_y))
                card_offset = max(104.0, min(172.0, h*.24))
                card_center_x = max(54.0, min(w-54.0, seat_x + away_x/away_len*card_offset))
                card_center_y = max(36.0, min(h-36.0, seat_y + away_y/away_len*card_offset))
                dest_x = card_center_x - (52 if is_flying_hero else 43) + flying_index * (56 if is_flying_hero else 48)
                dest_y = card_center_y - (33 if is_flying_hero else 26)
                progress = max(0.0, min(1.0, float(deal_flying.get("progress", 0.0))))
                start_x, start_y = w * .5, h * .5
                eased = progress * progress * (3 - 2 * progress)
                fx = start_x + (dest_x - start_x) * eased
                # Tiny lift arc and gradual approach create a physical slide instead of a flat teleport.
                fy = start_y + (dest_y - start_y) * eased - math.sin(math.pi * progress) * 12.0
                card_scale = .90 + .10 * eased
                flight_w, flight_h = 31 * card_scale, 43 * card_scale
                flight_tilt = math.sin(math.pi * progress) * (-8.0 if flying_index == 0 else 7.0)
                self._draw_card_3d(canvas, fx + (31-flight_w)/2, fy + (43-flight_h)/2,
                                   "As", flight_w, flight_h, progress=0.0,
                                   tilt=flight_tilt, tag="dealing_card_3d")

        if hand.finished and hand.winner_reason == "showdown":
            winners = []
            for award in hand.awards:
                winners.extend(award.winners)
            canvas.create_text(w/2, h*.285, text="SHOWDOWN  •  " + ", ".join(dict.fromkeys(winners)),
                               fill=COLORS["gold"], font=("Segoe UI", 11, "bold"))
        if table_record and pot_animation:
            self._draw_pot_award_overlay(canvas, table, table_record, w, h, hero_index)
        if table_record:
            self._draw_social_reaction_overlay(canvas, hand, w, h, hero_index, table)
            self._draw_big_pot_celebration_overlay(canvas, hand, w, h, hero_index, table)
        if not external:
            self._refresh_cash_history()
            self._refresh_table_windows()

    def _ensure_pot_award_animation(self, table_id: str, hand):
        """Start one visible payout/chop animation after a hand is settled."""
        if hand.winner_reason not in {"showdown", "fold"}:
            return
        record = self.table_windows.get(table_id)
        if record is None:
            return
        hand_key = (id(hand), str(hand.winner_reason))
        if record.get("pot_animation_key") == hand_key:
            return
        payouts: dict[str, int] = {}
        if hand.winner_reason == "showdown":
            for award in hand.awards:
                winners = list(award.winners)
                if not winners:
                    continue
                distributable = max(0, int(award.amount) - int(award.rake))
                for winner_id, share in payout_shares(distributable, winners).items():
                    payouts[winner_id] = payouts.get(winner_id, 0) + share
        else:
            event = next((e for e in reversed(hand.events)
                          if e.get("type") == "hand_won_by_fold"), None)
            if event:
                payouts[str(event.get("winner"))] = int(event.get("amount", hand.pot))
        payouts = {pid: amt for pid, amt in payouts.items() if amt > 0}
        if not payouts:
            return
        names = {p.player_id: p.name for p in hand.players}
        winners = list(payouts)
        record["pot_animation_key"] = hand_key
        record["social_effect_hand_key"] = id(hand)
        now = time.monotonic()
        record["pot_animation"] = {
            "started": now, "move_duration": POT_AWARD_MOVE_MS / 1000.0,
            "visible_until": now + POT_WIN_BANNER_MS / 1000.0,
            "payouts": payouts, "names": names, "winners": winners,
            "is_chop": (hand.winner_reason == "showdown"
                        and any(len(award.winners) > 1 for award in hand.awards)),
        }
        # 250BB+ showdowns get an automatic, original Pigeon celebration.
        # A non-showdown hero win exposes a manual CELEBRATE control instead.
        app_state = getattr(self, "__dict__", {})
        registry = app_state.get("multi_tables")
        table_slot = registry.get(table_id) if registry is not None else None
        table = table_slot.state.get("cash_table") if table_slot is not None else None
        bb = max(1, int(getattr(table, "big_blind", 1)))
        if table is not None and qualifies_for_big_pot(int(hand.pot), bb):
            if hand.winner_reason == "showdown":
                record["big_pot_celebration_available"] = None
                record["big_pot_celebration"] = {
                    "started": now + .35,
                    "duration": BIG_POT_CELEBRATION_SECONDS,
                    "winners": winners,
                    "seed": int(hand.hand_number if hasattr(hand, "hand_number") else len(hand.events)),
                }
                record["pot_animation"]["visible_until"] = max(
                    record["pot_animation"]["visible_until"],
                    now + .35 + BIG_POT_CELEBRATION_SECONDS)
                self._play_sound("big_win")
            elif "hero" in payouts:
                record["big_pot_celebration_available"] = {
                    "hand_key": hand_key, "winners": winners,
                    "seed": int(len(hand.events) + hand.pot),
                }
        if len(winners) > 1:
            self._play_sound("chip_split")
        else:
            self._play_sound("pot_award")
        if "hero" in payouts:
            self._play_sound("win")
        if (table is not None and qualifies_for_big_pot(int(hand.pot), bb)
                and hand.winner_reason == "showdown"):
            try:
                self.after(240, lambda: self._play_sound("applause"))
            except (tk.TclError, AttributeError):
                pass
        self._animate_pot_award_frame(table_id)

    def _animate_pot_award_frame(self, table_id: str):
        record = self.table_windows.get(table_id)
        if not record or not record.get("pot_animation"):
            return
        anim = record["pot_animation"]
        now = time.monotonic()
        elapsed = max(0.0, now - float(anim.get("started", now)))
        if not anim.get("slide_sound_played") and elapsed >= .11:
            anim["slide_sound_played"] = True
            self._play_sound("chip_slide")
        if (not anim.get("settle_sound_played")
                and elapsed >= max(0.0, float(anim.get("move_duration", 1.0)) - .035)):
            anim["settle_sound_played"] = True
            self._play_sound("chip_settle")
        if now >= float(anim.get("visible_until", 0.0)):
            record["pot_animation"] = None
            record["pot_animation_job"] = None
            celebration = record.get("big_pot_celebration")
            if celebration and now >= float(celebration.get("started", 0.0)) + float(celebration.get("duration", BIG_POT_CELEBRATION_SECONDS)):
                record["big_pot_celebration"] = None
            self._redraw_floating_table(table_id)
            return
        self._redraw_floating_table(table_id)
        try:
            record["pot_animation_job"] = self.after(
                24, lambda tid=table_id: self._animate_pot_award_frame(tid))
        except tk.TclError:
            record["pot_animation_job"] = None

    def _draw_pot_award_overlay(self, canvas, table, record, width, height, hero_index):
        anim = record.get("pot_animation")
        if not anim:
            return
        now = time.monotonic()
        elapsed = max(0.0, now - float(anim.get("started", now)))
        move_progress = min(1.0, elapsed / max(.1, float(anim.get("move_duration", 1.0))))
        positions = [
            (width*.50, height*.84), (width*.205, height*.69), (width*.205, height*.29),
            (width*.50, height*.125), (width*.795, height*.29), (width*.795, height*.69),
        ]
        if len(table.hand.players) == 2:
            positions = [(width*.50, height*.83), (width*.50, height*.15)]
        center = (width*.50, height*.355)
        winner_positions = []
        for winner_id, amount in anim["payouts"].items():
            idx = next((i for i, p in enumerate(table.hand.players) if p.player_id == winner_id), None)
            if idx is None:
                continue
            relative = (idx - hero_index) % len(table.hand.players)
            target = positions[relative]
            winner_positions.append((winner_id, target))
            breakdown = decompose_cents(int(amount), int(table.big_blind))
            moving_specs = [(d, count) for d, count in breakdown["counts"].items() if count]
            total_width = max(0, (len(moving_specs)-1)*24.0)
            for chip_i, (denomination, count) in enumerate(moving_specs):
                phase = chip_i * .055
                progress = max(0.0, min(1.0, (move_progress-phase)/(1.0-phase)))
                lane = -total_width/2 + chip_i*24.0
                origin = (center[0] + lane*.45, center[1] + 8.0)
                destination = (target[0] + lane*.20, target[1] + 8.0)
                x, y = chip_flight_position(
                    origin, destination, progress, lane=lane,
                    arc_height=min(42.0, math.hypot(destination[0]-origin[0],
                                                   destination[1]-origin[1])*.075))
                tag = ("pot_award_flight", f"pot_award_{winner_id}_{denomination}")
                draw_chip_stack(canvas, x, y, denomination, count, scale=.72,
                                tags=tag, max_visible_layers=7, show_count=True)
                if breakdown["fractional_bb"]:
                    canvas.create_text(x, y+20, text=f"+{breakdown['fractional_bb']}BB",
                                       fill="#F7F0D8", font=("Segoe UI", 5, "bold"), tags=tag)
        banner_progress = max(0.0, min(1.0, (elapsed - .28) / .34))
        banner_ease = 1.0 - (1.0 - banner_progress) ** 3
        for winner_id, target in winner_positions:
            name = anim["names"].get(winner_id, winner_id)
            label = "WIN" if not anim.get("is_chop") else "WIN • CHOP"
            rise = (1.0 - banner_ease) * 12.0
            bx, by = target[0], target[1] - rise
            canvas.create_rectangle(bx-47, by-65, bx+47, by-39,
                                    fill="#6b5428", outline="#f5d98d", width=2,
                                    tags=("winner_banner",))
            canvas.create_rectangle(bx-43, by-62, bx+43, by-42,
                                    fill="#f3cf75", outline="#fff0bd", width=1,
                                    tags=("winner_banner",))
            canvas.create_text(bx, by-52, text=label,
                               fill="#282014", font=("Segoe UI", 10, "bold"),
                               tags=("winner_banner",))
            canvas.create_text(bx, by-78, text=name,
                               fill="#fff0bd", font=("Segoe UI", 9, "bold"),
                               tags=("winner_banner",))
        if anim.get("is_chop"):
            canvas.create_text(width/2, height*.27, text="CHOP • SPLIT POT",
                               fill="#f3cf75", font=("Segoe UI", 12, "bold"),
                               tags=("winner_banner",))

    def _show_cpu_profile_popup(self, cpu_id: str):
        """Open the persistent opponent profile and recent head-to-head hand history."""
        try:
            profile = self.cpu_pool_store.get_profile(cpu_id, self.cash_rate)
        except Exception as exc:
            messagebox.showerror("CPU profile", str(exc))
            return
        window = tk.Toplevel(self)
        window.title(f"{profile.name} • {cpu_id}")
        window.geometry("820x620")
        window.minsize(640, 420)
        window.configure(bg=COLORS["bg"])
        header = tk.Frame(window, bg=COLORS["panel"], padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(header, text=f"{profile.avatar}  {profile.name}", bg=COLORS["panel"],
                 fg=COLORS["text"], font=("Segoe UI", 16, "bold")).pack(anchor="w")
        vip_role = self.vip_cpu_roles.get(cpu_id) if is_vip_mode(self.cash_game_mode) else None
        role_detail = (
            f" • {vip_cpu_role_label(vip_role)} • lineup role only; strategy implementation is still in progress"
            if vip_role else f" • {profile.archetype}"
        )
        tk.Label(header, text=(f"{cpu_id} • {self.cash_rate}{role_detail} • "
                               f"{profile.notes or 'No notes'}"),
                 bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 9),
                 wraplength=760, justify="left").pack(anchor="w", pady=(3, 0))
        stats = tk.Frame(window, bg=COLORS["bg"], padx=14, pady=10)
        stats.pack(fill="x")
        stat_text = (f"HANDS  {profile.hands}     VPIP  {profile.vpip:.1f}%     "
                     f"PFR  {profile.pfr:.1f}%     3BET  {profile.three_bet:.1f}%     "
                     f"AF  {profile.aggression_factor:.2f}")
        tk.Label(stats, text=stat_text, bg=COLORS["bg"], fg=COLORS["green"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        body = tk.Frame(window, bg=COLORS["bg"], padx=14, pady=4)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="RECENT HANDS AGAINST YOU", bg=COLORS["bg"], fg=COLORS["text"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))
        cols = ("date", "stake", "hole", "board", "pot", "net", "result")
        tree = ttk.Treeview(body, columns=cols, show="headings", height=10)
        labels = {"date": "DATE", "stake": "STAKE", "hole": "CPU HAND", "board": "BOARD",
                  "pot": "POT", "net": "CPU NET", "result": "RESULT"}
        widths = {"date": 140, "stake": 65, "hole": 85, "board": 145,
                  "pot": 80, "net": 85, "result": 95}
        for col in cols:
            tree.heading(col, text=labels[col])
            tree.column(col, width=widths[col], anchor="center")
        tree.pack(fill="both", expand=True)
        detail = tk.Text(body, height=9, bg="#081321", fg="#dce8f7", relief="flat",
                         font=("Consolas", 8), wrap="word")
        detail.pack(fill="both", expand=True, pady=(8, 0))
        detail.insert("end", "Select a hand to inspect its actions. Hidden CPU cards remain hidden unless shown at showdown.")
        detail.configure(state="disabled")
        rows = self.history_store.list_for_player(cpu_id, limit=100)
        by_iid: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows):
            player = next((item for item in row["players"] if item["id"] == cpu_id), None)
            if not player:
                continue
            shown = " ".join(player["hole_cards"]) if player["cards_shown"] else "Hidden"
            net = int(player["net"])
            result = "WIN" if net > 0 else ("LOSS" if net < 0 else "EVEN")
            iid = str(index)
            by_iid[iid] = row
            tree.insert("", "end", iid=iid, values=(
                row["played_at"].replace("T", " ")[:16], row["table_rate"], shown,
                row["board"] or "—", f"${row['pot']/100:.2f}",
                f"${net/100:+.2f}", result))

        def show_detail(_event=None):
            selected = tree.selection()
            if not selected:
                return
            row = by_iid.get(selected[0])
            if not row:
                return
            lines = [f"{row['table_rate']} • {row['played_at']}",
                     f"Board: {row['board'] or '—'}  Pot: ${row['pot']/100:.2f}", "", "PLAYERS"]
            for item in row["players"]:
                cards = " ".join(item["hole_cards"]) if item["cards_shown"] else "not shown"
                lines.append(f"{item['name']}: {cards} • net ${item['net']/100:+.2f}")
            lines.append("\nACTIONS")
            for event in row["events"]:
                if event.get("type") == "action":
                    lines.append(f"{event.get('player')}: {event.get('action')} {event.get('target', '')}".strip())
                elif event.get("type") == "street":
                    lines.append(f"--- {event.get('street', '').upper()} --- {' '.join(event.get('board', []))}")
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", "\n".join(lines))
            detail.configure(state="disabled")
        tree.bind("<<TreeviewSelect>>", show_detail)
        if not rows:
            detail.configure(state="normal")
            detail.delete("1.0", "end")
            detail.insert("end", "No completed hands against this CPU have been recorded yet.")
            detail.configure(state="disabled")

    def _draw_peel_card(self, canvas, x, y, value, width=48, height=66, progress=0.0):
        """Render a face card below a back flap peeled from bottom to top."""
        from math import sin, pi
        progress = max(0.0, min(1.0, float(progress)))
        self._draw_card(canvas, x, y, value, width, height)
        if progress >= 1.0:
            return
        back_name = str(self.appearance.get("card_back_theme", "Blue"))
        back_fill, back_line = CARD_BACK_THEMES.get(back_name, CARD_BACK_THEMES["Blue"])
        edge_y = y + height * (1.0 - progress)
        curl = max(1.5, width * .10) * sin(pi * progress)
        edge_points = []
        for step in range(13):
            u = 1.0 - step / 12.0
            py = edge_y - curl * sin(pi * u)
            edge_points.append((x + u * width, py))
        polygon = [(x, y), (x + width, y)] + edge_points
        shadow = [(px + 1.6, py + 2.6) for px, py in polygon]
        canvas.create_polygon(*[v for pt in shadow for v in pt], fill="#06100d",
                               outline="", tags=("peel_flap", "peel_shadow"))
        canvas.create_polygon(*[v for pt in polygon for v in pt], fill=back_fill,
                               outline="#d8bd7d", width=1, tags=("peel_flap",))
        for u in (.22, .50, .78):
            for v in (.20, .43, .66):
                if v >= 1.0 - progress - .07:
                    continue
                px, py = x + u * width, y + v * height
                r = max(1.3, width * .045)
                canvas.create_polygon(px, py-r, px+r, py, px, py+r, px-r, py,
                                      fill="", outline=back_line, width=1,
                                      tags=("peel_flap", "peel_pattern"))
        canvas.create_line(*[v for pt in edge_points for v in pt],
                           fill="#14231e", width=3, smooth=True,
                           tags=("peel_flap", "peel_fold"))
        canvas.create_line(*[v for pt in edge_points for v in pt],
                           fill="#fff3c5", width=1.3, smooth=True,
                           tags=("peel_flap", "peel_fold"))

    def _draw_card_back(self, canvas, x, y, width=42, height=58):
        """Classic patterned card back rather than a single crossed-line placeholder."""
        back_name = str(self.appearance.get("card_back_theme", "Blue"))
        back_fill, back_line = CARD_BACK_THEMES.get(back_name, CARD_BACK_THEMES["Blue"])
        canvas.create_rectangle(x+2, y+3, x+width+2, y+height+3,
                                fill="#06110d", outline="", tags=("playing_card_back",))
        canvas.create_rectangle(x, y, x+width, y+height, fill=back_fill,
                                outline="#d7b76e", width=2, tags=("playing_card_back",))
        inset = max(4, min(width, height)*.10)
        canvas.create_rectangle(x+inset, y+inset, x+width-inset, y+height-inset,
                                outline=back_line, width=1, tags=("playing_card_back",))
        # Repeating diamond lattice, familiar from physical casino decks.
        step = max(7, int(min(width, height)*.22))
        for row, yy in enumerate(range(int(y+inset+2), int(y+height-inset-1), step)):
            for xx in range(int(x+inset+2+(step//2 if row%2 else 0)), int(x+width-inset-1), step):
                r = max(2, step*.25)
                canvas.create_polygon(xx, yy-r, xx+r, yy, xx, yy+r, xx-r, yy,
                                      outline=back_line, fill="", width=1,
                                      tags=("playing_card_back",))
        cx, cy = x+width/2, y+height/2
        canvas.create_oval(cx-width*.18, cy-height*.13, cx+width*.18, cy+height*.13,
                           outline="#e7cf91", width=1, tags=("playing_card_back",))
        canvas.create_text(cx, cy, text="♠", fill="#f0d79d",
                           font=("Segoe UI Symbol", max(9, int(width*.22)), "bold"),
                           tags=("playing_card_back",))

    def _draw_card(self, canvas, x, y, value, width=52, height=70):
        """Draw a readable standard two-way playing card with correct rank/suit indexing and pips."""
        ranks = "23456789TJQKA"
        suit_map = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
        code = str(value).strip()
        # Accept both compact solver notation (Th) and human-readable rank notation (10h).
        if code[:2].upper() == "10":
            rank = "T"
            suit = code[2].lower() if len(code) > 2 else "s"
        else:
            rank = code[0].upper() if code else "A"
            suit = code[1].lower() if len(code) > 1 else "s"
        rank_text = {"T": "10"}.get(rank, rank)
        suit_text = suit_map.get(suit, "♠")
        color = self._card_suit_ink(rank, suit)
        face_fill, face_edge, face_inner, court_panel = card_face_palette(
            self.appearance.get("card_face_theme", "Classic"))
        tag = ("playing_card",)
        shadow = max(3, int(width*.055))
        canvas.create_rectangle(x+shadow+1, y+shadow+2, x+width+shadow+1, y+height+shadow+2,
                                fill="#03080b", outline="", tags=tag)
        canvas.create_rectangle(x+2, y+3, x+width+2, y+height+3,
                                fill="#7c8288", outline="", tags=tag)
        canvas.create_rectangle(x, y, x+width, y+height, fill=face_fill,
                                outline=face_edge, width=1, tags=tag)
        canvas.create_rectangle(x+1.5, y+1.5, x+width-1.5, y+height-1.5,
                                outline=face_inner, width=1, tags=tag)
        canvas.create_line(x+4, y+3, x+width-4, y+3,
                           fill="#ffffff", width=1, tags=tag)
        canvas.create_line(x+3, y+4, x+3, y+height-5,
                           fill="#ffffff", width=1, tags=tag)
        canvas.create_line(x+4, y+height-3, x+width-4, y+height-3,
                           fill=face_inner, width=1, tags=tag)
        corner_font = max(8, int(width*.205))
        suit_font = max(7, int(width*.16))
        # Upper-left index and the opposing, upside-down lower-right index.
        canvas.create_text(x+4, y+3, text=rank_text, anchor="nw", fill=color,
                           font=("Georgia", corner_font, "bold"), tags=tag)
        canvas.create_text(x+5, y+3+corner_font, text=suit_text, anchor="nw", fill=color,
                           font=("Segoe UI Symbol", suit_font, "bold"), tags=tag)
        canvas.create_text(x+width-10, y+height-9, text=rank_text, anchor="center", angle=180,
                           fill=color, font=("Georgia", corner_font, "bold"), tags=tag)
        canvas.create_text(x+width-10, y+height-9-corner_font*.78, text=suit_text,
                           anchor="center", angle=180, fill=color,
                           font=("Segoe UI Symbol", suit_font, "bold"), tags=tag)

        cx, cy = x+width*.52, y+height*.52
        if rank in {"J", "Q", "K"}:
            # Mirrored court artwork: the two halves meet at the waist like a real face card.
            canvas.create_rectangle(x+width*.25, y+height*.18, x+width*.80, y+height*.82,
                                    fill=court_panel, outline="#c6a96c", width=1, tags=tag)
            canvas.create_line(x+width*.26, cy, x+width*.79, cy,
                               fill="#c6a96c", width=1, tags=tag)
            for sign in (-1, 1):
                fy = cy + sign*height*.18
                canvas.create_oval(cx-width*.12, fy-height*.075, cx+width*.12, fy+height*.075,
                                   fill="#e1b58e", outline="#9b7658", width=1, tags=tag)
                canvas.create_arc(cx-width*.16, fy-height*.12, cx+width*.16, fy+height*.12,
                                  start=0 if sign == 1 else 180, extent=180,
                                  style="arc", outline=color, width=max(1, int(width*.035)), tags=tag)
                canvas.create_polygon(cx-width*.15, fy-height*.08,
                                      cx-width*.10, fy-height*.19,
                                      cx, fy-height*.11,
                                      cx+width*.11, fy-height*.19,
                                      cx+width*.16, fy-height*.08,
                                      fill="#d7b45f", outline="#987739", tags=tag)
                canvas.create_text(cx, fy+sign*height*.105, text=suit_text, fill=color,
                                   font=("Segoe UI Symbol", max(8, int(width*.17)), "bold"), tags=tag)
            canvas.create_text(cx, cy, text=rank, fill=color,
                               font=("Georgia", max(8, int(width*.17)), "bold"), tags=tag)
        elif rank == "A":
            canvas.create_text(cx, cy, text=suit_text, fill=color,
                               font=("Segoe UI Symbol", max(18, int(width*.48)), "bold"), tags=tag)
            canvas.create_oval(cx-width*.23, cy-height*.25, cx+width*.23, cy+height*.25,
                               outline="#d5bd88", width=1, tags=tag)
            for offset in (-.31, .31):
                canvas.create_oval(cx-2, cy+height*offset-2, cx+2, cy+height*offset+2,
                                   fill="#d5bd88", outline="", tags=tag)
        else:
            # Conventional symmetrical pip map for 2–10; lower pips are inverted.
            count = ranks.index(rank)+2 if rank in ranks[:9] else 10
            patterns = {
                2: [(0,.24),(0,.76)],
                3: [(0,.20),(0,.50),(0,.80)],
                4: [(-.19,.23),(.19,.23),(-.19,.77),(.19,.77)],
                5: [(-.19,.23),(.19,.23),(0,.50),(-.19,.77),(.19,.77)],
                6: [(-.19,.18),(.19,.18),(-.19,.50),(.19,.50),(-.19,.82),(.19,.82)],
                7: [(-.19,.17),(.19,.17),(0,.34),(-.19,.50),(.19,.50),(-.19,.83),(.19,.83)],
                8: [(-.19,.17),(.19,.17),(-.19,.39),(.19,.39),(-.19,.61),(.19,.61),(-.19,.83),(.19,.83)],
                9: [(-.19,.15),(.19,.15),(-.19,.34),(.19,.34),(0,.50),(-.19,.66),(.19,.66),(-.19,.85),(.19,.85)],
                10:[(-.19,.14),(.19,.14),(-.19,.32),(.19,.32),(-.19,.50),(.19,.50),(-.19,.68),(.19,.68),(-.19,.86),(.19,.86)],
            }
            pip_font = max(8, int(width*.185))
            for dx, fy in patterns.get(count, patterns[10]):
                angle = 180 if fy > .5 else 0
                canvas.create_text(cx+width*dx, y+height*fy, text=suit_text, fill=color,
                                   angle=angle,
                                   font=("Segoe UI Symbol", pip_font, "bold"), tags=tag)

    def _render_practice_actions(self):
        for child in self.action_buttons_frame.winfo_children():
            child.destroy()
        if self.hand_finished:
            tk.Label(self.action_buttons_frame, text="HAND COMPLETE — start another match from the loaded GTO+ tree.", bg=COLORS["bg"], fg=COLORS["gold"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            return
        context = self.current_node_context
        if not context:
            tk.Label(self.action_buttons_frame, text="GTO+の解析済みツリーを開き、対戦を開始してください。", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w")
            return
        node = context["node"]
        human_side = self.human_side_var.get().lower()
        cpu_side = self.side_var.get().lower()
        if node["next_to_act"] == cpu_side:
            tk.Label(self.action_buttons_frame, text=f"CPU ({cpu_side.upper()}) is using GTO+ mixed strategy. CPU actions run automatically.", bg=COLORS["bg"], fg=COLORS["gold"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            return
        if node["next_to_act"] != human_side:
            tk.Label(self.action_buttons_frame, text=f"GTO+ next to act: {node['next_to_act'].upper()} (role selection mismatch)", bg=COLORS["bg"], fg=COLORS["red"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
            return
        tk.Label(self.action_buttons_frame, text=f"YOUR TURN ({human_side.upper()}) — select a legal action from the GTO+ tree:", bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 5))
        buttons = tk.Frame(self.action_buttons_frame, bg=COLORS["bg"])
        buttons.pack(anchor="w")
        for action in node["actions"]:
            tk.Button(buttons, text=action, bg=COLORS["panel2"], fg="white", activebackground="#28405e", activeforeground="white",
                      relief="flat", padx=13, pady=9, font=("Segoe UI", 9, "bold"),
                      command=lambda a=action: self._human_action(a)).pack(side="left", padx=(0, 7))

    def _start_practice(self):
        if self.tree_file is None:
            messagebox.showwarning("Solved tree required", "先にGTO+ ENGINEで解析済みツリーを選択してください。")
            self.show_page("lobby")
            return
        try:
            self._save_connection_config()
            rake = float(self.rake_var.get().strip() or "0")
            cpu_side = self.side_var.get().lower()
            human_side = self.human_side_var.get().lower()
            if cpu_side == human_side:
                raise ValueError("CPU side and Your side must be different.")
        except Exception as exc:
            messagebox.showerror("Pigeon Poker", str(exc))
            return
        self.current_node_context = None
        self.hand_finished = False
        self.active_cpu_hand = None
        self.active_human_hand = None
        self.cpu_last_action.set("GTO+ solved treeを読み込み、双方のホールカードをレンジから配布中…")
        self.status_var.set("GTO+ table starting — CPU has no action deadline")
        tree = self.tree_file
        cpu_hand = self.hand_var.get().strip() or "AUTO"
        human_hand = self.human_hand_var.get().strip() or "AUTO"

        def work():
            try:
                self.integration.open_solved_tree(tree)
                # Draw both players' actual combos from the loaded solver ranges.
                dealt = self.integration.sample_private_hands(
                    cpu_side, human_side, cpu_hand=cpu_hand, human_hand=human_hand
                )
                self.active_cpu_hand = dealt["cpu"]
                self.active_human_hand = dealt["human"]
                # Import the current decision node immediately. More nodes are captured
                # automatically after each action during the hand.
                context = self.integration.import_current_node(tree, rake)
                context["cpu_hand"] = dealt["cpu"]
                context["human_hand"] = dealt["human"]
                self.jobs.put(("practice_node", {"context": context, "actions": [], "dealt": dealt}))
                if context["node"]["next_to_act"] == cpu_side:
                    self._run_cpu_chain(tree, rake, [], cpu_side, dealt["cpu"], dealt["human"], context)
            except Exception as exc:
                self.jobs.put(("error", f"GTO+ practice start failed: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def _run_cpu_chain(self, tree: Path, rake: float, actions: list[dict[str, Any]],
                       cpu_side: str, cpu_hand: str, human_hand: str | None = None,
                       start_context: dict[str, Any] | None = None):
        """Let GTO+ CPU act until the human side is next or the tree reaches a leaf.

        There is intentionally no elapsed-time/action clock. The 1,000-step guard
        is only for malformed/cyclic tree responses, not a decision deadline.
        """
        try:
            context = start_context or self.integration.import_current_node(tree, rake)
            steps = 0
            while True:
                if context["node"]["next_to_act"] != cpu_side:
                    context["cpu_hand"] = cpu_hand
                    context["human_hand"] = human_hand
                    self.jobs.put(("practice_update", {"context": context, "actions": actions}))
                    return
                result = self.integration.cpu_act_from_imported_context(
                    context, cpu_hand, cpu_side
                )
                actions.append(result)
                steps += 1
                if steps >= 1000:
                    raise RuntimeError("Safety stop: GTO+ tree exceeded 1,000 consecutive CPU decisions.")
                # Read and cache the next node exactly once. This also collects the
                # strategy snapshot for the next decision while the hand progresses.
                context = self.integration.import_current_node(tree, rake)
                context["cpu_hand"] = cpu_hand
                context["human_hand"] = human_hand
        except Exception as exc:
            # A terminal leaf has no further decision node; previous imported
            # snapshots remain saved and the completed hand is displayed.
            self.jobs.put(("practice_update", {"context": None, "actions": actions, "error": str(exc)}))

    def _human_action(self, action_label: str):
        context = self.current_node_context
        if not context:
            return
        expected = self.human_side_var.get()
        self.cpu_last_action.set(f"Your action: {action_label} — GTO+ツリーを進行中…")
        tree = self.tree_file
        rake = float(self.rake_var.get().strip() or "0")
        cpu_side = self.side_var.get().lower()
        cpu_hand = self.active_cpu_hand or self.hand_var.get().strip()
        human_hand = self.active_human_hand

        def work():
            try:
                moved = self.integration.advance_current_node(action_label, expected_player=expected)
                # Import/cache the reached node before handing control to the CPU.
                try:
                    context2 = self.integration.import_current_node(tree, rake)
                    context2["cpu_hand"] = cpu_hand
                    context2["human_hand"] = human_hand
                    self.jobs.put(("human_advanced", {"moved": moved, "context": context2}))
                    if context2["node"]["next_to_act"] == cpu_side:
                        self._run_cpu_chain(tree, rake, [], cpu_side, cpu_hand, human_hand, context2)
                except Exception as terminal_exc:
                    # The action itself was already accepted. A missing next node
                    # normally means the loaded GTO+ tree reached a terminal leaf.
                    self.jobs.put(("hand_terminal", {"moved": moved, "error": str(terminal_exc)}))
            except Exception as exc:
                self.jobs.put(("error", f"Could not advance your action: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    # ---------- GTO+ page / integration ----------
    def _build_gto_page(self):
        page = self._new_page("gto")
        row = tk.Frame(page, bg=COLORS["bg"])
        row.pack(fill="both", expand=True, padx=0, pady=0)
        host_col = tk.Frame(row, bg=COLORS["panel"], highlightbackground=COLORS["border"], highlightthickness=1)
        host_col.pack(side="left", fill="both", expand=True)
        titlebar = tk.Frame(host_col, bg=COLORS["panel2"])
        titlebar.pack(fill="x")
        tk.Label(titlebar, text="GTO+ WORKSPACE", bg=COLORS["panel2"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")).pack(side="left", padx=12, pady=9)
        self.gto_viewport = tk.Frame(host_col, bg="#080f18")
        self.gto_viewport.pack(fill="both", expand=True, padx=0, pady=0)
        self.gto_host = tk.Frame(
            self.gto_viewport, bg="#080f18", width=1320, height=718,
        )
        self.gto_host.place(
            relx=0.5, rely=0.0, anchor="n", y=-42,
            width=1320, height=718,
        )
        self.gto_viewport.bind("<Configure>", self._resize_embedded)
        tk.Label(self.gto_host, text="GTO+ window will appear here after launch.\nIf native docking fails, GTO+ will remain in a separate window.", bg="#080f18", fg=COLORS["muted"], justify="center", font=("Segoe UI", 11)).place(relx=.5, rely=.5, anchor="center")

        # The right-side GTO+ controls contain more panels than fit in the
        # available vertical space. Keep the column fixed-width but make its
        # contents scrollable instead of silently clipping panels below the fold.
        self._gto_controls_drawer_open = False
        self.gto_controls_drawer = tk.Frame(
            host_col, bg=COLORS["panel"],
            highlightbackground=COLORS["border"], highlightthickness=1,
        )
        self.gto_controls_drawer.place(
            relx=1.0, rely=0.0, anchor="ne", relheight=1.0, width=40,
        )
        self.gto_controls_toggle = ttk.Button(
            self.gto_controls_drawer, text="◀", width=2,
            style="DrawerToggle.TButton",
            command=self._toggle_gto_controls_drawer,
        )
        self.gto_controls_toggle.place(x=0, y=12, width=40, height=44)
        controls_outer = tk.Frame(
            self.gto_controls_drawer, bg=COLORS["bg"], width=360,
        )
        self.gto_controls_panel = controls_outer
        controls_outer.place_forget()
        self.gto_controls_drawer.lift()
        controls_canvas = tk.Canvas(
            controls_outer, bg=COLORS["bg"], highlightthickness=0,
            width=340, yscrollincrement=24,
        )
        controls_scrollbar = ttk.Scrollbar(
            controls_outer, orient="vertical", command=controls_canvas.yview,
        )
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.pack(side="left", fill="both", expand=True)
        controls_scrollbar.pack(side="right", fill="y")
        controls = tk.Frame(controls_canvas, bg=COLORS["bg"])
        controls_window = controls_canvas.create_window(
            (0, 0), window=controls, anchor="nw",
        )
        controls.bind(
            "<Configure>",
            lambda _event: controls_canvas.configure(
                scrollregion=controls_canvas.bbox("all")
            ),
        )
        controls_canvas.bind(
            "<Configure>",
            lambda event: controls_canvas.itemconfigure(
                controls_window, width=event.width
            ),
        )

        def _scroll_gto_controls(event):
            widget = event.widget
            while widget is not None:
                if widget is controls_canvas:
                    delta = getattr(event, "delta", 0)
                    if delta:
                        controls_canvas.yview_scroll(
                            int(-delta / 120) or (-1 if delta > 0 else 1), "units"
                        )
                    return "break"
                widget = getattr(widget, "master", None)
            return None

        self.bind_all("<MouseWheel>", _scroll_gto_controls, add="+")
        conn_box, conn = self._panel(controls, "CONNECTION")
        conn_box.pack(fill="x")
        tk.Label(conn, text="GTO+ executable", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w")
        pathrow = tk.Frame(conn, bg=COLORS["panel"])
        pathrow.pack(fill="x", pady=(3, 8))
        ttk.Entry(pathrow, textvariable=self.executable_var).pack(side="left", fill="x", expand=True)
        ttk.Button(pathrow, text="…", width=3, command=self._browse_exe).pack(side="left", padx=(4, 0))
        tk.Label(conn, text="Socket port", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w")
        ttk.Entry(conn, textvariable=self.port_var, width=10).pack(anchor="w", pady=(3, 8))
        ttk.Button(conn, text="① ソケット設定（手動/初回）", command=self._enable_socket).pack(fill="x", pady=3)
        ttk.Button(conn, text="② GTO+起動", style="Accent.TButton", command=self._launch_gto).pack(fill="x", pady=3)
        ttk.Button(conn, text="③ GTO+接続", command=self._connect_gto).pack(fill="x", pady=3)
        ttk.Label(conn, textvariable=self.status_var, wraplength=270, style="Panel.TLabel").pack(anchor="w", pady=(7, 0))

        tree_box, tree = self._panel(controls, "SOLVED TREE")
        tree_box.pack(fill="x", pady=(10, 0))
        tk.Label(tree, textvariable=self.tree_var, bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270, justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 6))
        ttk.Button(tree, text="解析済みツリーを追加・ロード", command=self._load_tree).pack(fill="x")
        tk.Label(tree, text="GTO+の保存済みツリーを登録します。完全一致する局面ではCPUがGTO+戦略を使用します。",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270, justify="left",
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 0))
        ttk.Button(tree, text="現在ノードの全ハンド戦略を保存", style="Accent.TButton", command=self._import_node).pack(fill="x", pady=(6, 0))
        self.import_status = tk.StringVar(value="未取り込み")
        tk.Label(tree, textvariable=self.import_status, bg=COLORS["panel"], fg=COLORS["gold"], wraplength=270, justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(7, 0))

        auto_box, auto = self._panel(controls, "AUTOMATIC TREE ANALYSIS")
        auto_box.pack(fill="x", pady=(10, 0))
        tk.Label(auto, text="登録済み解析ツリーの全分岐を自動巡回し、各ノードの全コンボ戦略をDBへ蓄積します。未知局面の新規Solveとは別機能です。Solve診断は読み取り専用、OOPレンジ編集画面診断はOOP表を1回クリックして編集画面を撮影します（レンジ変更・Solveなし）。",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 6))
        ttk.Button(auto, text="AUTO COLLECT ALL NODES", style="Accent.TButton",
                   command=self._start_auto_analysis).pack(fill="x")
        ttk.Button(auto, text="未知HU局面の自動Solve設定を診断",
                   command=self._run_auto_solve_ui_probe).pack(fill="x", pady=(5, 0))
        tk.Label(auto, text="OOP/IPレンジとBoard欄が空の場合のみテスト値を一時投入。Build Tree押下後の「プレイヤー2のレンジを入力してください」メッセージを識別し、OK後にPlayer2 Source欄をクリックしてネイティブEditを特定。PID/所有関係・Source文字列を再読取し、既知のAA+AKs:40%だけDoneで再試行。再度拒否された場合も同じ方法でSourceを特定し、既知テスト値だけClearしてIP/OOP/Boardを復元。Sourceを特定できない場合は手動対応を要求し、他の値を変更しません。Pot/Stack/Rake変更・Tree確定・Solver実行はしません。",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))
        auto_row = tk.Frame(auto, bg=COLORS["panel"])
        auto_row.pack(fill="x", pady=(5, 0))
        ttk.Button(auto_row, text="STOP", style="Danger.TButton",
                   command=self._stop_auto_analysis).pack(side="left", fill="x", expand=True)
        ttk.Button(auto_row, text="Solve診断", command=self._run_gto_ui_diagnostic).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )
        ttk.Button(auto, text="OOPレンジ編集画面を開く（単独テスト）",
                   style="Accent.TButton",
                   command=lambda: self._run_gto_ui_diagnostic(open_oop_range_editor=True)).pack(
            fill="x", pady=(5, 0)
        )
        tk.Label(auto, text="埋め込み中のGTO+画面だけを対象に、OOPレンジ表を1回クリックして編集画面を開きます。文字入力・レンジ確定・ツリー構築・Solver実行はしません。",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))
        ttk.Button(auto, text="OOPレンジ編集→テキスト欄フォーカス診断",
                    command=lambda: self._run_gto_ui_diagnostic(
                        open_oop_range_editor=True, focus_oop_source_field=True)).pack(
            fill="x", pady=(5, 0)
        )
        ttk.Button(auto, text="Source code一時入力テスト（AA→復元）",
                    command=lambda: self._run_gto_ui_diagnostic(
                        open_oop_range_editor=True, focus_oop_source_field=True,
                        probe_oop_source_field_input=True)).pack(
            fill="x", pady=(5, 0)
        )
        tk.Label(auto, text="空欄にAAを一時入力して読戻し、元の空欄へ復元します。完了ボタンは押しません。",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))
        ttk.Button(auto, text="OOPテストレンジAAを確定（単独テスト）",
                   style="Accent.TButton",
                   command=lambda: self._run_gto_ui_diagnostic(commit_oop_aa=True)).pack(
            fill="x", pady=(7, 0)
        )
        tk.Label(auto, text="OOPのSource code欄が空の場合だけAAを入力して完了を押します。既存文字列は上書きせず停止。IP・Board・Tree・Solverは変更しません。",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))
        ttk.Checkbutton(auto, text="接続・ツリー読込時に自動実行",
                        variable=self.auto_collect_enabled_var,
                        command=self._save_auto_collect_preference).pack(anchor="w", pady=(5, 0))
        self.auto_scan_status_var = tk.StringVar(value="自動収集は待機中")
        tk.Label(auto, textvariable=self.auto_scan_status_var, bg=COLORS["panel"],
                 fg=COLORS["gold"], wraplength=270, justify="left",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(5, 0))

        db_box, db = self._panel(controls, "STRATEGY CACHE")
        db_box.pack(fill="x", pady=(10, 0))
        self.db_count_var = tk.StringVar(value=f"保存済み戦略: {self._count_cached_strategies()} combos")
        tk.Label(db, textvariable=self.db_count_var, bg=COLORS["panel"], fg=COLORS["green"], font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(db, text="Imported GTO+ mixed frequencies are stored locally in SQLite and reused by matching CPU spots.", bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270, justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

        coverage_box, coverage = self._panel(controls, "IMPORTED STRATEGY COVERAGE")
        coverage_box.pack(fill="x", pady=(10, 0))
        self.gto_coverage_summary_var = tk.StringVar(value="Reading imported strategy database…")
        tk.Label(coverage, textvariable=self.gto_coverage_summary_var, bg=COLORS["panel"],
                 fg=COLORS["green"], wraplength=270, justify="left",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 5))
        self.gto_coverage_tree = ttk.Treeview(
            coverage, columns=("street", "nodes", "combos", "boards", "actions"),
            show="headings", height=3)
        for key, title, width in (("street", "STREET", 58), ("nodes", "NODES", 52),
                                  ("combos", "COMBOS", 62), ("boards", "BOARDS", 58),
                                  ("actions", "ACTIONS", 60)):
            self.gto_coverage_tree.heading(key, text=title)
            self.gto_coverage_tree.column(key, width=width, minwidth=42,
                                          anchor="w" if key == "street" else "center", stretch=False)
        self.gto_coverage_tree.pack(fill="x", pady=(0, 5))
        self.gto_coverage_quality_var = tk.StringVar(value="")
        tk.Label(coverage, textvariable=self.gto_coverage_quality_var, bg=COLORS["panel"],
                 fg=COLORS["muted"], wraplength=270, justify="left",
                 font=("Segoe UI", 7)).pack(anchor="w")
        coverage_buttons = tk.Frame(coverage, bg=COLORS["panel"])
        coverage_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(coverage_buttons, text="REFRESH", command=self._refresh_gto_coverage).pack(side="left", fill="x", expand=True)
        ttk.Button(coverage_buttons, text="EXPORT JSON", command=self._export_gto_coverage).pack(side="left", fill="x", expand=True, padx=(5, 0))

        pending_box, pending = self._panel(controls, "UNMATCHED SPOT LOG")
        pending_box.pack(fill="x", pady=(10, 0))
        self.gto_pending_summary_var = tk.StringVar(value="No unresolved GTO+ spots")
        tk.Label(pending, textvariable=self.gto_pending_summary_var, bg=COLORS["panel"],
                 fg=COLORS["gold"], wraplength=270, justify="left",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 3))
        self.gto_cpu_decision_summary_var = tk.StringVar(value="CPU decisions: reading…")
        tk.Label(pending, textvariable=self.gto_cpu_decision_summary_var, bg=COLORS["panel"],
                 fg=COLORS["green"], wraplength=270, justify="left",
                 font=("Segoe UI", 7, "bold")).pack(anchor="w", pady=(0, 5))
        self.gto_pending_tree = ttk.Treeview(
            pending, columns=("street", "board", "hits", "status"), show="headings", height=3)
        for key, title, width in (("street", "STREET", 58), ("board", "BOARD", 132),
                                  ("hits", "HITS", 48), ("status", "STATUS", 72)):
            self.gto_pending_tree.heading(key, text=title)
            self.gto_pending_tree.column(key, width=width, minwidth=40,
                                         anchor="w" if key == "board" else "center", stretch=False)
        self.gto_pending_tree.pack(fill="x", pady=(0, 5))
        tk.Label(pending, text=("登録ツリーにない局面はここへ記録されます。GTO+の新規ツリー生成はこのキューから自動実行されません。新しい解析済みツリーを読み込むとCPUが再照合します。"),
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=270,
                 justify="left", font=("Segoe UI", 7)).pack(anchor="w")
        pending_buttons = tk.Frame(pending, bg=COLORS["panel"])
        pending_buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(pending_buttons, text="REFRESH", command=self._refresh_gto_pending_queue).pack(side="left", fill="x", expand=True)
        ttk.Button(pending_buttons, text="EXPORT QUEUE", command=self._export_gto_pending_queue).pack(side="left", fill="x", expand=True, padx=(5, 0))
        self._refresh_gto_coverage()
        self._refresh_gto_pending_queue()
        ttk.Button(db, text="Pigeon Pokerテーブルへ戻る", command=lambda: self.show_page("table")).pack(fill="x", pady=(10, 0))

    def _toggle_gto_controls_drawer(self):
        """Open/close the right controls over GTO+ without resizing the workspace."""
        try:
            opening = not bool(getattr(self, "_gto_controls_drawer_open", False))
            self._gto_controls_drawer_open = opening
            if opening:
                self.gto_controls_drawer.place_configure(width=400)
                self.gto_controls_panel.place(
                    x=40, y=0, width=360, relheight=1.0,
                )
                self.gto_controls_toggle.configure(text="▶")
            else:
                self.gto_controls_panel.place_forget()
                self.gto_controls_drawer.place_configure(width=40)
                self.gto_controls_toggle.configure(text="◀")
            self.gto_controls_drawer.lift()
            self.gto_controls_toggle.lift()
            self.after_idle(self.gto_controls_drawer.lift)
        except tk.TclError:
            return

    def _build_placeholder_pages(self):
        self._build_ggcare_page()
        self._build_settings_page()

    def _build_ggcare_page(self):
        page = self._new_page("gg_care")
        self._page_header(page, "GG Care", "Simulated bad-beat care ledger • no real-money payments")
        summary_row = tk.Frame(page, bg=COLORS["bg"])
        summary_row.pack(fill="x", padx=22, pady=(0, 10))
        self.ggcare_summary_var = tk.StringVar(value="No GG Care events")
        tk.Label(summary_row, textvariable=self.ggcare_summary_var, bg=COLORS["bg"], fg=COLORS["green"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(summary_row, text="REFRESH", command=self._refresh_ggcare).pack(side="right")
        box, inner = self._panel(page, "RECENT GG CARE EVENTS")
        box.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        columns = ("date", "stake", "pot", "equity", "roll", "reward", "reason")
        self.ggcare_tree = ttk.Treeview(inner, columns=columns, show="headings", height=12)
        headings = {"date": "DATE", "stake": "STAKE", "pot": "POT", "equity": "ALL-IN EQUITY",
                    "roll": "ROLL", "reward": "REWARD", "reason": "RESULT"}
        widths = {"date": 150, "stake": 80, "pot": 90, "equity": 100, "roll": 60, "reward": 90, "reason": 420}
        for col in columns:
            self.ggcare_tree.heading(col, text=headings[col])
            self.ggcare_tree.column(col, width=widths[col], anchor="center" if col != "reason" else "w")
        self.ggcare_tree.pack(fill="both", expand=True)
        rules, rule_inner = self._panel(page, "PIGEON SIMULATION RULES")
        rules.pack(fill="x", padx=22, pady=(0, 12))
        tk.Label(rule_inner, text=(
            "Qualification: hero goes all-in; estimated equity at that moment is at least 50%; "
            "final pot is at least approximately 150 BB; hero loses at showdown. "
            "Equity is a Monte Carlo estimate against random unseen opponent hands.\n"
            "Lottery: 1–50 $0 • 51–90 $20 • 91–93 $30 • 94–95 $50 • "
            "96 $60 • 97 $70 • 98 $80 • 99 $90 • 100 $200."
        ), bg=COLORS["panel"], fg=COLORS["muted"], justify="left", wraplength=1050,
           font=("Segoe UI", 9)).pack(anchor="w")
        self._refresh_ggcare()

    def _refresh_ggcare(self):
        if not hasattr(self, "ggcare_tree"):
            return
        summary = self.ggcare_ledger.summary()
        self.ggcare_summary_var.set(
            f"{summary['events']} events • {summary['paid_events']} paid • Total rewards ${summary['rewards']/100:,.2f}"
        )
        for item in self.ggcare_tree.get_children():
            self.ggcare_tree.delete(item)
        for index, row in enumerate(self.ggcare_ledger.recent(200)):
            date_text = row["played_at"].replace("T", " ").replace("+00:00", " UTC")
            self.ggcare_tree.insert("", "end", iid=str(index), values=(
                date_text, row["stake"], f"${row['pot']/100:.2f}", f"{row['equity']*100:.1f}%",
                row["roll"] if row["roll"] is not None else "—", f"${row['reward_cents']/100:.2f}", row["reason"]))

    def _build_settings_page(self):
        page = self._new_page("settings")
        self._page_header(page, "Settings & CPU Pool", "Per-stake CPU levels, persistent identities and editable profiles")
        body = tk.Frame(page, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, padx=22, pady=(0, 16))
        # The left settings column contains more controls than a typical
        # viewport can display. Give it its own scroll canvas so the SOUND
        # sliders and lower controls cannot be clipped by the fixed-width shell.
        left_shell = tk.Frame(body, bg=COLORS["bg"], width=390)
        left_shell.pack(side="left", fill="y", padx=(0, 12))
        left_shell.pack_propagate(False)
        left_canvas = tk.Canvas(
            left_shell, bg=COLORS["bg"], highlightthickness=0, bd=0,
            yscrollincrement=24,
        )
        left_scrollbar = ttk.Scrollbar(
            left_shell, orient="vertical", command=left_canvas.yview
        )
        left_canvas.configure(yscrollcommand=left_scrollbar.set)
        left_scrollbar.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)
        left = tk.Frame(left_canvas, bg=COLORS["bg"])
        left_window = left_canvas.create_window(
            (0, 0), window=left, anchor="nw"
        )

        def _sync_settings_left_scroll(_event=None):
            try:
                left_canvas.configure(scrollregion=left_canvas.bbox("all"))
            except tk.TclError:
                return

        def _fit_settings_left_width(event):
            try:
                left_canvas.itemconfigure(left_window, width=max(1, event.width))
                left_canvas.after_idle(_sync_settings_left_scroll)
            except tk.TclError:
                return

        left.bind("<Configure>", _sync_settings_left_scroll, add="+")
        left_canvas.bind("<Configure>", _fit_settings_left_width, add="+")
        self.nested_page_scroll_canvases.add(left_canvas)

        right = tk.Frame(body, bg=COLORS["bg"])
        right.pack(side="left", fill="both", expand=True)

        dist_box, dist = self._panel(left, "CPU LEVEL POPULATION BY STAKE")
        dist_box.pack(fill="x")
        tk.Label(dist, text="All 100 identities are shared across rates; each rate has its own Lv.1–Lv.5 assignment.",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=330, justify="left",
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 8))
        self.cpu_stake_var = tk.StringVar(value="NL2")
        stake_row = tk.Frame(dist, bg=COLORS["panel"])
        stake_row.pack(fill="x", pady=(0, 7))
        tk.Label(stake_row, text="Stake", bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")
        stake_combo = ttk.Combobox(stake_row, textvariable=self.cpu_stake_var,
                                   values=list(self.cpu_pool_store.stakes), state="readonly", width=12)
        stake_combo.pack(side="right")
        stake_combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh_cpu_settings())
        self.cpu_distribution_vars = {level: tk.StringVar(value="20") for level in range(1, 6)}
        for level in range(1, 6):
            line = tk.Frame(dist, bg=COLORS["panel"])
            line.pack(fill="x", pady=2)
            tk.Label(line, text=f"Level {level}", bg=COLORS["panel"], fg=COLORS["text"], width=12, anchor="w").pack(side="left")
            ttk.Spinbox(line, from_=0, to=100, textvariable=self.cpu_distribution_vars[level], width=8).pack(side="right")
        ttk.Button(dist, text="SAVE LEVEL DISTRIBUTION (TOTAL MUST BE 100)", style="Accent.TButton",
                   command=self._apply_cpu_distribution).pack(fill="x", pady=(9, 0))
        self.cpu_distribution_status = tk.StringVar(value="Default: 20 CPUs at each level")
        tk.Label(dist, textvariable=self.cpu_distribution_status, bg=COLORS["panel"], fg=COLORS["gold"],
                 wraplength=330, justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(7, 0))

        rebuy_box, rebuy = self._panel(left, "CASH TABLE")
        rebuy_box.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(rebuy, text="Auto Rebuy to 100 BB when below 100 BB",
                        variable=self.cash_auto_rebuy_var, command=self._save_auto_rebuy).pack(anchor="w")
        tk.Label(rebuy, text="When disabled, rebuy is manual from the table after a hand.",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=330, justify="left",
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

        appearance_box, appearance = self._panel(left, "TABLE APPEARANCE")
        appearance_box.pack(fill="x", pady=(10, 0))
        self.felt_theme_var = tk.StringVar(value=str(self.appearance["felt_theme"]))
        self.table_background_var = tk.StringVar(value=str(self.appearance["table_background"]))
        self.card_face_theme_var = tk.StringVar(value=str(self.appearance["card_face_theme"]))
        self.card_back_theme_var = tk.StringVar(value=str(self.appearance["card_back_theme"]))
        self.four_color_var = tk.BooleanVar(value=bool(self.appearance["four_color_deck"]))
        appearance_choices = (
            ("Felt", self.felt_theme_var, list(FELT_THEMES)),
            ("Table background", self.table_background_var, list(TABLE_BACKGROUND_THEMES)),
            ("Card face", self.card_face_theme_var, list(CARD_FACE_THEMES)),
            ("Card back", self.card_back_theme_var, list(CARD_BACK_THEMES)),
        )
        for label, variable, options in appearance_choices:
            line = tk.Frame(appearance, bg=COLORS["panel"]); line.pack(fill="x", pady=2)
            tk.Label(line, text=label, bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")
            ttk.Combobox(line, textvariable=variable, values=options, state="readonly", width=13).pack(side="right")
        ttk.Checkbutton(appearance, text="4-color deck (♠ black / ♥ red / ♦ blue / ♣ green)",
                        variable=self.four_color_var).pack(anchor="w", pady=(4, 0))
        ttk.Button(appearance, text="SAVE APPEARANCE", command=self._save_appearance).pack(fill="x", pady=(6, 0))

        hotkey_box, hotkey = self._panel(left, "TABLE HOTKEYS")
        hotkey_box.pack(fill="x", pady=(10, 0))
        self.hotkey_vars = {name: tk.StringVar(value=key) for name, key in self.hotkeys.items()}
        hotkey_labels = {"fold": "Fold", "check_call": "Check / Call", "bet_raise": "Bet / Raise",
                         "all_in": "All-in", "next_hand": "Next hand"}
        for name, label in hotkey_labels.items():
            line = tk.Frame(hotkey, bg=COLORS["panel"]); line.pack(fill="x", pady=1)
            tk.Label(line, text=label, bg=COLORS["panel"], fg=COLORS["text"]).pack(side="left")
            ttk.Entry(line, textvariable=self.hotkey_vars[name], width=5, justify="center").pack(side="right")
        ttk.Button(hotkey, text="SAVE HOTKEYS", command=self._save_hotkeys).pack(fill="x", pady=(6, 0))
        tk.Label(hotkey, text="Keys act on the selected / frontmost cash table. Text fields keep normal typing.",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=330, justify="left",
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 0))

        sound_box, sound = self._panel(left, "SOUND")
        sound_box.pack(fill="x", pady=(10, 0))
        self.sound_master_var = tk.BooleanVar(value=self.sound_master)
        self.sound_volume_var = tk.IntVar(value=self.sound_volume)
        ttk.Checkbutton(sound, text="Master sound", variable=self.sound_master_var).pack(anchor="w")
        sound_grid = tk.Frame(sound, bg=COLORS["panel"])
        sound_grid.pack(fill="x", pady=(2, 5))
        sound_labels = tuple(SOUND_LABELS.items())
        for index, (name, label) in enumerate(sound_labels):
            variable = tk.BooleanVar(value=self.sound_settings[name])
            setattr(self, f"sound_{name}_var", variable)
            ttk.Checkbutton(sound_grid, text=label, variable=variable).grid(
                row=index // 3, column=index % 3, sticky="w", padx=(0, 9), pady=1)
        volume_heading = tk.Frame(sound, bg=COLORS["panel"])
        volume_heading.pack(fill="x", pady=(2, 0))
        tk.Label(volume_heading, text="効果音音量 / EFFECT VOLUME",
                 bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="left")
        self.sound_volume_percent_var = tk.StringVar(value=f"{self.sound_volume}%")
        tk.Label(volume_heading, textvariable=self.sound_volume_percent_var,
                 bg=COLORS["panel"], fg=COLORS["gold"],
                 font=("Segoe UI", 9, "bold")).pack(side="right")
        volume_row = tk.Frame(sound, bg=COLORS["panel"])
        volume_row.pack(fill="x")
        volume_scale = ttk.Scale(
            volume_row, from_=0, to=100, variable=self.sound_volume_var,
            orient="horizontal", command=self._on_sound_master_volume_change)
        volume_scale.pack(side="left", fill="x", expand=True, padx=(0, 5))
        volume_scale.bind(
            "<ButtonRelease-1>",
            lambda _event: self._save_sound_settings(), add="+")
        volume_scale.bind(
            "<KeyRelease>",
            lambda _event: self._save_sound_settings(), add="+")
        ttk.Button(
            volume_row, text="PREVIEW", width=8,
            command=self._preview_master_sound_volume).pack(side="right")
        tk.Label(sound, text="0% = mute     100% = maximum",
                 bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 7)).pack(anchor="w", pady=(0, 3))
        tk.Label(sound, text="Individual sound buses", bg=COLORS["panel"], fg=COLORS["gold"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(5, 1))
        self.sound_group_vars = {}
        for group, label in SOUND_GROUP_LABELS.items():
            row = tk.Frame(sound, bg=COLORS["panel"]); row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=COLORS["panel"], fg=COLORS["text"],
                     width=22, anchor="w").pack(side="left")
            variable = tk.IntVar(value=int(self.sound_group_levels.get(group, 100)))
            self.sound_group_vars[group] = variable
            group_scale = ttk.Scale(
                row, from_=0, to=100, variable=variable, orient="horizontal")
            group_scale.pack(side="left", fill="x", expand=True, padx=(5, 4))
            group_scale.bind(
                "<ButtonRelease-1>",
                lambda _event: self._save_sound_settings(), add="+")
            group_scale.bind(
                "<KeyRelease>",
                lambda _event: self._save_sound_settings(), add="+")
            ttk.Button(row, text="PREVIEW", width=8,
                       command=lambda selected_group=group: self._preview_sound_group(selected_group)).pack(side="right")
        self.sound_settings_status_var = tk.StringVar(
            value="音量スライダーは操作後に自動保存されます。")
        tk.Label(sound, textvariable=self.sound_settings_status_var,
                 bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 7)).pack(anchor="w", pady=(4, 0))
        ttk.Button(sound, text="SAVE SOUND SETTINGS", command=self._save_sound_settings).pack(fill="x", pady=(6, 0))

        hud_box, hud = self._panel(left, "TABLE HUD FIELDS")
        hud_box.pack(fill="x", pady=(10, 0))
        self.hud_field_vars = {key: tk.BooleanVar(value=value) for key, value in self.hud_fields.items()}
        for key, label in HUD_LABELS.items():
            ttk.Checkbutton(hud, text=label, variable=self.hud_field_vars[key]).pack(anchor="w")
        ttk.Button(hud, text="SAVE HUD FIELDS", command=self._save_hud_fields).pack(fill="x", pady=(6, 0))

        # One-click stable-channel app updater. Only allow-listed application .py
        # files are replaced; wallet/history/strategy/config data stay untouched.
        update_box, update = self._panel(right, "APPLICATION UPDATE", padding=8)
        update_box.pack(fill="x", pady=(0, 8))
        tk.Label(update, text="UPDATE NOW is always available in the top application bar.",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=620,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 5))
        tk.Label(update, textvariable=self.update_status_var, bg=COLORS["panel"],
                 fg=COLORS["gold"], wraplength=620, justify="left",
                 font=("Segoe UI", 8)).pack(anchor="w")
        self._update_in_progress = False

        # Compact settings for table stack/pot units and four editable pot-size presets.
        betting_box, betting = self._panel(right, "BET DISPLAY & POT-SIZE PRESETS", padding=8)
        betting_box.pack(fill="x", pady=(0, 8))
        bet_top = tk.Frame(betting, bg=COLORS["panel"])
        bet_top.pack(fill="x")
        tk.Label(bet_top, text="Chip display", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 8))
        self.chip_display_unit_var = tk.StringVar(value=self.chip_display_unit)
        ttk.Radiobutton(bet_top, text="$ USD", value="USD", variable=self.chip_display_unit_var).pack(side="left", padx=4)
        ttk.Radiobutton(bet_top, text="Big Blinds (BB)", value="BB", variable=self.chip_display_unit_var).pack(side="left", padx=4)
        tk.Label(bet_top, text="Pot buttons", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(16, 5))
        self.bet_pot_percent_vars = [tk.StringVar(value=str(value)) for value in self.bet_pot_percentages]
        for index, variable in enumerate(self.bet_pot_percent_vars):
            ttk.Spinbox(bet_top, from_=1, to=500, increment=1, textvariable=variable,
                        width=4, justify="center").pack(side="left", padx=2)
            tk.Label(bet_top, text="%", bg=COLORS["panel"], fg=COLORS["muted"],
                     font=("Segoe UI", 7)).pack(side="left")
        self.betting_display_save_button = ttk.Button(
            betting, text="SAVE BETTING DISPLAY", style="CompactAccent.TButton",
            command=self._save_betting_display_settings)
        # Fill the panel width so the save control remains visible on narrower screens.
        self.betting_display_save_button.pack(fill="x", pady=(6, 0))

        profile_box, profile = self._panel(right, "100 PERSISTENT CPU IDENTITIES")
        profile_box.pack(fill="both", expand=True)
        columns = ("id", "name", "level", "hands", "vpip", "pfr", "3bet", "af")
        self.cpu_profiles_tree = ttk.Treeview(profile, columns=columns, show="headings", height=12)
        headings = {"id": "ID", "name": "NAME", "level": "LV", "hands": "HANDS",
                    "vpip": "VPIP", "pfr": "PFR", "3bet": "3BET", "af": "AF"}
        widths = {"id": 70, "name": 150, "level": 45, "hands": 65, "vpip": 65, "pfr": 65, "3bet": 65, "af": 55}
        for col in columns:
            self.cpu_profiles_tree.heading(col, text=headings[col])
            self.cpu_profiles_tree.column(col, width=widths[col], anchor="center")
        self.cpu_profiles_tree.pack(fill="both", expand=True)
        self.cpu_profiles_tree.bind("<<TreeviewSelect>>", self._load_cpu_profile_editor)
        self.cpu_profile_name_var = tk.StringVar()
        self.cpu_profile_avatar_var = tk.StringVar()
        self.cpu_profile_color_var = tk.StringVar()
        self.cpu_profile_notes_var = tk.StringVar()
        self.cpu_profile_archetype_var = tk.StringVar(value="balanced")
        self.cpu_profile_stats_var = tk.StringVar(value="Select an identity to edit its profile.")
        edit = tk.Frame(profile, bg=COLORS["panel"])
        edit.pack(fill="x", pady=(8, 0))
        for label, var, width in (("Name", self.cpu_profile_name_var, 18),
                                  ("Avatar", self.cpu_profile_avatar_var, 14),
                                  ("Color", self.cpu_profile_color_var, 12)):
            tk.Label(edit, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="left", padx=(0, 3))
            ttk.Entry(edit, textvariable=var, width=width).pack(side="left", padx=(0, 8))
        style_row = tk.Frame(profile, bg=COLORS["panel"])
        style_row.pack(fill="x", pady=(7, 0))
        tk.Label(style_row, text="Tendency", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="left")
        ttk.Combobox(style_row, textvariable=self.cpu_profile_archetype_var,
                     values=["overfolder", "calling_station", "underbluffer", "aggressive", "balanced"],
                     state="readonly", width=18).pack(side="left", padx=(6, 0))
        tk.Label(profile, text="Notes", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(7, 0))
        ttk.Entry(profile, textvariable=self.cpu_profile_notes_var).pack(fill="x")
        tk.Label(profile, textvariable=self.cpu_profile_stats_var, bg=COLORS["panel"], fg=COLORS["gold"],
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(5, 0))
        ttk.Button(profile, text="SAVE CPU PROFILE", style="Accent.TButton",
                   command=self._save_cpu_profile_edits).pack(anchor="e", pady=(6, 0))
        self._refresh_cpu_settings()

    def _periodic_update_check(self):
        """Recheck the stable channel every minute while Pigeon is open."""
        try:
            if not getattr(self, "_update_check_active", False) and not getattr(
                self, "_update_in_progress", False
            ):
                self._refresh_update_button_state()
        finally:
            try:
                self.after(UPDATE_CHECK_INTERVAL_MS, self._periodic_update_check)
            except tk.TclError:
                pass

    def _refresh_update_button_state(self):
        """Check only the stable manifest; do not download if no update exists."""
        if getattr(self, "_update_check_active", False) or getattr(self, "_update_in_progress", False):
            return
        self._update_check_active = True
        try:
            self.update_button.configure(state="normal", style="Accent.TButton", text="CHECK / UPDATE")
        except tk.TclError:
            self._update_check_active = False
            return
        def on_result(available: bool, current: str, candidate: str):
            def apply_result():
                self._update_check_active = False
                if available:
                    self.update_button.configure(state="normal", style="Accent.TButton", text="CHECK / UPDATE", command=self._begin_app_update)
                    self.update_status_var.set(f"Update {candidate} available (current {current}).")
                else:
                    self.update_button.configure(state="normal", style="Accent.TButton", text="CHECK / UPDATE")
                    self.update_status_var.set(f"Pigeon Poker is up to date ({current}). Press CHECK / UPDATE to check again.")
            try:
                self.after(0, apply_result)
            except tk.TclError:
                pass
        def on_error(error: str):
            def apply_error():
                self._update_check_active = False
                self.update_button.configure(state="normal", style="Accent.TButton", text="CHECK / UPDATE")
                self.update_status_var.set(f"Update check failed: {error}")
            try:
                self.after(0, apply_error)
            except tk.TclError:
                pass
        start_update_availability_check(ROOT, on_result, on_error)

    def _begin_app_update(self):
        """Check, verify and apply a stable update without touching user data."""
        if getattr(self, "_update_in_progress", False):
            return
        self._update_in_progress = True
        self.update_button.configure(state="normal", style="Accent.TButton", text="CHECK / UPDATE")
        self.update_status_var.set("Checking for updates…")

        def report(message: str):
            def apply_report():
                self.update_status_var.set(message)
                if message.startswith("Pigeon Poker is up to date"):
                    self._update_in_progress = False
                    self.update_button.configure(state="normal", style="Accent.TButton", text="CHECK / UPDATE")
            try:
                self.after(0, apply_report)
            except tk.TclError:
                pass

        def close_for_update():
            def close_now():
                try:
                    self.update_status_var.set("Applying update and restarting Pigeon Poker…")
                except tk.TclError:
                    pass
                # Reuse the normal shutdown path so open table stacks, wallet
                # state and GTO+ shutdown are saved before files are replaced.
                self.after(500, self._on_close)
            try:
                self.after(0, close_now)
            except tk.TclError:
                pass

        def show_error(message: str):
            def display_error():
                self._update_in_progress = False
                try:
                    self.update_button.configure(state="normal", style="Accent.TButton", text="CHECK / UPDATE")
                    self.update_status_var.set(message)
                    messagebox.showerror("Pigeon Poker Update", message, parent=self)
                except tk.TclError:
                    pass
            try:
                self.after(0, display_error)
            except tk.TclError:
                pass

        start_update_check(ROOT, os.getpid(), report, close_for_update, show_error)

    def _save_betting_display_settings(self):
        try:
            unit = str(self.chip_display_unit_var.get()).upper()
            if unit not in {"USD", "BB"}:
                raise ValueError("表示単位はUSDまたはBBを選択してください。")
            percentages = normalize_pot_presets([variable.get() for variable in self.bet_pot_percent_vars])
            self.chip_display_unit = unit
            self.bet_pot_percentages = percentages
            self.config_data["chip_display_unit"] = unit
            self.config_data["bet_pot_percentages"] = list(percentages)
            save_config(self.config_data)
            self._refresh_table_windows()
            messagebox.showinfo("Betting display", "表示単位とポットサイズボタンを保存しました。")
        except Exception as exc:
            messagebox.showerror("Betting display", str(exc))

    def _save_appearance(self):
        self.appearance = {
            "felt_theme": self.felt_theme_var.get(),
            "table_background": self.table_background_var.get(),
            "card_face_theme": self.card_face_theme_var.get(),
            "card_back_theme": self.card_back_theme_var.get(),
            "four_color_deck": bool(self.four_color_var.get()),
        }
        self.config_data.update(self.appearance)
        save_config(self.config_data)
        self._draw_table()
        self.cash_log_lines.append("Table appearance updated")
        self._refresh_cash_history()

    def _save_hotkeys(self):
        try:
            self.hotkeys = validate_hotkeys({name: var.get() for name, var in self.hotkey_vars.items()})
            self.config_data["hotkeys"] = dict(self.hotkeys)
            save_config(self.config_data)
            messagebox.showinfo("Hotkeys", "ホットキーを保存しました。")
        except Exception as exc:
            messagebox.showerror("Hotkeys", str(exc))

    def _on_sound_master_volume_change(self, value: str):
        try:
            level = max(0, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            level = max(0, min(100, int(self.sound_volume_var.get())))
        self.sound_volume_var.set(level)
        label = getattr(self, "sound_volume_percent_var", None)
        if label is not None:
            label.set(f"{level}%")

    def _preview_master_sound_volume(self):
        """Preview the pending master and per-group levels without saving first."""
        old_master = self.sound_master
        old_volume = self.sound_volume
        old_groups = dict(self.sound_group_levels)
        old_sounds = dict(self.sound_settings)
        try:
            self.sound_master = bool(self.sound_master_var.get())
            self.sound_volume = max(0, min(100, int(self.sound_volume_var.get())))
            self.sound_group_levels = {
                name: max(0, min(100, int(variable.get())))
                for name, variable in self.sound_group_vars.items()
            }
            self.sound_settings = {
                name: bool(getattr(self, f"sound_{name}_var").get())
                for name in SOUND_KEYS
            }
            self._play_sound("your_turn")
        finally:
            self.sound_master = old_master
            self.sound_volume = old_volume
            self.sound_group_levels = old_groups
            self.sound_settings = old_sounds

    def _preview_sound_group(self, group: str):
        """Audition one representative event using the current unsaved bus controls."""
        sample_by_group = {
            "cards": "card_peel",
            "chips": "raise",
            "alerts": "your_turn",
            "celebration": "big_win",
        }
        key = sample_by_group.get(str(group))
        if not key:
            return
        old_master = self.sound_master
        old_volume = self.sound_volume
        old_level = int(self.sound_group_levels.get(group, 100))
        old_event = bool(self.sound_settings.get(key, True))
        try:
            if hasattr(self, "sound_master_var"):
                self.sound_master = bool(self.sound_master_var.get())
            if hasattr(self, "sound_volume_var"):
                self.sound_volume = max(0, min(100, int(self.sound_volume_var.get())))
            variable = getattr(self, "sound_group_vars", {}).get(group)
            if variable is not None:
                self.sound_group_levels[group] = max(0, min(100, int(variable.get())))
            event_variable = getattr(self, f"sound_{key}_var", None)
            if event_variable is not None:
                self.sound_settings[key] = bool(event_variable.get())
            self._play_sound(key)
        finally:
            self.sound_master = old_master
            self.sound_volume = old_volume
            self.sound_group_levels[group] = old_level
            self.sound_settings[key] = old_event

    def _save_sound_settings(self):
        self.sound_master = bool(self.sound_master_var.get())
        self.sound_volume = max(0, min(100, int(self.sound_volume_var.get())))
        self.sound_settings = {name: bool(getattr(self, f"sound_{name}_var").get()) for name in SOUND_KEYS}
        self.sound_group_levels = {name: max(0, min(100, int(variable.get())))
                                   for name, variable in self.sound_group_vars.items()}
        self.config_data["sound_master"] = self.sound_master
        self.config_data["sound_volume"] = self.sound_volume
        self.config_data["sounds"] = dict(self.sound_settings)
        self.config_data["sound_group_volumes"] = dict(self.sound_group_levels)
        save_config(self.config_data)
        if hasattr(self, "sound_volume_percent_var"):
            self.sound_volume_percent_var.set(f"{self.sound_volume}%")
        status = getattr(self, "sound_settings_status_var", None)
        if status is not None:
            status.set("効果音の音量設定を保存しました。")

    def _save_hud_fields(self):
        self.hud_fields = {key: bool(var.get()) for key, var in self.hud_field_vars.items()}
        self.config_data["hud_fields"] = dict(self.hud_fields)
        save_config(self.config_data)
        self._draw_table()

    def _on_global_hotkey(self, event):
        if not self.multi_tables.list() or not self.active_cash_table_id:
            return
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
            return
        key = str(getattr(event, "keysym", "")).upper()
        action_name = next((name for name, value in self.hotkeys.items() if value == key), None)
        if action_name is None:
            return
        slot = self.multi_tables.get(self.active_cash_table_id)
        if slot is None:
            return
        table = slot.state.get("cash_table")
        if table is None or table.hand is None:
            return
        hand = table.hand
        if action_name == "next_hand":
            if hand.finished and not slot.state.get("cash_busy"):
                if self.active_cash_table_id != self.multi_tables.active_id:
                    self._open_floating_table(self.active_cash_table_id)
                self._start_cash_hand(first=False)
                return "break"
            return
        if hand.finished or hand.next_to_act != "hero" or slot.state.get("cash_busy"):
            return
        if self.active_cash_table_id != self.multi_tables.active_id:
            self._open_floating_table(self.active_cash_table_id)
        legal = hand.legal_actions("hero")
        if action_name == "fold" and "fold" in legal["actions"]:
            self._floating_table_action(self.active_cash_table_id, "fold")
        elif action_name == "check_call":
            if "check" in legal["actions"]:
                self._floating_table_action(self.active_cash_table_id, "check")
            elif "call" in legal["actions"]:
                self._floating_table_action(self.active_cash_table_id, "call")
        elif action_name == "all_in" and "all-in" in legal["actions"]:
            self._floating_table_action(self.active_cash_table_id, "all-in")
        elif action_name == "bet_raise" and ("bet" in legal["actions"] or "raise" in legal["actions"]):
            target_var = self.table_windows.get(self.active_cash_table_id, {}).get("bet_target", self.cash_bet_var)
            self._floating_table_bet_action(self.active_cash_table_id, target_var)
        return "break"

    def _play_action_sound(self, action: str):
        """Play one tactile cue and queue a separate spoken action announcement."""
        key = str(action).lower().replace("_", "-")
        if key in {"all-in", "allin", "all-in-call"}:
            sound_key, spoken = "all_in", "All-in"
        elif key in {"check", "call", "bet", "raise", "fold"}:
            sound_key = key
            spoken = {"check": "Check", "call": "Call", "bet": "Bet",
                      "raise": "Raise", "fold": "Fold"}[key]
        else:
            return
        self._play_sound(sound_key)
        self._queue_action_voice(spoken)

    def _queue_action_voice(self, phrase: str):
        """Queue short Action Voice phrases without delaying betting or animation."""
        # __new__-constructed test doubles do not have Tk's internal `tk`
        # field; reading absent Tk attributes through __getattr__ can recurse.
        attributes = getattr(self, "__dict__", {})
        voice_queue = attributes.get("action_voice_queue")
        if voice_queue is None:
            return
        if (not attributes.get("sound_master", False)
                or not attributes.get("sound_settings", {}).get("action_voice", True)
                or int(attributes.get("sound_volume", 0)) <= 0
                or attributes.get("action_voice_stop", threading.Event()).is_set()):
            return
        alert_bus = int(attributes.get("sound_group_levels", {}).get("alerts", 100))
        effective_volume = int(self.sound_volume * max(0, min(100, alert_bus)) / 100)
        if effective_volume <= 0:
            return
        try:
            voice_queue.put_nowait((str(phrase), effective_volume))
        except queue.Full:
            try:
                voice_queue.get_nowait()
                voice_queue.put_nowait((str(phrase), effective_volume))
            except (queue.Empty, queue.Full):
                pass

    def _action_voice_worker_loop(self):
        """Keep a persistent speech engine alive so action callouts have no process-start lag."""
        voice_process = None
        tts_engine = None
        unavailable_reported = False

        def report_unavailable(exc):
            nonlocal unavailable_reported
            if unavailable_reported:
                return
            unavailable_reported = True
            try:
                self.jobs.put_nowait(("sound_error", f"Action Voice unavailable: {exc}"))
            except (queue.Full, AttributeError):
                pass

        while not self.action_voice_stop.is_set():
            try:
                item = self.action_voice_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                self.action_voice_queue.task_done()
                break
            phrase, volume = item
            try:
                spoken = str(phrase).replace("\r", " ").replace("\n", " ").replace("|", " ")[:48]
                if sys.platform.startswith("win"):
                    # System.Speech is part of Windows/.NET. One persistent
                    # hidden PowerShell process avoids spawning a process for
                    # every Check/Call and keeps speech off the Tk thread.
                    if voice_process is None or voice_process.poll() is not None:
                        script = ("Add-Type -AssemblyName System.Speech; "
                                  "$probe=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                                  "$voices=@($probe.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'en-*' }); "
                                  "$en=$voices | Where-Object { $_.VoiceInfo.Culture.Name -eq 'en-US' } | Select-Object -First 1; "
                                  "if(-not $en){$en=$voices | Where-Object { $_.VoiceInfo.Culture.Name -eq 'en-GB' } | Select-Object -First 1}; "
                                  "if(-not $en){$en=$voices | Select-Object -First 1}; "
                                  "if(-not $en){throw 'No English Action Voice is installed'}; "
                                  "$voiceName=$en.VoiceInfo.Name; $probe.Dispose(); "
                                  "while(($l=[Console]::ReadLine()) -ne $null){ "
                                  "$p=$l.Split('|',2); if($p.Length -eq 2){ "
                                  "$sp=$null; try{$sp=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                                  "$sp.SelectVoice($voiceName); "
                                  "$sp.Volume=[Math]::Max(0,[Math]::Min(100,[int]$p[0])); "
                                  "$sp.Rate=-1; "
                                  "$sp.add_SpeakCompleted({ param($sender,$eventArgs) try{$sender.Dispose()}catch{} }); "
                                  "$sp.SpeakAsync($p[1])}catch{if($sp){try{$sp.Dispose()}catch{}}} } }")
                        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        voice_process = subprocess.Popen(
                            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", bufsize=1, creationflags=flags)
                    if voice_process.stdin is None:
                        raise RuntimeError("Windows speech input stream was not created")
                    voice_process.stdin.write(f"{max(0, min(100, int(volume * .52)))}|{spoken}\n")
                    voice_process.stdin.flush()
                else:
                    # Optional developer fallback for non-Windows test runs.
                    if tts_engine is None:
                        import pyttsx3
                        tts_engine = pyttsx3.init()
                        tts_engine.setProperty("rate", 166)
                    tts_engine.setProperty("volume", max(0.0, min(1.0, float(volume) / 100.0 * 0.52)))
                    tts_engine.say(spoken)
                    tts_engine.runAndWait()
            except Exception as exc:
                report_unavailable(exc)
                if voice_process is not None:
                    try:
                        voice_process.terminate()
                    except Exception:
                        pass
                    voice_process = None
                tts_engine = None
            finally:
                self.action_voice_queue.task_done()
        try:
            if voice_process is not None:
                if voice_process.stdin is not None:
                    voice_process.stdin.close()
                voice_process.terminate()
        except Exception:
            pass
        try:
            if tts_engine is not None:
                tts_engine.stop()
        except Exception:
            pass

    def _play_sound(self, name: str):
        """Queue a pre-rendered varied effect through its own adjustable sound bus."""
        key = str(name).lower()
        if key not in SOUND_ASSETS:
            key = "ui_tap"
        if not self.sound_master or not self.sound_settings.get(key, True) or self.sound_volume <= 0:
            return
        group = SOUND_GROUPS.get(key, "alerts")
        group_levels = getattr(self, "sound_group_levels", {})
        bus_level = max(0, min(100, int(group_levels.get(group, 100))))
        # Lower all output; repeating card-deal effects get an additional trim.
        output_scale = 0.45 if key not in {"deal", "card_land"} else 0.15
        effective_volume = int(round(self.sound_volume * bus_level / 100 * output_scale))
        if effective_volume <= 0:
            return
        previous = self.sound_last_variants.get(key, -1)
        options = [value for value in range(SOUND_VARIANT_COUNT) if value != previous]
        variant = random.choice(options or [0])
        self.sound_last_variants[key] = variant
        try:
            self.sound_queue.put_nowait((key, effective_volume, variant))
        except queue.Full:
            try:
                self.sound_queue.get_nowait()
                self.sound_queue.put_nowait((key, effective_volume, variant))
            except (queue.Empty, queue.Full):
                pass

    def _sound_wave_file(self, name: str, volume: int = 70, variation: int = 0) -> Path:
        """Return a pre-rendered stereo take; packaging includes every variation."""
        root = ROOT / "data" / "sounds"
        root.mkdir(parents=True, exist_ok=True)
        key = str(name).lower()
        if key not in SOUND_ASSETS:
            key = "ui_tap"
        take = max(0, min(SOUND_VARIANT_COUNT - 1, int(variation)))
        path = root / f"{key}_v{SOUND_FILE_VERSION}_{take}.wav"
        if not path.is_file():
            write_sound_wav(path, key, variation=take)
        return path

    def _attenuated_wav_file(self, sound_path: Path, volume: int) -> Path | None:
        """Create/cache a PCM WAV attenuated to the same level as the MCI sound bus."""
        level = max(0, min(520, int(volume) * 5))
        if level <= 0:
            return None
        cached = sound_path.with_name(f"{sound_path.stem}_vol{level}.wav")
        try:
            if cached.is_file() and cached.stat().st_mtime_ns >= sound_path.stat().st_mtime_ns:
                return cached
        except OSError:
            pass

        factor = level / 1000.0
        with wave.open(str(sound_path), "rb") as source:
            params = source.getparams()
            if params.comptype != "NONE":
                raise wave.Error("Only uncompressed PCM WAV effects can be attenuated")
            frames = source.readframes(params.nframes)

        width = int(params.sampwidth)
        if width <= 0 or len(frames) % width:
            raise wave.Error("Invalid PCM sample width")
        if width == 1:
            samples = bytearray(frames)
            for index, sample in enumerate(samples):
                samples[index] = max(0, min(255, int(round(128 + (sample - 128) * factor))))
            attenuated = bytes(samples)
        elif width in (2, 4):
            code = "h" if width == 2 else "i"
            count = len(frames) // width
            values = struct.unpack("<" + code * count, frames)
            info = struct.Struct("<" + code * count)
            lower = -(1 << (width * 8 - 1))
            upper = (1 << (width * 8 - 1)) - 1
            attenuated = info.pack(*(
                max(lower, min(upper, int(round(value * factor))))
                for value in values
            ))
        elif width == 3:
            result = bytearray()
            for index in range(0, len(frames), 3):
                sample = int.from_bytes(frames[index:index + 3], "little", signed=True)
                scaled = max(-(1 << 23), min((1 << 23) - 1, int(round(sample * factor))))
                result.extend(scaled.to_bytes(3, "little", signed=True))
            attenuated = bytes(result)
        else:
            raise wave.Error(f"Unsupported PCM sample width: {width}")

        temporary = cached.with_name(cached.name + f".{threading.get_ident()}.tmp")
        with wave.open(str(temporary), "wb") as output:
            output.setparams(params)
            output.writeframes(attenuated)
        temporary.replace(cached)
        return cached

    def _play_wav_nonblocking(self, sound_path: Path, volume: int = 70) -> bool:
        """Play an independently attenuated WAV; both Windows backends honor volume."""
        if int(volume) <= 0:
            return False
        # Windows MCI keeps overlapping effects independent. Never start the
        # original full-level clip unless the per-stream volume command worked.
        win_dll = getattr(ctypes, "WinDLL", None)
        if callable(win_dll):
            alias = "ppk_" + uuid.uuid4().hex[:12]
            try:
                winmm = win_dll("winmm")
                send = winmm.mciSendStringW
                send.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p,
                                 ctypes.c_uint, ctypes.c_void_p]
                send.restype = ctypes.c_uint
                path_text = str(sound_path).replace('"', '')
                opened = send(f'open "{path_text}" type waveaudio alias {alias}', None, 0, None)
                if opened == 0:
                    volume_set = send(
                        f"setaudio {alias} volume to {max(0, min(520, int(volume) * 5))}",
                        None, 0, None
                    )
                    if volume_set == 0:
                        played = send(f"play {alias}", None, 0, None)
                        if played == 0:
                            with wave.open(str(sound_path), "rb") as wav:
                                duration = wav.getnframes() / max(1, wav.getframerate())
                            def close_alias():
                                try:
                                    send(f"close {alias}", None, 0, None)
                                except Exception:
                                    pass
                            timer = threading.Timer(max(.08, duration + .12), close_alias)
                            timer.daemon = True
                            timer.start()
                            return True
                    send(f"close {alias}", None, 0, None)
            except Exception:
                # MCI can be unavailable or reject per-stream volume. The
                # fallback below uses a physically attenuated WAV, not the raw clip.
                pass

        try:
            import winsound
            fallback_path = self._attenuated_wav_file(sound_path, volume)
            if fallback_path is None:
                return False
            winsound.PlaySound(str(fallback_path), winsound.SND_FILENAME
                               | winsound.SND_ASYNC
                               | getattr(winsound, "SND_NODEFAULT", 0))
            return True
        except (ImportError, OSError, RuntimeError, wave.Error, struct.error):
            return False

    def _sound_worker_loop(self):
        """Start each generated WAV asynchronously; clip length never blocks later UI events."""
        while not self.sound_worker_stop.is_set():
            try:
                item = self.sound_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                self.sound_queue.task_done()
                break
            # Accept the legacy two-field queue item used by older tests/plugins.
            if len(item) == 2:
                name, volume = item
                variation = 0
            else:
                name, volume, variation = item
            try:
                sound_path = self._sound_wave_file(name, volume, variation)
                # MCI aliases provide true independent asynchronous streams;
                # a fast follow-up effect never waits for the previous clip.
                self._play_wav_nonblocking(sound_path, volume)
            except (OSError, RuntimeError, wave.Error) as exc:
                # A failed WAV must not disappear silently. Fall back to the
                # Windows system alert and surface the playback failure in the UI.
                try:
                    import winsound
                    winsound.MessageBeep(getattr(winsound, "MB_ICONEXCLAMATION", 0))
                except Exception:
                    pass
                try:
                    self.jobs.put_nowait(("sound_error", f"{name}: {exc}"))
                except queue.Full:
                    pass
            finally:
                self.sound_queue.task_done()

    def _save_auto_rebuy(self):
        self.config_data["cash_auto_rebuy"] = bool(self.cash_auto_rebuy_var.get())
        save_config(self.config_data)

    def _refresh_cpu_settings(self):
        stake = self.cpu_stake_var.get()
        try:
            distribution = self.cpu_pool_store.get_distribution(stake)
            for level, var in self.cpu_distribution_vars.items():
                var.set(str(distribution[level]))
            self.cpu_distribution_status.set(f"{stake}: " + " / ".join(f"Lv.{level}={distribution[level]}" for level in range(1, 6)))
        except Exception as exc:
            self.cpu_distribution_status.set(str(exc))
        self._refresh_cpu_profiles_tree()

    def _refresh_cpu_profiles_tree(self):
        if not hasattr(self, "cpu_profiles_tree"):
            return
        selected = self.cpu_profiles_tree.selection()
        selected_id = selected[0] if selected else None
        for item in self.cpu_profiles_tree.get_children():
            self.cpu_profiles_tree.delete(item)
        stake = self.cpu_stake_var.get()
        for index in range(1, 101):
            cpu_id = f"cpu{index:03d}"
            profile = self.cpu_pool_store.get_profile(cpu_id, stake)
            self.cpu_profiles_tree.insert("", "end", iid=cpu_id, values=(
                cpu_id, profile.name, profile.level, profile.hands,
                f"{profile.vpip:.1f}", f"{profile.pfr:.1f}",
                f"{profile.three_bet:.1f}", f"{profile.aggression_factor:.2f}"))
        if selected_id and self.cpu_profiles_tree.exists(selected_id):
            self.cpu_profiles_tree.selection_set(selected_id)
            self._load_cpu_profile_editor()

    def _load_cpu_profile_editor(self, _event=None):
        selected = self.cpu_profiles_tree.selection()
        if not selected:
            return
        cpu_id = selected[0]
        profile = self.cpu_pool_store.get_profile(cpu_id, self.cpu_stake_var.get())
        self.cpu_profile_name_var.set(profile.name)
        self.cpu_profile_avatar_var.set(profile.avatar)
        self.cpu_profile_color_var.set(profile.color)
        self.cpu_profile_notes_var.set(profile.notes)
        self.cpu_profile_archetype_var.set(profile.archetype)
        self.cpu_profile_stats_var.set(
            f"{cpu_id} • {self.cpu_stake_var.get()} Lv.{profile.level} • Hands {profile.hands} • "
            f"{profile.archetype} • VPIP {profile.vpip:.1f}% / PFR {profile.pfr:.1f}% / 3Bet {profile.three_bet:.1f}% / AF {profile.aggression_factor:.2f}"
        )

    def _save_cpu_profile_edits(self):
        selected = self.cpu_profiles_tree.selection()
        if not selected:
            messagebox.showinfo("CPU profile", "編集するCPUを一覧から選択してください。")
            return
        cpu_id = selected[0]
        try:
            self.cpu_pool_store.update_profile(
                cpu_id, name=self.cpu_profile_name_var.get(),
                avatar=self.cpu_profile_avatar_var.get(), notes=self.cpu_profile_notes_var.get(),
                color=self.cpu_profile_color_var.get(),
                archetype=self.cpu_profile_archetype_var.get())
            self._refresh_cpu_profiles_tree()
            self.cpu_profiles_tree.selection_set(cpu_id)
            self._load_cpu_profile_editor()
            self.cpu_distribution_status.set(f"{cpu_id} profile saved")
        except Exception as exc:
            messagebox.showerror("CPU profile", str(exc))

    def _apply_cpu_distribution(self):
        try:
            distribution = {level: int(var.get().strip()) for level, var in self.cpu_distribution_vars.items()}
            self.cpu_pool_store.set_distribution(self.cpu_stake_var.get(), distribution)
            self._refresh_cpu_settings()
            self.cpu_distribution_status.set(f"{self.cpu_stake_var.get()} distribution saved (100 total).")
        except Exception as exc:
            messagebox.showerror("CPU level distribution", str(exc))

    def _build_pokercraft_page(self):
        page = self._new_page("poker_craft")
        self._page_header(page, "PokerCraft", "Session-based hand history • profit, All-in EV and player/position analysis")
        summary = tk.Frame(page, bg=COLORS["bg"])
        summary.pack(fill="x", padx=22, pady=(0, 7))
        self.pokercraft_summary_var = tk.StringVar(value="0 hands")
        tk.Label(summary, textvariable=self.pokercraft_summary_var, bg=COLORS["bg"],
                 fg=COLORS["green"], font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(summary, text="EXPORT CSV", command=self._export_pokercraft_csv).pack(side="right", padx=(6, 0))
        ttk.Button(summary, text="REFRESH", command=self._refresh_pokercraft).pack(side="right")

        # PokerCraft session overview: date/stake filter plus sortable session rows.
        session_box = tk.Frame(page, bg=COLORS["panel"], padx=9, pady=6)
        session_box.pack(fill="x", padx=22, pady=(0, 8))
        session_head = tk.Frame(session_box, bg=COLORS["panel"])
        session_head.pack(fill="x")
        tk.Label(session_head, text="SESSION HISTORY  •  DOUBLE-CLICK THE CHECK COLUMN TO INCLUDE / EXCLUDE",
                 bg=COLORS["panel"], fg=COLORS["gold"], font=("Segoe UI", 8, "bold")).pack(side="left")
        ttk.Button(session_head, text="ALL", width=6, command=lambda: self._set_pokercraft_sessions(True)).pack(side="right", padx=(4, 0))
        ttk.Button(session_head, text="NONE", width=6, command=lambda: self._set_pokercraft_sessions(False)).pack(side="right")
        session_filters = tk.Frame(session_box, bg=COLORS["panel"])
        session_filters.pack(fill="x", pady=(4, 4))
        self.poker_from_filter_var = tk.StringVar(value="")
        self.poker_to_filter_var = tk.StringVar(value="")
        self.poker_session_stake_var = tk.StringVar(value="ALL")
        tk.Label(session_filters, text="FROM", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 3))
        ttk.Entry(session_filters, textvariable=self.poker_from_filter_var, width=12).pack(side="left", padx=(0, 8))
        tk.Label(session_filters, text="TO", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 3))
        ttk.Entry(session_filters, textvariable=self.poker_to_filter_var, width=12).pack(side="left", padx=(0, 8))
        tk.Label(session_filters, text="BLINDS", bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 3))
        ttk.Combobox(session_filters, textvariable=self.poker_session_stake_var,
                     values=["ALL", "NL2", "NL5", "NL10", "NL25", "NL50", "NL100", "NL200", "VIP25/50"],
                     state="readonly", width=9).pack(side="left", padx=(0, 8))
        ttk.Button(session_filters, text="SHOW", style="Accent.TButton",
                   command=self._refresh_pokercraft).pack(side="left", padx=(0, 8))
        tk.Label(session_filters, text="TIME DISPLAY: JAPAN (JST)",
                 bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="right")
        session_cols = ("include", "time", "blinds", "table", "hands", "duration", "winloss")
        self.poker_session_tree = ttk.Treeview(
            session_box, columns=session_cols, show="headings", height=4, selectmode="browse")
        session_headings = {"include": "✓", "time": "TIME (JST)", "blinds": "BLINDS",
                            "table": "TABLE", "hands": "HANDS", "duration": "DURATION",
                            "winloss": "WIN / LOSS"}
        session_widths = {"include": 34, "time": 160, "blinds": 100, "table": 130,
                          "hands": 72, "duration": 100, "winloss": 110}
        for column in session_cols:
            self.poker_session_tree.heading(
                column, text=session_headings[column],
                command=(lambda col=column: self._sort_pokercraft_sessions(col)) if column != "include" else "")
            self.poker_session_tree.column(column, width=session_widths[column],
                                           anchor="center", stretch=(column in {"time", "table"}))
        self.poker_session_tree.pack(fill="x", expand=False)
        self.poker_session_tree.bind("<Double-1>", self._toggle_pokercraft_session_row)
        self.poker_session_vars: dict[str, tk.BooleanVar] = {}
        self.poker_session_meta: list[dict[str, Any]] = []
        self.poker_session_signature: tuple[tuple[Any, ...], ...] = ()
        self.poker_session_known_ids: set[str] = set()
        self.poker_session_selected_ids: set[str] | None = None
        self.poker_session_sort_column: str | None = None
        self.poker_session_sort_reverse = True

        notebook = ttk.Notebook(page)
        self.poker_notebook = notebook
        notebook.pack(fill="both", expand=True, padx=22, pady=(0, 15))
        hands_host, hands_tab = self._make_scrollable_tab(notebook, "Game History", COLORS["bg"])
        analytics_host, analytics_tab = self._make_scrollable_tab(notebook, "EV Graph", COLORS["bg"])
        hole_cards_host, hole_cards_tab = self._make_scrollable_tab(notebook, "Hole Cards", COLORS["bg"])
        position_host, position_tab = self._make_scrollable_tab(notebook, "Position", COLORS["bg"])
        breakdown_host, breakdown_tab = self._make_scrollable_tab(notebook, "Opponents", COLORS["bg"])
        stats_host, stats_tab = self._make_scrollable_tab(notebook, "Player Stats", COLORS["bg"])

        hole_header = tk.Frame(hole_cards_tab, bg=COLORS["bg"])
        hole_header.pack(fill="x", pady=(0, 7))
        self.poker_hole_cards_summary_var = tk.StringVar(value="Starting-hand results from the selected sessions")
        tk.Label(hole_header, textvariable=self.poker_hole_cards_summary_var,
                 bg=COLORS["bg"], fg=COLORS["green"],
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        hole_panel, hole_inner = self._panel(hole_cards_tab, "STARTING HAND PERFORMANCE  •  169 HAND CLASSES")
        hole_panel.pack(fill="both", expand=True)
        hole_columns = ("hand", "hands", "winrate", "net", "avgpot", "avgnet")
        self.poker_hole_cards_tree = ttk.Treeview(
            hole_inner, columns=hole_columns, show="headings", height=20)
        hole_headings = {
            "hand": "HAND", "hands": "HANDS", "winrate": "WIN RATE",
            "net": "NET", "avgpot": "AVG POT", "avgnet": "AVG NET",
        }
        hole_widths = {"hand": 100, "hands": 90, "winrate": 110,
                       "net": 130, "avgpot": 120, "avgnet": 120}
        for column in hole_columns:
            self.poker_hole_cards_tree.heading(
                column, text=hole_headings[column],
                command=lambda col=column: self._sort_pokercraft_hole_cards(col))
            self.poker_hole_cards_tree.column(column, width=hole_widths[column], anchor="center")
        self.poker_hole_cards_tree.pack(fill="both", expand=True)
        self.poker_hole_cards_rows: list[dict[str, Any]] = []
        self.poker_hole_cards_sort_column = "hands"
        self.poker_hole_cards_sort_reverse = True

        filters = tk.Frame(hands_tab, bg=COLORS["panel"], padx=10, pady=7)
        filters.pack(fill="x", pady=(0, 7))
        row1 = tk.Frame(filters, bg=COLORS["panel"]); row1.pack(fill="x")
        self.poker_filter_stake_var = tk.StringVar(value="ALL")
        self.poker_sort_var = tk.StringVar(value="DATE")
        self.poker_sort_order_var = tk.StringVar(value="DESC")
        self.poker_include_rake_var = tk.BooleanVar(value=True)
        tk.Label(row1, text="Stake", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="left")
        ttk.Combobox(row1, textvariable=self.poker_filter_stake_var,
                     values=["ALL", "NL2", "NL5", "NL10", "NL25", "NL50", "NL100", "NL200", "VIP25/50"],
                     state="readonly", width=8).pack(side="left", padx=(4, 12))
        tk.Label(row1, text="Sort", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="left")
        ttk.Combobox(row1, textvariable=self.poker_sort_var,
                     values=["DATE", "POT", "PROFIT", "LOSS"], state="readonly", width=9).pack(side="left", padx=(4, 12))
        ttk.Combobox(row1, textvariable=self.poker_sort_order_var,
                     values=["DESC", "ASC"], state="readonly", width=7).pack(side="left", padx=(0, 10))
        tk.Label(row1, text="Result", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="left")
        self.poker_filter_result_var = tk.StringVar(value="ALL")
        ttk.Combobox(row1, textvariable=self.poker_filter_result_var,
                     values=["ALL", "WIN", "LOSS", "EVEN"], state="readonly", width=7).pack(side="left", padx=(4, 10))
        tk.Label(row1, text="Showdown", bg=COLORS["panel"], fg=COLORS["muted"]).pack(side="left")
        self.poker_filter_showdown_var = tk.StringVar(value="ALL")
        ttk.Combobox(row1, textvariable=self.poker_filter_showdown_var,
                     values=["ALL", "SHOWDOWN", "NO SHOWDOWN"], state="readonly", width=12).pack(side="left", padx=(4, 10))
        ttk.Checkbutton(row1, text="Include rake in displayed net", variable=self.poker_include_rake_var,
                        command=self._refresh_pokercraft).pack(side="left", padx=4)

        row2 = tk.Frame(filters, bg=COLORS["panel"]); row2.pack(fill="x", pady=(6, 0))
        self.poker_hole_filter_var = tk.StringVar()
        self.poker_board_filter_var = tk.StringVar()
        for label, variable, width in (("Hole", self.poker_hole_filter_var, 7),
                                       ("Board", self.poker_board_filter_var, 7)):
            tk.Label(row2, text=label, bg=COLORS["panel"], fg=COLORS["muted"],
                     font=("Segoe UI", 8)).pack(side="left", padx=(0, 3))
            ttk.Entry(row2, textvariable=variable, width=width).pack(side="left", padx=(0, 8))
        ttk.Button(row2, text="APPLY", style="Accent.TButton",
                   command=self._refresh_pokercraft).pack(side="left", padx=(0, 5))
        ttk.Button(row2, text="RESET", command=self._reset_pokercraft_filters).pack(side="left")

        body = tk.Frame(hands_tab, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)
        cols = ("date", "session", "stake", "board", "hand", "pot", "rake", "net", "allin_ev", "result")
        self.history_tree = ttk.Treeview(body, columns=cols, show="headings", height=11)
        headings = {"date": "DATE", "session": "TABLE SESSION", "stake": "STAKE", "board": "BOARD",
                    "hand": "YOUR HAND", "pot": "POT", "rake": "RAKE", "net": "NET", "allin_ev": "ALL-IN EV", "result": "RESULT"}
        widths = {"date": 140, "session": 105, "stake": 62, "board": 100, "hand": 80,
                  "pot": 72, "rake": 68, "net": 82, "allin_ev": 82, "result": 70}
        self.poker_history_sort_column: str | None = None
        self.poker_history_sort_reverse = True
        for col in cols:
            self.history_tree.heading(
                col, text=headings[col],
                command=lambda column=col: self._sort_pokercraft_hands(column))
            self.history_tree.column(col, width=widths[col], anchor="center")
        self.history_tree.pack(fill="both", expand=True)
        self.history_tree.bind("<<TreeviewSelect>>", self._show_pokercraft_hand)
        detail_box, detail = self._panel(body, "HAND DETAIL / ACTIONS")
        detail_box.pack(fill="both", expand=True, pady=(7, 0))
        detail_toolbar = tk.Frame(detail, bg=COLORS["panel"])
        detail_toolbar.pack(fill="x", pady=(0, 4))
        self.history_replay_button = ttk.Button(
            detail_toolbar, text="▶  REPLAY HAND", style="Accent.TButton",
            command=self._open_pokercraft_replay, state="disabled")
        self.history_replay_button.pack(side="left", padx=(0, 6))
        self.history_range_button = ttk.Button(
            detail_toolbar, text="▦  PREFLOP RANGE",
            command=self._open_pokercraft_history_range, state="disabled")
        self.history_range_button.pack(side="left")
        self.selected_history_preflop_range = None
        self.history_detail = tk.Text(detail, height=7, bg="#081321", fg="#dce8f7",
                                      insertbackground="white", relief="flat",
                                      font=("Consolas", 8), wrap="word")
        self.history_detail.pack(fill="both", expand=True)
        self.history_detail.configure(state="disabled")
        self.history_records: dict[str, dict[str, Any]] = {}
        self.selected_history_record: dict[str, Any] | None = None

        graph_panel, graph_inner = self._panel(
            analytics_tab, "WIN / LOSS + ALL-IN EV  •  HAND-ALIGNED COMPARISON"
        )
        graph_panel.pack(fill="both", expand=True)
        self.poker_comparison_canvas = tk.Canvas(
            graph_inner, bg="#081321", height=330, highlightthickness=0, cursor="crosshair"
        )
        self.poker_comparison_canvas.pack(fill="both", expand=True)
        self.poker_comparison_canvas.bind("<Configure>", self._on_pokercraft_graph_resize)
        self.poker_comparison_canvas.bind("<Motion>", self._on_pokercraft_graph_hover)
        self.poker_comparison_canvas.bind("<Leave>", self._clear_pokercraft_graph_hover)
        self.poker_comparison_canvas.bind("<Button-1>", self._on_pokercraft_graph_click)
        self.poker_graph_points: list[dict[str, Any]] = []
        self.poker_graph_rows: list[dict[str, Any]] = []
        self.poker_graph_last_size: tuple[int, int] | None = None
        self.poker_graph_plot_bounds = (64, 398, 24, 198)
        self.poker_ev_note = tk.StringVar(value="Green = actual net • Amber = All-in EV • click a hand point to inspect it.")
        tk.Label(analytics_tab, textvariable=self.poker_ev_note, bg=COLORS["bg"], fg=COLORS["muted"],
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(5, 0))

        breakdowns = tk.Frame(breakdown_tab, bg=COLORS["bg"])
        breakdowns.pack(fill="both", expand=True)
        opp_panel, opp_inner = self._panel(breakdowns, "RESULT ATTRIBUTION BY OPPONENT")
        opp_panel.pack(side="left", fill="both", expand=True, padx=(0, 5))
        opp_cols = ("opponent", "hands", "wins", "net")
        self.poker_opponent_tree = ttk.Treeview(opp_inner, columns=opp_cols, show="headings", height=15)
        for col, label, width in (("opponent", "OPPONENT", 170), ("hands", "SHARED HANDS", 90),
                                  ("wins", "HERO POT WINS", 95), ("net", "ATTRIBUTED NET", 110)):
            self.poker_opponent_tree.heading(col, text=label)
            self.poker_opponent_tree.column(col, width=width, anchor="center")
        self.poker_opponent_tree.pack(fill="both", expand=True)
        pos_panel, pos_inner = self._panel(position_tab, "RESULT BY HERO POSITION")
        pos_panel.pack(fill="both", expand=True)
        tk.Label(position_tab, text="Position results use the same date / blinds / session filters as Game History.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(5, 0))
        pos_cols = ("position", "hands", "wins", "net", "bb100")
        self.poker_position_tree = ttk.Treeview(pos_inner, columns=pos_cols, show="headings", height=15)
        for col, label, width in (("position", "POSITION", 95), ("hands", "HANDS", 70),
                                  ("wins", "WINS", 65), ("net", "NET", 100), ("bb100", "BB / 100", 90)):
            self.poker_position_tree.heading(col, text=label)
            self.poker_position_tree.column(col, width=width, anchor="center")
        self.poker_position_tree.pack(fill="both", expand=True)
        tk.Label(breakdown_tab, text="Opponent attribution is calculated from shared-pot contributors/winners; multiway pots are allocated across the involved opponents.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(5, 0))

        stats_header = tk.Frame(stats_tab, bg=COLORS["bg"])
        stats_header.pack(fill="x", pady=(0, 7))
        self.poker_stats_summary_var = tk.StringVar(value="Player statistics from selected hands")
        tk.Label(stats_header, textvariable=self.poker_stats_summary_var, bg=COLORS["bg"],
                 fg=COLORS["green"], font=("Segoe UI", 10, "bold")).pack(side="left")
        stats_panel, stats_inner = self._panel(stats_tab, "PLAYER PERFORMANCE  •  CLICK A COLUMN TO SORT")
        stats_panel.pack(fill="both", expand=True)
        stats_cols = ("player", "hands", "vpip", "pfr", "three_bet", "wtsd", "wsd", "wwsf", "af", "bb100", "net")
        self.poker_stats_tree = ttk.Treeview(stats_inner, columns=stats_cols, show="headings", height=18)
        stats_headings = {"player": "PLAYER", "hands": "HANDS", "vpip": "VPIP", "pfr": "PFR",
                          "three_bet": "3-BET", "wtsd": "WTSD", "wsd": "W$SD", "wwsf": "WWSF",
                          "af": "AGG. FACTOR", "bb100": "BB / 100", "net": "NET"}
        stats_widths = {"player": 170, "hands": 70, "vpip": 75, "pfr": 75, "three_bet": 75,
                        "wtsd": 75, "wsd": 75, "wwsf": 75, "af": 85, "bb100": 95, "net": 110}
        for col in stats_cols:
            self.poker_stats_tree.heading(col, text=stats_headings[col])
            self.poker_stats_tree.column(col, width=stats_widths[col], anchor="center")
        self.poker_stats_tree.pack(fill="both", expand=True)
        for column in stats_cols:
            self.poker_stats_tree.heading(column, command=lambda c=column: self._sort_pokercraft_player_stats(c))
        tk.Label(stats_tab, text="VPIP/PFR use dealt hands; 3-Bet uses observed 3-bet opportunities; WTSD/W$SD/WWSF use flop/showdown reach. AF = postflop bets+raises ÷ calls. These are local Pigeon calculations.",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=1150, justify="left").pack(anchor="w", pady=(5, 0))
        self.poker_stats_rows: list[dict[str, Any]] = []
        self.poker_stats_sort_column = "hands"
        self.poker_stats_sort_reverse = True
        self.poker_filtered_rows: list[dict[str, Any]] = []
        self._pokercraft_last_latest_signature = None
        self._refresh_pokercraft()

    @staticmethod
    def _pokercraft_parse_timestamp(value: Any, *, assume_utc: bool = True):
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc if assume_utc else timezone(timedelta(hours=9)))
            return parsed
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _format_pokercraft_jst(cls, value: Any, fmt: str = "%Y-%m-%d %H:%M:%S"):
        parsed = cls._pokercraft_parse_timestamp(value, assume_utc=True)
        if parsed is None:
            return "—"
        return parsed.astimezone(timezone(timedelta(hours=9))).strftime(fmt) + " JST"

    @staticmethod
    def _pokercraft_blinds_label(rate: str) -> str:
        return {
            "NL2": "$0.01 / $0.02", "NL5": "$0.02 / $0.05",
            "NL10": "$0.05 / $0.10", "NL25": "$0.10 / $0.25",
            "NL50": "$0.25 / $0.50", "NL100": "$0.50 / $1",
            "NL200": "$1 / $2", "VIP25/50": "$25 / $50",
        }.get(str(rate), str(rate))

    def _session_duration_sort_value(self, item: dict[str, Any]) -> int:
        start = self._pokercraft_parse_timestamp(item.get("started_at"))
        end = self._pokercraft_parse_timestamp(item.get("last_hand_at"))
        return max(0, int((end - start).total_seconds())) if start and end else 0

    def _session_duration_label(self, item: dict[str, Any]) -> str:
        seconds = self._session_duration_sort_value(item)
        return f"{seconds // 3600:02d}:{(seconds // 60) % 60:02d}:{seconds % 60:02d}"

    def _set_pokercraft_sessions(self, enabled: bool):
        all_ids = {str(item.get("session_id", "")) for item in self.poker_session_meta
                   if str(item.get("session_id", ""))}
        if self.poker_session_selected_ids is None:
            self.poker_session_selected_ids = set(all_ids)
        elif enabled:
            self.poker_session_selected_ids.update(all_ids)
        else:
            self.poker_session_selected_ids.difference_update(all_ids)
        self._refresh_pokercraft_session_checks()
        self._refresh_pokercraft()

    def _sort_pokercraft_sessions(self, column: str):
        if self.poker_session_sort_column == column:
            self.poker_session_sort_reverse = not bool(self.poker_session_sort_reverse)
        else:
            self.poker_session_sort_column = column
            self.poker_session_sort_reverse = False
        self._refresh_pokercraft_session_checks()

    def _toggle_pokercraft_session_row(self, event=None):
        tree = getattr(self, "poker_session_tree", None)
        if tree is None:
            return
        iid = tree.identify_row(event.y) if event is not None else ""
        if not iid:
            return
        if self.poker_session_selected_ids is None:
            self.poker_session_selected_ids = {
                str(item.get("session_id", "")) for item in self.poker_session_meta
            }
        if iid in self.poker_session_selected_ids:
            self.poker_session_selected_ids.remove(iid)
        else:
            self.poker_session_selected_ids.add(iid)
        self._refresh_pokercraft_session_checks()
        self._refresh_pokercraft()

    def _refresh_pokercraft_session_checks(self):
        sessions = self.history_store.list_sessions(1000)
        full_ids = {str(item.get("session_id", "")) for item in sessions
                    if str(item.get("session_id", ""))}
        if self.poker_session_selected_ids is None:
            self.poker_session_selected_ids = set(full_ids)
        else:
            newly_seen = full_ids - set(self.poker_session_known_ids)
            self.poker_session_selected_ids.intersection_update(full_ids)
            self.poker_session_selected_ids.update(newly_seen)
        self.poker_session_known_ids = set(full_ids)
        self.poker_session_meta = sessions

        from_text = self.poker_from_filter_var.get().strip()
        to_text = self.poker_to_filter_var.get().strip()
        stake = self.poker_session_stake_var.get().strip()
        start_bound = self._pokercraft_parse_timestamp(from_text, assume_utc=False) if from_text else None
        end_bound = self._pokercraft_parse_timestamp(to_text, assume_utc=False) if to_text else None
        if end_bound is not None and len(to_text) == 10:
            end_bound = end_bound.replace(hour=23, minute=59, second=59, microsecond=999999)
        filtered = []
        for item in sessions:
            if stake and stake != "ALL" and str(item.get("table_rate", "")) != stake:
                continue
            started = self._pokercraft_parse_timestamp(item.get("started_at"))
            if started is not None:
                started_jst = started.astimezone(timezone(timedelta(hours=9)))
                if start_bound is not None and started_jst < start_bound:
                    continue
                if end_bound is not None and started_jst > end_bound:
                    continue
            filtered.append(item)

        signature = tuple((
            str(item.get("session_id", "")), str(item.get("table_rate", "")),
            int(item.get("hands", 0)), int(item.get("net", 0)),
            str(item.get("started_at", "")), str(item.get("last_hand_at", "")),
        ) for item in filtered)
        filter_signature = (
            from_text, to_text, stake, self.poker_session_sort_column,
            bool(self.poker_session_sort_reverse),
            tuple(sorted(self.poker_session_selected_ids or set())),
        )
        if (signature != self.poker_session_signature
                or getattr(self, "poker_session_filter_signature", None) != filter_signature
                or not self.poker_session_tree.get_children()):
            rows = list(filtered)
            column = self.poker_session_sort_column or "time"
            sorters = {
                "time": lambda item: str(item.get("started_at", "")),
                "blinds": lambda item: str(item.get("table_rate", "")),
                "table": lambda item: str(item.get("table_mode") or item.get("table_name")
                                           or item.get("table_id") or item.get("table_rate", "")),
                "hands": lambda item: int(item.get("hands", 0)),
                "duration": lambda item: self._session_duration_sort_value(item),
                "winloss": lambda item: int(item.get("net", 0)),
                "include": lambda item: str(item.get("session_id", "")),
            }
            rows.sort(key=sorters.get(column, sorters["time"]),
                      reverse=(self.poker_session_sort_reverse if self.poker_session_sort_column else True))
            for child in self.poker_session_tree.get_children():
                self.poker_session_tree.delete(child)
            self.poker_session_vars = {}
            for item in rows:
                sid = str(item.get("session_id", ""))
                selected = sid in self.poker_session_selected_ids
                self.poker_session_vars[sid] = tk.BooleanVar(value=selected)
                time_text = self._format_pokercraft_jst(item.get("started_at"), "%Y-%m-%d %I:%M %p")
                rate = str(item.get("table_rate", ""))
                default_table = ("VIP" if rate == "VIP25/50"
                                 else ("Rush & Cash" if item.get("table_id") else "Cash"))
                table_name = str(item.get("table_mode") or item.get("table_name") or default_table)
                self.poker_session_tree.insert("", "end", iid=sid, values=(
                    "✓" if selected else "□", time_text,
                    self._pokercraft_blinds_label(str(item.get("table_rate", ""))),
                    table_name, int(item.get("hands", 0)),
                    self._session_duration_label(item),
                    f"${int(item.get('net', 0))/100:+.2f}",
                ))
            headers = {"include": "✓", "time": "TIME (JST)", "blinds": "BLINDS",
                       "table": "TABLE", "hands": "HANDS", "duration": "DURATION",
                       "winloss": "WIN / LOSS"}
            for column_name, label in headers.items():
                arrow = ""
                if self.poker_session_sort_column == column_name:
                    arrow = " ↓" if self.poker_session_sort_reverse else " ↑"
                self.poker_session_tree.heading(column_name, text=label + arrow)
        self.poker_session_signature = signature
        self.poker_session_filter_signature = filter_signature
        visible_ids = {str(item.get("session_id", "")) for item in filtered}
        return sorted(visible_ids.intersection(self.poker_session_selected_ids))

    def _draw_pokercraft_comparison_graph(self, canvas: tk.Canvas, rows: list[dict[str, Any]]):
        """Draw actual cumulative net and All-in EV on one shared hand axis."""
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(420, canvas.winfo_width())
        height = max(240, canvas.winfo_height())
        left, right, top, bottom = 64, width - 22, 24, height - 42
        self.poker_graph_last_size = (width, height)
        self.poker_graph_rows = [dict(row) for row in rows]
        self.poker_graph_plot_bounds = (left, right, top, bottom)
        canvas.create_rectangle(left, top, right, bottom, outline="#294158", width=1)
        series = cumulative_comparison_values(rows)
        chronological = [point["row"] for point in series]
        actual_values = [int(point["actual_cumulative"]) for point in series]
        ev_values = [int(point["ev_cumulative"]) for point in series]

        self.poker_graph_points = []
        if not chronological:
            canvas.create_text(width / 2, height / 2, text="No selected hand history",
                               fill="#91a3b8", font=("Segoe UI", 10, "bold"))
            self._draw_pokercraft_graph_legend(canvas, left, top)
            return

        minimum = min([0] + actual_values + ev_values)
        maximum = max([0] + actual_values + ev_values)
        if minimum == maximum:
            minimum -= 100
            maximum += 100
        pad = max(1, int((maximum - minimum) * .08))
        minimum -= pad
        maximum += pad

        def point_xy(index: int, value: int) -> tuple[float, float]:
            x = left + (index / max(1, len(chronological) - 1)) * (right - left)
            y = bottom - ((value - minimum) / (maximum - minimum)) * (bottom - top)
            return x, y

        for grid_index in range(5):
            ratio = grid_index / 4
            y = bottom - ratio * (bottom - top)
            amount = minimum + (maximum - minimum) * ratio
            canvas.create_line(left, y, right, y, fill="#1e3348", dash=(2, 3))
            canvas.create_text(left - 8, y, text=f"${amount / 100:,.0f}", fill="#91a3b8",
                               anchor="e", font=("Segoe UI", 7))

        actual_points = [point_xy(i, v) for i, v in enumerate(actual_values)]
        ev_points = [point_xy(i, v) for i, v in enumerate(ev_values)]
        if len(actual_points) > 1:
            canvas.create_line(*[coord for point in actual_points for coord in point],
                               fill="#43d6a0", width=2, smooth=False, tags=("actual_curve",))
            canvas.create_line(*[coord for point in ev_points for coord in point],
                               fill="#efbf68", width=2, smooth=False,
                               dash=(5, 2), tags=("ev_curve",))
        for i, (actual_point, ev_point, point_data) in enumerate(zip(actual_points, ev_points, series)):
            x, ya = actual_point
            _xe, ye = ev_point
            radius = 2.2 if len(chronological) > 180 else 3
            canvas.create_oval(x-radius, ya-radius, x+radius, ya+radius,
                               fill="#43d6a0", outline="", tags=("actual_point",))
            canvas.create_oval(x-radius, ye-radius, x+radius, ye+radius,
                               fill="#efbf68", outline="", tags=("ev_point",))
            self.poker_graph_points.append({
                "x": x, "actual_y": ya, "ev_y": ye,
                "actual": actual_values[i], "ev": ev_values[i],
                "row": point_data["row"],
                "actual_step": point_data["actual_step"],
                "ev_step": point_data["ev_step"],
            })

        canvas.create_text(left, height - 17, text="HAND 1", fill="#91a3b8",
                           anchor="w", font=("Segoe UI", 7))
        canvas.create_text(right, height - 17, text=f"HAND {len(chronological)}", fill="#91a3b8",
                           anchor="e", font=("Segoe UI", 7))
        self._draw_pokercraft_graph_legend(canvas, left, top)

    @staticmethod
    def _draw_pokercraft_graph_legend(canvas: tk.Canvas, left: int, top: int):
        canvas.create_line(left + 8, top - 10, left + 28, top - 10, fill="#43d6a0", width=3)
        canvas.create_text(left + 34, top - 10, text="WIN / LOSS", fill="#d9e6f4",
                           anchor="w", font=("Segoe UI", 8, "bold"))
        canvas.create_line(left + 120, top - 10, left + 140, top - 10,
                           fill="#efbf68", width=3, dash=(5, 2))
        canvas.create_text(left + 146, top - 10, text="ALL-IN EV", fill="#d9e6f4",
                           anchor="w", font=("Segoe UI", 8, "bold"))

    def _on_pokercraft_graph_resize(self, event):
        if event.width < 420 or event.height < 240:
            return
        size = (int(event.width), int(event.height))
        if size == self.poker_graph_last_size:
            return
        self._draw_pokercraft_comparison_graph(self.poker_comparison_canvas, self.poker_graph_rows)

    def _on_pokercraft_graph_hover(self, event):
        canvas = self.poker_comparison_canvas
        canvas.delete("graph_hover")
        if not self.poker_graph_points:
            return
        left, right, top, bottom = self.poker_graph_plot_bounds
        if event.x < left or event.x > right or event.y < top or event.y > bottom:
            return
        point = min(self.poker_graph_points, key=lambda item: min(
            (float(item["x"]) - event.x) ** 2 + (float(item["actual_y"]) - event.y) ** 2,
            (float(item["x"]) - event.x) ** 2 + (float(item["ev_y"]) - event.y) ** 2,
        ))
        x = float(point["x"])
        canvas.create_line(x, 24, x, canvas.winfo_height() - 42,
                           fill="#dce8f7", dash=(2, 3), tags=("graph_hover",))
        row = point["row"]
        hand_no = int(row.get("hand_number", 0))
        actual = int(point["actual"])
        ev = int(point["ev"])
        label = (f"Hand #{hand_no}  •  Cumulative ${actual/100:+.2f} / EV ${ev/100:+.2f}  "
                 f"• This hand ${int(point['actual_step'])/100:+.2f}")
        box_x = min(canvas.winfo_width() - 8, max(8, x + 8))
        box_y = 38
        text_id = canvas.create_text(box_x, box_y, text=label, fill="#f4f8fc",
                                     anchor="nw", font=("Segoe UI", 8, "bold"), tags=("graph_hover",))
        bounds = canvas.bbox(text_id)
        if bounds:
            bg = canvas.create_rectangle(bounds[0]-5, bounds[1]-3, bounds[2]+5, bounds[3]+3,
                                         fill="#15263a", outline="#50677f", tags=("graph_hover",))
            canvas.tag_lower(bg, text_id)

    def _clear_pokercraft_graph_hover(self, _event=None):
        canvas = getattr(self, "poker_comparison_canvas", None)
        if canvas:
            canvas.delete("graph_hover")

    def _on_pokercraft_graph_click(self, event):
        if not self.poker_graph_points:
            return
        canvas = self.poker_comparison_canvas
        left, right, top, bottom = self.poker_graph_plot_bounds
        if event.x < left or event.x > right or event.y < top or event.y > bottom:
            return
        point = min(self.poker_graph_points, key=lambda item: min(
            (float(item["x"]) - event.x) ** 2 + (float(item["actual_y"]) - event.y) ** 2,
            (float(item["x"]) - event.x) ** 2 + (float(item["ev_y"]) - event.y) ** 2,
        ))
        distance = min(
            (float(point["x"]) - event.x) ** 2 + (float(point["actual_y"]) - event.y) ** 2,
            (float(point["x"]) - event.x) ** 2 + (float(point["ev_y"]) - event.y) ** 2,
        ) ** .5
        if distance > 34:
            return
        row = point["row"]
        hand_key = str(row.get("hand_key", ""))
        matching_iid = next((iid for iid, candidate in self.history_records.items()
                             if str(candidate.get("hand_key", "")) == hand_key), None)
        if matching_iid is not None:
            self.history_tree.selection_set(matching_iid)
            self.history_tree.focus(matching_iid)
            self.history_tree.see(matching_iid)
            self._show_pokercraft_hand()

    @staticmethod
    def _draw_cumulative_graph(canvas: tk.Canvas, rows: list[dict[str, Any]], *, ev: bool = False):
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(340, canvas.winfo_width())
        height = max(210, canvas.winfo_height())
        left, right, top, bottom = 58, width - 18, 18, height - 36
        canvas.create_rectangle(left, top, right, bottom, outline="#294158", width=1)
        chronological = sorted(rows, key=lambda row: (row.get("played_at", ""), row.get("hand_number", 0)))
        values = []
        cumulative = 0
        for row in chronological:
            actual = int(row.get("display_net", row.get("hero_net", 0)))
            if ev and row.get("hero_allin_ev") is not None:
                step = int(row["hero_allin_ev"])
                if not row.get("include_rake_for_graph", True):
                    step += int(row.get("hero_rake", 0))
            else:
                step = actual
            cumulative += step
            values.append(cumulative)
        if not values:
            canvas.create_text(width/2, height/2, text="No selected hand history", fill="#91a3b8",
                               font=("Segoe UI", 10, "bold"))
            return
        minimum, maximum = min([0] + values), max([0] + values)
        if minimum == maximum:
            minimum -= 100
            maximum += 100
        pad = (maximum - minimum) * .08
        minimum -= pad
        maximum += pad
        for i in range(5):
            ratio = i / 4
            y = bottom - ratio * (bottom - top)
            amount = minimum + (maximum - minimum) * ratio
            canvas.create_line(left, y, right, y, fill="#1e3348", dash=(2, 3))
            canvas.create_text(left - 7, y, text=f"${amount/100:,.0f}", fill="#91a3b8",
                               anchor="e", font=("Segoe UI", 7))
        points = []
        for index, value in enumerate(values):
            x = left + ((index / max(1, len(values)-1)) * (right-left))
            y = bottom - ((value-minimum)/(maximum-minimum)) * (bottom-top)
            points.extend((x, y))
        if len(values) == 1:
            x, y = points
            canvas.create_oval(x-3, y-3, x+3, y+3, fill="#43d6a0" if not ev else "#efbf68", outline="")
        else:
            color = "#efbf68" if ev else "#43d6a0"
            canvas.create_line(*points, fill=color, width=2, smooth=False)
            for index in range(0, len(values), max(1, len(values)//30)):
                x, y = points[index*2:index*2+2]
                canvas.create_oval(x-2, y-2, x+2, y+2, fill=color, outline="")
        canvas.create_text(left, height-14, text="HAND 1", fill="#91a3b8", anchor="w", font=("Segoe UI", 7))
        canvas.create_text(right, height-14, text=f"HAND {len(values)}", fill="#91a3b8", anchor="e", font=("Segoe UI", 7))
        title = "ALL-IN ADJUSTED" if ev else "ACTUAL NET"
        canvas.create_text((left+right)/2, 8, text=f"{title}  •  {len(values)} HANDS",
                           fill="#d9e6f4", font=("Segoe UI", 8, "bold"))

    def _refresh_pokercraft_breakdowns(self, rows: list[dict[str, Any]]):
        if not hasattr(self, "poker_opponent_tree"):
            return
        for tree in (self.poker_opponent_tree, self.poker_position_tree):
            for child in tree.get_children():
                tree.delete(child)
        opponent_stats: dict[str, dict[str, int]] = {}
        position_stats: dict[str, dict[str, int]] = {}
        for row in rows:
            players = list(row.get("players", []))
            hero = next((player for player in players if player.get("id") == "hero"), None)
            if hero:
                position = str(hero.get("position") or "Unknown")
                stat = position_stats.setdefault(position, {"hands": 0, "wins": 0, "net": 0, "bb_units": 0.0})
                row_net = int(row.get("display_net", row.get("hero_net", 0)))
                stat["hands"] += 1
                stat["net"] += row_net
                bb_cents_for_hand = {"NL2": 2, "NL5": 5, "NL10": 10, "NL25": 25,
                                     "NL50": 50, "NL100": 100, "NL200": 200, "VIP25/50": 5000}.get(str(row.get("table_rate", "")), 0)
                if bb_cents_for_hand:
                    stat["bb_units"] += row_net / bb_cents_for_hand
                if row_net > 0:
                    stat["wins"] += 1
            # Allocate a hero's net per contested pot to the other contributors.
            # Multiway amounts are shared evenly among the involved opponents.
            per_opponent: dict[str, int] = {}
            for award in row.get("awards", []):
                contributors = [str(pid) for pid in award.get("contributors", [])]
                if "hero" not in contributors:
                    continue
                opponents = [pid for pid in contributors if pid != "hero"]
                if not opponents:
                    continue
                amount = int(award.get("amount", 0))
                rake = int(award.get("rake", 0))
                winners = [str(pid) for pid in award.get("winners", [])]
                hero_payout = ((amount-rake)//len(winners) if "hero" in winners and winners else 0)
                hero_contribution = amount // max(1, len(contributors))
                delta = hero_payout - hero_contribution
                recipients = ([pid for pid in opponents if pid in winners] if delta < 0
                              else opponents)
                if not recipients:
                    recipients = opponents
                quotient, remainder = divmod(abs(delta), len(recipients))
                for index, opponent_id in enumerate(recipients):
                    allocated = quotient + (1 if index < remainder else 0)
                    per_opponent[opponent_id] = per_opponent.get(opponent_id, 0) + (allocated if delta >= 0 else -allocated)
            for player in players:
                pid = str(player.get("id", ""))
                if pid in {"", "hero"}:
                    continue
                stat = opponent_stats.setdefault(pid, {"name": str(player.get("name", pid)),
                                                        "hands": 0, "wins": 0, "net": 0})
                stat["hands"] += 1
                stat["net"] += per_opponent.get(pid, 0)
                if per_opponent.get(pid, 0) > 0:
                    stat["wins"] += 1
        for pid, stat in sorted(opponent_stats.items(), key=lambda item: item[1]["net"], reverse=True):
            self.poker_opponent_tree.insert("", "end", iid=pid, values=(
                stat["name"], stat["hands"], stat["wins"], f"${stat['net']/100:+.2f}"))
        for position, stat in sorted(position_stats.items(), key=lambda item: item[0]):
            net = stat["net"]
            bb100 = stat["bb_units"] / max(1, stat["hands"]) * 100
            self.poker_position_tree.insert("", "end", values=(
                position, stat["hands"], stat["wins"], f"${net/100:+.2f}", f"{bb100:+.1f}"))

    def _export_pokercraft_csv(self):
        rows = []
        for source_row in list(getattr(self, "poker_filtered_rows", [])):
            row = dict(source_row)
            row["played_at"] = self._format_pokercraft_jst(row.get("played_at"))
            rows.append(row)
        if not rows:
            messagebox.showinfo("PokerCraft export", "エクスポートするハンドがありません。先にセッション／フィルターを確認してください。")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        path = filedialog.asksaveasfilename(
            title="Export filtered PokerCraft hands",
            defaultextension=".csv",
            initialfile=f"PigeonPoker_PokerCraft_{stamp}.csv",
            filetypes=[("CSV UTF-8", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            count = export_hand_history_csv(path, rows)
            messagebox.showinfo("PokerCraft export", f"{count:,} ハンドをCSVに出力しました。\n{path}")
        except Exception as exc:
            messagebox.showerror("PokerCraft export", f"CSV出力に失敗しました。\n{exc}")

    @staticmethod
    def _pokercraft_hand_class(cards_value: Any) -> str | None:
        try:
            import re
            if isinstance(cards_value, str):
                text = cards_value
            else:
                text = " ".join(str(card) for card in list(cards_value or ()))
            matches = re.findall(r"(10|[AKQJT2-9])([SHDC♠♥♦♣])", text.upper())
            if len(matches) != 2:
                return None
            rank_order = "AKQJT98765432"
            rank_a = "T" if matches[0][0] == "10" else matches[0][0]
            rank_b = "T" if matches[1][0] == "10" else matches[1][0]
            if rank_a not in rank_order or rank_b not in rank_order:
                return None
            if rank_a == rank_b:
                return rank_a * 2
            high, low = sorted((rank_a, rank_b), key=rank_order.index)
            suit_a, suit_b = matches[0][1], matches[1][1]
            return high + low + ("s" if suit_a == suit_b else "o")
        except (TypeError, ValueError, IndexError):
            return None

    def _refresh_pokercraft_hole_cards(self, rows: list[dict[str, Any]]):
        grouped: dict[str, dict[str, int]] = {}
        for row in rows:
            hand_class = self._pokercraft_hand_class(row.get("hero_cards", ""))
            if not hand_class:
                continue
            stat = grouped.setdefault(hand_class, {
                "hand": hand_class, "hands": 0, "wins": 0, "net": 0,
                "pot": 0, "positive_ev": 0, "ev_count": 0,
            })
            net = int(row.get("display_net", row.get("hero_net", 0)))
            stat["hands"] += 1
            stat["net"] += net
            stat["pot"] += int(row.get("pot", 0))
            if net > 0:
                stat["wins"] += 1
            if row.get("hero_allin_ev") is not None:
                stat["positive_ev"] += int(row["hero_allin_ev"])
                stat["ev_count"] += 1
        self.poker_hole_cards_rows = list(grouped.values())
        total = sum(int(item["hands"]) for item in self.poker_hole_cards_rows)
        self.poker_hole_cards_summary_var.set(
            f"{len(self.poker_hole_cards_rows)} starting-hand classes • {total} hands • "
            "current PokerCraft filters applied")
        self._render_pokercraft_hole_cards()

    def _render_pokercraft_hole_cards(self):
        tree = self.poker_hole_cards_tree
        for child in tree.get_children():
            tree.delete(child)
        rows = list(self.poker_hole_cards_rows)
        column = self.poker_hole_cards_sort_column
        reverse = bool(self.poker_hole_cards_sort_reverse)
        sorters = {
            "hand": lambda item: str(item["hand"]),
            "hands": lambda item: int(item["hands"]),
            "winrate": lambda item: int(item["wins"]) / max(1, int(item["hands"])),
            "net": lambda item: int(item["net"]),
            "avgpot": lambda item: int(item["pot"]) / max(1, int(item["hands"])),
            "avgnet": lambda item: int(item["net"]) / max(1, int(item["hands"])),
        }
        rows.sort(key=sorters.get(column, sorters["hands"]), reverse=reverse)
        labels = {"hand": "HAND", "hands": "HANDS", "winrate": "WIN RATE",
                  "net": "NET", "avgpot": "AVG POT", "avgnet": "AVG NET"}
        for col, label in labels.items():
            arrow = (" ↓" if reverse else " ↑") if column == col else ""
            tree.heading(col, text=label + arrow)
        for index, item in enumerate(rows):
            hands = max(1, int(item["hands"]))
            win_rate = int(item["wins"]) / hands * 100.0
            tree.insert("", "end", iid=f"hole_{index}", values=(
                item["hand"], int(item["hands"]), f"{win_rate:.1f}%",
                f"${int(item['net'])/100:+.2f}",
                f"${int(item['pot'])/hands/100:.2f}",
                f"${int(item['net'])/hands/100:+.2f}",
            ))

    def _sort_pokercraft_hole_cards(self, column: str):
        if self.poker_hole_cards_sort_column == column:
            self.poker_hole_cards_sort_reverse = not bool(self.poker_hole_cards_sort_reverse)
        else:
            self.poker_hole_cards_sort_column = column
            self.poker_hole_cards_sort_reverse = False
        self._render_pokercraft_hole_cards()

    def _refresh_pokercraft_player_stats(self, rows: list[dict[str, Any]]):
        if not hasattr(self, "poker_stats_tree"):
            return
        self.poker_stats_rows = calculate_player_statistics(rows)
        self.poker_stats_summary_var.set(
            f"{len(self.poker_stats_rows)} players • {sum(int(item['hands']) for item in self.poker_stats_rows)} player-hands • based on current session / hand filters"
        )
        self._render_pokercraft_player_stats()

    def _render_pokercraft_player_stats(self):
        tree = self.poker_stats_tree
        for child in tree.get_children():
            tree.delete(child)
        rows = list(getattr(self, "poker_stats_rows", []))
        column = getattr(self, "poker_stats_sort_column", "hands")
        reverse = bool(getattr(self, "poker_stats_sort_reverse", True))
        sort_keys = {
            "player": lambda item: str(item.get("name", "")).lower(),
            "hands": lambda item: int(item.get("hands", 0)),
            "vpip": lambda item: float(item.get("vpip_pct", 0.0)),
            "pfr": lambda item: float(item.get("pfr_pct", 0.0)),
            "three_bet": lambda item: -1.0 if item.get("three_bet_pct") is None else float(item["three_bet_pct"]),
            "wtsd": lambda item: -1.0 if item.get("wtsd_pct") is None else float(item["wtsd_pct"]),
            "wsd": lambda item: -1.0 if item.get("wsd_pct") is None else float(item["wsd_pct"]),
            "wwsf": lambda item: -1.0 if item.get("wwsf_pct") is None else float(item["wwsf_pct"]),
            "af": lambda item: -1.0 if item.get("aggression_factor") is None else float(item["aggression_factor"]),
            "bb100": lambda item: float(item.get("bb_per_100", 0.0)),
            "net": lambda item: int(item.get("net", 0)),
        }
        # Keep HERO pinned to the top regardless of the selected sort column.
        rows.sort(key=lambda item: (item.get("player_id") != "hero", sort_keys.get(column, sort_keys["hands"])(item)),
                  reverse=False)
        if column != "player":
            hero_rows = [item for item in rows if item.get("player_id") == "hero"]
            other_rows = [item for item in rows if item.get("player_id") != "hero"]
            other_rows.sort(key=sort_keys.get(column, sort_keys["hands"]), reverse=reverse)
            rows = hero_rows + other_rows
        else:
            rows.sort(key=lambda item: item.get("player_id") != "hero")
            hero_rows = [item for item in rows if item.get("player_id") == "hero"]
            other_rows = [item for item in rows if item.get("player_id") != "hero"]
            other_rows.sort(key=sort_keys["player"], reverse=reverse)
            rows = hero_rows + other_rows
        def pct(value):
            return "—" if value is None else f"{float(value):.1f}%"
        for index, item in enumerate(rows):
            player_name = "YOU" if item.get("player_id") == "hero" else str(item.get("name", item.get("player_id", "?")))
            af = item.get("aggression_factor")
            net = int(item.get("net", 0))
            tree.insert("", "end", iid=f"player_{index}", values=(
                player_name, int(item.get("hands", 0)), pct(item.get("vpip_pct")),
                pct(item.get("pfr_pct")), pct(item.get("three_bet_pct")),
                pct(item.get("wtsd_pct")), pct(item.get("wsd_pct")),
                pct(item.get("wwsf_pct")), "—" if af is None else f"{float(af):.2f}",
                f"{float(item.get('bb_per_100', 0.0)):+.1f}", f"${net/100:+.2f}"))

    def _sort_pokercraft_player_stats(self, column: str):
        if getattr(self, "poker_stats_sort_column", None) == column:
            self.poker_stats_sort_reverse = not bool(getattr(self, "poker_stats_sort_reverse", True))
        else:
            self.poker_stats_sort_column = column
            self.poker_stats_sort_reverse = column != "player"
        self._render_pokercraft_player_stats()

    @staticmethod
    def _rank_filter_tokens(value: str) -> list[str]:
        text = str(value).upper().replace("10", "T")
        ranks = set("AKQJT98765432")
        tokens = [char for char in text if char in ranks]
        return tokens

    @classmethod
    def _matches_rank_filter(cls, cards_text: str, query: str, *, exact_two: bool = False) -> bool:
        wanted = cls._rank_filter_tokens(query)
        if not wanted:
            return True
        available = [char for char in str(cards_text).upper() if char in "AKQJT98765432"]
        if exact_two and len(wanted) == 2:
            return sorted(available) == sorted(wanted)
        return all(rank in available for rank in wanted)

    def _reset_pokercraft_filters(self):
        self.poker_filter_stake_var.set("ALL")
        self.poker_sort_var.set("DATE")
        self.poker_sort_order_var.set("DESC")
        self.poker_hole_filter_var.set("")
        self.poker_board_filter_var.set("")
        self.poker_filter_result_var.set("ALL")
        self.poker_filter_showdown_var.set("ALL")
        self.poker_from_filter_var.set("")
        self.poker_to_filter_var.set("")
        self.poker_session_stake_var.set("ALL")
        self.poker_session_selected_ids = None
        self.poker_session_sort_column = None
        self.poker_session_sort_reverse = True
        self.poker_history_sort_column = None
        self.poker_history_sort_reverse = True
        self.poker_include_rake_var.set(True)
        self._refresh_pokercraft()

    def _sort_pokercraft_hands(self, column: str):
        if self.poker_history_sort_column == column:
            self.poker_history_sort_reverse = not bool(self.poker_history_sort_reverse)
        else:
            self.poker_history_sort_column = column
            self.poker_history_sort_reverse = False
        self._refresh_pokercraft()

    def _refresh_pokercraft(self):
        if not hasattr(self, "history_tree"):
            return
        previous_key = ""
        if getattr(self, "selected_history_record", None):
            previous_key = str(self.selected_history_record.get("hand_key", ""))

        selected_sessions = self._refresh_pokercraft_session_checks()
        rows = (self.history_store.list_recent(5000, session_ids=selected_sessions)
                if selected_sessions else [])
        stake = self.poker_filter_stake_var.get().strip()
        if stake and stake != "ALL":
            rows = [row for row in rows if row["table_rate"] == stake]
        hole_query = self.poker_hole_filter_var.get()
        board_query = self.poker_board_filter_var.get()
        rows = [row for row in rows
                if self._matches_rank_filter(row.get("hero_cards", ""), hole_query, exact_two=True)
                and self._matches_rank_filter(row.get("board", ""), board_query)]
        from_text = self.poker_from_filter_var.get().strip()
        to_text = self.poker_to_filter_var.get().strip()
        try:
            from_dt = self._pokercraft_parse_timestamp(from_text, assume_utc=False) if from_text else None
            to_dt = self._pokercraft_parse_timestamp(to_text, assume_utc=False) if to_text else None
            if to_dt is not None and len(to_text) == 10:
                to_dt = to_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        except (TypeError, ValueError):
            messagebox.showerror(
                "PokerCraft filter",
                "日時は YYYY-MM-DD または YYYY-MM-DD HH:MM 形式で入力してください（日本時間）。")
            return
        if from_dt is not None:
            from_dt = from_dt.astimezone(timezone.utc)
        if to_dt is not None:
            to_dt = to_dt.astimezone(timezone.utc)

        filtered = []
        for row in rows:
            played = self._pokercraft_parse_timestamp(row.get("played_at"), assume_utc=True)
            if played is None:
                continue
            played = played.astimezone(timezone.utc)
            if from_dt and played < from_dt:
                continue
            if to_dt and played > to_dt:
                continue
            row = dict(row)
            rake_share = int(row.get("hero_rake", 0))
            row["display_net"] = int(row["hero_net"] if self.poker_include_rake_var.get()
                                     else row["hero_net"] + rake_share)
            filtered.append(row)

        filtered = filter_hand_results(
            filtered, self.poker_filter_result_var.get(), self.poker_filter_showdown_var.get())
        sorters = {
            "date": lambda item: str(item.get("played_at", "")),
            "session": lambda item: str(item.get("session_id", "")),
            "stake": lambda item: str(item.get("table_rate", "")),
            "board": lambda item: str(item.get("board", "")),
            "hand": lambda item: str(item.get("hero_cards", "")),
            "pot": lambda item: int(item.get("pot", 0)),
            "rake": lambda item: int(item.get("rake", 0)),
            "net": lambda item: int(item.get("display_net", item.get("hero_net", 0))),
            "allin_ev": lambda item: (-10**18 if item.get("hero_allin_ev") is None
                                      else int(item.get("hero_allin_ev"))),
            "result": lambda item: ("WIN" if int(item.get("display_net", 0)) > 0
                                    else "LOSS" if int(item.get("display_net", 0)) < 0 else "EVEN"),
        }
        sort_column = self.poker_history_sort_column
        if sort_column:
            filtered.sort(key=sorters.get(sort_column, sorters["date"]),
                          reverse=bool(self.poker_history_sort_reverse))
        else:
            sort_key = self.poker_sort_var.get()
            reverse = self.poker_sort_order_var.get() == "DESC"
            if sort_key == "POT":
                filtered.sort(key=lambda item: item["pot"], reverse=reverse)
            elif sort_key == "PROFIT":
                filtered.sort(key=lambda item: item["display_net"], reverse=reverse)
            elif sort_key == "LOSS":
                filtered.sort(key=lambda item: item["display_net"], reverse=not reverse)
            else:
                filtered.sort(key=lambda item: item["played_at"], reverse=reverse)

        headings = {
            "date": "DATE", "session": "TABLE SESSION", "stake": "STAKE",
            "board": "BOARD", "hand": "YOUR HAND", "pot": "POT", "rake": "RAKE",
            "net": "NET", "allin_ev": "ALL-IN EV", "result": "RESULT",
        }
        if sort_column:
            for column, label in headings.items():
                arrow = (" ↓" if self.poker_history_sort_reverse else " ↑") if sort_column == column else ""
                self.history_tree.heading(column, text=label + arrow)

        total_net = sum(item["display_net"] for item in filtered)
        total_rake = sum(int(item.get("rake", 0)) for item in filtered)
        biggest_pot = max((int(item["pot"]) for item in filtered), default=0)
        rake_mode = "after rake" if self.poker_include_rake_var.get() else "excluding hero rake share"
        self.pokercraft_summary_var.set(
            f"{len(filtered)} hands • Net ({rake_mode}) ${total_net/100:,.2f} • "
            f"Total rake ${total_rake/100:,.2f} • Biggest pot ${biggest_pot/100:,.2f}"
        )
        self.poker_filtered_rows = sorted(
            filtered, key=lambda item: (item.get("played_at", ""), item.get("hand_number", 0)))
        graph_rows = []
        for item in self.poker_filtered_rows:
            graph_item = dict(item)
            graph_item["include_rake_for_graph"] = bool(self.poker_include_rake_var.get())
            graph_rows.append(graph_item)
        if hasattr(self, "poker_comparison_canvas"):
            self._draw_pokercraft_comparison_graph(self.poker_comparison_canvas, graph_rows)
            allin_count = sum(1 for item in filtered if item.get("hero_allin_ev") is not None)
            self.poker_ev_note.set(
                f"Same hand axis • {allin_count} hands with All-in EV estimates • "
                "non-all-in hands follow actual net • click a point to open that hand.")
        self._refresh_pokercraft_breakdowns(filtered)
        self._refresh_pokercraft_player_stats(filtered)
        self._refresh_pokercraft_hole_cards(filtered)

        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        self.history_records = {}
        selected_iid = None
        for index, row in enumerate(filtered):
            iid = str(index)
            self.history_records[iid] = row
            date_text = self._format_pokercraft_jst(row.get("played_at"))
            result = "WIN" if row["display_net"] > 0 else ("LOSS" if row["display_net"] < 0 else "EVEN")
            sid_short = str(row.get("session_id", ""))[:8]
            ev_value = row.get("hero_allin_ev")
            self.history_tree.insert("", "end", iid=iid, values=(
                date_text, sid_short, row["table_rate"], row["board"] or "—", row["hero_cards"] or "—",
                f"${row['pot']/100:.2f}", f"${row.get('rake', 0)/100:.2f}",
                f"${row['display_net']/100:+.2f}",
                f"${int(ev_value)/100:+.2f}" if ev_value is not None else "—", result))
            if previous_key and str(row.get("hand_key", "")) == previous_key:
                selected_iid = iid

        self.selected_history_record = None
        self.selected_history_preflop_range = None
        try:
            self.history_replay_button.configure(state="disabled")
            self.history_range_button.configure(state="disabled")
        except (AttributeError, tk.TclError):
            pass
        if selected_iid is not None:
            self.history_tree.selection_set(selected_iid)
            self.history_tree.focus(selected_iid)
            self._show_pokercraft_hand()
        else:
            self._set_history_detail("Select a hand to inspect its recorded actions.")

    def _tick_pokercraft_live_refresh(self):
        try:
            if not self.winfo_exists():
                return
            if getattr(self, "_active_page_key", "") == "poker_craft":
                latest_rows = self.history_store.list_recent(1)
                signature = None
                if latest_rows:
                    latest = latest_rows[0]
                    signature = (
                        str(latest.get("hand_key", "")),
                        str(latest.get("played_at", "")),
                        latest.get("hero_allin_ev"),
                        int(latest.get("hero_net", 0)),
                    )
                if signature != self._pokercraft_last_latest_signature:
                    self._pokercraft_last_latest_signature = signature
                    self._refresh_pokercraft()
        except (tk.TclError, RuntimeError):
            return
        except Exception:
            # Live history refresh is opportunistic; it must never interrupt play.
            pass
        try:
            self._pokercraft_live_refresh_job = self.after(1800, self._tick_pokercraft_live_refresh)
        except tk.TclError:
            pass

    def _set_history_detail(self, value: str):
        self.history_detail.configure(state="normal")
        self.history_detail.delete("1.0", "end")
        self.history_detail.insert("end", value)
        self.history_detail.configure(state="disabled")

    def _show_pokercraft_hand(self, _event=None):
        selected = self.history_tree.selection()
        if not selected:
            return
        row = self.history_records.get(selected[0])
        if not row:
            return
        self.selected_history_record = row
        try:
            self.history_replay_button.configure(state="normal")
        except (AttributeError, tk.TclError):
            pass
        hero_rake = int(row.get("hero_rake", 0))
        allin_ev = row.get("hero_allin_ev")
        lines = [f"{row['table_rate']} • {self._format_pokercraft_jst(row.get('played_at'))} • SESSION {row.get('session_id', '')}",
                 f"Board: {row['board'] or '—'}", f"Hero: {row['hero_cards'] or '—'}",
                 f"Pot: ${row['pot']/100:.2f} • Net: ${row.get('display_net', row['hero_net'])/100:+.2f} "
                 f"• Total rake: ${row['rake']/100:.2f} • Hero rake share: ${hero_rake/100:.2f}",
                 f"All-in EV: ${int(allin_ev)/100:+.2f}" if allin_ev is not None else "All-in EV: —",
                 f"Result: {row['winner_reason']}", "", "PLAYERS"]
        for player in row["players"]:
            cards = " ".join(player["hole_cards"]) if player["cards_shown"] else "not shown"
            position = player.get("position", "")
            lines.append(f"{position} {player['name']}: {cards} | net ${player['net']/100:+.2f} | {'folded' if player['folded'] else 'in hand'}")
        lines.append("\nACTIONS")
        for event in row["events"]:
            etype = event.get("type")
            if etype == "action":
                lines.append(f"{event.get('player')}: {event.get('action')} {event.get('target', '')}".strip())
            elif etype == "street":
                lines.append(f"--- {event.get('street', '').upper()} --- {' '.join(event.get('board', []))}")
            elif etype == "pot_award":
                lines.append(f"Pot ${event.get('amount', 0)/100:.2f} → {', '.join(event.get('winners', []))}")
            elif etype == "hand_won_by_fold":
                lines.append(f"{event.get('winner')} won by fold (${event.get('amount', 0)/100:.2f})")
        self._set_history_detail("\n".join(lines))
        self.selected_history_preflop_range = self._historical_preflop_range_chart(row)
        try:
            self.history_range_button.configure(
                state="normal" if self.selected_history_preflop_range is not None else "disabled")
        except (AttributeError, tk.TclError):
            pass

    def _historical_preflop_range_chart(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """Resolve only the exact screenshot-backed node at HERO's first decision."""
        try:
            players_data = list(row.get("players", []) or [])
            if not players_data:
                return None
            id_by_name: dict[str, str] = {}
            player_by_id: dict[str, Any] = {}
            for item in players_data:
                pid = str(item.get("id") or "")
                name = str(item.get("name") or pid)
                if not pid:
                    continue
                id_by_name[name] = pid
                id_by_name[name.casefold()] = pid
                if pid.casefold() in {"hero", "you"} or name.casefold() in {"hero", "you"}:
                    id_by_name["YOU"] = pid
                    id_by_name["HERO"] = pid
                player_by_id[pid] = SimpleNamespace(
                    player_id=pid, name=name,
                    position=str(item.get("position") or ""),
                    hole_cards=tuple(item.get("hole_cards") or ()),
                    stack=100000, street_contribution=0, eligible=True,
                )
            hero_id = next((pid for pid, item in player_by_id.items()
                            if pid.casefold() in {"hero", "you"}
                            or str(getattr(item, "name", "")).casefold() in {"hero", "you"}),
                           None)
            if hero_id is None:
                return None

            normalized_events = []
            hero_decision_index = None
            for index, raw in enumerate(row.get("events", []) or []):
                if not isinstance(raw, dict):
                    continue
                event = dict(raw)
                street = str(event.get("street", "preflop")).lower().replace("-", "")
                if street not in {"preflop", "pre"}:
                    continue
                actor = str(event.get("player_id") or event.get("player") or "")
                pid = actor if actor in player_by_id else id_by_name.get(actor, id_by_name.get(actor.casefold(), actor))
                if not pid:
                    continue
                event["player_id"] = pid
                event["player"] = pid
                event["street"] = "preflop"
                normalized_events.append(event)
                action = str(event.get("action", "")).lower().replace("-", "_")
                if pid == hero_id and hero_decision_index is None and action in {
                    "fold", "call", "check", "raise", "bet", "all_in", "allin", "limp"
                }:
                    hero_decision_index = len(normalized_events) - 1

            if hero_decision_index is None:
                return None
            prior = normalized_events[:hero_decision_index]
            if not prior:
                prior = []

            # Explicit per-player positions are used by _position_map when the
            # player count differs from six. Add a non-seated marker to force it
            # to use these stored positions rather than infer a button seat.
            helper_players = list(player_by_id.values())
            helper_players.append(SimpleNamespace(
                player_id="__position_hint__", name="Position metadata",
                position="UNKNOWN", hole_cards=(), stack=100000,
                street_contribution=0, eligible=False,
            ))
            rate = str(row.get("table_rate", ""))
            bb_cents = {
                "NL2": 2, "NL5": 5, "NL10": 10, "NL25": 25,
                "NL50": 50, "NL100": 100, "NL200": 200, "VIP25/50": 5000,
            }.get(rate)
            if not bb_cents:
                return None
            hand = SimpleNamespace(
                players=helper_players, events=prior, big_blind=int(bb_cents),
                dealer_index=0, street="preflop",
            )
            chart = preflop_gto_range_for_situation(
                SimpleNamespace(dealer_index=0), hand, hero_id, prior_events=prior)
            return chart
        except Exception:
            return None

    def _open_pokercraft_history_range(self):
        chart = getattr(self, "selected_history_preflop_range", None)
        if not chart:
            return
        self._open_preflop_range_view(
            chart,
            title="HISTORICAL PREFLOP RANGE",
            charge_label="Historical review • FREE",
        )

    def _open_preflop_range_view(
        self,
        chart: dict[str, Any],
        *,
        title: str,
        charge_label: str,
        table_id: str | None = None,
    ):
        """Render only the 13x13 GTO Wizard-style starting-hand matrix."""
        order = list((chart or {}).get("hand_order", []) or [])
        hands = (chart or {}).get("hands", {}) or {}
        if len(order) != 169:
            return

        # Keep the range on top of the actual poker table; never navigate
        # away to the lobby or open a detached application page.
        table_record = self.table_windows.get(table_id) if table_id else None
        table_canvas = table_record.get("canvas") if table_record else None
        parent = table_canvas.winfo_toplevel() if table_canvas and table_canvas.winfo_exists() else self
        win = tk.Toplevel(parent)
        win.title("PIGEON POKER • RANGE")
        # Keep normal Windows decorations and z-order. A topmost, borderless
        # window can cover the Windows taskbar and obscure the table.
        win.configure(bg="#0b1018")
        win.resizable(False, False)
        width, height = 620, 680
        try:
            parent.update_idletasks()
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = max(width, parent.winfo_width()), max(height, parent.winfo_height())
            x = px + (pw - width) // 2
            y = py + (ph - height) // 2
            win.geometry(f"{width}x{height}+{x}+{y}")
            win.transient(parent)
            win.lift()
            win.focus_force()
        except tk.TclError:
            win.geometry("620x680")

        # Freeze only the active hero decision clock while the range overlay
        # is open. Resume with the exact remaining time when it is dismissed.
        paused_clock = None
        if table_id and table_id in self.multi_tables:
            slot_for_clock = self.multi_tables[table_id]
            state_for_clock = slot_for_clock.state
            deadline = float(state_for_clock.get("cash_squeeze_deadline_at", 0.0) or 0.0)
            if deadline > 0:
                paused_clock = {
                    "slot": slot_for_clock,
                    "remaining": max(0.0, deadline - time.monotonic()),
                    "mode": str(state_for_clock.get("cash_action_deadline_mode", "action") or "action"),
                    "hand_token": id(getattr(state_for_clock.get("cash_table"), "hand", None)),
                }
                pending = self.squeeze_deadline_jobs.pop(table_id, None)
                if pending:
                    try:
                        self.after_cancel(pending)
                    except tk.TclError:
                        pass
                state_for_clock["cash_squeeze_deadline_at"] = 0.0

        def close_range_overlay(_event=None):
            if paused_clock is not None:
                active_slot = self.multi_tables.get(table_id)
                active_hand = (
                    active_slot.state.get("cash_table").hand
                    if active_slot and active_slot.state.get("cash_table") else None
                )
                if active_slot is paused_clock["slot"] and active_hand is not None and id(active_hand) == paused_clock["hand_token"] and active_hand.next_to_act == "hero":
                    resumed_deadline = time.monotonic() + paused_clock["remaining"]
                    active_slot.state["cash_squeeze_deadline_at"] = resumed_deadline
                    active_slot.state["cash_action_deadline_mode"] = paused_clock["mode"]
                    if table_id == self.active_cash_table_id:
                        self.cash_squeeze_deadline_at = resumed_deadline
                        self.cash_action_deadline_mode = paused_clock["mode"]
                    self._update_action_timer_display(table_id, paused_clock["remaining"], paused_clock["mode"])
                    self.squeeze_deadline_jobs[table_id] = self.after(
                        200,
                        lambda tid=table_id, token=paused_clock["hand_token"]: self._tick_squeeze_action_deadline(tid, token),
                    )
            try:
                win.destroy()
            except tk.TclError:
                pass

        win.bind("<Escape>", close_range_overlay)
        win.protocol("WM_DELETE_WINDOW", close_range_overlay)
        overlay_bar = tk.Frame(win, bg="#0b1018", height=38)
        overlay_bar.pack(fill="x", padx=12, pady=(8, 0))
        position_text = " • ".join(
            str(chart.get(key, "")).strip()
            for key in ("actor_position", "opener_position")
            if str(chart.get(key, "")).strip()
        )
        header_text = str(title or "PREFLOP RANGE").upper()
        if position_text:
            header_text += "  •  " + position_text
        tk.Label(
            overlay_bar, text=header_text, bg="#0b1018", fg="#f2f6fc",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        tk.Button(
            overlay_bar, text="×", command=close_range_overlay,
            bg="#17263a", fg="#f2f6fc", activebackground="#263b55",
            activeforeground="#ffffff", relief="flat", bd=0,
            font=("Segoe UI", 15, "bold"), cursor="hand2",
            width=3,
        ).pack(side="right")
        canvas = tk.Canvas(
            win, width=580, height=580, bg="#0b1018",
            highlightthickness=0, bd=0,
        )
        canvas.pack(fill="both", expand=True, padx=12, pady=(2, 4))
        tk.Label(
            win,
            text="RAISE  ■     CALL / CHECK  ■     FOLD  ■     " + str(charge_label or ""),
            bg="#0b1018", fg="#aebed0", anchor="w",
            font=("Segoe UI", 8, "bold"),
        ).pack(fill="x", padx=14, pady=(0, 8))

        # GTO Wizard's three core preflop actions are represented as
        # proportional segments inside each hand-class cell.
        palette = {
            "raise": "#e05252",
            "allin": "#e05252",
            "call": "#45a879",
            "limp": "#45a879",
            "check": "#45a879",
            "fold": "#438ac5",
        }

        def draw(_event=None):
            if not canvas.winfo_exists():
                return
            width = max(260, canvas.winfo_width())
            height = max(260, canvas.winfo_height())
            cell_w = width / 13.0
            cell_h = height / 13.0
            canvas.delete("range_cell")
            for index, hand_class in enumerate(order):
                row, col = divmod(index, 13)
                x0, y0 = col * cell_w, row * cell_h
                x1, y1 = x0 + cell_w, y0 + cell_h
                choices = [
                    item for item in (hands.get(hand_class, []) or [])
                    if float(item.get("frequency", 0.0) or 0.0) > 0.000001
                ]
                total = sum(max(0.0, float(item.get("frequency", 0.0) or 0.0))
                            for item in choices)
                if total <= 0.0:
                    choices = [{"action": "fold", "frequency": 1.0}]
                    total = 1.0
                cursor_x = x0
                for choice in choices:
                    frequency = max(0.0, float(choice.get("frequency", 0.0) or 0.0))
                    if frequency <= 0:
                        continue
                    segment_end = min(x1, cursor_x + cell_w * frequency / total)
                    action = str(choice.get("action", "fold")).lower().replace("_", "")
                    color = palette.get(action, "#438ac5")
                    canvas.create_rectangle(
                        cursor_x, y0, segment_end, y1,
                        fill=color, outline="", tags=("range_cell",),
                    )
                    cursor_x = segment_end
                if cursor_x < x1:
                    canvas.create_rectangle(
                        cursor_x, y0, x1, y1,
                        fill="#438ac5", outline="", tags=("range_cell",),
                    )
                canvas.create_rectangle(
                    x0, y0, x1, y1, fill="", outline="#101722",
                    width=1, tags=("range_cell",),
                )
                font_size = max(7, min(11, int(min(cell_w, cell_h) * 0.24)))
                canvas.create_text(
                    (x0 + x1) / 2, (y0 + y1) / 2,
                    text=str(hand_class), fill="#ffffff",
                    font=("Segoe UI", font_size, "bold"),
                    tags=("range_cell",),
                )

        canvas.bind("<Configure>", draw)
        # Force geometry calculation before the first paint. The old
        # after_idle-only first draw could leave an empty black canvas on
        # some Windows/Tk DPI configurations.
        try:
            win.update_idletasks()
            draw()
        except tk.TclError:
            pass
        win.after(80, draw)
    def _open_pokercraft_replay(self):
        """Open an animated, step-based replay using only cards shown originally."""
        record = getattr(self, "selected_history_record", None)
        if not record:
            return
        frames = build_replay_frames(record)
        if len(frames) < 2:
            return
        win = tk.Toplevel(self)
        win.title(f"HAND REPLAY  •  {record.get('table_rate', '')}  •  #{record.get('hand_number', 0)}")
        win.geometry("1000x700")
        win.minsize(760, 560)
        win.configure(bg=COLORS["bg"])
        try:
            win.transient(self)
            win.lift()
        except tk.TclError:
            pass
        header = tk.Frame(win, bg="#080e19", padx=14, pady=9)
        header.pack(fill="x")
        street_var = tk.StringVar(value="PREFLOP")
        action_var = tk.StringVar(value="HAND START")
        tk.Label(header, text=f"POKERCRAFT  •  {record.get('table_rate', '')}",
                 bg="#080e19", fg=COLORS["gold"], font=("Segoe UI", 10, "bold")).pack(side="left")
        tk.Label(header, textvariable=street_var, bg="#080e19", fg=COLORS["text"],
                 font=("Segoe UI", 10, "bold")).pack(side="right")
        canvas = tk.Canvas(win, bg="#07101c", highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=8, pady=8)
        controls = tk.Frame(win, bg=COLORS["panel"], padx=10, pady=8)
        controls.pack(fill="x", padx=8, pady=(0, 8))
        current = {"index": 0, "playing": False, "after_id": None}
        step_var = tk.IntVar(value=0)
        step_label = tk.StringVar(value=f"1 / {len(frames)}")
        play_button = ttk.Button(controls, text="▶  PLAY")
        prev_button = ttk.Button(controls, text="◀  PREV")
        next_button = ttk.Button(controls, text="NEXT  ▶")
        prev_button.pack(side="left", padx=3)
        play_button.pack(side="left", padx=3)
        next_button.pack(side="left", padx=3)
        tk.Label(controls, textvariable=step_label, bg=COLORS["panel"], fg=COLORS["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="right", padx=(8, 2))
        scale = tk.Scale(controls, from_=0, to=len(frames)-1, orient="horizontal",
                         showvalue=False, variable=step_var, resolution=1,
                         bg=COLORS["panel"], fg=COLORS["text"], highlightthickness=0,
                         troughcolor="#263b55", activebackground=COLORS["green"],
                         command=lambda value: render(int(float(value))))
        scale.pack(side="left", fill="x", expand=True, padx=10)

        def stop_playback():
            current["playing"] = False
            if current.get("after_id"):
                try:
                    win.after_cancel(current["after_id"])
                except tk.TclError:
                    pass
                current["after_id"] = None
            try:
                play_button.configure(text="▶  PLAY")
            except tk.TclError:
                pass

        def render(index: int):
            index = max(0, min(len(frames)-1, int(index)))
            current["index"] = index
            frame = frames[index]
            if step_var.get() != index:
                step_var.set(index)
            step_label.set(f"{index+1} / {len(frames)}")
            street_var.set(str(frame.get("street", "PREFLOP")).upper())
            action_var.set(str(frame.get("last_action", "")))
            self._draw_hand_replay_frame(canvas, record, frame)
            if index >= len(frames)-1 and current["playing"]:
                stop_playback()

        def move(delta: int):
            stop_playback()
            render(current["index"] + delta)

        def tick():
            if not current["playing"]:
                return
            next_index = current["index"] + 1
            if next_index >= len(frames):
                stop_playback()
                return
            render(next_index)
            current["after_id"] = win.after(1050, tick)

        def toggle_play():
            if current["playing"]:
                stop_playback()
                return
            if current["index"] >= len(frames)-1:
                render(0)
            current["playing"] = True
            play_button.configure(text="Ⅱ  PAUSE")
            current["after_id"] = win.after(250, tick)

        prev_button.configure(command=lambda: move(-1))
        next_button.configure(command=lambda: move(1))
        play_button.configure(command=toggle_play)
        win.protocol("WM_DELETE_WINDOW", lambda: (stop_playback(), win.destroy()))
        render(0)
        win.update_idletasks()

    def _draw_hand_replay_frame(self, canvas, record: dict[str, Any], frame: dict[str, Any]):
        width = max(680, canvas.winfo_width())
        height = max(420, canvas.winfo_height())
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, height, fill="#07101c", outline="")
        canvas.create_oval(width*.035, height*.07, width*.965, height*.96,
                           fill="#0b6045", outline="#c5a05a", width=9)
        canvas.create_oval(width*.08, height*.11, width*.92, height*.91,
                           fill="#084b37", outline="#267d5e", width=2)
        street = str(frame.get("street", "preflop")).upper()
        pot = int(frame.get("pot", 0))
        canvas.create_text(width/2, height*.205,
                           text=f"POT  ${pot/100:,.2f}  •  {street}",
                           fill="#f2d58b", font=("Segoe UI", 13, "bold"))
        board = list(frame.get("board", []) or [])
        card_w, card_h, gap = 54, 76, 9
        board_start = width/2 - (5*card_w + 4*gap)/2
        for idx in range(5):
            x = board_start + idx*(card_w+gap)
            if idx < len(board):
                self._draw_card(canvas, x, height*.34, board[idx], card_w, card_h)
            else:
                self._draw_card_back(canvas, x, height*.34, card_w, card_h)
        players = list(frame.get("players", []) or [])
        hero_index = next((i for i, player in enumerate(players) if player.get("id") == "hero"), 0)
        relative_positions = [
            (width*.50, height*.84), (width*.205, height*.70), (width*.205, height*.28),
            (width*.50, height*.13), (width*.795, height*.28), (width*.795, height*.70),
        ]
        if len(players) == 2:
            relative_positions = [(width*.50, height*.84), (width*.50, height*.14)]
        folded = set(frame.get("folded", []))
        all_in = set(frame.get("all_in", []))
        for index, player in enumerate(players):
            relative = (index-hero_index) % max(1, len(players))
            x, y = relative_positions[relative]
            pid = str(player.get("id", ""))
            is_folded = pid in folded or bool(player.get("folded", False))
            is_allin = pid in all_in or bool(player.get("all_in", False))
            is_winner = pid in set(frame.get("winners", []))
            fill = "#173c34" if pid == "hero" else "#142a43"
            outline = "#f0cf7c" if is_winner else ("#7c8997" if is_folded else "#426b61")
            canvas.create_rectangle(x-88, y-28, x+88, y+28, fill=fill,
                                    outline=outline, width=3 if is_winner else 1)
            state = "FOLDED" if is_folded else ("ALL-IN" if is_allin else ("WIN" if is_winner else "IN HAND"))
            canvas.create_text(x, y-10, text=str(player.get("name", pid)),
                               fill="#f3f6fb", font=("Segoe UI", 9, "bold"))
            canvas.create_text(x, y+10, text=f"{state}  •  NET ${int(player.get('net', 0))/100:+.2f}",
                               fill="#e5d5aa" if is_winner else "#b6c6d7",
                               font=("Segoe UI", 7, "bold"))
            if player.get("cards_shown") and player.get("hole_cards"):
                cards = list(player["hole_cards"])
                for card_index, card in enumerate(cards[:2]):
                    self._draw_card(canvas, x-45+card_index*48, y-105, card, 40, 56)
        last_action = str(frame.get("last_action", ""))
        canvas.create_rectangle(width*.23, height*.70, width*.77, height*.76,
                                fill="#0a1b17", outline="#b99a58", width=1)
        canvas.create_text(width*.5, height*.73, text=last_action,
                           fill="#fae4ad", font=("Segoe UI", 11, "bold"))
        if frame.get("showdown"):
            canvas.create_text(width/2, height*.25, text="SHOWDOWN",
                               fill="#f7d88d", font=("Segoe UI", 10, "bold"))
        if frame.get("result") and frame.get("event_type") == "complete":
            canvas.create_text(width/2, height*.91, text=str(frame["result"]).upper(),
                               fill="#f7d88d", font=("Segoe UI", 10, "bold"))

    def _browse_exe(self):
        path = filedialog.askopenfilename(title="GTO+ executable", filetypes=[("GTO+", "GTO.exe"), ("Executable", "*.exe"), ("All files", "*.*")])
        if path:
            self.executable_var.set(path)

    def _save_connection_config(self):
        exe = self.executable_var.get().strip()
        port = int(self.port_var.get().strip())
        if not exe or not 1 <= port <= 65535:
            raise ValueError("GTO+ path or socket port is invalid")
        self.config_data["gto_plus_executable"] = exe
        self.config_data["gto_plus_port"] = port
        self.config_data["rake_pct"] = float(self.rake_var.get().strip() or "0")
        save_config(self.config_data)
        # Preserve the currently docked process/client if the connection settings did not change.
        if (str(self.integration.executable) != str(Path(exe).expanduser()) or
                self.integration.port != port):
            try:
                self.integration.stop(detach=True, terminate=False)
            except Exception:
                pass
            self.integration = PigeonGTOPlusIntegration(exe, self.store, port=port, bridge_root=ROOT)

    def _auto_start_gto_plus(self):
        """Start GTO+ inside Pigeon at app launch and after update restart."""
        if self._gto_auto_start_started:
            return
        try:
            self.update_idletasks()
            if (not self.gto_host.winfo_ismapped()
                    or self.gto_host.winfo_width() < 250
                    or self.gto_host.winfo_height() < 180):
                self.after(250, self._auto_start_gto_plus)
                return
            self._save_connection_config()
            self._gto_auto_start_started = True
            try:
                self.integration.enable_socket_connection()
            except Exception as socket_exc:
                self.status_var.set(f"GTO+ソケット設定: {socket_exc}")
            self._launch_gto(automatic=True)
        except Exception as exc:
            self.status_var.set(f"GTO+自動起動準備失敗: {type(exc).__name__}: {exc}")


    def _auto_connect_gto_plus(self, attempt: int = 0):
        """Connect to the local GTO+ socket with bounded retries; never block the UI."""
        if not self.gto_embedded:
            return
        if self.integration.connected:
            self._gto_auto_connect_busy = False
            return
        if self._gto_auto_connect_busy:
            return
        if attempt >= 10:
            self.status_var.set("GTO+自動接続に失敗しました。接続設定を確認してください。")
            return
        self._gto_auto_connect_busy = True
        preferred_tree = self.tree_file if self.tree_file and self.tree_file.is_file() else None
        def work():
            try:
                greeting = self.integration.connect(timeout=10.0)
                loaded_tree = None
                tree_error = None
                if preferred_tree is not None:
                    try:
                        self.integration.open_solved_tree(preferred_tree)
                        loaded_tree = str(preferred_tree)
                    except Exception as exc:
                        tree_error = str(exc)
                self.jobs.put(("connect_ok", {
                    "greeting": greeting, "loaded_tree": loaded_tree,
                    "tree_error": tree_error, "library_count": len(self.tree_files),
                }))
            except Exception as exc:
                self.jobs.put(("auto_gto_connect_retry", {
                    "error": str(exc), "attempt": int(attempt),
                }))
        threading.Thread(target=work, daemon=True, name="PigeonGTOPlusAutoConnect").start()
        self.status_var.set(f"GTO+自動接続中… ({attempt + 1}/10)")

    def _enable_socket(self):
        try:
            self._save_connection_config()
            exe = Path(self.executable_var.get()).expanduser()
            if not exe.is_file():
                raise FileNotFoundError(f"GTO+が見つかりません: {exe}")
            if os.name != "nt":
                raise OSError("GTO+ socket setup is Windows-only")
            target = self.integration.enable_socket_connection()
            messagebox.showinfo(
                "GTO+ connection enabled",
                f"外部接続設定を追加しました。\n{target}\n\n"
                "GTO+が起動中なら一度終了して再起動してください。"
            )
            self.status_var.set("ソケット設定済み。GTO+を再起動して接続してください")
        except Exception as exc:
            messagebox.showerror("GTO+ setup error", str(exc))

    def _layout_embedded_gto_host(self) -> bool:
        """Align the visible GTO+ content with the marked top-left guide.

        The screenshot guide is measured relative to the GTO viewport:
        14 px from its left edge and 38 px below its top edge. Preserve
        GTO+'s aspect ratio and fit the remaining area so the bottom
        stays visible instead of being clipped.
        """
        try:
            self.update_idletasks()
            viewport_width = int(self.gto_viewport.winfo_width())
            viewport_height = int(self.gto_viewport.winfo_height())
            if viewport_width < 2 or viewport_height < 2:
                return False

            content_width = 1320.0
            content_height = 676.0
            native_top_inset = 42.0
            target_left_offset = 14.0
            target_top_offset = 38.0

            usable_width = max(2, viewport_width - int(round(target_left_offset)))
            usable_height = max(2, viewport_height - int(round(target_top_offset)))
            scale = min(
                usable_width / content_width,
                usable_height / content_height,
            )
            if scale <= 0:
                return False

            target_width = max(2, min(usable_width, int(content_width * scale)))
            target_client_height = max(
                2, min(usable_height, int(content_height * scale))
            )
            top_inset = max(0, int(round(native_top_inset * scale)))
            target_window_height = target_client_height + top_inset

            self.gto_host.place_configure(
                relx=0.0,
                rely=0.0,
                anchor="nw",
                x=int(round(target_left_offset)),
                y=int(round(target_top_offset)) - top_inset,
                width=target_width,
                height=target_window_height,
            )
            self._gto_display_scale = scale
            self._gto_content_scale_percent = int(round(scale * 100))
            self._gto_native_top_inset = top_inset
            self._gto_blue_guide_left_px = int(round(target_left_offset))
            self._gto_blue_guide_top_px = int(round(target_top_offset))
            return True
        except (tk.TclError, ZeroDivisionError, ValueError):
            return False
    def _sync_embedded_gto_geometry(self, reason: str = "") -> bool:
        """Resize the docked GTO+ child to the fitted inner viewport."""
        if not self.gto_embedded or not getattr(self.integration, "embedder", None):
            return False
        try:
            self.update_idletasks()
            if not self._layout_embedded_gto_host():
                raise RuntimeError("GTO+ viewport has no usable client area")
            self.update_idletasks()
            host_width = int(self.gto_host.winfo_width())
            host_height = int(self.gto_host.winfo_height())
            if host_width < 2 or host_height < 2:
                raise RuntimeError(
                    f"invalid fitted GTO+ host geometry: {host_width}x{host_height}"
                )
            self.integration.resize_docked_window(host_width, host_height)
            self.update_idletasks()
            return True
        except Exception as exc:
            try:
                suffix = f" ({reason})" if reason else ""
                self.status_var.set(
                    f"GTO+表示位置・サイズの再同期に失敗{suffix}: {exc}"
                )
            except Exception:
                pass
            return False
    def _schedule_embedded_gto_geometry_sync(self, reason: str) -> None:
        """Fit and resync after the solver processes its native WM_SIZE."""
        if not self.gto_embedded:
            return
        self._sync_embedded_gto_geometry(reason)
        try:
            self.after_idle(
                lambda r=reason: self._sync_embedded_gto_geometry(r + "-idle")
            )
            self.after(
                250,
                lambda r=reason: self._sync_embedded_gto_geometry(r + "-settled")
            )
            self.after(
                900,
                lambda r=reason: self._sync_embedded_gto_geometry(
                    r + "-native-zoom-settled"
                )
            )
        except tk.TclError:
            pass
    def _launch_gto(self, automatic: bool = False):
        try:
            self._save_connection_config()
            self.update_idletasks()
            host_hwnd = int(self.gto_host.winfo_id())
            hwnd = self.integration.launch_and_dock(host_hwnd, startup_timeout=25)
            process = getattr(self.integration, 'process', None)
            if process is not None:
                try:
                    self.gto_owned_process_pid = int(process.pid)
                except Exception:
                    self.gto_owned_process_pid = None
            self.gto_embedded = True
            self.status_var.set(f'GTO+をPigeon内に表示中 (HWND {hwnd})')
            self._schedule_embedded_gto_geometry_sync('launch')
            if automatic:
                self.after(1800, self._auto_connect_gto_plus)
        except Exception as exc:
            process = getattr(self.integration, 'process', None)
            try:
                still_running = process is not None and process.poll() is None
            except Exception:
                still_running = process is not None
            if still_running:
                try:
                    self.gto_owned_process_pid = int(process.pid)
                except Exception:
                    pass
                self.gto_embedded = False
                if isinstance(exc, WindowPermissionError):
                    # Match v1.3.69: preserve the already-running GTO+ PID,
                    # elevate Pigeon, and reattach rather than launching a copy.
                    self._restart_pigeon_elevated_for_gto(int(process.pid))
                    return
                self.status_var.set(
                    f'GTO+は起動しましたが、Pigeon内表示に失敗: {type(exc).__name__}: {exc}'
                )
            else:
                self.gto_embedded = False
                self.status_var.set(f'GTO+自動起動失敗: {type(exc).__name__}: {exc}')

    def _restart_pigeon_elevated_for_gto(self, process_id: int):
        """Restart Pigeon at the GTO+ integrity level and transfer the live GTO+ PID.
        The Windows UAC prompt is owned by Windows and cannot be silently bypassed.
        """
        if os.name != 'nt':
            self.status_var.set('GTO+の権限レベルをそろえられません (Windows only)')
            return
        try:
            script = str((ROOT / 'PigeonPoker.pyw').resolve())
            parameters = subprocess.list2cmdline([script, '--dock-gto-pid', str(int(process_id))])
            shell32 = ctypes.WinDLL('shell32', use_last_error=True)
            shell32.ShellExecuteW.argtypes = [
                ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int,
            ]
            shell32.ShellExecuteW.restype = ctypes.c_void_p
            result = shell32.ShellExecuteW(
                None, 'runas', str(Path(sys.executable).resolve()), parameters,
                str(ROOT), 1,
            )
            if int(result or 0) <= 32:
                error = ctypes.get_last_error()
                self._gto_handoff_in_progress = False
                if int(result or 0) == 1223 or error == 1223:
                    self.status_var.set('Windows UACで昇格がキャンセルされました。GTO+は別ウィンドウで起動中です。')
                else:
                    self.status_var.set(f'Pigeonの管理者再起動に失敗: {ctypes.FormatError(error or int(result or 5))}')
                return
            # Do not kill GTO+ when the old Pigeon closes; the new elevated
            # Pigeon instance will dock this exact PID.
            self._gto_handoff_in_progress = True
            self.status_var.set('Windowsの確認後、Pigeon内へGTO+を再接続します…')
            self.after(500, self._on_close)
        except Exception as exc:
            self._gto_handoff_in_progress = False
            self.status_var.set(f'Pigeonの権限再起動に失敗: {type(exc).__name__}: {exc}')


    def _attach_existing_gto(self, process_id: int):
        attempt = int(getattr(self, '_gto_attach_retry_attempt', 0))
        if attempt >= 30:
            self._gto_attach_retry_attempt = 0
            self.status_var.set('既存GTO+のPigeon内再接続に失敗しました。')
            return
        try:
            self.update_idletasks()
            if (not self.gto_host.winfo_ismapped()
                    or self.gto_host.winfo_width() < 250
                    or self.gto_host.winfo_height() < 180):
                self._gto_attach_retry_attempt = attempt + 1
                self.after(250, lambda pid=process_id: self._attach_existing_gto(pid))
                return
            hwnd = self.integration.attach_existing_and_dock(
                int(process_id), int(self.gto_host.winfo_id()), startup_timeout=15,
            )
            self._gto_attach_retry_attempt = 0
            self.gto_owned_process_pid = int(process_id)
            self.gto_embedded = True
            self.status_var.set(f'GTO+をPigeon内に再接続 (HWND {hwnd})')
            self._schedule_embedded_gto_geometry_sync('attach')
            self.after(1800, self._auto_connect_gto_plus)
        except Exception as exc:
            self._gto_attach_retry_attempt = 0
            self.gto_embedded = False
            self.gto_owned_process_pid = int(process_id)
            self.status_var.set(f'既存GTO+の再ドッキングに失敗: {type(exc).__name__}: {exc}')

    def _connect_gto(self):
        try:
            self._save_connection_config()
        except Exception as exc:
            messagebox.showerror("GTO+ settings", str(exc))
            return
        preferred_tree = self.tree_file if self.tree_file and self.tree_file.is_file() else None
        def work():
            try:
                greeting = self.integration.connect(timeout=10.0)
                loaded_tree = None
                tree_error = None
                # On subsequent launches, restore the preferred saved solve automatically.
                if preferred_tree is not None:
                    try:
                        self.integration.open_solved_tree(preferred_tree)
                        loaded_tree = str(preferred_tree)
                    except Exception as exc:
                        tree_error = str(exc)
                self.jobs.put(("connect_ok", {
                    "greeting": greeting, "loaded_tree": loaded_tree,
                    "tree_error": tree_error, "library_count": len(self.tree_files),
                }))
            except Exception as exc:
                self.jobs.put(("error", f"GTO+接続失敗: {exc}\nGTO+が起動中か、ソケット設定後に再起動したか確認してください。"))
        threading.Thread(target=work, daemon=True, name="PigeonGTOPlusConnect").start()
        self.status_var.set("GTO+へ接続中…")

    def _load_tree(self):
        """Add one or more GTO+ solve files to the persistent auto-match library."""
        selected = filedialog.askopenfilenames(
            title="GTO+ solved trees (複数選択できます)",
            filetypes=[("GTO+ save", "*.gto2 *.gto"), ("All files", "*.*")],
        )
        if not selected:
            return
        added = []
        existing = {str(path.expanduser().resolve()).casefold() for path in self.tree_files}
        for item in selected:
            path = Path(item).expanduser().resolve()
            if not path.is_file():
                continue
            key = str(path).casefold()
            if key not in existing:
                self.tree_files.append(path)
                existing.add(key)
                added.append(path)
        # Prefer the last selected file for manual navigation in the GTO+ workspace.
        self.tree_file = Path(selected[-1]).expanduser().resolve()
        self.config_data["gto_plus_tree_library"] = [str(path) for path in self.tree_files]
        self.config_data["gto_plus_preferred_tree"] = str(self.tree_file)
        save_config(self.config_data)
        self.tree_var.set(f"解析済みツリー {len(self.tree_files)} 本登録 • 優先: {self.tree_file.name}")
        tree = self.tree_file
        def work():
            try:
                result = self.integration.open_solved_tree(tree)
                self.jobs.put(("tree_loaded", {"result": result, "tree": str(tree),
                                                "library_count": len(self.tree_files),
                                                "added_count": len(added)}))
            except Exception as exc:
                self.jobs.put(("error", f"ツリーのロードに失敗: {exc}"))
        threading.Thread(target=work, daemon=True, name="PigeonGTOPlusTreeLoad").start()

    def _save_auto_collect_preference(self):
        self.config_data["gto_plus_auto_collect"] = bool(self.auto_collect_enabled_var.get())
        save_config(self.config_data)

    def _start_auto_analysis(self, paths=None):
        """Automatically crawl registered GTO+ solve trees and cache all decision nodes."""
        if self.auto_scan_thread is not None and self.auto_scan_thread.is_alive():
            self.auto_scan_status_var.set("自動収集中です。停止後に再実行できます。")
            return
        if not self.integration.connected:
            self.auto_scan_status_var.set("先にGTO+へ接続してください。")
            self.status_var.set("AUTO COLLECT: GTO+未接続")
            return
        if paths is None:
            candidates = list(self.tree_files)
            if self.tree_file is not None and self.tree_file.is_file():
                candidates.insert(0, self.tree_file)
        else:
            candidates = list(paths)
        unique = []
        seen = set()
        for raw in candidates:
            path = Path(raw).expanduser().resolve()
            key = str(path).casefold()
            if path.is_file() and key not in seen:
                unique.append(path)
                seen.add(key)
        if not unique:
            self.auto_scan_status_var.set("解析済み .gto2 / .gto ファイルを先に登録してください。")
            return
        self.auto_scan_cancel_event.clear()
        self.config_data["gto_plus_auto_collect"] = bool(self.auto_collect_enabled_var.get())
        save_config(self.config_data)
        try:
            rake = float(self.rake_var.get().strip() or "0")
        except (TypeError, ValueError):
            self.auto_scan_status_var.set("Rake (%) は数値で入力してください。")
            return
        self.auto_scan_status_var.set(f"自動収集を開始: {len(unique)} ツリー")
        self.status_var.set("GTO+ AUTO COLLECT • 全ノード巡回中")

        def progress(payload):
            self.jobs.put(("auto_scan_progress", dict(payload)))

        def work():
            results = []
            analyzer = GTOPlusAutoAnalyzer(self.integration, self.store)
            for path in unique:
                if self.auto_scan_cancel_event.is_set():
                    break
                try:
                    final_result = None
                    while not self.auto_scan_cancel_event.is_set():
                        final_result = analyzer.scan_tree(
                            path, rake_pct=rake, cancel_event=self.auto_scan_cancel_event,
                            progress_callback=progress, max_nodes=50000, checkpoint_interval=5,
                        )
                        # Continue in bounded chunks until the whole saved tree is
                        # collected. A user STOP request breaks at a checkpoint.
                        if final_result.get("status") != "paused" or self.auto_scan_cancel_event.is_set():
                            break
                        if not str(final_result.get("last_error", "")).startswith("Node limit reached"):
                            break
                    if final_result is not None:
                        results.append(final_result)
                except Exception as exc:
                    results.append({"tree_file": str(path), "status": "error",
                                    "last_error": f"{type(exc).__name__}: {exc}"})
                    # A disconnected solver cannot service any remaining trees.
                    if not self.integration.connected:
                        break
            self.jobs.put(("auto_scan_done", {
                "results": results, "cancelled": self.auto_scan_cancel_event.is_set(),
                "tree_count": len(unique),
            }))

        self.auto_scan_thread = threading.Thread(
            target=work, daemon=True, name="PigeonGTOPlusAutoCollector")
        self.auto_scan_thread.start()

    def _stop_auto_analysis(self):
        if self.auto_scan_thread is not None and self.auto_scan_thread.is_alive():
            self.auto_scan_cancel_event.set()
            self.auto_scan_status_var.set("停止要求を送信しました。現在のノードの保存後に停止します。")
        else:
            self.auto_scan_status_var.set("実行中の自動収集はありません。")

    def _run_auto_solve_ui_probe(self):
        """Run reversible OOP/IP weighted ranges, a three-card Board test, and inspect the Build Tree dialog."""
        if os.name != "nt":
            messagebox.showinfo("GTO+ auto-solve probe", "この診断はWindows上のGTO+で実行してください。")
            return
        if getattr(self, "_gto_ui_diagnostic_running", False):
            messagebox.showinfo("GTO+ auto-solve probe", "GTO+診断はすでに実行中です。")
            return
        integration_process = getattr(self.integration, "process", None)
        target_pid = getattr(integration_process, "pid", None) if integration_process is not None else None
        embedder = getattr(self.integration, "embedder", None)
        target_hwnd = getattr(embedder, "embedded_hwnd", None) if embedder is not None else None
        if not target_pid or not target_hwnd:
            messagebox.showerror(
                "GTO+ auto-solve probe",
                "Pigeon内のGTO+ PID/HWNDを特定できません。GTO+をPigeon内で起動し、接続してから実行してください。\n"
                "別のGTO.exeを推測して操作することはありません。",
            )
            return
        python_exe = Path(sys.executable)
        if python_exe.name.casefold() == "pythonw.exe":
            candidate = python_exe.with_name("python.exe")
            if candidate.is_file():
                python_exe = candidate
        output_dir = ROOT / "diagnostics"
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(python_exe), "-m", "pigeon_gto_plus.auto_solve_ui",
            "--output", str(output_dir),
            "--target-pid", str(int(target_pid)),
            "--target-hwnd", str(int(target_hwnd)),
        ]
        self._gto_ui_diagnostic_running = True
        self.status_var.set("未知局面Solve用のGTO+入力を可逆テスト中…（Player2 Source欄を特定・再読取して復旧を試行、テスト設定を復元）")

        def worker():
            started = time.time()
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUTF8"] = "1"
                completed = subprocess.run(
                    command, cwd=str(ROOT), capture_output=True, text=True,
                    encoding="utf-8", errors="replace", check=False,
                    env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                detail = (completed.stdout or "") + ("\n[stderr]\n" + completed.stderr if completed.stderr else "")
                log_path = output_dir / "auto_solve_ui_probe.log"
                log_path.write_text(detail or f"Exit code: {completed.returncode}", encoding="utf-8")
                reports = sorted(output_dir.glob("gto_auto_solve_ui_*.zip"),
                                 key=lambda item: item.stat().st_mtime, reverse=True)
                report = reports[0] if reports and reports[0].stat().st_mtime >= started - 2 else None
                success = completed.returncode == 0 and report is not None
                if success:
                    try:
                        with zipfile.ZipFile(report, "r") as report_zip:
                            report_json_name = next((name for name in report_zip.namelist() if name.endswith(".json")), None)
                            if report_json_name is None:
                                success = False
                            else:
                                report_json = json.loads(report_zip.read(report_json_name).decode("utf-8"))
                                report_safety = report_json.get("safety", {})
                                success = bool(report_safety.get("oop_expected_matrix_cells_reflection_verified") and report_safety.get("oop_restore_source_text_accepted") and report_safety.get("oop_test_range_restored") and report_safety.get("oop_weight_display_capture_saved") and report_safety.get("ip_expected_matrix_cells_reflection_verified") and report_safety.get("ip_restore_source_text_accepted") and report_safety.get("ip_test_range_restored") and report_safety.get("ip_weight_display_capture_saved") and report_safety.get("board_test_cards_reflection_verified") and report_safety.get("board_test_restored") and report_safety.get("build_tree_dialog_opened") and report_safety.get("build_tree_dialog_closed_verified") and report_safety.get("build_tree_probe_inputs_restored") and not report_safety.get("build_tree_probe_may_remain_configured") and not report_safety.get("manual_close_required"))
                                if not success:
                                    detail += " [Build Tree可逆テスト] 設定ダイアログの表示・閉鎖、または一時レンジ/Boardの復元に未達です。"
                    except Exception as exc:
                        success = False
                        detail += " [Build Tree可逆テスト] 設定ダイアログの表示・閉鎖、または一時レンジ/Boardの復元に未達です。"+str(exc)
                self.after(0, lambda: finish(success, report, detail, completed.returncode))
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                self.after(0, lambda: finish(False, None, detail, -1))

        def finish(success, report, detail, return_code):
            self._gto_ui_diagnostic_running = False
            if success and report is not None:
                self.status_var.set("GTO+画面診断完了（Build Tree設定画面の採取・閉鎖・OOP/IPレンジとBoardの完全復元を確認。Tree構築/Solver未実行）")
                try:
                    os.startfile(str(output_dir))
                except Exception:
                    pass
            else:
                self.status_var.set("GTO+画面診断は安全停止しました。Player2 Source欄の特定・再読取、Build Tree画面の閉鎖、OOP/IPレンジ・Boardの復元結果を確認してください。Source欄を特定できない場合は手動対応してください。")
                messagebox.showwarning(
                    "GTO+ auto-solve probe",
                    "診断は完了条件に届かず安全停止しました。Player2 Source欄の特定・再読取、Build Tree画面の検査、またはテスト設定の復元に未達です。診断JSONと画像を確認してください。Source欄が開いている場合は値を確認して手動対応してください。Tree/Solverは未実行です。\n\n"
                    + (detail[-3000:] if detail else f"Exit code: {return_code}")
                    + "\n\n診断フォルダ: " + str(output_dir),
                    parent=self,
                )
                try:
                    os.startfile(str(output_dir))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True, name="PigeonGTOAutoSolveUIProbe").start()

    def _run_gto_ui_diagnostic(self, open_oop_range_editor=False, focus_oop_source_field=False,
                                probe_oop_source_field_input=False, commit_oop_aa=False, batch_setup_probe=False):
        """Inspect GTO+; optionally run one guarded OOP=AA commit test."""
        if os.name != "nt":
            messagebox.showinfo("GTO+画面診断", "この診断はGTO+をインストールしたWindows PC上で実行してください。")
            return
        if commit_oop_aa:
            if not messagebox.askyesno(
                "OOPテストレンジAAの確定",
                "現在のOOPレンジをテスト用の AA に置き換えます。\n\n"
                "Source code欄が空の場合だけ実行し、空でなければ上書きせず停止します。\n"
                "前回の失敗でStarting Range Editorが開いたままの場合は、先にEscで閉じてください。\n"
                "IPレンジ・Board・Pot・Stack・Rakeは変更せず、ツリー構築・Solver実行もしません。\n\n"
                "現在のOOPレンジを残したい場合はキャンセルしてください。\n\n実行しますか？",
            ):
                return
        if batch_setup_probe:
            if not messagebox.askyesno(
                "GTO+ 4工程まとめてテスト",
                "テスト用のレンジ OOP=AA / IP=KK をGTO+に確定します。\n"
                "BoardとBuild Tree設定画面は開いて撮影後に閉じます。\n\n"
                "ボード・ポット・スタックは変更せず、ツリー構築・Solver実行はしません。\n"
                "現在のGTO+に保存しておきたい未保存の設定がないことを確認してください。\n\n実行しますか？",
            ):
                return
        probe_module = ROOT / "pigeon_gto_plus" / "ui_probe.py"
        if not probe_module.is_file():
            messagebox.showerror(
                "GTO+画面診断",
                "診断ツールが見つかりません。Pigeon Pokerを最新版へ更新してください。",
            )
            return
        if getattr(self, "_gto_ui_diagnostic_running", False):
            messagebox.showinfo("GTO+画面診断", "診断はすでに実行中です。完了すると保存先フォルダが自動で開きます。")
            return
        try:
            python_exe = Path(sys.executable)
            if python_exe.name.casefold() == "pythonw.exe":
                console_python = python_exe.with_name("python.exe")
                if console_python.is_file():
                    python_exe = console_python
            if not python_exe.is_file():
                raise FileNotFoundError(f"Python executable not found: {python_exe}")
            output_dir = ROOT / "diagnostics"
            output_dir.mkdir(parents=True, exist_ok=True)
            command = [str(python_exe), "-m", "pigeon_gto_plus.ui_probe", "--output", str(output_dir)]
            # Pass the exact GTO+ process/window Pigeon embedded. Do not let the
            # diagnostic guess among stale or separately launched GTO.exe windows.
            integration_process = getattr(self.integration, "process", None)
            integration_pid = getattr(integration_process, "pid", None) if integration_process is not None else None
            integration_embedder = getattr(self.integration, "embedder", None)
            integration_hwnd = getattr(integration_embedder, "embedded_hwnd", None) if integration_embedder is not None else None
            requires_exact_target = bool(batch_setup_probe or open_oop_range_editor or
                                         focus_oop_source_field or probe_oop_source_field_input or commit_oop_aa)
            if requires_exact_target:
                if not integration_pid or not integration_hwnd:
                    messagebox.showerror(
                        "GTO+画面操作",
                        "Pigeon Pokerが埋め込んでいるGTO+のPID/HWNDを確認できません。\n"
                        "GTO+接続パネルで②起動・③接続を行ってから再実行してください。\n"
                        "別のGTO+ウィンドウを推測して操作することはしません。",
                    )
                    return
                command.extend(["--target-pid", str(int(integration_pid)),
                                "--target-hwnd", str(int(integration_hwnd))])
            if open_oop_range_editor:
                command.append("--open-oop-range-editor")
            if focus_oop_source_field or probe_oop_source_field_input:
                command.append("--focus-oop-source-field")
            if probe_oop_source_field_input:
                command.append("--probe-oop-source-field-input")
            if commit_oop_aa:
                command.append("--commit-oop-aa")
            if batch_setup_probe:
                command.append("--batch-pre-solve-probe")
            self._gto_ui_diagnostic_running = True
            self.status_var.set(("GTO+ OOP=AAテストレンジ確定中… 完了すると結果フォルダが自動で開きます"
                                 if commit_oop_aa else
                                 "GTO+ 4工程まとめてテスト中… 完了すると結果フォルダが自動で開きます"
                                 if batch_setup_probe else
                                 "GTO+ Source code欄の一時入力テスト中… 完了すると結果フォルダが自動で開きます"
                                 if probe_oop_source_field_input else
                                 "GTO+ OOPレンジのSource code欄を確認中… 完了すると結果フォルダが自動で開きます"
                                 if focus_oop_source_field else
                                 "GTO+ OOPレンジ画面診断中… 完了すると結果フォルダが自動で開きます"
                                 if open_oop_range_editor else
                                 "GTO+ UI診断中… 完了すると結果フォルダが自動で開きます"))

            def worker():
                started = time.time()
                try:
                    diagnostic_env = os.environ.copy()
                    diagnostic_env["PYTHONIOENCODING"] = "utf-8"
                    diagnostic_env["PYTHONUTF8"] = "1"
                    # Do not create a console window: the Win32 screenshot fallback
                    # captures desktop pixels, and a visible console would cover GTO+.
                    no_console = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    completed = subprocess.run(
                        command, cwd=str(ROOT), capture_output=True, text=True,
                        encoding="utf-8", errors="replace", check=False,
                        env=diagnostic_env, creationflags=no_console,
                    )
                    log_text = (completed.stdout or "") + ("\n[stderr]\n" + completed.stderr if completed.stderr else "")
                    log_path = output_dir / "diagnostic_run.log"
                    log_path.write_text(log_text or f"Exit code: {completed.returncode}", encoding="utf-8")
                    reports = sorted(
                        output_dir.glob("gto_plus_ui_*.zip"),
                        key=lambda item: item.stat().st_mtime,
                        reverse=True,
                    )
                    report = reports[0] if reports and reports[0].stat().st_mtime >= started - 2 else None
                    success = completed.returncode == 0 and report is not None
                    detail = log_text[-5000:]
                    self.after(0, lambda: finish(success, report, log_path, detail, completed.returncode))
                except Exception as exc:
                    detail = f"{type(exc).__name__}: {exc}"
                    self.after(0, lambda: finish(False, None, output_dir / "diagnostic_run.log", detail, -1))

            def finish(success, report, log_path, detail, return_code):
                self._gto_ui_diagnostic_running = False
                if success and report is not None:
                    self.status_var.set("GTO+ OOP=AAレンジ確定テスト完了。診断ZIPを保存しました" if commit_oop_aa else ("GTO+ 4工程まとめてテスト完了。診断ZIPを保存しました" if batch_setup_probe else ("GTO+ Source code一時入力テスト完了。診断ZIPを保存しました" if probe_oop_source_field_input else ("GTO+ OOPレンジ画面診断完了。診断ZIPを保存しました" if open_oop_range_editor else "GTO+ UI診断完了。診断ZIPを保存しました"))))
                    try:
                        os.startfile(str(output_dir))
                    except Exception as open_exc:
                        messagebox.showwarning("GTO+画面診断", f"診断ZIPは作成されましたが、フォルダを自動で開けませんでした。\n{report}\n{open_exc}")
                        return
                    if commit_oop_aa:
                        info_text = "OOPテストレンジ AA を入力し、完了ボタンを押して編集画面が閉じたことを確認しました。IP・Board・pot・stack・Tree・Solverは変更していません。\n\n"
                    elif batch_setup_probe:
                        info_text = "OOP=AA / IP=KKのテストレンジを確定しました。BoardとBuild Tree設定画面を撮影して閉じました。Board・pot・stackは変更せず、Tree/Solver実行は行っていません。\n\n"
                    elif probe_oop_source_field_input:
                        info_text = "Source code欄へAAを一時設定し、読み戻し後に元の空欄へ復元しました。完了ボタン・ツリー構築・Solver実行は行っていません。\n\n"
                    elif open_oop_range_editor and focus_oop_source_field:
                        info_text = "OOPレンジ編集画面を開き、Source code欄にフォーカスしました。文字入力・レンジ変更・ツリー構築・Solver実行はしていません。\n\n"
                    elif open_oop_range_editor:
                        info_text = "OOPレンジ編集画面の診断結果を作成しました。レンジ変更・ツリー構築・Solver実行はしていません。\n\n"
                    else:
                        info_text = "診断結果を作成しました。\n\n"
                    messagebox.showinfo(
                        "GTO+画面診断 完了",
                        info_text + f"{report}\n\nいま開いたフォルダ内の gto_plus_ui_....zip を、このチャットに添付してください。",
                    )
                else:
                    self.status_var.set("GTO+ UI診断に失敗しました。エラー内容を確認してください")
                    try:
                        log_path.write_text(detail or f"Exit code: {return_code}", encoding="utf-8")
                        os.startfile(str(output_dir))
                    except Exception:
                        pass
                    messagebox.showerror(
                        "GTO+画面診断 失敗",
                        "診断ZIPを作成できませんでした。\n"
                        f"ログ保存先: {log_path}\n終了コード: {return_code}\n\n"
                        f"{detail or '詳細ログがありません。'}",
                    )

            threading.Thread(target=worker, daemon=True, name="PigeonGTOPlusUIDiagnostic").start()
        except Exception as exc:
            self._gto_ui_diagnostic_running = False
            messagebox.showerror("GTO+画面診断", f"診断を起動できませんでした。\n{exc}")

    def _import_node(self):
        client = getattr(self.integration, "_client", None)
        if client is None or not client.connected:
            messagebox.showwarning("GTO+ not connected", "先にGTO+ ENGINEで接続してください。保存済みファイルの登録は必須ではありません。")
            return
        tree = self.tree_file if self.tree_file is not None and self.tree_file.is_file() else None
        rake = float(self.rake_var.get() or "0")
        def work():
            try:
                context = self.integration.import_current_node(tree, rake)
                self.jobs.put(("node_imported", context))
            except Exception as exc:
                self.jobs.put(("error", f"ノード取り込み失敗: {exc}"))
        self.import_status.set("現在ノードを読み取り、全ハンドを保存中…")
        threading.Thread(target=work, daemon=True).start()

    def _cpu_decide(self):
        client = getattr(self.integration, "_client", None)
        if client is None or not client.connected:
            messagebox.showwarning("GTO+ not connected", "先にGTO+ ENGINEで接続してください。保存済みツリーか、GTO+で現在開いている解析済みノードを利用できます。")
            self.show_page("lobby")
            return
        hand = self.active_cpu_hand or self.hand_var.get().strip()
        side = self.side_var.get().strip()
        try:
            rake = float(self.rake_var.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Invalid rake", "Rake (%) must be numeric")
            return
        tree = self.tree_file if self.tree_file is not None and self.tree_file.is_file() else None
        self.cpu_last_action.set("CPU is consulting GTO+ and sampling its mixed strategy…")
        self.status_var.set("CPU is thinking. No CPU action time limit.")
        def work():
            try:
                result = self.integration.cpu_act_current_node(hand, side, tree, rake_pct=rake)
                try:
                    context = self.integration.read_current_context()
                except Exception as terminal_exc:
                    context = None
                self.jobs.put(("cpu_advanced", {"result": result, "context": context,
                                                "terminal_error": None if context else str(terminal_exc)}))
            except Exception as exc:
                self.jobs.put(("error", f"CPU decision failed: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def _resize_embedded(self, _event=None):
        self._sync_embedded_gto_geometry("viewport-configure")
    def _count_cached_strategies(self) -> int:
        try:
            with self.store._connect() as con:
                return int(con.execute("SELECT COUNT(*) FROM spots").fetchone()[0])
        except Exception:
            return 0

    def _refresh_gto_coverage(self):
        """Refresh visible counts from the actual imported strategy database."""
        if not hasattr(self, "gto_coverage_tree"):
            return
        try:
            report = self.store.coverage_report()
            self.gto_coverage_summary_var.set(
                f"{report['nodes']:,} unique nodes • {report['combos']:,} exact combos • "
                f"{report['boards']:,} boards • {report['actions']:,} action rows"
            )
            for item in self.gto_coverage_tree.get_children():
                self.gto_coverage_tree.delete(item)
            for street in ("flop", "turn", "river"):
                row = report["by_street"].get(street, {})
                self.gto_coverage_tree.insert("", "end", values=(
                    street.upper(), row.get("nodes", 0), row.get("combos", 0),
                    row.get("boards", 0), row.get("actions", 0)))
            precision_note = report["unverified_strategies"]
            self.gto_coverage_quality_var.set(
                f"Solver precision metadata unavailable/unverified: {precision_note:,} strategies. "
                "Counts show imported data only; no total-state coverage percentage is inferred."
            )
        except Exception as exc:
            self.gto_coverage_summary_var.set(f"Coverage read error: {exc}")

    def _export_gto_coverage(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="Export GTO+ strategy coverage",
            defaultextension=".json", initialfile="pigeon_gto_strategy_coverage.json",
            filetypes=[("JSON report", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            saved = self.store.export_coverage_json(path)
            messagebox.showinfo("GTO+ coverage", f"Coverage report exported:\n{saved}", parent=self)
        except Exception as exc:
            messagebox.showerror("GTO+ coverage", str(exc), parent=self)

    def _show_node_context(self, context: dict[str, Any]):
        self.current_node_context = context
        self._refresh_gto_coverage()
        node = context["node"]
        line = context.get("line", [])
        pot_stacks = context.get("pot_stacks", {})
        effective = min(pot_stacks.get("oop_stack", 0), pot_stacks.get("ip_stack", 0)) if pot_stacks else 0
        self.node_var.set(f"Board: {' '.join(node['board'])} | To act: {node['next_to_act'].upper()} | Pot: {pot_stacks.get('pot', 0):.2f} | Effective stack: {effective:.2f}")
        self._set_node_text(self._format_node(node, line, pot_stacks))
        self.db_count_var.set(f"保存済み戦略: {self._count_cached_strategies()} combos")
        self._render_practice_actions()
        self._draw_table()

    def _set_node_text(self, value: str):
        self.node_text.configure(state="normal")
        self.node_text.delete("1.0", "end")
        self.node_text.insert("end", value)
        self.node_text.configure(state="disabled")

    def _drain_jobs(self):
        try:
            while True:
                kind, payload = self.jobs.get_nowait()
                if kind == "cash_gto_spot_ready":
                    self.cash_busy = False
                    self.cash_table = payload["table"]
                    self.cash_hand_instance += 1
                    self.cash_current_hand_key = f"{self.cash_session_id}-{self.cash_hand_instance}"
                    self.cash_gto_session = payload["session"]
                    self.cash_cpus = {"cpu1": CashGameCPU(level=5, rng=random.Random(), simulations=48)}
                    self.cash_rate = "GTO+ SPOT"
                    self.cash_sb, self.cash_bb = 50, 100
                    self.table_title_var.set("GTO+ POSTFLOP SPOT  •  HEADS-UP")
                    self.cash_status_var.set(f"GTO+ {self.cash_table.hand.street.upper()} • Pot {payload['context']['pot_stacks']['pot']:.2f} BB")
                    self.cash_source_var.set("GTO+ exact solved-node strategy • CPU Lv.5 • results cached as you play")
                    self.cash_log_lines = ["GTO+ postflop spot loaded",
                                           "Board: " + " ".join(self.cash_table.hand.board),
                                           f"CPU hand: hidden • Your hand: {payload['dealt']['human']}",
                                           f"Pot: {payload['context']['pot_stacks']['pot']:.2f} BB"]
                    if (self.pending_gto_restart_table_id
                            and self.multi_tables.get(self.pending_gto_restart_table_id)):
                        self.active_cash_table_id = self.pending_gto_restart_table_id
                        self.multi_tables.activate(self.active_cash_table_id)
                        self.multi_tables.update_active(self._cash_state_snapshot(), "GTO+ SPOT")
                    else:
                        slot = self.multi_tables.add("GTO+ SPOT", self._cash_state_snapshot())
                        self.active_cash_table_id = slot.table_id
                    self._create_table_window(self.active_cash_table_id)
                    self.pending_gto_previous_table_id = None
                    self.pending_gto_restart_table_id = None
                    self._refresh_table_tabs()
                    self._draw_table()
                    self._render_cash_actions()
                    self._start_cash_cpu_chain_if_needed()
                elif kind == "cash_start_error":
                    self.cash_busy = False
                    self.cash_gto_spot_mode = False
                    self.cash_status_var.set("GTO+ spot could not be loaded")
                    restore_id = self.pending_gto_previous_table_id or self.pending_gto_restart_table_id
                    self.pending_gto_previous_table_id = None
                    self.pending_gto_restart_table_id = None
                    if restore_id and self.multi_tables.get(restore_id):
                        self._restore_cash_slot(restore_id)
                        self.show_page("table")
                    else:
                        self.active_cash_table_id = None
                        self.show_page("lobby")
                    messagebox.showerror("GTO+ spot", str(payload))
                elif kind == "cash_gto_query_started":
                    table_id = payload.get("table_id")
                    slot = self.multi_tables.get(table_id) if table_id else None
                    if slot is not None:
                        slot.state["cash_gto_querying"] = True
                        slot.state["cash_action_feed"] = "GTO+へ局面を照合中…"
                        slot.state["cash_status"] = "GTO+局面照合中…"
                        if table_id == self.active_cash_table_id:
                            self.cash_action_feed = slot.state["cash_action_feed"]
                            self.cash_status_var.set(slot.state["cash_status"])
                            self.cash_source_var.set("GTO+ solver • checking current HU postflop node")
                        self._refresh_table_windows()
                elif kind == "gto_solver_status":
                    busy = bool(payload.get("busy"))
                    table_id = payload.get("table_id")
                    if not table_id:
                        table_id = self.active_cash_table_id
                    slot = self.multi_tables.get(table_id) if table_id else None
                    if busy:
                        self.status_var.set("GTO+解析中…")
                        if slot is not None:
                            slot.state["cash_gto_solver_busy"] = True
                            slot.state["cash_gto_querying"] = True
                            slot.state["cash_action_feed"] = "GTO+解析中…"
                            slot.state["cash_status"] = "GTO+解析中… CPUの判断を待っています"
                            slot.state["cash_source"] = "GTO+ solver • actively calculating"
                            if table_id == self.active_cash_table_id:
                                self.cash_action_feed = "GTO+解析中…"
                                self.cash_status_var.set("GTO+解析中… CPUの判断を待っています")
                                self.cash_source_var.set("GTO+ソルバー解析中 • 結果待ち")
                    else:
                        self.status_var.set("GTO+解析応答を受信しました")
                        if slot is not None and slot.state.get("cash_gto_solver_busy"):
                            slot.state["cash_gto_solver_busy"] = False
                            slot.state["cash_action_feed"] = "GTO+解析完了 • 戦略を照合中…"
                            slot.state["cash_status"] = "GTO+解析完了 • CPU戦略を確認中…"
                            if table_id == self.active_cash_table_id:
                                self.cash_action_feed = slot.state["cash_action_feed"]
                                self.cash_status_var.set(slot.state["cash_status"])
                                self.cash_source_var.set("GTO+ solver • result received, matching strategy")
                    self._refresh_table_windows()
                elif kind == "cash_cpu_thinking":
                    table_id = payload.get("table_id")
                    slot = self.multi_tables.get(table_id) if table_id else None
                    if slot is not None:
                        slot.state["cash_thinking_player"] = payload.get("player_id")
                        slot.state["cash_action_feed"] = f"{payload.get('name', 'Opponent')} is thinking…"
                        if table_id == self.active_cash_table_id:
                            self.cash_thinking_player = payload.get("player_id")
                            self.cash_action_feed = slot.state["cash_action_feed"]
                            self._refresh_table_windows()
                        else:
                            self._refresh_table_windows()
                elif kind == "cash_cpu_action_event":
                    table_id = payload.get("table_id")
                    slot = self.multi_tables.get(table_id) if table_id else None
                    if slot is not None:
                        action_line = str(payload.get("line", "Opponent acted"))
                        slot.state["cash_thinking_player"] = None
                        slot.state["cash_gto_querying"] = False
                        slot.state["cash_gto_solver_busy"] = False
                        slot.state["cash_action_feed"] = action_line
                        slot.state.setdefault("cash_log_lines", []).append(action_line)
                        if payload.get("gto_used"):
                            slot.state["cash_source"] = "GTO+ exact solved-node strategy"
                        if table_id == self.active_cash_table_id:
                            self.cash_thinking_player = None
                            self.cash_action_feed = action_line
                            if payload.get("gto_used"):
                                self.cash_source_var.set("GTO+ exact solved-node strategy • node cached during play")
                        cpu_action = str(payload.get("action", "check"))
                        self._set_cash_action_flash(
                            table_id, str(payload.get("player_id", "")), cpu_action,
                            payload.get("amount"), actor_name=str(payload.get("name", "Opponent"))
                        )
                        self._play_action_sound(cpu_action)
                        self._refresh_table_windows()
                        if str(payload.get("action", "")).lower().replace("_", "-") in {
                                "call", "bet", "raise", "all-in", "all-in-call"}:
                            self._animate_action_chips(table_id, str(payload.get("player_id", "")))
                elif kind == "cash_board_animation":
                    table_id = payload.get("table_id")
                    if table_id and self.multi_tables.get(table_id):
                        slot = self.multi_tables.get(table_id)
                        slot.state["cash_busy"] = True
                        if table_id == self.active_cash_table_id:
                            self.cash_busy = True
                        self._refresh_table_windows()
                        self._animate_board_reveal(
                            table_id, list(payload.get("board", [])),
                            ready_event=payload.get("ready_event"),
                            squeeze_start_index=payload.get("squeeze_start_index")
                        )
                elif kind == "cash_gto_waiting":
                    table_id = payload.get("table_id")
                    self.cash_cpu_cancel_events.pop(table_id, None)
                    reason = str(payload.get("reason", "GTO+ exact solve required"))
                    path = str(payload.get("request_path", ""))
                    slot = self.multi_tables.get(table_id) if table_id else None
                    if slot is not None:
                        slot.state["cash_busy"] = False
                        slot.state["cash_syncing_gto"] = False
                        slot.state["cash_thinking_player"] = None
                        slot.state["cash_gto_waiting"] = True
                        slot.state["cash_gto_querying"] = False
                        slot.state["cash_gto_solver_busy"] = False
                        slot.state["cash_action_feed"] = "GTO+未解決 • CPU待機中"
                        slot.state["cash_status"] = "GTO+ solve required • CPU paused"
                        slot.state.setdefault("cash_log_lines", []).append(
                            f"GTO+ WAIT • scenario {payload.get('scenario_key', '')[:12]} • {reason}")
                    if table_id == self.active_cash_table_id:
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self.cash_gto_session = None
                        self.cash_action_feed = "GTO+未解決 • CPU待機中"
                        self.cash_status_var.set("GTO+未解決 • CPU待機中（通常CPUには切替えません）")
                        self.cash_source_var.set("GTO+ required • waiting for exact solved tree")
                        self.cash_log_lines.append(
                            f"GTO+ WAIT • scenario {payload.get('scenario_key', '')[:12]} • {reason}")
                        self._save_active_cash_slot()
                        self._draw_table()
                        self._render_cash_actions()
                    self._refresh_table_windows()
                    self._refresh_gto_pending_queue()
                elif kind == "cash_gto_bind_done":
                    self.cash_busy = False
                    self.cash_syncing_gto = False
                    session = payload.get("session")
                    source_status = payload.get("source_status", "CPU fallback")
                    table_id = payload.get("table_id")
                    self.cash_cpu_cancel_events.pop(table_id, None)
                    if table_id in self.rush_fold_poll_jobs:
                        if table_id != self.active_cash_table_id:
                            self._save_active_cash_slot()
                            self._restore_cash_slot(table_id)
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self._poll_rush_fold(table_id)
                        continue
                    if table_id in self.quick_leave_poll_jobs:
                        if table_id != self.active_cash_table_id:
                            self._save_active_cash_slot()
                            self._restore_cash_slot(table_id)
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self._poll_quick_leave(table_id)
                        continue
                    if table_id == self.active_cash_table_id:
                        self.cash_gto_session = session
                        active_slot = self.multi_tables.get(table_id) if table_id else None
                        if active_slot is not None:
                            active_slot.state["cash_gto_querying"] = False
                            active_slot.state["cash_gto_solver_busy"] = False
                        self.cash_status_var.set("GTO+局面の同期完了" if session is not None else "GTO+局面を利用できません")
                        self.cash_source_var.set(source_status)
                        if session is not None:
                            self.cash_log_lines.append("GTO+: HU postflop node matched before HERO action; solver line is synchronized.")
                        elif payload.get("gto_reason"):
                            self.cash_log_lines.append("GTO+ not used for this spot: " + str(payload["gto_reason"]))
                        self._save_active_cash_slot()
                        self._draw_table()
                        self._render_cash_actions()
                        self._refresh_table_windows()
                        if self.cash_table and self.cash_table.hand and self.cash_table.hand.next_to_act == "hero":
                            if self._consume_queued_auto_fold(table_id):
                                continue
                            self._ensure_squeeze_action_deadline(table_id)
                        elif self.cash_table and self.cash_table.hand and session is not None:
                            self.after(50, self._start_cash_cpu_chain_if_needed)
                    elif table_id and self.multi_tables.get(table_id):
                        slot = self.multi_tables.get(table_id)
                        slot.state["cash_gto_session"] = session
                        slot.state["cash_busy"] = False
                        slot.state["cash_syncing_gto"] = False
                        slot.state["cash_source"] = source_status
                        slot.state["cash_gto_querying"] = False
                        slot.state["cash_gto_solver_busy"] = False
                        if payload.get("gto_reason"):
                            slot.state.setdefault("cash_log_lines", []).append("GTO+ not used for this spot: " + str(payload["gto_reason"]))
                        self._refresh_table_windows()

                elif kind == "cash_cpu_timeout":
                    table_id = payload.get("table_id")
                    slot = self.multi_tables.get(table_id) if table_id else None
                    self.cash_cpu_cancel_events.pop(table_id, None)
                    if slot is None:
                        continue
                    state = slot.state
                    table = state.get("cash_table")
                    hand = table.hand if table is not None else None
                    player_id = str(payload.get("player_id", ""))
                    hand_token = payload.get("hand_token")
                    event_count = int(payload.get("event_count", -1))
                    if (
                        hand is None or hand.finished or id(hand) != hand_token
                        or len(hand.events) != event_count or hand.next_to_act != player_id
                        or state.get("cash_sitting_out") or table_id in self.rush_fold_poll_jobs
                        or table_id in self.quick_leave_poll_jobs
                    ):
                        continue
                    previous_id = self.active_cash_table_id
                    if previous_id != table_id:
                        if previous_id and self.multi_tables.get(previous_id):
                            self._save_active_cash_slot()
                        self._restore_cash_slot(table_id)
                        slot = self.multi_tables.get(table_id)
                        state = slot.state if slot else {}
                        table = state.get("cash_table") if slot else None
                        hand = table.hand if table else None
                        if hand is None or id(hand) != hand_token or hand.next_to_act != player_id:
                            if previous_id and previous_id != table_id and self.multi_tables.get(previous_id):
                                self._restore_cash_slot(previous_id)
                            continue
                    try:
                        legal = hand.legal_actions(player_id)
                        actions = {str(value).lower().replace("_", "-") for value in legal.get("actions", [])}
                        timeout_action = "check" if "check" in actions else "fold"
                        if timeout_action == "fold" and "fold" not in actions:
                            timeout_action = "check"
                        table.act(player_id, timeout_action)
                        table.sync_external_hand_state()
                        state["cash_busy"] = False
                        state["cash_syncing_gto"] = False
                        state["cash_thinking_player"] = None
                        state["cash_gto_waiting"] = False
                        state["cash_gto_querying"] = False
                        state["cash_gto_solver_busy"] = False
                        state["cash_action_feed"] = f"{payload.get('name', 'CPU')} TIMEOUT • {timeout_action.upper()}"
                        state.setdefault("cash_log_lines", []).append(
                            f"{payload.get('name', 'CPU')}: {timeout_action.upper()} "
                            f"[same {int(payload.get('seconds', 0))}s action limit as HERO]"
                        )
                        if table_id == self.active_cash_table_id:
                            self.cash_busy = False
                            self.cash_syncing_gto = False
                            self.cash_thinking_player = None
                            self.cash_action_feed = state["cash_action_feed"]
                            self._save_active_cash_slot()
                            self._update_cash_after_action()
                            self._refresh_table_windows()
                        else:
                            self._save_active_cash_slot()
                            self._restore_cash_slot(table_id)
                            self.cash_busy = False
                            self.cash_syncing_gto = False
                            self.cash_thinking_player = None
                            self.cash_gto_session = None
                            self._save_active_cash_slot()
                            self._update_cash_after_action()
                            self._save_active_cash_slot()
                            if previous_id and previous_id != table_id and self.multi_tables.get(previous_id):
                                self._restore_cash_slot(previous_id)
                            self._refresh_table_windows()
                    except Exception as timeout_exc:
                        state["cash_busy"] = False
                        state["cash_syncing_gto"] = False
                        state["cash_thinking_player"] = None
                        state.setdefault("cash_log_lines", []).append("CPU timeout action error: " + str(timeout_exc))
                        if table_id == self.active_cash_table_id:
                            self.cash_busy = False
                            self.cash_syncing_gto = False
                            self.cash_thinking_player = None
                            self.cash_status_var.set("CPU TIMEOUT • ACTION RECOVERY ERROR")
                        self._refresh_table_windows()
                elif kind == "cash_cpu_done":
                    table_id = payload.get("table_id")
                    session = payload.get("session")
                    # Live HU GTO+ sessions import the next node during CPU play.
                    # Refresh the coverage dashboard after the worker has finished
                    # writing those rows, not on every low-level socket command.
                    self._refresh_gto_coverage()
                    self._refresh_gto_pending_queue()
                    self.cash_cpu_cancel_events.pop(table_id, None)
                    if table_id in self.rush_fold_poll_jobs:
                        if table_id != self.active_cash_table_id:
                            self._save_active_cash_slot()
                            self._restore_cash_slot(table_id)
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self._poll_rush_fold(table_id)
                        continue
                    if table_id in self.quick_leave_poll_jobs:
                        if table_id != self.active_cash_table_id:
                            self._save_active_cash_slot()
                            self._restore_cash_slot(table_id)
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self._poll_quick_leave(table_id)
                        continue
                    if table_id == self.active_cash_table_id:
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self.cash_gto_session = session
                        self.cash_source_var.set(payload.get("source_status", "CPU strategy complete"))
                        for line in payload.get("decisions", []):
                            self.cash_log_lines.append(line)
                        self._save_active_cash_slot()
                        self._update_cash_after_action()
                        self._refresh_cash_history()
                    elif table_id and self.multi_tables.get(table_id):
                        previous_id = self.active_cash_table_id
                        self._save_active_cash_slot()
                        self._restore_cash_slot(table_id)
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self.cash_gto_session = session
                        self.cash_source_var.set(payload.get("source_status", "CPU strategy complete"))
                        self.cash_log_lines.extend(payload.get("decisions", []))
                        try:
                            if self.cash_table:
                                self.cash_table.sync_external_hand_state()
                            self._update_cash_after_action()
                            self._save_active_cash_slot()
                        finally:
                            if previous_id and previous_id != table_id and self.multi_tables.get(previous_id):
                                self._restore_cash_slot(previous_id)
                        self._refresh_table_windows()
                elif kind == "ev_cashout_offer_ready":
                    table_id = payload.get("table_id")
                    dialog_state = self.cash_runout_dialogs.get(table_id)
                    if dialog_state and dialog_state.get("token") == payload.get("token"):
                        offer = payload.get("offer")
                        dialog_state["offer"] = offer
                        try:
                            button = dialog_state.get("cashout_button")
                            if button is not None and offer is not None:
                                amount = self._format_table_chips(offer.payout, dialog_state.get("bb", 1))
                                button.configure(
                                    text=f"EV CASHOUT  •  {amount}  •  {offer.equity:.1%}",
                                    state="normal")
                            elif button is not None:
                                button.configure(text="EV CASHOUT NOT AVAILABLE", state="disabled")
                            status = dialog_state.get("status")
                            if status is not None:
                                status.set("Choose how to resolve the all-in.")
                        except tk.TclError:
                            pass
                elif kind == "cash_cpu_error":
                    table_id = payload.get("table_id")
                    self.cash_cpu_cancel_events.pop(table_id, None)
                    if table_id in self.rush_fold_poll_jobs:
                        if table_id != self.active_cash_table_id:
                            self._save_active_cash_slot()
                            self._restore_cash_slot(table_id)
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self._poll_rush_fold(table_id)
                        continue
                    if table_id in self.quick_leave_poll_jobs:
                        if table_id != self.active_cash_table_id:
                            self._save_active_cash_slot()
                            self._restore_cash_slot(table_id)
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self._poll_quick_leave(table_id)
                        continue
                    if table_id == self.active_cash_table_id:
                        self.cash_busy = False
                        self.cash_syncing_gto = False
                        self.cash_thinking_player = None
                        self.cash_gto_session = payload.get("session")
                        for line in payload.get("decisions", []):
                            self.cash_log_lines.append(line)
                        self.cash_status_var.set("CPU action error — inspect message")
                        self._draw_table()
                        self._render_cash_actions()
                        messagebox.showerror("Pigeon CPU", payload.get("error", "Unknown CPU error"))
                    elif table_id and self.multi_tables.get(table_id):
                        slot = self.multi_tables.get(table_id)
                        slot.state["cash_busy"] = False
                        slot.state["cash_syncing_gto"] = False
                        slot.state["cash_thinking_player"] = None
                        slot.state["cash_status"] = "CPU action error — inspect table log"
                        slot.state.setdefault("cash_log_lines", []).append(
                            "CPU action error: " + str(payload.get("error", "Unknown CPU error")))
                        self._refresh_table_windows()
                elif kind == "connect_ok":
                    self._gto_auto_connect_busy = False
                    if isinstance(payload, dict):
                        message = str(payload.get("greeting", "GTO+ connected"))
                        if payload.get("loaded_tree"):
                            message += f" • loaded {Path(payload['loaded_tree']).name}"
                        if payload.get("tree_error"):
                            message += f" • tree load failed: {payload['tree_error']}"
                        elif payload.get("library_count"):
                            message += f" • {payload['library_count']} saved tree(s) in auto-match library"
                        self.status_var.set(message)
                    else:
                        self.status_var.set(str(payload))
                    self._refresh_gto_pending_queue()
                    self.after(100, self._resume_waiting_gto_tables)
                    if (isinstance(payload, dict) and payload.get("loaded_tree")
                            and self.auto_collect_enabled_var.get()):
                        self.after(350, self._start_auto_analysis)
                elif kind == "auto_gto_connect_retry":
                    self._gto_auto_connect_busy = False
                    details = payload if isinstance(payload, dict) else {}
                    attempt = int(details.get("attempt", 0))
                    error = str(details.get("error", "GTO+ socket is not ready"))
                    if attempt < 9:
                        self.status_var.set(f"GTO+接続待機中… ({attempt + 2}/10)")
                        self.after(1800, lambda n=attempt + 1: self._auto_connect_gto_plus(n))
                    else:
                        self.status_var.set(f"GTO+自動接続失敗: {error}")
                elif kind == "tree_loaded":
                    details = payload if isinstance(payload, dict) else {}
                    self.status_var.set(
                        f"GTO+解析済みツリーをロード。ライブラリ {details.get('library_count', len(self.tree_files))} 本"
                    )
                    self.after(100, self._resume_waiting_gto_tables)
                    if self.auto_collect_enabled_var.get():
                        self.after(350, self._start_auto_analysis)
                elif kind == "auto_scan_progress":
                    tree_name = Path(payload.get("tree_file", "GTO+ tree")).name
                    status = payload.get("status", "running")
                    self.auto_scan_status_var.set(
                        f"{tree_name}: {payload.get('nodes_scanned', 0):,} nodes / "
                        f"{payload.get('strategies_saved', 0):,} combos saved / "
                        f"{payload.get('pending', 0):,} branches pending ({status})"
                    )
                    if int(payload.get("nodes_scanned", 0)) % 20 == 0:
                        self.db_count_var.set(f"保存済み戦略: {self._count_cached_strategies()} combos")
                elif kind == "auto_scan_done":
                    results = payload.get("results", []) if isinstance(payload, dict) else []
                    completed = sum(1 for row in results if row.get("status") in {"complete", "already_complete"})
                    paused = sum(1 for row in results if row.get("status") == "paused")
                    errors = [row for row in results if row.get("status") == "error"]
                    total_nodes = sum(int(row.get("nodes_scanned", 0)) for row in results)
                    total_strategies = sum(int(row.get("strategies_saved", 0)) for row in results)
                    if errors:
                        self.auto_scan_status_var.set(
                            f"自動収集エラー: {errors[0].get('last_error', 'unknown error')}"
                        )
                    elif payload.get("cancelled") or paused:
                        self.auto_scan_status_var.set(
                            f"一時停止: {total_nodes:,} nodes / {total_strategies:,} combos。次回は保存地点から再開します。"
                        )
                    else:
                        self.auto_scan_status_var.set(
                            f"完了: {completed}/{len(results)} trees • {total_nodes:,} nodes • {total_strategies:,} combos保存"
                        )
                    self.status_var.set("GTO+自動収集が終了しました")
                    self.db_count_var.set(f"保存済み戦略: {self._count_cached_strategies()} combos")
                    self._refresh_gto_coverage()
                    self._refresh_gto_pending_queue()
                elif kind == "node_imported":
                    self._show_node_context(payload)
                    self._refresh_gto_coverage()
                    self.import_status.set(f"{payload['imported_hands']} combos をSQLiteへ保存。Board: {' '.join(payload['node']['board'])} / To act: {payload['node']['next_to_act'].upper()}")
                    self.status_var.set("GTO+ current node imported into Pigeon cache")
                    self.after(100, self._resume_waiting_gto_tables)
                    self._refresh_gto_pending_queue()
                elif kind == "practice_node":
                    self._show_node_context(payload["context"])
                    dealt = payload.get("dealt", {})
                    self.cpu_last_action.set(
                        f"GTO+ range deal complete. Your hand: {dealt.get('human', '—')}\n"
                        "CPU acts automatically from GTO+ mixed frequencies; each visited node is cached."
                    )
                    self.status_var.set("GTO+ powered match running — CPU has no action deadline")
                elif kind == "practice_update":
                    actions = payload.get("actions", [])
                    summary = "\n".join(f"CPU {a['hand']} ({a['player'].upper()}) → {a['action']}" for a in actions) or "No CPU action was needed."
                    if payload.get("context"):
                        self._show_node_context(payload["context"])
                    elif payload.get("error"):
                        self.hand_finished = True
                        self._render_practice_actions()
                        self.node_var.set("GTO+ tree reached a terminal or unsupported leaf")
                        self._set_node_text("Last CPU action:\n" + summary + "\n\nNode read: " + payload["error"])
                    self.cpu_last_action.set(summary)
                    self.status_var.set("GTO+ CPU chain finished")
                elif kind == "human_advanced":
                    self._show_node_context(payload["context"])
                    self.cpu_last_action.set(f"Human selected {payload['moved']['action']}. GTO+ tree advanced.")
                    self.status_var.set("Human action accepted by GTO+ tree")
                elif kind == "hand_terminal":
                    self.hand_finished = True
                    self._render_practice_actions()
                    self._draw_table()
                    self.cpu_last_action.set(f"Hand reached a terminal GTO+ node after: {payload['moved']['action']}")
                    self.node_var.set("GTO+ tree reached a terminal node")
                    self._set_node_text("The hand is complete in the loaded GTO+ tree.\nStart another match from the root to play again.")
                    self.status_var.set("GTO+ hand complete — visited nodes were cached")
                elif kind == "cpu_advanced":
                    result = payload["result"]
                    mix_text = "  •  ".join(f"{m['action']}: {m['frequency']*100:.1f}%" for m in result["mix"])
                    self.cpu_last_action.set(f"CPU {result['hand']} ({result['player'].upper()}) → {result['action']}\n{mix_text}")
                    if payload.get("context"):
                        self._show_node_context(payload["context"])
                    else:
                        self.hand_finished = True
                        self._render_practice_actions()
                        self.node_var.set("GTO+ tree may have reached a terminal leaf")
                    self.status_var.set("CPU selected an action from GTO+ and advanced the same tree")
                    self.db_count_var.set(f"保存済み戦略: {self._count_cached_strategies()} combos")
                elif kind == "history_allin_ev_done":
                    if hasattr(self, "history_tree") and self.pages.get("poker_craft") is not None:
                        if self.pages["poker_craft"].winfo_ismapped():
                            self._refresh_pokercraft()
                elif kind == "history_allin_ev_error":
                    self.cash_log_lines.append(f"All-in EV calculation error: {payload}")
                elif kind == "sound_error":
                    notice = f"AUDIO OUTPUT ERROR: {payload}"
                    self.cash_action_feed = notice
                    self.status_var.set(notice)
                    self._refresh_table_windows()
                elif kind == "error":
                    self.status_var.set("接続 / 解析エラー")
                    self.import_status.set(str(payload))
                    messagebox.showerror("Pigeon Poker", str(payload))
        except queue.Empty:
            pass
        # Resume requests made on another table while a CPU calculation was
        # in-flight are retried by their own timer and never silently discarded.
        for table_id, state_slot in ((slot.table_id, slot) for slot in self.multi_tables.list()):
            if state_slot.state.get("cash_resume_requested") and not self.cash_busy:
                pending = self.table_resume_retry_jobs.pop(table_id, None)
                if pending:
                    try:
                        self.after_cancel(pending)
                    except tk.TclError:
                        pass
                state_slot.state["cash_resume_requested"] = False
                self._resume_cash_table(table_id)
                break
        try:
            if self.winfo_exists():
                self._job_drain_after_id = self.after(120, self._drain_jobs)
        except tk.TclError:
            self._job_drain_after_id = None

    def destroy(self):
        """Cancel table, squeeze and worker callbacks before destroying Tk."""
        if getattr(self, "_pigeon_destroying", False):
            return
        self._pigeon_destroying = True
        cashier_refresh = getattr(self, "_study_cashier_refresh_id", None)
        if cashier_refresh:
            try:
                self.after_cancel(cashier_refresh)
            except tk.TclError:
                pass
            self._study_cashier_refresh_id = None
        sound_stop = getattr(self, "sound_worker_stop", None)
        if sound_stop is not None:
            sound_stop.set()
            sound_queue = getattr(self, "sound_queue", None)
            if sound_queue is not None:
                try:
                    sound_queue.put_nowait(None)
                except queue.Full:
                    try:
                        sound_queue.get_nowait()
                        sound_queue.put_nowait(None)
                    except (queue.Empty, queue.Full):
                        pass
        voice_stop = getattr(self, "action_voice_stop", None)
        if voice_stop is not None:
            voice_stop.set()
            voice_queue = getattr(self, "action_voice_queue", None)
            if voice_queue is not None:
                try:
                    voice_queue.put_nowait(None)
                except queue.Full:
                    try:
                        voice_queue.get_nowait()
                        voice_queue.put_nowait(None)
                    except (queue.Empty, queue.Full):
                        pass
        voice_worker = getattr(self, "action_voice_worker", None)
        if voice_worker is not None and voice_worker.is_alive():
            voice_worker.join(timeout=0.25)
        sound_worker = getattr(self, "sound_worker", None)
        if sound_worker is not None and sound_worker.is_alive():
            sound_worker.join(timeout=0.25)
        after_id = getattr(self, "_job_drain_after_id", None)
        if after_id:
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
            self._job_drain_after_id = None

        # Stop background CPU workers so they cannot enqueue follow-up work
        # against windows that are being destroyed.
        for cancel_event in list(getattr(self, "cash_cpu_cancel_events", {}).values()):
            try:
                cancel_event.set()
            except Exception:
                pass

        # Signal any thread waiting for a board animation before removing jobs.
        for job in list(getattr(self, "board_animation_jobs", {}).values()):
            ready = job.get("ready_event") if isinstance(job, dict) else None
            if ready:
                try:
                    ready.set()
                except Exception:
                    pass

        # Close all squeeze popups first, then table windows (which cancel their
        # own deadline / flip / board-squeeze timers).
        for table_id, popup in list(getattr(self, "squeeze_popups", {}).items()):
            try:
                popup["window"].destroy()
            except (tk.TclError, KeyError, TypeError):
                pass
        self.squeeze_popups.clear()
        for table_id in list(getattr(self, "table_windows", {}).keys()):
            try:
                self._destroy_table_window(table_id)
            except Exception:
                pass

        # Also cancel timers for a table whose floating window was already
        # closed, but whose state is still being removed from the lobby.
        for mapping_name in ("squeeze_deadline_jobs", "board_squeeze_auto_jobs", "hole_flip_jobs"):
            mapping = getattr(self, mapping_name, {})
            for table_id, pending in list(mapping.items()):
                try:
                    self.after_cancel(pending)
                except tk.TclError:
                    pass
                mapping.pop(table_id, None)
        self.deal_animation_jobs.clear()
        self.board_animation_jobs.clear()
        self.cash_cpu_cancel_events.clear()
        try:
            super().destroy()
        except tk.TclError:
            pass

    @staticmethod
    def _format_node(node, line, pot_stacks):
        lines = ["BOARD: " + " ".join(node["board"]),
                 "NEXT TO ACT: " + node["next_to_act"].upper(),
                 f"POT: {pot_stacks['pot']:.3f}",
                 f"OOP STACK: {pot_stacks['oop_stack']:.3f}",
                 f"IP STACK: {pot_stacks['ip_stack']:.3f}",
                 "LINE: " + (" / ".join(line) if line else "ROOT"),
                 "ACTIONS: " + ", ".join(node["actions"]),
                 "", "COMBOS AVAILABLE: " + str(len(node.get(node["next_to_act"], {})))]
        return "\n".join(lines)

    def _on_close(self):
        self._sync_external_wallet_balance()
        self.auto_scan_cancel_event.set()
        # Return all active cash-table stacks to the common simulated wallet.
        try:
            self._save_active_cash_slot()
            for slot in self.multi_tables.list():
                state = slot.state
                table = state.get("cash_table")
                if table is None or state.get("cash_gto_spot_mode"):
                    continue
                table.sync_external_hand_state()
                hero = next((seat for seat in table.seats if seat["id"] == "hero"), None)
                if hero:
                    cash_out = max(0, int(hero["stack"]))
                    self.cash_balance_cents += cash_out
                    if cash_out:
                        self.cashier_ledger.record(
                            "cash-out", cash_out, self.cash_balance_cents,
                            note=f"{slot.rate} application shutdown cash-out"
                        )
            self._update_cash_balance()
            self.wallet_store.set_live_poker_stack(0)
            self.config_data["balance"] = self.cash_balance_cents / 100
            save_config(self.config_data)
        except Exception:
            pass
        try:
            self.integration.stop(detach=True, terminate=False)
        except Exception:
            pass
        owned_pid = int(getattr(self, "gto_owned_process_pid", 0) or 0)
        if owned_pid > 0 and os.name == "nt" and not self._gto_handoff_in_progress:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(owned_pid), "/T", "/F"],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                pass
        self.destroy()


def main():
    dock_pid = None
    if len(sys.argv) >= 3 and sys.argv[1] == "--dock-gto-pid":
        try:
            dock_pid = int(sys.argv[2])
        except ValueError:
            dock_pid = None
    app = PigeonPokerApp()
    if dock_pid is not None and dock_pid > 0:
        app._gto_auto_start_started = True
        app.after(900, lambda pid=dock_pid: app._attach_existing_gto(pid))
    app.mainloop()


if __name__ == "__main__":
    main()
