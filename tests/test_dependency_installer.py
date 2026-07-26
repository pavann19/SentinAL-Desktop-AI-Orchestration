"""
tests/test_dependency_installer.py
Unit tests for capabilities/developer/dependency_installer.py.
Mocks subprocess.Popen and time.sleep — never launches a real terminal.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from capabilities.developer.dependency_installer import (
    pip_install, npm_install, _validate_packages, _run_install,
)


class TestValidatePackages:

    def test_empty_string_invalid(self):
        valid, reason = _validate_packages("")
        assert valid is False
        assert "No package name" in reason

    def test_whitespace_only_invalid(self):
        valid, reason = _validate_packages("   ")
        assert valid is False

    def test_safe_package_valid(self):
        valid, reason = _validate_packages("requests flask")
        assert valid is True

    def test_unsafe_shell_chars_invalid(self):
        valid, reason = _validate_packages("requests; rm -rf /")
        assert valid is False
        assert "Unsafe characters" in reason

    def test_pip_extras_and_versions_valid(self):
        valid, reason = _validate_packages("requests[security]>=2.0,<3.0")
        assert valid is True


class TestPipInstall:

    def test_invalid_package_returns_error(self):
        result = pip_install("bad; rm -rf /")
        assert result.startswith("ERROR")

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_valid_package_launches_terminal(self, mock_popen, mock_sleep):
        mock_popen.return_value = MagicMock()
        result = pip_install("requests")
        mock_popen.assert_called_once()
        assert "Launched visible terminal" in result

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_upgrade_flag_included_in_command(self, mock_popen, mock_sleep):
        mock_popen.return_value = MagicMock()
        pip_install("requests", upgrade=True)
        # The launched powershell command string should reference the upgrade flag
        call_args = mock_popen.call_args[0][0]
        assert any("upgrade" in str(arg) for arg in call_args)


class TestNpmInstall:

    def test_nonexistent_directory_returns_error(self):
        result = npm_install("lodash", cwd="C:/totally/fake/nonexistent/dir_12345")
        assert result.startswith("ERROR")
        assert "does not exist" in result

    def test_invalid_package_returns_error(self):
        result = npm_install("bad; rm -rf /", cwd=os.getcwd())
        assert result.startswith("ERROR")

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_valid_package_launches_terminal(self, mock_popen, mock_sleep):
        mock_popen.return_value = MagicMock()
        result = npm_install("lodash", cwd=os.getcwd())
        mock_popen.assert_called_once()
        assert "Launched visible terminal" in result

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_no_packages_installs_from_package_json(self, mock_popen, mock_sleep):
        mock_popen.return_value = MagicMock()
        result = npm_install("", cwd=os.getcwd())
        mock_popen.assert_called_once()
        assert "Launched visible terminal" in result


class TestRunInstallFallback:

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_powershell_not_found_falls_back_to_cmd(self, mock_popen, mock_sleep):
        # First call (powershell) raises FileNotFoundError, second call (cmd) succeeds
        mock_popen.side_effect = [FileNotFoundError(), MagicMock()]
        result = _run_install(["python", "-m", "pip", "install", "requests"], label="pip install requests")
        assert mock_popen.call_count == 2
        assert "Launched terminal" in result

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_unexpected_exception_returns_error(self, mock_popen, mock_sleep):
        mock_popen.side_effect = RuntimeError("boom")
        result = _run_install(["npm", "install"], label="npm install")
        assert result.startswith("ERROR")
        assert "boom" in result
