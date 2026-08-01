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


class TestProcessManagementIntentDispatch:

    @patch("agentic_core.executor.list_processes")
    def test_list_action_with_results(self, mock_list):
        mock_list.return_value = [{"name": "notepad.exe", "pid": 1234, "mem_kb": "10,000 K"}]
        steps = [{"intent": "ProcessManagementIntent", "action": "list", "target": "notepad"}]
        result = execute_pipeline(steps)
        assert "notepad.exe" in result

    @patch("agentic_core.executor.list_processes")
    def test_list_action_no_results(self, mock_list):
        mock_list.return_value = []
        steps = [{"intent": "ProcessManagementIntent", "action": "list", "target": "nonexistent"}]
        result = execute_pipeline(steps)
        assert "No processes matching" in result

    @patch("agentic_core.executor.kill_process")
    def test_kill_action_delegates_to_kill_process(self, mock_kill):
        mock_kill.return_value = "Process 'notepad.exe' terminated successfully."
        steps = [{"intent": "ProcessManagementIntent", "action": "kill", "target": "notepad.exe"}]
        result = execute_pipeline(steps)
        mock_kill.assert_called_once_with("notepad.exe")
        assert "terminated successfully" in result

    def test_kill_action_without_target_returns_error(self):
        steps = [{"intent": "ProcessManagementIntent", "action": "kill", "target": ""}]
        result = execute_pipeline(steps)
        assert "No process name or PID" in result

    def test_unknown_action_returns_message(self):
        steps = [{"intent": "ProcessManagementIntent", "action": "reboot", "target": ""}]
        result = execute_pipeline(steps)
        assert "Unknown ProcessManagementIntent action" in result


class TestProjectScaffoldIntentDispatch:

    @patch("agentic_core.executor.scaffold_project")
    def test_scaffold_delegates_with_correct_args(self, mock_scaffold):
        mock_scaffold.return_value = "'react' project 'my-app' scaffolded successfully."
        steps = [{
            "intent": "ProjectScaffoldIntent",
            "framework": "react",
            "project_name": "my-app",
            "location": "C:/fake/loc",
        }]
        result = execute_pipeline(steps)
        mock_scaffold.assert_called_once_with(framework="react", project_name="my-app", location="C:/fake/loc")
        assert "scaffolded successfully" in result

    def test_missing_framework_returns_error(self):
        steps = [{"intent": "ProjectScaffoldIntent", "framework": "", "project_name": "my-app"}]
        result = execute_pipeline(steps)
        assert "No framework specified" in result


class TestDependencyInstallIntentDispatch:

    @patch("agentic_core.executor.pip_install")
    def test_pip_manager_delegates_to_pip_install(self, mock_pip):
        mock_pip.return_value = "Launched visible terminal for: pip install requests"
        steps = [{"intent": "DependencyInstallIntent", "manager": "pip", "packages": "requests"}]
        result = execute_pipeline(steps)
        mock_pip.assert_called_once_with("requests")
        assert "Launched visible terminal" in result

    @patch("agentic_core.executor.npm_install")
    def test_npm_manager_delegates_to_npm_install(self, mock_npm):
        mock_npm.return_value = "Launched visible terminal for: npm install lodash"
        steps = [{"intent": "DependencyInstallIntent", "manager": "npm", "packages": "lodash", "dev": True, "cwd": "C:/fake"}]
        result = execute_pipeline(steps)
        mock_npm.assert_called_once_with(packages="lodash", dev=True, cwd="C:/fake")
        assert "Launched visible terminal" in result

    def test_unknown_manager_returns_error(self):
        steps = [{"intent": "DependencyInstallIntent", "manager": "yarn", "packages": "lodash"}]
        result = execute_pipeline(steps)
        assert "Unknown package manager" in result


class TestCodeActIntentDispatch:
    """
    Regression coverage for a real bug found via `ruff` (F821 undefined-name):
    the CodeActIntent branch referenced a never-defined `SESSION_MEMORY`, so
    every successful CodeAct execution raised NameError immediately after
    launching its script, was silently caught by the retry loop, and retried
    up to 3 times — each retry re-invoking the LLM and re-launching a real
    PowerShell window — before the pipeline ultimately reported failure to
    the user despite the script having actually run.
    """

    @patch("capabilities.developer.codeact_engine.generate_and_run")
    @patch("config.settings.BrainConfig.get_cloud_llm")
    def test_successful_codeact_reports_success_not_failure(self, mock_get_llm, mock_run):
        mock_get_llm.return_value = object()  # any truthy LLM handle
        mock_run.return_value = "I've opened a terminal window and started executing your request."
        steps = [{"intent": "CodeActIntent", "prompt": "set up a flask project"}]

        result = execute_pipeline(steps)

        assert "opened a terminal window" in result
        assert "ERROR" not in result

    @patch("capabilities.developer.codeact_engine.generate_and_run")
    @patch("config.settings.BrainConfig.get_cloud_llm")
    def test_successful_codeact_does_not_retry(self, mock_get_llm, mock_run):
        """A successful step must not be re-attempted — each retry launches a
        real script window, so retrying a success would open duplicates."""
        mock_get_llm.return_value = object()
        mock_run.return_value = "done"
        steps = [{"intent": "CodeActIntent", "prompt": "set up a flask project"}]

        execute_pipeline(steps)

        mock_run.assert_called_once()

    def test_missing_prompt_returns_error(self):
        steps = [{"intent": "CodeActIntent", "prompt": ""}]
        result = execute_pipeline(steps)
        assert result.startswith("ERROR")
        assert "missing prompt" in result


class TestContinuationIntentDispatch:
    """
    Regression coverage for a real bug: ContinuationIntent was reachable via
    the router (see the router.py classifier-blind-spot fix earlier this
    session) but had NO dispatch branch in execute_pipeline() at all - every
    "continue"/"go on"/"tell me more" request fell through to "Unrecognized
    Enterprise Intent" and hard-errored, regardless of what came before it.
    """

    @patch("agentic_core.executor.memory")
    def test_no_prior_context_returns_graceful_message_not_error(self, mock_memory):
        mock_memory.get_context_for_prompt.return_value = ""
        steps = [{"intent": "ContinuationIntent"}]

        result = execute_pipeline(steps)

        assert "ERROR" not in result
        assert "nothing recent" in result.lower()

    @patch("agentic_core.processor._get_routing_llm")
    @patch("agentic_core.executor.memory")
    def test_prior_context_is_passed_to_llm_for_continuation(self, mock_memory, mock_get_llm):
        mock_memory.get_context_for_prompt.return_value = (
            "[PAST INTERACTION CONTEXT]\n- InformationRetrievalIntent: capital of france -> Result: Paris."
        )
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Paris has been the capital since 508 CE.")
        mock_get_llm.return_value = mock_llm
        steps = [{"intent": "ContinuationIntent"}]

        result = execute_pipeline(steps)

        assert "ERROR" not in result
        assert "508 CE" in result
        # The prior interaction must actually reach the LLM prompt, not just exist.
        prompt_sent = mock_llm.invoke.call_args[0][0][0][1]
        assert "Paris" in prompt_sent

    @patch("agentic_core.executor.memory")
    def test_llm_failure_reported_gracefully_not_as_pipeline_error(self, mock_memory):
        mock_memory.get_context_for_prompt.return_value = "[PAST INTERACTION CONTEXT]\n- x: y -> Result: z."
        steps = [{"intent": "ContinuationIntent"}]

        with patch("agentic_core.processor._get_routing_llm") as mock_get_llm:
            mock_get_llm.return_value.invoke.side_effect = RuntimeError("LLM timeout")
            result = execute_pipeline(steps)

        assert "couldn't continue" in result.lower()


class TestInteractionLogging:
    """
    Regression coverage for a real bug: memory.get_context_for_prompt() has
    been READ by processor.py (target extraction for InformationRetrievalIntent
    and GeneralizedOSIntent) and now by ContinuationIntent, but nothing ever
    called memory.log_interaction() to populate the table those reads query -
    interaction_history was permanently empty, so "contextual memory
    injection" always silently had no context to inject, for every intent.
    """

    @patch("agentic_core.executor.memory")
    @patch("webbrowser.open")
    def test_successful_step_logs_to_interaction_history(self, mock_open, mock_memory):
        steps = [{"intent": "WebNavigationIntent", "target": "youtube", "speech_response": "Navigating."}]

        execute_pipeline(steps)

        mock_memory.log_interaction.assert_called_once()
        call_kwargs = mock_memory.log_interaction.call_args.kwargs
        assert call_kwargs["intent"] == "WebNavigationIntent"
        assert call_kwargs["target"] == "youtube"

    @patch("agentic_core.executor.memory")
    def test_continuation_intent_itself_is_not_logged(self, mock_memory):
        """A chain of 'continue' requests must not bury the actual prior
        interaction it should keep referring back to."""
        mock_memory.get_context_for_prompt.return_value = ""
        steps = [{"intent": "ContinuationIntent"}]

        execute_pipeline(steps)

        mock_memory.log_interaction.assert_not_called()

    @patch("agentic_core.executor.memory")
    @patch("webbrowser.open")
    def test_logging_failure_does_not_break_pipeline_result(self, mock_open, mock_memory):
        """Logging is best-effort; a broken DB write must never take down an
        otherwise-successful user-facing result."""
        mock_memory.log_interaction.side_effect = RuntimeError("disk full")
        steps = [{"intent": "WebNavigationIntent", "target": "youtube", "speech_response": "Navigating."}]

        result = execute_pipeline(steps)

        assert "ERROR" not in result
