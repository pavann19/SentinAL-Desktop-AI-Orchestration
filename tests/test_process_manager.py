"""
tests/test_process_manager.py
Unit tests for capabilities/system/process_manager.py.
Mocks subprocess.run — never lists or kills real processes.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import subprocess
from unittest.mock import patch, MagicMock
from capabilities.system.process_manager import list_processes, kill_process


_TASKLIST_CSV = (
    '"notepad.exe","1234","Console","1","10,000 K"\r\n'
    '"chrome.exe","5678","Console","1","250,000 K"\r\n'
)


class TestListProcesses:

    @patch("subprocess.run")
    def test_no_filter_returns_all_processes(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=_TASKLIST_CSV, stderr="")
        result = list_processes()
        assert len(result) == 2
        assert result[0]["name"] == "notepad.exe"
        assert result[0]["pid"] == 1234

    @patch("subprocess.run")
    def test_filter_matches_substring_case_insensitive(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=_TASKLIST_CSV, stderr="")
        result = list_processes("CHROME")
        assert len(result) == 1
        assert result[0]["name"] == "chrome.exe"

    @patch("subprocess.run")
    def test_filter_no_match_returns_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=_TASKLIST_CSV, stderr="")
        result = list_processes("nonexistent_app")
        assert result == []

    @patch("subprocess.run")
    def test_tasklist_failure_returns_empty_list(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="access denied")
        result = list_processes()
        assert result == []

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="tasklist", timeout=10))
    def test_timeout_returns_empty_list(self, mock_run):
        result = list_processes()
        assert result == []

    @patch("subprocess.run", side_effect=RuntimeError("boom"))
    def test_unexpected_exception_returns_empty_list(self, mock_run):
        result = list_processes()
        assert result == []

    @patch("subprocess.run")
    def test_malformed_row_skipped(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout='"tooshort","1"\r\n', stderr="")
        result = list_processes()
        assert result == []


class TestKillProcess:

    def test_empty_target_returns_error(self):
        result = kill_process("")
        assert result.startswith("ERROR")

    def test_protected_process_blocked(self):
        result = kill_process("explorer.exe")
        assert "protected OS process" in result

    def test_protected_process_blocked_without_exe_suffix(self):
        result = kill_process("winlogon")
        assert "protected OS process" in result

    @patch("subprocess.run")
    def test_successful_kill_by_name(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="SUCCESS", stderr="")
        result = kill_process("notepad.exe")
        assert "terminated successfully" in result
        args = mock_run.call_args[0][0]
        assert "/IM" in args

    @patch("subprocess.run")
    def test_successful_kill_by_pid(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="SUCCESS", stderr="")
        result = kill_process("4321")
        assert "terminated successfully" in result
        args = mock_run.call_args[0][0]
        assert "/PID" in args

    @patch("subprocess.run")
    def test_taskkill_failure_returns_message(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="not found")
        result = kill_process("nonexistent.exe")
        assert "Could not terminate" in result

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="taskkill", timeout=10))
    def test_timeout_returns_error(self, mock_run):
        result = kill_process("notepad.exe")
        assert result.startswith("ERROR")
        assert "timed out" in result

    @patch("subprocess.run", side_effect=RuntimeError("boom"))
    def test_unexpected_exception_returns_error(self, mock_run):
        result = kill_process("notepad.exe")
        assert result.startswith("ERROR")
