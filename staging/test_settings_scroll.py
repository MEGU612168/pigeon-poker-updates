from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"
SOURCE_TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE_TEXT, filename=str(SOURCE))


def method_text(name: str) -> str:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SOURCE_TEXT, node) or ""
    raise AssertionError(f"Missing method: {name}")


def test_settings_left_column_has_its_own_scroll_canvas() -> None:
    settings = method_text("_build_settings_page")
    assert 'left_shell.pack_propagate(False)' in settings
    assert 'left_canvas = tk.Canvas(' in settings
    assert 'left_scrollbar = ttk.Scrollbar(' in settings
    assert 'left_canvas.create_window(' in settings
    assert 'left_canvas.configure(scrollregion=left_canvas.bbox("all"))' in settings
    assert 'self.nested_page_scroll_canvases.add(left_canvas)' in settings


def test_sound_volume_controls_are_inside_scrollable_left_column() -> None:
    settings = method_text("_build_settings_page")
    left_start = settings.index('left = tk.Frame(left_canvas')
    right_start = settings.index('right = tk.Frame(body')
    sound_start = settings.index('sound_box, sound = self._panel(left, "SOUND")')
    sound_end = settings.index('hud_box, hud = self._panel(left, "TABLE HUD FIELDS")')
    assert left_start < sound_start < sound_end < right_start
    assert 'text="効果音音量 / EFFECT VOLUME"' in settings
    assert 'volume_scale = ttk.Scale(' in settings
    assert 'group_scale = ttk.Scale(' in settings


def test_mouse_wheel_routes_to_nested_page_canvas() -> None:
    scroll = method_text("_scroll_active_page")
    assert 'if current in self.nested_page_scroll_canvases:' in scroll
    assert 'target = current' in scroll
    assert 'target.yview_scroll(units, "units")' in scroll


if __name__ == "__main__":
    tests = [
        test_settings_left_column_has_its_own_scroll_canvas,
        test_sound_volume_controls_are_inside_scrollable_left_column,
        test_mouse_wheel_routes_to_nested_page_canvas,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "settings scroll tests")
