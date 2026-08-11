"""
tests/test_executor_generalized_os.py

Coverage for agentic_core/executor.py's GeneralizedOSIntent branch
(lines ~361-643), previously the single densest untested block in the
codebase — 285 lines with no dedicated unit test file, only incidentally
exercised through pipeline/benchmark integration tests that mostly hit the
GUI-vs-CLI classification path.

Mocks at the subprocess/os boundary (subprocess.Popen, os.startfile,
os.path.exists), matching the pattern in test_executor.py, so the real
branching logic in execute_pipeline() runs — sanitization, retry/self-healing,
explorer interception, GUI-vs-CLI routing, visible-terminal routing — rather
than being replaced by a mock.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.executor import execute_pipeline


def _os_step(actions, speech_response=""):
    return [{
        "intent": "GeneralizedOSIntent",
        "actions": actions,
        "speech_response": speech_response,
    }]


def _shell_action(payload, value=""):
    return {"type": "shell", "payload": payload, "value": value}


class TestEmptyActions:
    def test_missing_actions_array_returns_error(self):
        result = execute_pipeline([{"intent": "GeneralizedOSIntent", "actions": []}])
        assert result.startswith("ERROR")
        assert "missing actions array" in result

    def test_actions_key_entirely_absent_returns_error(self):
        result = execute_pipeline([{"intent": "GeneralizedOSIntent"}])
        assert result.startswith("ERROR")


class TestUnrecognizedActionType:
    def test_unknown_action_type_returns_error(self):
        result = execute_pipeline(_os_step([{"type": "teleport", "payload": "x"}]))
        assert result.startswith("ERROR")
        assert "Unrecognized action type" in result


class TestShellInjectionRejected:
    def test_chained_command_via_ampersand_is_blocked_before_any_subprocess_call(self):
        with patch("subprocess.Popen") as mock_popen:
            result = execute_pipeline(_os_step([
                _shell_action("dir C:\\Users && del /f C:\\Users\\secret.txt")
            ]))
        assert result.startswith("ERROR")
        mock_popen.assert_not_called()


class TestPayloadValueCombination:
    """LLMs often split a command into payload + value separately
    ('mkdir' + '%USERPROFILE%/Desktop/my_folder') - the executor must combine
    them, expand env vars, and quote paths containing spaces."""

    @patch("subprocess.Popen")
    def test_value_with_space_gets_quoted(self, mock_popen):
        proc = MagicMock()
        proc.communicate.return_value = ("done", "")
        proc.returncode = 0
        mock_popen.return_value = proc

        execute_pipeline(_os_step([_shell_action("mkdir", "C:\\My Folder")]))

        called_cmd = mock_popen.call_args[0][0]
        assert '"C:\\My Folder"' in called_cmd

    @patch("subprocess.Popen")
    def test_value_without_space_is_not_quoted(self, mock_popen):
        proc = MagicMock()
        proc.communicate.return_value = ("done", "")
        proc.returncode = 0
        mock_popen.return_value = proc

        execute_pipeline(_os_step([_shell_action("mkdir", "C:\\Notes")]))

        called_cmd = mock_popen.call_args[0][0]
        assert '"C:\\Notes"' not in called_cmd


class TestVisualDirRewrite:
    """A speech_response containing 'open'/'show'/'look at'/'display' signals
    the user wants to SEE the result, so a bare dir/ls listing command is
    rewritten to open Explorer instead of dumping text nobody will read."""

    @patch("os.startfile")
    @patch("os.path.exists", return_value=True)
    def test_dir_rewritten_to_explorer_when_speech_is_visual(self, mock_exists, mock_startfile):
        execute_pipeline(_os_step(
            [_shell_action("dir C:\\Users\\test\\Desktop")],
            speech_response="Let me open that for you",
        ))
        mock_startfile.assert_called_once()


class TestExplorerInterceptor:
    @patch("os.startfile")
    @patch("os.path.exists", return_value=True)
    def test_verified_path_opens_directly(self, mock_exists, mock_startfile):
        result = execute_pipeline(_os_step([_shell_action("explorer C:\\Users\\test\\Documents")]))
        mock_startfile.assert_called_once()
        assert "opened" in result.lower() or "found" in result.lower()

    @patch("agentic_core.executor.memory")
    @patch("os.startfile")
    @patch("os.path.exists", return_value=False)
    def test_missing_path_falls_back_to_memory_cache_hit(self, mock_exists, mock_startfile, mock_memory):
        mock_memory.get_cached_path.return_value = "C:\\Real\\Cached\\Path"
        result = execute_pipeline(_os_step([_shell_action("explorer C:\\guessed\\wrong\\path")]))
        mock_startfile.assert_called_once_with("C:\\Real\\Cached\\Path")
        assert not result.startswith("ERROR")

    @patch("agentic_core.executor.memory")
    @patch("os.path.exists", return_value=False)
    def test_missing_path_and_cache_miss_reports_could_not_locate(self, mock_exists, mock_memory):
        mock_memory.get_cached_path.return_value = None
        result = execute_pipeline(_os_step([_shell_action("explorer nonexistent_folder_xyz")]))
        assert "could not locate" in result.lower()

    @patch("os.startfile", side_effect=OSError("blocked by policy"))
    @patch("os.path.exists", return_value=True)
    def test_os_startfile_failure_reports_blocked_not_a_crash(self, mock_exists, mock_startfile):
        result = execute_pipeline(_os_step([_shell_action("explorer C:\\Users\\test")]))
        assert not result.startswith("ERROR")  # degrades to a spoken explanation, doesn't crash
        assert "blocked" in result.lower()


class TestGuiVsCliRouting:
    """Regression coverage for the taskkill-misclassification fix: GUI
    detection must key on the command's own executable, not any trigger
    word appearing anywhere in the line."""

    @patch("subprocess.Popen")
    def test_bare_notepad_launch_is_detached_not_waited_on(self, mock_popen):
        proc = MagicMock()
        mock_popen.return_value = proc
        execute_pipeline(_os_step([_shell_action("notepad")]))
        # Detached GUI launches never call communicate() - they fire-and-forget.
        proc.communicate.assert_not_called()
        _, kwargs = mock_popen.call_args
        assert kwargs.get("creationflags") is not None

    @patch("subprocess.Popen")
    def test_taskkill_referencing_notepad_is_synchronous_not_detached(self, mock_popen):
        proc = MagicMock()
        proc.communicate.return_value = ("", "")
        proc.returncode = 0
        mock_popen.return_value = proc
        execute_pipeline(_os_step([_shell_action("taskkill /IM notepad.exe /F")]))
        # Must wait for the kill to actually complete - the whole point of the fix.
        proc.communicate.assert_called_once()


class TestVisibleTerminalRouting:
    @patch("subprocess.Popen")
    def test_npm_install_opens_a_visible_terminal(self, mock_popen):
        proc = MagicMock()
        mock_popen.return_value = proc
        execute_pipeline(_os_step([_shell_action("npm install react")]))
        called_cmd = mock_popen.call_args[0][0]
        assert "powershell" in called_cmd.lower()
        proc.communicate.assert_not_called()  # fire-and-forget, like GUI launches


class TestStandardCliExecution:
    @patch("subprocess.Popen")
    def test_successful_command_returns_without_error(self, mock_popen):
        proc = MagicMock()
        proc.communicate.return_value = ("output text", "")
        proc.returncode = 0
        mock_popen.return_value = proc
        result = execute_pipeline(_os_step([_shell_action("echo hello")]))
        assert not result.startswith("ERROR")

    @patch("subprocess.Popen")
    def test_timeout_degrades_to_background_success_not_a_hang(self, mock_popen):
        import subprocess as sp
        proc = MagicMock()
        proc.communicate.side_effect = sp.TimeoutExpired(cmd="slow_cmd", timeout=15)
        mock_popen.return_value = proc
        result = execute_pipeline(_os_step([_shell_action("slow_cmd")]))
        assert not result.startswith("ERROR")

    @patch("subprocess.Popen")
    @patch("os.path.isdir", return_value=True)
    def test_successful_mkdir_auto_opens_explorer_at_new_folder(self, mock_isdir, mock_popen):
        cli_proc = MagicMock()
        cli_proc.communicate.return_value = ("", "")
        cli_proc.returncode = 0
        explorer_proc = MagicMock()
        # First Popen call is the mkdir itself; second is the auto-opened Explorer.
        mock_popen.side_effect = [cli_proc, explorer_proc]

        execute_pipeline(_os_step([_shell_action('mkdir "C:\\Users\\test\\NewFolder"')]))

        assert mock_popen.call_count == 2
        second_call_cmd = mock_popen.call_args_list[1][0][0]
        assert "explorer" in second_call_cmd.lower()

    @patch("agentic_core.processor._get_routing_llm")
    @patch("subprocess.Popen")
    def test_failed_command_triggers_llm_self_healing_and_then_succeeds(self, mock_popen, mock_get_llm):
        failing = MagicMock()
        failing.communicate.return_value = ("", "command not found")
        failing.returncode = 1
        healed = MagicMock()
        healed.communicate.return_value = ("fixed output", "")
        healed.returncode = 0
        mock_popen.side_effect = [failing, healed]

        fixer_llm = MagicMock()
        fixer_llm.invoke.return_value = MagicMock(content="mkdir \"%USERPROFILE%\\Desktop\\fixed\"")
        mock_get_llm.return_value = fixer_llm

        result = execute_pipeline(_os_step([_shell_action("mkdir badcmd")]))

        assert mock_popen.call_count == 2
        # _get_routing_llm is called twice from this single patched target: once
        # to fix the failing command, once more afterward to summarize the
        # (now successful) command's stdout for the spoken response.
        assert fixer_llm.invoke.call_count == 2
        first_call_prompt = fixer_llm.invoke.call_args_list[0][0][0][0][1]
        assert "repair agent" in first_call_prompt
        assert not result.startswith("ERROR")
        assert "Task failed" not in result

    @patch("agentic_core.processor._get_routing_llm")
    @patch("subprocess.Popen")
    def test_exhausted_retries_returns_hard_failure_not_a_silent_success(self, mock_popen, mock_get_llm):
        always_fails = MagicMock()
        always_fails.communicate.return_value = ("", "still broken")
        always_fails.returncode = 1
        mock_popen.return_value = always_fails

        fixer_llm = MagicMock()
        fixer_llm.invoke.return_value = MagicMock(content="still broken")
        mock_get_llm.return_value = fixer_llm

        result = execute_pipeline(_os_step([_shell_action("permanently broken cmd")]))

        assert "Task failed" in result or "aborting" in result.lower()

    @patch("agentic_core.processor._get_routing_llm")
    @patch("subprocess.Popen")
    def test_llm_healing_call_itself_failing_does_not_crash(self, mock_popen, mock_get_llm):
        """The healing attempt is itself best-effort - if the LLM call raises,
        the loop must break out cleanly, not propagate the exception."""
        failing = MagicMock()
        failing.communicate.return_value = ("", "broken")
        failing.returncode = 1
        mock_popen.return_value = failing
        mock_get_llm.side_effect = Exception("LLM unavailable")

        result = execute_pipeline(_os_step([_shell_action("broken cmd")]))

        assert isinstance(result, str)
        assert "Task failed" in result or result.startswith("ERROR") or "aborting" in result.lower()


class TestGuiActionType:
    @patch("agentic_core.executor.execute_gui_command")
    def test_gui_action_dispatches_to_gui_engine(self, mock_gui_exec):
        mock_gui_exec.return_value = "Clicked the button."
        result = execute_pipeline(_os_step([
            {"type": "gui", "payload": "click", "value": "Submit", "resolved_x": 100, "resolved_y": 200}
        ]))
        mock_gui_exec.assert_called_once()
        assert not result.startswith("ERROR")

    @patch("agentic_core.executor.execute_gui_command")
    def test_gui_action_error_propagates_as_step_error(self, mock_gui_exec):
        mock_gui_exec.return_value = "ERROR: element not found"
        result = execute_pipeline(_os_step([
            {"type": "gui", "payload": "click", "value": "Missing", "resolved_x": 1, "resolved_y": 1}
        ]))
        assert result.startswith("ERROR")

    @patch("agentic_core.executor.resolve_element")
    @patch("agentic_core.executor.execute_gui_command")
    def test_click_without_coords_resolves_element_first(self, mock_gui_exec, mock_resolve):
        mock_resolve.return_value = (500, 300)
        mock_gui_exec.return_value = "Clicked."
        execute_pipeline(_os_step([
            {"type": "gui", "payload": "click", "value": "Submit", "label": "Submit button"}
        ]))
        mock_resolve.assert_called_once()
        simulated_intent = mock_gui_exec.call_args[0][0]
        assert simulated_intent["resolved_x"] == 500
        assert simulated_intent["resolved_y"] == 300


class TestReturnRouting:
    @patch("os.startfile")
    @patch("os.path.exists", return_value=True)
    def test_explorer_step_returns_the_boss_message(self, mock_exists, mock_startfile):
        result = execute_pipeline(_os_step([_shell_action("explorer C:\\Users\\test")]))
        assert "Boss" in result or "opened" in result.lower()

    @patch("subprocess.Popen")
    def test_diagnostic_speech_response_is_returned_verbatim(self, mock_popen):
        proc = MagicMock()
        proc.communicate.return_value = ("", "")
        proc.returncode = 0
        mock_popen.return_value = proc
        result = execute_pipeline(_os_step(
            [_shell_action("echo test")],
            speech_response="Running system diagnostic now.",
        ))
        assert result == "Running system diagnostic now."

    @patch("agentic_core.processor._get_routing_llm")
    @patch("subprocess.Popen")
    def test_stdout_is_summarized_via_llm_when_no_diagnostic_override(self, mock_popen, mock_get_llm):
        proc = MagicMock()
        proc.communicate.return_value = ("lots of raw terminal output here", "")
        proc.returncode = 0
        mock_popen.return_value = proc

        summarizer = MagicMock()
        summarizer.invoke.return_value = MagicMock(content="Here's a short summary.")
        mock_get_llm.return_value = summarizer

        result = execute_pipeline(_os_step([_shell_action("echo lots of raw terminal output here")]))

        summarizer.invoke.assert_called_once()
        assert result == "Here's a short summary."

    @patch("agentic_core.processor._get_routing_llm")
    @patch("subprocess.Popen")
    def test_summarization_failure_degrades_to_generic_success_message(self, mock_popen, mock_get_llm):
        proc = MagicMock()
        proc.communicate.return_value = ("some output", "")
        proc.returncode = 0
        mock_popen.return_value = proc
        mock_get_llm.side_effect = Exception("LLM down")

        result = execute_pipeline(_os_step([_shell_action("echo some output")]))

        assert not result.startswith("ERROR")
        assert "successfully executed" in result.lower()
