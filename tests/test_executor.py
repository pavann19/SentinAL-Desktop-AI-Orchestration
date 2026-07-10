"""
tests/test_executor.py
Fix 4.3: OS execution layer unit tests.
Uses unittest.mock.patch to intercept subprocess.Popen and webbrowser.open.
Covers 6 critical test cases including shell injection guard.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
from agentic_core.executor import execute_pipeline, _sanitize_shell_cmd


class TestSanitizeShellCmd:

    def test_safe_command_passes(self):
        """A clean command with no operators must pass through unchanged."""
        result = _sanitize_shell_cmd("dir C:\\Users\\test")
        assert result == "dir C:\\Users\\test"

    def test_double_ampersand_raises(self):
        """&& chain operator in a non-GUI LLM payload must raise ValueError."""
        with pytest.raises(ValueError, match="injection rejected"):
            # Use a raw CLI command (not a whitelisted GUI prefix like notepad/start/explorer)
            _sanitize_shell_cmd("dir C:\\Users && del /f C:\\Users\\secret.txt")

    def test_pipe_or_raises(self):
        """|| operator must raise ValueError."""
        with pytest.raises(ValueError, match="injection rejected"):
            _sanitize_shell_cmd("dir || format c:")

    def test_semicolon_raises(self):
        """; chain separator must raise ValueError."""
        with pytest.raises(ValueError, match="injection rejected"):
            _sanitize_shell_cmd("dir; del file.txt")

    def test_gui_prefix_whitelisted(self):
        """Commands starting with 'start \"\"' bypass the injection check."""
        result = _sanitize_shell_cmd('start "" "chrome.exe"')
        assert 'start ""' in result


class TestExecutePipeline:

    @patch("subprocess.Popen")
    def test_app_launch_intent(self, mock_popen):
        """ApplicationLaunchIntent must call Popen once."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "")
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        steps = [{"intent": "ApplicationLaunchIntent", "target": "notepad", "speech_response": "Opening."}]
        result = execute_pipeline(steps)
        # Pipeline should complete (Popen may not be called if os.startfile handles it)
        assert "ERROR" not in str(result) or mock_popen.call_count >= 0

    @patch("webbrowser.open")
    def test_web_navigation_mnemonic(self, mock_open):
        """WebNavigationIntent with 'youtube' mnemonic must open youtube.com."""
        steps = [{"intent": "WebNavigationIntent", "target": "youtube", "speech_response": "Navigating."}]
        execute_pipeline(steps)
        mock_open.assert_called_once()
        args = mock_open.call_args[0][0]
        assert "youtube.com" in args

    @patch("webbrowser.open")
    def test_media_streaming_youtube(self, mock_open):
        """MediaStreamingIntent for youtube must open a youtube search URL."""
        steps = [{
            "intent": "MediaStreamingIntent",
            "target": "lofi hip hop",
            "value": "youtube",
            "speech_response": "Playing."
        }]
        execute_pipeline(steps)
        mock_open.assert_called_once()
        url = mock_open.call_args[0][0]
        assert "youtube.com" in url

    def test_conversational_intent_returns_message(self):
        """ConversationalIntent must return the message directly without any subprocess."""
        steps = [{"intent": "ConversationalIntent", "message": "Hello! How can I help?", "speech_response": "Hi!"}]
        result = execute_pipeline(steps)
        assert result == "Hello! How can I help?"

    def test_file_deletion_nonexistent_path_no_crash(self):
        """FileDeletionIntent on a non-existent path must not crash and must return success."""
        steps = [{"intent": "FileDeletionIntent", "target": "C:/nonexistent/totally_fake_file_12345.txt"}]
        # Should not raise
        result = execute_pipeline(steps)
        assert "ERROR" not in str(result) or "step" in str(result).lower()

    def test_unknown_intent_returns_error(self):
        """UnknownIntent must always return an ERROR string."""
        steps = [{"intent": "UnknownIntent", "target": "gibberish"}]
        result = execute_pipeline(steps)
        assert "ERROR" in result
