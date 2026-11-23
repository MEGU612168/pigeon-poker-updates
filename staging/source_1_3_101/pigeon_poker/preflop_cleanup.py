from __future__ import annotations

from pathlib import Path


_LEGACY_PREFIXES = (
    "preflop_screenshot_ranges",
    "preflop_range_policy",
    "preflop_range_data",
    "preflop_gto_strategy",
    "preflop-screenshot-module.part-",
)


def cleanup_retired_preflop_modules(app_root: Path | None = None) -> tuple[str, ...]:
    """Remove only retired preflop source fragments from the app's package folder.

    User databases, saved hands, wallet files, configuration and replacement
    policy files are outside this cleanup scope.
    The operation is idempotent and confined to pigeon_poker/ and its __pycache__.
    """
    root = Path(app_root).resolve() if app_root is not None else Path(__file__).resolve().parent.parent
    package_dir = (root / "pigeon_poker").resolve()
    if not package_dir.is_dir() or not package_dir.is_relative_to(root):
        return ()

    targets: set[Path] = set()
    try:
        for item in package_dir.iterdir():
            if item.is_file() and item.name.startswith(_LEGACY_PREFIXES):
                if item.suffix.lower() in {".py", ".part"} or ".part-" in item.name:
                    targets.add(item)

        cache_dir = package_dir / "__pycache__"
        if cache_dir.is_dir():
            for item in cache_dir.iterdir():
                if item.is_file() and item.suffix.lower() == ".pyc":
                    if item.name.startswith(_LEGACY_PREFIXES):
                        targets.add(item)
    except OSError:
        return ()

    removed: list[str] = []
    for target in sorted(targets):
        try:
            target.unlink()
            removed.append(target.relative_to(root).as_posix())
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return tuple(removed)
