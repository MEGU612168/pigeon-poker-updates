"""Remove the standalone GTO+ ENGINE feature without touching preflop policy."""
from __future__ import annotations

def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected exactly one match, found {count}")
    return source.replace(old, new, 1)

def remove_engine(main_source: str) -> str:
    source = main_source
    source = _replace_once(source,
        'nav = [("LOBBY", "lobby"), ("OPEN TABLES", "table"), ("CASHIER", "cashier"), ("GTO+ ENGINE", "gto"), ("POKERCRAFT", "poker_craft"), ("GG CARE", "gg_care"), ("SETTINGS", "settings")]',
        'nav = [("LOBBY", "lobby"), ("OPEN TABLES", "table"), ("CASHIER", "cashier"), ("POKERCRAFT", "poker_craft"), ("GG CARE", "gg_care"), ("SETTINGS", "settings")]',
        "remove GTO+ ENGINE navigation")
    source = _replace_once(source,
        '        tk.Label(self.sidebar, text="GTO+ exact HU postflop\\n20s hero action clock", bg="#0d1726", fg=COLORS["green"], justify="left", font=("Segoe UI", 8, "bold")).pack(side="bottom", anchor="w", padx=16, pady=18)\n',
        "", "remove GTO+ sidebar status")
    source = _replace_once(source, "        self._build_gto_page()\n", "", "remove GTO+ page construction")
    source = _replace_once(source, '        self.show_page("gto")\n', '        self.show_page("lobby")\n', "open lobby by default")
    source = _replace_once(source, "        self.after(1200, self._auto_start_gto_plus)\n", "",
                           "disable automatic GTO+ launch")
    # The separate solver bridge must not be a prerequisite for ordinary CPU turns.
    source = _replace_once(source,
        "        gto_supported = is_gto_plus_supported_postflop_hand(hand)\n",
        "        gto_supported = False  # GTO+ ENGINE removed; use local CPU policy on every street.\n",
        "route all postflop decisions to local CPU")
    source = _replace_once(source, '        self.cash_gto_session = state.get("cash_gto_session")\n',
        "        self.cash_gto_session = None  # Discard legacy GTO+ sessions after engine removal.\n",
        "discard saved GTO+ sessions")
    source = _replace_once(source, '        self.cash_gto_spot_mode = bool(state.get("cash_gto_spot_mode", False))\n',
        "        self.cash_gto_spot_mode = False  # GTO+ spot mode is no longer available.\n",
        "disable saved GTO+ spot mode")
    source = _replace_once(source, '        self.cash_syncing_gto = bool(state.get("cash_syncing_gto", False))\n',
        "        self.cash_syncing_gto = False\n", "clear legacy GTO+ sync state")
    source = source.replace('self.show_page("gto")', 'self.show_page("lobby")')
    return source

def validate_removed_engine(main_source: str) -> None:
    checks = {
        "no GTO+ ENGINE menu": '"GTO+ ENGINE"' not in main_source,
        "no GTO+ page builder call": "self._build_gto_page()" not in main_source,
        "no GTO+ page selected at startup": 'self.show_page("gto")' not in main_source,
        "no automatic GTO+ launch": "self.after(1200, self._auto_start_gto_plus)" not in main_source,
        "postflop no longer requires a GTO+ tree": "gto_supported = False  # GTO+ ENGINE removed" in main_source,
        "legacy GTO+ session discarded": "self.cash_gto_session = None  # Discard legacy GTO+ sessions" in main_source,
    }
    failures = [name for name, ok in checks.items() if not ok]
    if failures:
        raise AssertionError("GTO+ removal checks failed: " + ", ".join(failures))
    if main_source.count("from pigeon_poker.preflop_screenshot_ranges import choose_preflop_action") != 1:
        raise AssertionError("Preflop policy import was changed.")
    if main_source.count("range_decision = choose_preflop_action(") != 1:
        raise AssertionError("Live CPU preflop decision hook was changed.")
