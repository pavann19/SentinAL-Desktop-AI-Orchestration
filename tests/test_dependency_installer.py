"""
tests/test_dependency_installer.py
Unit tests for capabilities/developer/dependency_installer.py.
Mocks subprocess.Popen, time.sleep, and file I/O — never launches a real
terminal or writes to disk.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock, mock_open
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

    @patch("agentic_core.process_supervisor.register_watch")
    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_valid_package_launches_terminal(self, mock_makedirs, mock_file, mock_popen, mock_sleep, mock_register):
        mock_popen.return_value = MagicMock(pid=4242)
        result = pip_install("requests")
        mock_popen.assert_called_once()
        assert "Launched visible terminal" in result

    @patch("agentic_core.process_supervisor.register_watch")
    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_upgrade_flag_included_in_script(self, mock_makedirs, mock_file, mock_popen, mock_sleep, mock_register):
        mock_popen.return_value = MagicMock(pid=4242)
        pip_install("requests", upgrade=True)
        # The command is now written into the generated .ps1 script, not passed
        # as a Popen argument (see the PID-bug fix docstring in _run_install).
        written = mock_file().write.call_args[0][0]
        assert "upgrade" in written


class TestNpmInstall:

    def test_nonexistent_directory_returns_error(self):
        result = npm_install("lodash", cwd="C:/totally/fake/nonexistent/dir_12345")
        assert result.startswith("ERROR")
        assert "does not exist" in result

    def test_invalid_package_returns_error(self):
        result = npm_install("bad; rm -rf /", cwd=os.getcwd())
        assert result.startswith("ERROR")

    @patch("agentic_core.process_supervisor.register_watch")
    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_valid_package_launches_terminal(self, mock_makedirs, mock_file, mock_popen, mock_sleep, mock_register):
        mock_popen.return_value = MagicMock(pid=4242)
        result = npm_install("lodash", cwd=os.getcwd())
        mock_popen.assert_called_once()
        assert "Launched visible terminal" in result

    @patch("agentic_core.process_supervisor.register_watch")
    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_no_packages_installs_from_package_json(self, mock_makedirs, mock_file, mock_popen, mock_sleep, mock_register):
        mock_popen.return_value = MagicMock(pid=4242)
        result = npm_install("", cwd=os.getcwd())
        mock_popen.assert_called_once()
        assert "Launched visible terminal" in result


class TestRunInstallPidFix:
    """
    Regression coverage for the PID bug: the launch must be a direct,
    list-form Popen (no `start`/`Start-Process` shell wrapper) so
    Popen.pid is the real, visible PowerShell process — and a completion
    sentinel must be woven into the generated script so the process
    supervisor can tell success from failure, not just "the process died".
    """

    @patch("agentic_core.process_supervisor.register_watch")
    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_launch_is_list_form_with_no_shell_wrapper(self, mock_makedirs, mock_file, mock_popen, mock_sleep, mock_register):
        mock_popen.return_value = MagicMock(pid=9001)
        _run_install(["python", "-m", "pip", "install", "requests"], label="pip install requests")

        args, kwargs = mock_popen.call_args
        launch_cmd = args[0]
        assert isinstance(launch_cmd, list)
        assert launch_cmd[0] == "powershell"
        assert "-File" in launch_cmd
        # Nothing in the launch args re-wraps this in another shell/process —
        # that indirection is exactly what made Popen.pid wrong before.
        assert not kwargs.get("shell")
        assert not any("Start-Process" in str(a) for a in launch_cmd)
        assert not any(str(a).strip().lower().startswith("start ") for a in launch_cmd)

    @patch("agentic_core.process_supervisor.register_watch")
    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_real_pid_is_registered_with_the_supervisor(self, mock_makedirs, mock_file, mock_popen, mock_sleep, mock_register):
        mock_popen.return_value = MagicMock(pid=9001)
        _run_install(["npm", "install"], label="npm install")

        mock_register.assert_called_once()
        _, kwargs = mock_register.call_args
        assert kwargs["pid"] == 9001
        assert kwargs["label"] == "dependency_install"
        assert kwargs["sentinel_path"]  # a real sentinel path, not None

    @patch("agentic_core.process_supervisor.register_watch")
    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_generated_script_contains_command_and_sentinel_footer(self, mock_makedirs, mock_file, mock_popen, mock_sleep, mock_register):
        mock_popen.return_value = MagicMock(pid=9001)
        _run_install(["npm", "install", "lodash"], label="npm install lodash")

        written = mock_file().write.call_args[0][0]
        assert "npm install lodash" in written
        assert "SentinAL completion sentinel" in written


class TestRunInstallFallback:

    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_powershell_not_found_falls_back_to_cmd(self, mock_makedirs, mock_file, mock_popen, mock_sleep):
        # First call (powershell) raises FileNotFoundError, second call (cmd) succeeds
        mock_popen.side_effect = [FileNotFoundError(), MagicMock()]
        result = _run_install(["python", "-m", "pip", "install", "requests"], label="pip install requests")
        assert mock_popen.call_count == 2
        assert "Launched terminal" in result

    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_unexpected_exception_returns_error(self, mock_makedirs, mock_file, mock_popen, mock_sleep):
        mock_popen.side_effect = RuntimeError("boom")
        result = _run_install(["npm", "install"], label="npm install")
        assert result.startswith("ERROR")
        assert "boom" in result

    @patch("time.sleep")
    @patch("subprocess.Popen")
    def test_script_prep_failure_still_launches_unsupervised(self, mock_popen, mock_sleep):
        # os.makedirs raising means the try/except around script prep catches
        # it and falls through to the no-sentinel launch path — the install
        # must still happen, just unobserved, exactly like the pre-fix behaviour.
        mock_popen.return_value = MagicMock(pid=4242)
        with patch("os.makedirs", side_effect=OSError("disk full")):
            result = _run_install(["python", "-m", "pip", "install", "requests"], label="pip install requests")
        assert "Launched visible terminal" in result
        launch_cmd = mock_popen.call_args[0][0]
        assert "-File" not in launch_cmd
        assert "-Command" in launch_cmd
