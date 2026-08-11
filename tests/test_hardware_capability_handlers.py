"""
tests/test_hardware_capability_handlers.py

Coverage for four small, genuinely-implemented capability handlers that had
zero unit tests despite driving real hardware (pyautogui keypresses,
screenshots, typing) or real system state (PowerShell/registry via
subprocess): window_manager.py (10%), dictation.py (12%), media_control.py
(20%), sys_utility.py (49%).

These were verified NOT to be the fabricated-success stubs fixed earlier in
24aad7f - they genuinely call pyautogui/subprocess and already fail honestly
on error. The gap here is pure test coverage, not a correctness defect (with
one exception noted below on media_control's missing fallback).

Mocks pyautogui/subprocess at each module's own import (not globally), and
agentic_core.processor._get_routing_llm at its source - these handlers do
`from agentic_core.processor import _get_routing_llm` INSIDE the function
body, so patching the source before the call executes is what actually
intercepts it (patching the handler module's own namespace would miss a
not-yet-executed local import).
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from capabilities.system.dictation import handle_dictation
from capabilities.system.media_control import handle_media_control
from capabilities.system.sys_utility import handle_sys_utility
from capabilities.system.window_manager import handle_window_management


def _llm_returning(text):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=text)
    return llm


# ══════════════════════════════════════════════════════════════════════════════
# window_manager.py
# ══════════════════════════════════════════════════════════════════════════════
class TestWindowManagement:
    def test_empty_input_is_handled_without_calling_llm(self):
        assert "couldn't understand" in handle_window_management("", "").lower()

    @patch("capabilities.system.window_manager.pyautogui")
    @patch("agentic_core.processor._get_routing_llm")
    def test_screenshot_action_saves_to_desktop(self, mock_get_llm, mock_pyautogui):
        mock_get_llm.return_value = _llm_returning("screenshot")
        result = handle_window_management("", "take a screenshot")
        mock_pyautogui.screenshot.assert_called_once()
        saved_path = mock_pyautogui.screenshot.call_args[0][0]
        assert "SentinAL_Screenshot_" in saved_path
        assert saved_path.endswith(".png")
        assert not result.startswith("ERROR")

    @pytest.mark.parametrize(("action", "expected_keys"), [
        ("minimize_all", ("win", "d")),
        ("snap_left", ("win", "left")),
        ("snap_right", ("win", "right")),
        ("maximize", ("win", "up")),
        ("switch_desktop", ("win", "ctrl", "right")),
    ])
    @patch("capabilities.system.window_manager.pyautogui")
    @patch("agentic_core.processor._get_routing_llm")
    def test_hotkey_actions_press_the_right_keys(self, mock_get_llm, mock_pyautogui, action, expected_keys):
        mock_get_llm.return_value = _llm_returning(action)
        handle_window_management("", f"do {action}")
        mock_pyautogui.hotkey.assert_called_once_with(*expected_keys)

    @patch("capabilities.system.window_manager.pyautogui")
    @patch("agentic_core.processor._get_routing_llm", side_effect=Exception("LLM down"))
    def test_llm_failure_falls_back_to_screenshot_keyword_match(self, mock_get_llm, mock_pyautogui):
        handle_window_management("", "please take a screenshot for me")
        mock_pyautogui.screenshot.assert_called_once()

    @patch("capabilities.system.window_manager.pyautogui")
    @patch("agentic_core.processor._get_routing_llm", side_effect=Exception("LLM down"))
    def test_llm_failure_without_screenshot_keyword_is_unknown(self, mock_get_llm, mock_pyautogui):
        result = handle_window_management("", "do something with the window")
        mock_pyautogui.screenshot.assert_not_called()
        mock_pyautogui.hotkey.assert_not_called()
        assert "don't know how to physically execute" in result

    @patch("agentic_core.processor._get_routing_llm")
    def test_unrecognized_classified_action_reports_honestly(self, mock_get_llm):
        mock_get_llm.return_value = _llm_returning("levitate_window")
        result = handle_window_management("", "make it float")
        assert "don't know how to physically execute" in result
        assert "levitate_window" in result

    @patch("capabilities.system.window_manager.pyautogui")
    @patch("agentic_core.processor._get_routing_llm")
    def test_pyautogui_failure_is_reported_not_raised(self, mock_get_llm, mock_pyautogui):
        mock_get_llm.return_value = _llm_returning("maximize")
        mock_pyautogui.hotkey.side_effect = Exception("no active window")
        result = handle_window_management("", "maximize this")
        assert "Failed to execute window action" in result


# ══════════════════════════════════════════════════════════════════════════════
# dictation.py
# ══════════════════════════════════════════════════════════════════════════════
class TestDictation:
    def test_empty_input_is_handled_without_calling_llm(self):
        assert "didn't hear anything" in handle_dictation("", "").lower()

    @patch("capabilities.system.dictation.time.sleep")
    @patch("capabilities.system.dictation.pyautogui")
    @patch("agentic_core.processor._get_routing_llm")
    def test_extracted_payload_is_typed_via_pyautogui(self, mock_get_llm, mock_pyautogui, mock_sleep):
        mock_get_llm.return_value = _llm_returning("hello world")
        result = handle_dictation("", "start dictation hello world")
        mock_pyautogui.write.assert_called_once_with("hello world", interval=0.01)
        assert not result.startswith("ERROR")
        assert "typed" in result.lower()

    @patch("capabilities.system.dictation.time.sleep")
    @patch("capabilities.system.dictation.pyautogui")
    @patch("agentic_core.processor._get_routing_llm", side_effect=Exception("LLM down"))
    def test_llm_failure_falls_back_to_prefix_stripping(self, mock_get_llm, mock_pyautogui, mock_sleep):
        handle_dictation("", "start dictation buy milk tomorrow")
        mock_pyautogui.write.assert_called_once_with("buy milk tomorrow", interval=0.01)

    @patch("agentic_core.processor._get_routing_llm")
    def test_empty_extracted_payload_reports_honestly(self, mock_get_llm):
        mock_get_llm.return_value = _llm_returning("")
        result = handle_dictation("", "start dictation")
        assert "empty dictation payload" in result

    @patch("capabilities.system.dictation.time.sleep")
    @patch("capabilities.system.dictation.pyautogui")
    @patch("agentic_core.processor._get_routing_llm")
    def test_typing_failure_is_reported_not_raised(self, mock_get_llm, mock_pyautogui, mock_sleep):
        mock_get_llm.return_value = _llm_returning("hello")
        mock_pyautogui.write.side_effect = Exception("keyboard driver error")
        result = handle_dictation("", "type hello")
        assert "Failed to simulate typing" in result


# ══════════════════════════════════════════════════════════════════════════════
# media_control.py
# ══════════════════════════════════════════════════════════════════════════════
class TestMediaControl:
    def test_empty_input_is_handled_without_calling_llm(self):
        assert "couldn't understand" in handle_media_control("", "").lower()

    @patch("capabilities.system.media_control.pyautogui")
    @patch("agentic_core.processor._get_routing_llm")
    def test_volume_actions_press_five_times_for_a_noticeable_change(self, mock_get_llm, mock_pyautogui):
        mock_get_llm.return_value = _llm_returning("volumeup")
        handle_media_control("", "turn it up")
        mock_pyautogui.press.assert_called_once_with("volumeup", presses=5)

    @pytest.mark.parametrize("action", ["playpause", "nexttrack", "prevtrack", "volumemute"])
    @patch("capabilities.system.media_control.pyautogui")
    @patch("agentic_core.processor._get_routing_llm")
    def test_single_press_actions_press_once(self, mock_get_llm, mock_pyautogui, action):
        mock_get_llm.return_value = _llm_returning(action)
        handle_media_control("", f"do {action}")
        mock_pyautogui.press.assert_called_once_with(action)

    @patch("agentic_core.processor._get_routing_llm", side_effect=Exception("LLM down"))
    def test_llm_failure_reports_error_with_no_fallback(self, mock_get_llm):
        """Unlike window_manager/dictation, media_control has NO keyword
        fallback on LLM failure - it reports the failure directly. Documenting
        this as existing, intentional-looking behaviour (an ERROR-prefixed
        message would be more consistent with the rest of the fabricated-
        success cleanup, but this already fails honestly, just without a
        prefix - not the fabrication defect, out of scope here)."""
        result = handle_media_control("", "turn up the volume")
        assert "Failed to understand media command" in result

    @patch("agentic_core.processor._get_routing_llm")
    def test_invalid_classified_action_reports_honestly(self, mock_get_llm):
        mock_get_llm.return_value = _llm_returning("teleport_track")
        result = handle_media_control("", "do something weird")
        assert "invalid media action" in result
        assert "teleport_track" in result

    @patch("capabilities.system.media_control.pyautogui")
    @patch("agentic_core.processor._get_routing_llm")
    def test_key_press_failure_is_reported_not_raised(self, mock_get_llm, mock_pyautogui):
        mock_get_llm.return_value = _llm_returning("playpause")
        mock_pyautogui.press.side_effect = Exception("no media keys on this keyboard")
        result = handle_media_control("", "pause")
        assert "Failed to execute physical media key" in result


# ══════════════════════════════════════════════════════════════════════════════
# sys_utility.py
# ══════════════════════════════════════════════════════════════════════════════
class TestSysUtility:
    def test_empty_target_and_prompt_is_an_honest_error(self):
        result = handle_sys_utility("", "")
        assert result.startswith("ERROR")

    @patch("capabilities.system.sys_utility.subprocess")
    @patch("agentic_core.processor._get_routing_llm")
    def test_prompt_is_used_when_target_is_empty(self, mock_get_llm, mock_subprocess):
        captured = {}

        def _capture_classification(msgs):
            captured["prompt"] = msgs[0][1]
            return MagicMock(content="dark_mode")

        llm = MagicMock()
        llm.invoke.side_effect = _capture_classification
        mock_get_llm.return_value = llm

        handle_sys_utility("", "turn on dark mode")
        assert "turn on dark mode" in captured["prompt"]

    @pytest.mark.parametrize("action", ["recycle_bin", "dark_mode", "light_mode"])
    @patch("capabilities.system.sys_utility.subprocess")
    @patch("agentic_core.processor._get_routing_llm")
    def test_subprocess_backed_actions_invoke_powershell(self, mock_get_llm, mock_subprocess, action):
        mock_get_llm.return_value = _llm_returning(action)
        result = handle_sys_utility(action.replace("_", " "))
        mock_subprocess.run.assert_called_once()
        args = mock_subprocess.run.call_args[0][0]
        assert args[0] == "powershell"
        assert not result.startswith("ERROR")

    @pytest.mark.parametrize("action", ["recycle_bin", "dark_mode", "light_mode"])
    @patch("capabilities.system.sys_utility.subprocess")
    @patch("agentic_core.processor._get_routing_llm")
    def test_subprocess_failure_is_reported_as_error(self, mock_get_llm, mock_subprocess, action):
        mock_get_llm.return_value = _llm_returning(action)
        mock_subprocess.run.side_effect = Exception("powershell not found")
        result = handle_sys_utility(action.replace("_", " "))
        assert result.startswith("ERROR")

    @pytest.mark.parametrize("action", ["mute_mic", "brightness_down"])
    @patch("capabilities.system.sys_utility.subprocess")
    @patch("agentic_core.processor._get_routing_llm")
    def test_unimplemented_actions_report_error_without_touching_subprocess(self, mock_get_llm, mock_subprocess, action):
        mock_get_llm.return_value = _llm_returning(action)
        result = handle_sys_utility(action.replace("_", " "))
        mock_subprocess.run.assert_not_called()
        assert result.startswith("ERROR")
        assert "Nothing was changed" in result

    @patch("agentic_core.processor._get_routing_llm", side_effect=Exception("LLM down"))
    def test_llm_failure_degrades_to_unknown_action_error(self, mock_get_llm):
        result = handle_sys_utility("do a system thing")
        assert result.startswith("ERROR")
        assert "unknown" in result.lower()

    @patch("agentic_core.processor._get_routing_llm")
    def test_unrecognized_classified_action_reports_honestly(self, mock_get_llm):
        mock_get_llm.return_value = _llm_returning("reboot_bios")
        result = handle_sys_utility("do something exotic")
        assert result.startswith("ERROR")
        assert "reboot_bios" in result
