from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DIR = Path(__file__).with_name("source_1_3_101")
sys.path.insert(0, str(SOURCE_DIR))

from pigeon_poker.range_image_catalog import create_range_photo, range_catalog_summary  # noqa: E402


def _rgb(value):
    if isinstance(value, (tuple, list)):
        return tuple(int(part) for part in value[:3])
    if isinstance(value, str):
        parts = value.replace("{", "").replace("}", "").split()
        if len(parts) >= 3:
            return tuple(int(part) for part in parts[:3])
    raise AssertionError(f"Unsupported Tk PhotoImage.get() pixel value: {value!r}")


def main():
    if sys.platform != "win32":
        raise SystemExit("This test must run on Windows to exercise the native Windows Tk decoder.")

    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    summary = range_catalog_summary()
    assert summary["source_image_count"] == 174
    assert summary["scenario_count"] == 174

    failures = []
    try:
        for source_id in range(128, 302):
            image = create_range_photo(root, source_id)
            if (image.width(), image.height()) != (546, 354):
                failures.append((source_id, "unexpected dimensions", image.width(), image.height()))
                image = None
                continue

            colours = set()
            nonblack = 0
            # Sample a 25x17 grid through Tk itself, after PhotoImage has
            # decoded the PPM payload and applied the same half-size scaling
            # used by the app's live paid-range window.
            for yi in range(17):
                y = min(image.height() - 1, yi * (image.height() - 1) // 16)
                for xi in range(25):
                    x = min(image.width() - 1, xi * (image.width() - 1) // 24)
                    rgb = _rgb(image.get(x, y))
                    colours.add(rgb)
                    if rgb != (0, 0, 0):
                        nonblack += 1
            if nonblack == 0 or len(colours) < 2:
                failures.append((source_id, "black/blank after native Tk decode", nonblack, len(colours)))
            if source_id == 136 and (nonblack == 0 or len(colours) < 2):
                failures.append((source_id, "user-reported range #136 is blank", nonblack, len(colours)))
            image = None
            root.update_idletasks()
    finally:
        root.destroy()

    if failures:
        raise AssertionError(f"Native Windows Tk failed to render {len(failures)} / 174 images: {failures}")
    print("PASS: native Windows Tk decoded all 174 PPM range images; range #136 included")


if __name__ == "__main__":
    main()
