"""
tests/test_scaffolding.py
Unit tests for capabilities/developer/scaffolding.py.
Mocks subprocess.run/Popen and os.makedirs — never runs a real scaffold command.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import subprocess
from unittest.mock import patch, MagicMock
from capabilities.developer.scaffolding import scaffold_project


class TestScaffoldProject:

    def test_unsupported_framework_returns_message(self):
        result = scaffold_project("cobol-web-framework", "myapp")
        assert "not supported" in result

    @patch("os.makedirs")
    def test_workspace_framework_creates_dir_only(self, mock_makedirs):
        result = scaffold_project("workspace", "my-blank-project", location="C:/fake/loc")
        mock_makedirs.assert_called_once()
        assert "created" in result
        assert "No framework template applied" in result

    @patch("os.makedirs", side_effect=OSError("permission denied"))
    def test_directory_creation_failure_returns_error(self, mock_makedirs):
        result = scaffold_project("react", "myapp", location="C:/fake/loc")
        assert result.startswith("ERROR")
        assert "permission denied" in result

    @patch("shutil.which", return_value=None)
    @patch("os.makedirs")
    @patch("subprocess.run")
    def test_successful_scaffold_no_vscode(self, mock_run, mock_makedirs, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = scaffold_project("flask", "my-flask-app", location="C:/fake/loc")
        assert "scaffolded successfully" in result

    @patch("subprocess.Popen")
    @patch("shutil.which", return_value="C:/code/code.exe")
    @patch("os.makedirs")
    @patch("subprocess.run")
    def test_successful_scaffold_opens_vscode(self, mock_run, mock_makedirs, mock_which, mock_popen):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = scaffold_project("vite", "my-vite-app", location="C:/fake/loc")
        mock_popen.assert_called_once()
        assert "scaffolded successfully" in result

    @patch("os.makedirs")
    @patch("subprocess.run")
    def test_scaffold_command_failure_returns_error(self, mock_run, mock_makedirs):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="npm ERR! network timeout")
        result = scaffold_project("react", "my-app", location="C:/fake/loc")
        assert "failed" in result.lower()
        assert "network timeout" in result

    @patch("os.makedirs")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="npx", timeout=900))
    def test_scaffold_timeout_returns_error(self, mock_run, mock_makedirs):
        result = scaffold_project("next", "my-app", location="C:/fake/loc")
        assert result.startswith("ERROR")
        assert "timed out" in result

    @patch("os.makedirs")
    @patch("subprocess.run", side_effect=FileNotFoundError())
    def test_missing_tool_returns_error(self, mock_run, mock_makedirs):
        result = scaffold_project("django", "my-app", location="C:/fake/loc")
        assert result.startswith("ERROR")
        assert "PATH" in result

    @patch("os.makedirs")
    @patch("subprocess.run", side_effect=RuntimeError("unexpected"))
    def test_unexpected_exception_returns_error(self, mock_run, mock_makedirs):
        result = scaffold_project("vue", "my-app", location="C:/fake/loc")
        assert result.startswith("ERROR")
        assert "unexpected" in result

    def test_project_name_sanitized(self):
        with patch("os.makedirs") as mock_makedirs:
            scaffold_project("workspace", "my app!!with@@bad##chars", location="C:/fake/loc")
            call_path = mock_makedirs.call_args[0][0]
            assert "!" not in call_path and "@" not in call_path and "#" not in call_path
