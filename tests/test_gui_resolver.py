"""
tests/test_gui_resolver.py
Unit tests for capabilities/system/gui_resolver.py.

All external GUI/vision dependencies (pyautogui, pygetwindow, pywinauto, the
VLM pipeline) are mocked — no test here touches a real screen, window, or
model. pywinauto is not installed in this environment (an optional Tier-3
dependency, matching production where it may also be absent), so its
success/fallback paths are tested by injecting a fake module into
sys.modules before the function's local `from pywinauto import ...`
executes — the standard technique for testing an optional-dependency code
path without requiring the dependency itself.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from capabilities.system.gui_resolver import (
    find_by_image, find_window_center, find_control_by_label,
    find_by_description, resolve_element,
)


class TestFindByImage:

    def test_image_file_missing_returns_none(self):
        assert find_by_image("C:/nonexistent/button.png") is None

    @patch("os.path.exists", return_value=True)
    @patch("pyautogui.center")
    @patch("pyautogui.locateOnScreen")
    def test_match_found_returns_center(self, mock_locate, mock_center, mock_exists):
        mock_locate.return_value = (10, 20, 30, 40)
        mock_center.return_value = (25, 40)
        result = find_by_image("button.png")
        assert result == (25, 40)

    @patch("os.path.exists", return_value=True)
    @patch("pyautogui.locateOnScreen", return_value=None)
    def test_no_match_returns_none(self, mock_locate, mock_exists):
        assert find_by_image("button.png") is None

    @patch("os.path.exists", return_value=True)
    @patch("pyautogui.locateOnScreen", side_effect=Exception("opencv not installed"))
    def test_exception_returns_none_not_raised(self, mock_locate, mock_exists):
        assert find_by_image("button.png") is None


class TestFindWindowCenter:

    @patch("pygetwindow.getWindowsWithTitle")
    def test_window_found_returns_center(self, mock_get_windows):
        win = MagicMock(left=100, top=200, width=800, height=600)
        mock_get_windows.return_value = [win]
        with patch("time.sleep"):
            result = find_window_center("Notepad")
        assert result == (100 + 400, 200 + 300)
        win.activate.assert_called_once()

    @patch("pygetwindow.getWindowsWithTitle", return_value=[])
    def test_no_window_found_returns_none(self, mock_get_windows):
        assert find_window_center("DoesNotExist") is None

    @patch("pygetwindow.getWindowsWithTitle")
    def test_activate_failure_is_non_fatal(self, mock_get_windows):
        """Window may already be active — activate() raising must not abort."""
        win = MagicMock(left=0, top=0, width=200, height=100)
        win.activate.side_effect = Exception("already active")
        mock_get_windows.return_value = [win]
        with patch("time.sleep"):
            result = find_window_center("Notepad")
        assert result == (100, 50)

    def test_pygetwindow_not_installed_returns_none(self):
        with patch.dict(sys.modules, {"pygetwindow": None}):
            assert find_window_center("Notepad") is None

    @patch("pygetwindow.getWindowsWithTitle", side_effect=RuntimeError("X server unavailable"))
    def test_unexpected_exception_returns_none(self, mock_get_windows):
        assert find_window_center("Notepad") is None


class _FakeWinauto:
    """Injected into sys.modules to test pywinauto-dependent code without
    requiring pywinauto to actually be installed."""

    def __init__(self, top_window):
        self.Application = MagicMock(return_value=MagicMock(connect=MagicMock(
            return_value=MagicMock(top_window=MagicMock(return_value=top_window))
        )))
        self.findwindows = MagicMock()
        self.findwindows.find_windows.return_value = [12345]


class TestFindControlByLabel:

    def test_no_matching_window_returns_none(self):
        fake = _FakeWinauto(top_window=MagicMock())
        fake.findwindows.find_windows.return_value = []
        with patch.dict(sys.modules, {"pywinauto": fake}):
            assert find_control_by_label("Notepad", "Save") is None

    def test_direct_child_window_match_returns_center(self):
        ctrl = MagicMock()
        ctrl.rectangle.return_value = MagicMock(left=10, right=30, top=40, bottom=60)
        dlg = MagicMock()
        dlg.child_window.return_value = ctrl
        fake = _FakeWinauto(top_window=dlg)

        with patch.dict(sys.modules, {"pywinauto": fake}):
            result = find_control_by_label("Notepad", "Save")

        assert result == (20, 50)

    def test_falls_back_to_fuzzy_descendant_search(self):
        dlg = MagicMock()
        dlg.child_window.side_effect = Exception("no exact match")
        good_ctrl = MagicMock()
        good_ctrl.window_text.return_value = "Save As..."
        good_ctrl.rectangle.return_value = MagicMock(left=0, right=20, top=0, bottom=10)
        dlg.descendants.return_value = [good_ctrl]
        fake = _FakeWinauto(top_window=dlg)

        with patch.dict(sys.modules, {"pywinauto": fake}):
            result = find_control_by_label("Notepad", "save")

        assert result == (10, 5)

    def test_unreadable_descendant_is_skipped_not_fatal(self):
        dlg = MagicMock()
        dlg.child_window.side_effect = Exception("no exact match")
        broken_ctrl = MagicMock()
        broken_ctrl.window_text.side_effect = Exception("control disposed")
        dlg.descendants.return_value = [broken_ctrl]
        fake = _FakeWinauto(top_window=dlg)

        with patch.dict(sys.modules, {"pywinauto": fake}):
            result = find_control_by_label("Notepad", "Save")

        assert result is None

    def test_pywinauto_not_installed_returns_none(self):
        # Genuinely not installed in this environment — real ImportError path.
        assert find_control_by_label("Notepad", "Save") is None


class TestFindByDescription:

    def _mock_vlm_response(self, content):
        resp = MagicMock()
        resp.content = content
        return resp

    @patch("capabilities.system.vision_module.take_screenshot_base64", return_value="fakebase64")
    @patch("langchain_ollama.ChatOllama")
    def test_element_found_returns_coordinates(self, mock_chat_ollama, mock_screenshot):
        llm = MagicMock()
        llm.invoke.return_value = self._mock_vlm_response('{"x": 150, "y": 300, "found": true}')
        mock_chat_ollama.return_value = llm

        result = find_by_description("the Submit button")

        assert result == (150, 300)

    @patch("capabilities.system.vision_module.take_screenshot_base64", return_value="fakebase64")
    @patch("langchain_ollama.ChatOllama")
    def test_element_not_found_returns_none(self, mock_chat_ollama, mock_screenshot):
        llm = MagicMock()
        llm.invoke.return_value = self._mock_vlm_response('{"found": false}')
        mock_chat_ollama.return_value = llm

        assert find_by_description("a nonexistent widget") is None

    @patch("capabilities.system.vision_module.take_screenshot_base64", return_value="fakebase64")
    @patch("langchain_ollama.ChatOllama")
    def test_malformed_vlm_response_returns_none_not_raised(self, mock_chat_ollama, mock_screenshot):
        llm = MagicMock()
        llm.invoke.return_value = self._mock_vlm_response("not json at all")
        mock_chat_ollama.return_value = llm

        assert find_by_description("the Submit button") is None

    @patch("capabilities.system.vision_module.take_screenshot_base64", side_effect=Exception("screen capture failed"))
    def test_screenshot_failure_returns_none(self, mock_screenshot):
        assert find_by_description("the Submit button") is None


class TestResolveElement:

    def test_no_args_exhausts_all_tiers_returns_none(self):
        assert resolve_element() is None

    @patch("capabilities.system.gui_resolver.find_by_image", return_value=(1, 2))
    def test_image_tier_wins_when_provided(self, mock_find_image):
        result = resolve_element(image_path="btn.png", app_title="Notepad", label="Save")
        assert result == (1, 2)
        mock_find_image.assert_called_once()

    @patch("capabilities.system.gui_resolver.find_window_center", return_value=(5, 6))
    def test_window_tier_used_when_app_title_only(self, mock_find_window):
        result = resolve_element(app_title="Notepad")
        assert result == (5, 6)

    @patch("capabilities.system.gui_resolver.find_control_by_label", return_value=(7, 8))
    def test_accessibility_tier_used_when_app_and_label_both_given(self, mock_find_control):
        result = resolve_element(app_title="Notepad", label="Save")
        assert result == (7, 8)

    @patch("capabilities.system.gui_resolver.find_by_description", return_value=(9, 10))
    def test_vlm_tier_used_as_last_resort_for_label_only(self, mock_find_desc):
        result = resolve_element(label="the Save button")
        assert result == (9, 10)

    @patch("capabilities.system.gui_resolver.find_by_description", return_value=None)
    @patch("capabilities.system.gui_resolver.find_control_by_label", return_value=None)
    @patch("capabilities.system.gui_resolver.find_window_center", return_value=None)
    @patch("capabilities.system.gui_resolver.find_by_image", return_value=None)
    def test_all_tiers_exhausted_returns_none(self, *_mocks):
        result = resolve_element(label="ghost", image_path="x.png", app_title="Notepad")
        assert result is None

    @patch("capabilities.system.gui_resolver.find_by_description", return_value=(9, 9))
    @patch("capabilities.system.gui_resolver.find_window_center", return_value=None)
    def test_falls_through_to_next_tier_when_earlier_tier_fails(self, mock_window, mock_desc):
        """app_title with no label tries the window tier first; if that fails
        and a label is later added the VLM tier should still be reachable."""
        result = resolve_element(app_title="Notepad", label="Save button")
        # app_title + label routes straight to accessibility tier (mocked away
        # by not patching find_control_by_label -> real pywinauto ImportError
        # path returns None), then falls through to VLM.
        assert result == (9, 9)
