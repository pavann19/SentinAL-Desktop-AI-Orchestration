"""
tests/test_dependency_installer.py
Unit tests for capabilities/developer/dependency_installer.py.
Mocks subprocess.Popen, time.sleep, and file I/O â€” never launches a real
terminal or writes to disk.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock, mock_open
import agentic_core.process_supervisor  # initialize dependencies before filesystem mocks
from capabilities.developer.dependency_installer import (
    pip_install, npm_install, _validate_packages, _run_install,
    _docker_available, _sandboxed_npm_script_body,
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


class TestContainedInstallPolicy:
    @patch("subprocess.Popen")
    def test_pip_never_executes_on_host(self, launch):
        assert "disabled" in pip_install("requests")
        assert "disabled" in pip_install("requests", upgrade=True)
        launch.assert_not_called()

    @patch("capabilities.developer.dependency_installer._docker_available", return_value=False)
    @patch("subprocess.Popen")
    def test_missing_docker_never_executes_on_host(self, launch, docker):
        assert "host npm fallback is disabled" in npm_install("lodash", cwd=os.getcwd())
        launch.assert_not_called()

    @patch("subprocess.Popen")
    def test_uncontained_internal_command_rejected(self, launch):
        assert "disabled" in _run_install(["npm", "install"], label="npm")
        launch.assert_not_called()

    def test_invalid_package_and_directory_rejected(self):
        assert npm_install("bad; calc", cwd=os.getcwd()).startswith("ERROR")
        assert pip_install("bad; calc").startswith("ERROR")
        assert "does not exist" in npm_install("lodash", cwd="C:/nonexistent-sentinal-test")


class TestSandboxedNpmScriptBody:
    def test_container_mount_and_security_options(self):
        body = _sandboxed_npm_script_body(["lodash"], False, r"C:\proj")
        assert "'docker' 'run' '--rm'" in body
        assert r"'C:\proj:/workspace'" in body
        assert "--cap-drop=ALL" in body
        assert "no-new-privileges" in body
        assert "'npm' 'install' 'lodash'" in body
        assert "$LASTEXITCODE -ne 0" in body

    def test_dev_and_empty_restore(self):
        assert "--save-dev" in _sandboxed_npm_script_body(["lodash"], True, r"C:\proj")
        assert "'npm' 'install'" in _sandboxed_npm_script_body([], False, r"C:\proj")

    def test_native_modules_fail_without_second_install(self):
        body = _sandboxed_npm_script_body(["sharp"], False, r"C:\proj")
        assert "*.node" in body
        assert "throw 'Linux native modules" in body
        assert body.count("'npm' 'install'") == 1
        assert "host fallback is disabled" in body

    def test_workspace_metacharacters_are_literal(self):
        body = _sandboxed_npm_script_body(["lodash"], False, "C:/it's/$data")
        assert "Set-Location -LiteralPath 'C:/it''s/$data'" in body
        assert "'C:/it''s/$data:/workspace'" in body


class TestDockerAvailable:
    @patch("subprocess.run")
    def test_daemon_status(self, run):
        run.return_value = MagicMock(returncode=0)
        assert _docker_available()
        run.return_value = MagicMock(returncode=1)
        assert not _docker_available()

    @patch("subprocess.run", side_effect=FileNotFoundError())
    def test_missing_binary(self, run):
        assert not _docker_available()

    @patch("subprocess.run", side_effect=TimeoutError())
    def test_timeout(self, run):
        assert not _docker_available()


class TestSupervisedContainedLaunch:
    @patch("capabilities.developer.dependency_installer._docker_available", return_value=True)
    @patch("agentic_core.process_supervisor.register_watch", return_value="watch123")
    @patch("time.sleep")
    @patch("subprocess.Popen")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_real_pid_sentinel_and_task_id(self, mkdir, file, launch, sleep, register, docker):
        launch.return_value = MagicMock(pid=9001)
        result = npm_install("lodash", cwd=os.getcwd())
        launch.assert_called_once()
        args, kwargs = launch.call_args
        assert isinstance(args[0], list)
        assert args[0][0] == "powershell"
        assert "-File" in args[0]
        assert not kwargs.get("shell")
        assert not any("Start-Process" in value for value in args[0])
        register.assert_called_once()
        assert register.call_args.kwargs["pid"] == 9001
        assert register.call_args.kwargs["sentinel_path"]
        written = file().write.call_args.args[0]
        assert "'docker' 'run'" in written
        assert "SentinAL completion sentinel" in written
        assert "watch123" in result
        assert "not a completion" in result

    @patch("subprocess.Popen")
    @patch("os.makedirs", side_effect=OSError("disk full"))
    def test_script_preparation_failure_never_falls_back(self, mkdir, launch):
        result = _run_install(["npm", "install"], "npm", script_body="contained")
        assert "Could not prepare" in result
        launch.assert_not_called()

    @patch("subprocess.Popen", side_effect=FileNotFoundError())
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_missing_powershell_never_launches_cmd(self, mkdir, file, launch):
        result = _run_install(["npm", "install"], "npm", script_body="contained")
        assert "fallback is disabled" in result
        launch.assert_called_once()

    @patch("subprocess.Popen", side_effect=RuntimeError("boom"))
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_launch_error_is_reported(self, mkdir, file, launch):
        assert "boom" in _run_install(["npm", "install"], "npm", script_body="contained")

    @patch("agentic_core.process_supervisor.register_watch", side_effect=RuntimeError("db down"))
    @patch("subprocess.Popen", return_value=MagicMock(pid=9001))
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_failed_watch_does_not_fabricate_task_id(self, mkdir, file, launch, register):
        result = _run_install(["npm", "install"], "npm", script_body="contained")
        assert "Launched contained" in result
        assert "Task id" not in result
