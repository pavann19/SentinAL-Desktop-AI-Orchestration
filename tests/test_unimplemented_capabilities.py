"""
tests/test_unimplemented_capabilities.py

Regression tests for capabilities that are not implemented yet.

Found while extending postcondition coverage (S1): handle_academic_research()
and handle_data_modeling() were stubs that returned hardcoded strings claiming
work had been done — "I have saved a detailed summary to your desktop",
"The visualizations have been saved to your workspace" — plus invented
quantitative findings ("a 15% improvement over baseline models", "a strong
positive correlation between the primary features").

Nothing was retrieved, analysed, or written. And because neither string started
with "ERROR", api_wrapper.process_command() classified the pipeline run as
execution="Success", so the fabrication passed through the whole system
unchallenged.

That is a worse failure mode than an ordinary silent failure: the user is told a
file exists that does not, and given a statistical finding about data that was
never opened. These tests lock in honest failure, and are written so they fail
loudly if anyone reintroduces a fabricated-success stub.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from capabilities.developer.academic_research import handle_academic_research
from capabilities.developer.data_modeler import handle_data_modeling
from capabilities.system.scheduler import handle_scheduler

# Claims that may only appear in output if the work was actually performed.
# Substring match is intentional — a reworded fabrication is still a fabrication.
_FABRICATION_MARKERS = [
    "i have analyzed",
    "i have analysed",
    "i handled the missing values",
    "have been saved",
    "i have saved",
    "saved to your desktop",
    "saved to your workspace",
    "improvement over baseline",
    "strong positive correlation",
    "correlation matrix",
    "i will remind you",
    "i have planned",
    "synced the threat vectors",
    "added '",
    "to your personal schedule",
    "to your calendar",
]


def _assert_no_fabricated_claims(result: str):
    lowered = result.lower()
    for marker in _FABRICATION_MARKERS:
        assert marker not in lowered, (
            f"Unimplemented capability claimed {marker!r} in its response. "
            f"An unimplemented capability must not report work it did not do. "
            f"Full response: {result!r}"
        )


class TestAcademicResearchFailsHonestly:
    def test_reports_failure_not_success(self):
        result = handle_academic_research("attention is all you need", "summarize it")
        assert result.startswith("ERROR"), (
            "Must start with ERROR so api_wrapper.process_command() classifies the run "
            "as execution='Failed'. Without the prefix the pipeline reports Success."
        )

    def test_does_not_fabricate_results(self):
        _assert_no_fabricated_claims(
            handle_academic_research("attention is all you need", "summarize it")
        )

    def test_does_not_claim_a_file_was_saved(self):
        """The original stub told users a summary was on their desktop. Nothing
        was ever written, so a user would go looking for a file that isn't there."""
        result = handle_academic_research("some paper", "analyze").lower()
        assert "desktop" not in result

    def test_says_what_is_actually_unavailable(self):
        """Honest failure means explaining the limitation, not just erroring."""
        result = handle_academic_research("some paper", "analyze").lower()
        assert "isn't implemented" in result or "not implemented" in result


class TestDataModelingFailsHonestly:
    def test_reports_failure_not_success(self):
        result = handle_data_modeling("sales.csv", "run EDA")
        assert result.startswith("ERROR")

    def test_does_not_fabricate_results(self):
        _assert_no_fabricated_claims(handle_data_modeling("sales.csv", "run EDA"))

    def test_does_not_invent_a_statistical_finding(self):
        """The original stub reported a correlation in a dataset it never opened.
        Acting on a fabricated statistical result is materially worse than being
        told the feature doesn't exist."""
        result = handle_data_modeling("sales.csv", "run EDA").lower()
        assert "correlation" not in result

    def test_says_what_is_actually_unavailable(self):
        result = handle_data_modeling("sales.csv", "run EDA").lower()
        assert "isn't implemented" in result or "not implemented" in result


class TestSchedulerFailsHonestly:
    """The scheduler stub branched on prompt keywords and returned a different
    fabricated confirmation for each — so the reply was tailored to what the user
    asked for, which made it read as though the system had understood and acted."""

    @pytest.mark.parametrize("prompt", [
        "plan a holiday itinerary for Goa",
        "process the defense analytics schedule",
        "remind me to submit the thesis",
        "set a timer for 10 minutes",
        "add buy milk to my list",
        "",
    ])
    def test_every_branch_reports_failure(self, prompt):
        result = handle_scheduler("some task", prompt)
        assert result.startswith("ERROR"), (
            f"Prompt {prompt!r} produced a non-ERROR result: {result!r}. "
            "Each keyword branch previously returned its own fabricated confirmation."
        )

    @pytest.mark.parametrize("prompt", [
        "plan a holiday itinerary for Goa",
        "remind me to submit the thesis",
        "add buy milk to my list",
    ])
    def test_no_branch_fabricates(self, prompt):
        _assert_no_fabricated_claims(handle_scheduler("some task", prompt))

    def test_never_promises_a_reminder(self):
        """The most damaging claim: a user told 'I will remind you' reasonably
        stops tracking the thing themselves, and finds out it was never set at
        the moment the reminder was needed — too late to recover."""
        result = handle_scheduler("submit the thesis", "remind me to submit the thesis").lower()
        assert "remind you" not in result
        assert "will remind" not in result

    def test_tells_the_user_to_track_it_themselves(self):
        """Honest failure here means handing responsibility back explicitly,
        since the user may have already stopped tracking it."""
        result = handle_scheduler("x", "remind me about x").lower()
        assert "yourself" in result or "no reminder will fire" in result


class TestFailsHonestlyRegardlessOfInput:
    @pytest.mark.parametrize("target", ["", "   ", "x" * 500, "../../etc/passwd", None])
    def test_academic_research_never_reports_success(self, target):
        result = handle_academic_research(target, "prompt")
        assert result.startswith("ERROR")
        _assert_no_fabricated_claims(result)

    @pytest.mark.parametrize("target", ["", "   ", "x" * 500, "../../etc/passwd", None])
    def test_data_modeling_never_reports_success(self, target):
        result = handle_data_modeling(target, "prompt")
        assert result.startswith("ERROR")
        _assert_no_fabricated_claims(result)


class TestPipelineClassifiesTheseAsFailed:
    """The ERROR prefix is not cosmetic — it is what api_wrapper keys on to set
    execution='Failed'. This asserts the contract those handlers depend on."""

    def test_error_prefix_is_what_the_pipeline_checks(self):
        for result in (
            handle_academic_research("paper", "p"),
            handle_data_modeling("data.csv", "p"),
            handle_scheduler("task", "remind me"),
        ):
            assert isinstance(result, str)
            # Mirrors the check in api_wrapper.process_command()
            assert result.startswith("ERROR") is True


class TestImplementedCapabilitiesAreNotAffected:
    """Guard against over-correcting. sys_utility, window_manager, dictation and
    media_control make similar-sounding claims ("I have taken a screenshot and
    physically saved it...") but genuinely do the work via PowerShell/pyautogui,
    and already fail honestly on error. They must keep their success messages —
    the defect was fabrication, not confident phrasing."""

    def test_real_handlers_still_import_and_are_callable(self):
        from capabilities.system.dictation import handle_dictation
        from capabilities.system.media_control import handle_media_control
        from capabilities.system.sys_utility import handle_sys_utility
        from capabilities.system.window_manager import handle_window_management

        for fn in (handle_sys_utility, handle_window_management, handle_dictation, handle_media_control):
            assert callable(fn)

    def test_real_handlers_reject_empty_input_without_erroring_out(self):
        """Their empty-input guards are honest already and must stay untouched."""
        from capabilities.system.media_control import handle_media_control
        from capabilities.system.sys_utility import handle_sys_utility

        assert "didn't catch" in handle_sys_utility("").lower()
        assert "couldn't understand" in handle_media_control("", "").lower()
