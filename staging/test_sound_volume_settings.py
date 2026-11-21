from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).with_name("source_1_3_101") / "PigeonPoker.pyw"
SOURCE_TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE_TEXT, filename=str(SOURCE))


def method(name: str) -> ast.FunctionDef:
    for node in ast.walk(TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Missing method: {name}")


def method_text(name: str) -> str:
    return ast.get_source_segment(SOURCE_TEXT, method(name)) or ""


def test_effect_volume_has_a_clear_percent_slider_and_preview() -> None:
    settings = method_text("_build_settings_page")
    assert "効果音音量 / EFFECT VOLUME" in settings
    assert "sound_volume_percent_var" in settings
    assert "_on_sound_master_volume_change" in settings
    assert "_preview_master_sound_volume" in settings
    assert "0% = mute" in settings
    assert 'volume_scale.bind(' in settings


def test_master_and_group_sliders_auto_save_after_adjustment() -> None:
    settings = method_text("_build_settings_page")
    assert 'volume_scale.bind(' in settings
    assert 'group_scale.bind(' in settings
    assert '"<ButtonRelease-1>"' in settings
    assert "self._save_sound_settings()" in settings
    assert "SOUND_GROUP_LABELS.items()" in settings


def test_volume_is_clamped_and_saved_persistently() -> None:
    change = method_text("_on_sound_master_volume_change")
    save = method_text("_save_sound_settings")
    assert "max(0, min(100" in change
    assert 'label.set(f"{level}%")' in change
    assert "self.sound_volume = max(0, min(100" in save
    assert 'self.config_data["sound_volume"] = self.sound_volume' in save
    assert 'self.config_data["sound_group_volumes"]' in save
    assert "save_config(self.config_data)" in save


def test_preview_uses_pending_values_and_restores_runtime_settings() -> None:
    preview = method_text("_preview_master_sound_volume")
    assert "self.sound_volume = max(0, min(100" in preview
    assert "self.sound_group_levels = {" in preview
    assert 'self._play_sound("your_turn")' in preview
    assert "finally:" in preview
    assert "self.sound_volume = old_volume" in preview
    assert "self.sound_group_levels = old_groups" in preview
    assert "save_config" not in preview




def test_windows_action_voice_uses_parallel_speech_instances() -> None:
    worker = method_text("_action_voice_worker_loop")
    assert 'if sys.platform.startswith("win"):' in worker
    assert "$sp=New-Object System.Speech.Synthesis.SpeechSynthesizer" in worker
    assert "$sp.SpeakAsync($p[1])" in worker
    assert "$sp.add_SpeakCompleted(" in worker
    assert "$s.SpeakAsync($p[1])" not in worker



def test_card_deal_default_is_quieter_and_fallback_respects_volume() -> None:
    assert 'self.config_data.get("sound_volume", 50)' in SOURCE_TEXT
    play_sound = method_text("_play_sound")
    assert '0.45 if key not in {"deal", "card_land"} else 0.15' in play_sound

    attenuate = method_text("_attenuated_wav_file")
    assert "factor = level / 1000.0" in attenuate
    assert "writeframes(attenuated)" in attenuate

    playback = method_text("_play_wav_nonblocking")
    assert "volume_set == 0" in playback
    assert "self._attenuated_wav_file(sound_path, volume)" in playback
    assert "winsound.PlaySound(str(fallback_path)" in playback

if __name__ == "__main__":
    tests = [
        test_effect_volume_has_a_clear_percent_slider_and_preview,
        test_master_and_group_sliders_auto_save_after_adjustment,
        test_volume_is_clamped_and_saved_persistently,
        test_preview_uses_pending_values_and_restores_runtime_settings,
        test_windows_action_voice_uses_parallel_speech_instances,
        test_card_deal_default_is_quieter_and_fallback_respects_volume,
    ]
    for test_case in tests:
        test_case()
        print("PASS", test_case.__name__)
    print("ALL PASS", len(tests), "sound volume tests")
