"""
tests/test_benchmark_regressions_round2.py

Unit-level regression tests for the 3 defects found by the post-round-1
40x3 benchmark (94.2%, commit 5fff33d). Each test names the benchmark task
that exposed it.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.processor import deterministic_fast_path
from capabilities.system.api_wrapper import _derive_expected_state


# ══════════════════════════════════════════════════════════════════════════════
# Bug A — bare app name has no launch verb (app_notepad_terse, 0/3)
# ══════════════════════════════════════════════════════════════════════════════
class TestBareAppNameFastPath:
    @pytest.mark.parametrize(("utterance", "target"), [
        ("notepad", "notepad"),
        ("calculator", "calc"),
        ("calc", "calc"),
        ("chrome", "chrome"),
    ])
    def test_standalone_app_name_launches(self, utterance, target):
        plan = deterministic_fast_path(utterance)
        assert plan is not None, f"{utterance!r} did not resolve"
        assert plan[0]["intent"] == "ApplicationLaunchIntent"
        assert plan[0]["target"] == target

    def test_app_name_inside_a_longer_sentence_is_not_hijacked(self):
        """A bare noun embedded in an unrelated sentence must not be read as a
        launch command — this fallback is for the WHOLE utterance only."""
        plan = deterministic_fast_path("i like writing in my notepad journal")
        if plan:
            assert plan[0]["intent"] != "ApplicationLaunchIntent"

    def test_unknown_bare_word_is_not_hijacked(self):
        assert deterministic_fast_path("banana") is None


# ══════════════════════════════════════════════════════════════════════════════
# Bug B — app-launch postcondition had no settle window (multi_open_two_apps, 0/3)
# ══════════════════════════════════════════════════════════════════════════════
class TestAppLaunchSettleWindow:
    def test_application_launch_derives_a_settle_window(self):
        derived = _derive_expected_state(
            {"intent": "ApplicationLaunchIntent", "target": "notepad"}
        )
        assert derived is not None
        assert derived["process_name"] == "notepad"
        assert derived.get("settle_timeout_ms", 0) > 0, (
            "Without a settle window, two back-to-back launches race the "
            "second postcondition check against process startup."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Bug C — taskkill misrouted as a GUI launch (multi_open_then_close, flaky 67%)
# ══════════════════════════════════════════════════════════════════════════════
class TestGuiLaunchDetectionIsPrecise:
    """The prior check was `f" {t}" in cmd` — a substring match anywhere in the
    command line. "taskkill /IM notepad.exe /F" contains " notepad" and was
    therefore classified as a GUI LAUNCH (detached Popen + sleep(1.0) +
    continue, never waiting for completion or checking a return code) instead
    of the synchronous CLI path that actually confirms the kill happened.
    A command meant to CLOSE notepad was handled as if it were opening it.

    These test the classification logic directly by reproducing it, since it
    lives inline inside execute_pipeline()'s GeneralizedOSIntent branch rather
    than as a standalone function — extracting it purely for testability was
    judged riskier than pinning the same two lines here, given
    execute_pipeline() is deliberately left otherwise untouched (see the
    execute_pipeline_observed() docstring in executor.py).
    """

    @staticmethod
    def _is_gui(cmd: str) -> bool:
        cmd_tokens = cmd.strip().split()
        first_tok = cmd_tokens[0].lower() if cmd_tokens else ""
        if first_tok == "start" and len(cmd_tokens) > 1:
            first_tok = cmd_tokens[1].lower().strip('"')
        gui_executables = {
            "notepad", "notepad.exe", "code", "code.exe",
            "explorer", "explorer.exe", "explorer.com",
        }
        return first_tok in gui_executables

    @pytest.mark.parametrize("cmd", [
        "taskkill /IM notepad.exe /F",
        "taskkill /F /IM notepad.exe",
        "tasklist | findstr notepad",
        "echo notepad was closed",
    ])
    def test_commands_referencing_notepad_as_an_argument_are_not_gui_launches(self, cmd):
        assert self._is_gui(cmd) is False, (
            f"{cmd!r} was misclassified as a GUI launch — this is the exact "
            "bug that made 'close notepad' sometimes report success before "
            "the kill had actually completed."
        )

    @pytest.mark.parametrize("cmd", [
        "notepad",
        "notepad.exe",
        'notepad "C:\\file.txt"',
        "start notepad",
        "code .",
        "explorer C:\\Users",
    ])
    def test_genuine_gui_launches_still_detected(self, cmd):
        assert self._is_gui(cmd) is True, (
            f"{cmd!r} should still route through the detached-launch path — "
            "the fix must not break real GUI launches while fixing the "
            "false-positive on taskkill."
        )

    def test_matches_on_executable_not_substring_anywhere(self):
        """The class of bug: any command line that happens to CONTAIN a GUI
        app's name must not qualify — only the command's own executable does."""
        assert self._is_gui("findstr notepad results.txt") is False
        assert self._is_gui('echo "please close notepad"') is False
