from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "source_1_3_101"
sys.path.insert(0, str(SOURCE))

from pigeon_poker.preflop_cleanup import cleanup_retired_preflop_modules


def test_cleanup_removes_only_retired_preflop_code_and_cache_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        package = root / "pigeon_poker"
        cache = package / "__pycache__"
        cache.mkdir(parents=True)

        legacy_names = (
            "preflop_screenshot_ranges.py",
            "preflop_screenshot_ranges_75.py",
            "preflop_range_policy.py",
            "preflop_range_data.py",
            "preflop_range_data_legacy.py",
            "preflop-screenshot-module.part-000",
        )
        for name in legacy_names:
            (package / name).write_text("# retired\n", encoding="utf-8")
        (cache / "preflop_screenshot_ranges.cpython-312.pyc").write_bytes(b"old-cache")
        (package / "preflop_gto_strategy.py").write_text("VALUE = 1\n", encoding="utf-8")
        (package / "poker_reasoning.py").write_text("VALUE = 2\n", encoding="utf-8")
        (package / "strategy.sqlite3").write_bytes(b"USER STRATEGY DATA")
        (root / "pigeon_config.json").write_text('{"keep": true}\n', encoding="utf-8")

        removed = cleanup_retired_preflop_modules(root)
        assert len(removed) == len(legacy_names) + 1
        assert all(not (package / name).exists() for name in legacy_names)
        assert not (cache / "preflop_screenshot_ranges.cpython-312.pyc").exists()
        assert (package / "preflop_gto_strategy.py").is_file()
        assert (package / "poker_reasoning.py").is_file()
        assert (package / "strategy.sqlite3").read_bytes() == b"USER STRATEGY DATA"
        assert (root / "pigeon_config.json").is_file()
        assert cleanup_retired_preflop_modules(root) == ()


if __name__ == "__main__":
    test_cleanup_removes_only_retired_preflop_code_and_cache_files()
    print("PASS retired-preflop cleanup isolation")
