from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path


def patch_main(app_root: Path) -> None:
    main_path = app_root / "PigeonPoker.pyw"
    main = main_path.read_text(encoding="utf-8")

    method = r'''    def _run_auto_solve_ui_probe(self):
        """Read-only calibration of the exact embedded GTO+ range/Build Tree dialogs."""
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
        self.status_var.set("未知局面Solve用のGTO+画面を安全確認中…（レンジ・設定は変更しません）")

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
                self.after(0, lambda: finish(success, report, detail, completed.returncode))
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                self.after(0, lambda: finish(False, None, detail, -1))

        def finish(success, report, detail, return_code):
            self._gto_ui_diagnostic_running = False
            if success and report is not None:
                self.status_var.set("GTO+画面診断完了（設定変更・Tree構築・Solver実行なし）")
                try:
                    os.startfile(str(output_dir))
                except Exception:
                    pass
            else:
                self.status_var.set("GTO+画面診断は安全停止しました。設定やレンジは変更していません。")
                messagebox.showwarning(
                    "GTO+ auto-solve probe",
                    "診断は完了条件に届かず安全停止しました。GTO+の設定変更やSolver実行はしていません。\n\n"
                    + (detail[-3000:] if detail else f"Exit code: {return_code}")
                    + "\n\n診断フォルダ: " + str(output_dir),
                    parent=self,
                )
                try:
                    os.startfile(str(output_dir))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True, name="PigeonGTOAutoSolveUIProbe").start()

'''
    anchor = "    def _run_gto_ui_diagnostic("
    if main.count(anchor) != 1:
        raise SystemExit("Could not uniquely locate GTO UI diagnostic method")
    if "def _run_auto_solve_ui_probe" not in main:
        main = main.replace(anchor, method + anchor, 1)

    button_anchor = '''        ttk.Button(auto, text="AUTO COLLECT ALL NODES", style="Accent.TButton",
                   command=self._start_auto_analysis).pack(fill="x")
'''
    button_add = button_anchor + '''        ttk.Button(auto, text="未知HU局面の自動Solve設定を診断（変更なし）",
                   command=self._run_auto_solve_ui_probe).pack(fill="x", pady=(5, 0))
        tk.Label(auto, text="GTO+のOOPレンジ編集画面とBuild Tree設定画面を開いて撮影し、Escapeで閉じます。文字入力・レンジ確定・Board/Pot/Stack/Rake変更・Tree構築・Solver実行は行いません。",
                 bg=COLORS["panel"], fg=COLORS["muted"], wraplength=300,
                 justify="left", font=("Segoe UI", 8)).pack(anchor="w", pady=(3, 0))
'''
    if main.count(button_anchor) != 1:
        raise SystemExit("Could not uniquely locate AUTO COLLECT button")
    if "未知HU局面の自動Solve設定を診断（変更なし）" not in main:
        main = main.replace(button_anchor, button_add, 1)

    ast.parse(main, filename="PigeonPoker.pyw")
    main_path.write_text(main, encoding="utf-8", newline="\n")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_auto_solve_ui_integration.py APP_ROOT UI_PROBE_SOURCE")
    app_root = Path(sys.argv[1])
    ui_probe_source = Path(sys.argv[2])
    patch_main(app_root)
    target = app_root / "pigeon_gto_plus" / "auto_solve_ui.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ui_probe_source, target)
    ast.parse(target.read_text(encoding="utf-8"), filename="pigeon_gto_plus/auto_solve_ui.py")
    print("Integrated safe GTO+ setup probe button and module.")


if __name__ == "__main__":
    main()
