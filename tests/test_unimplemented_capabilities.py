"""
tests/test_unimplemented_capabilities.py

Originally: regression tests locking in honest failure for AcademicResearchIntent,
DataModelingIntent, and SchedulerIntent while they were fabricated-success stubs
(hardcoded strings claiming work that was never done — "a 15% improvement over
baseline models", "I will remind you", a correlation in data never opened).

All three are now genuinely implemented (real PDF extraction + LLM summary,
real pandas EDA, real persisted reminders — see capabilities/developer/
academic_research.py, capabilities/developer/data_modeler.py,
capabilities/system/scheduler.py). "Always returns ERROR" is no longer the
correct behavior for a well-formed request against a real file/task, so the
tests asserting that outright have been removed rather than left to fail.

What's kept and still matters:
  - Genuinely unresolvable input (no file found, garbage target) must still
    fail HONESTLY (ERROR, no fabricated claim) — that's the same property,
    just scoped to inputs where failure is actually the correct answer now.
  - The exact old fabrications (a specific desktop path, a specific invented
    percentage, "I will remind you" as an unfulfilled promise) must never
    reappear, in either the failure path or the new success path.
  - The ERROR-prefix contract with api_wrapper.process_command() still holds.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from agentic_core.memory_hook import MemoryManager
from capabilities.developer.academic_research import handle_academic_research
from capabilities.developer.data_modeler import handle_data_modeling
from capabilities.system.scheduler import handle_scheduler


@pytest.fixture()
def isolated_memory(tmp_path, monkeypatch):
    """Isolated MemoryManager, closed on teardown even if the test body
    raises — a bare m.close() at the end of a test function only runs on
    the happy path and silently leaks the sqlite connection on failure."""
    m = MemoryManager(db_path=str(tmp_path / "db.sqlite"))
    monkeypatch.setattr("capabilities.system.scheduler._memory", lambda: m)
    yield m
    m.close()

# The exact old fabrications. Substring match is intentional — a reworded
# version of the same lie is still the same lie.
_FABRICATION_MARKERS = [
    "i have analyzed",
    "i have analysed",
    "i handled the missing values",
    "saved to your desktop",
    "saved to your workspace",
    "improvement over baseline",
    "strong positive correlation between the primary features",
    "i will remind you",
    "i have planned",
    "synced the threat vectors",
    "to your personal schedule",
    "to your calendar",
]


def _assert_no_fabricated_claims(result: str):
    lowered = result.lower()
    for marker in _FABRICATION_MARKERS:
        assert marker not in lowered, (
            f"Response contained the old fabricated claim {marker!r}. "
            f"Full response: {result!r}"
        )


class TestAcademicResearchFailsHonestlyOnUnresolvableInput:
    """Genuinely unimplemented in the old stub; now genuinely implemented,
    but a request that can't be fulfilled (no such file) must still fail
    honestly rather than claim success."""

    def test_no_filename_in_request_reports_failure(self):
        result = handle_academic_research("", "summarize a paper for me")
        assert result.startswith("ERROR")

    def test_unresolvable_file_reports_failure_not_success(self, tmp_path):
        with patch("capabilities.developer.academic_research._SEARCH_DIRS", [str(tmp_path)]):
            result = handle_academic_research("nonexistent_paper.pdf", "")
        assert result.startswith("ERROR")

    def test_does_not_fabricate_results_on_failure(self):
        _assert_no_fabricated_claims(handle_academic_research("", "summarize"))

    def test_does_not_claim_a_desktop_file_was_saved_on_failure(self):
        """The original stub told users a summary was on their desktop
        regardless of outcome. A failure path must not still say that."""
        result = handle_academic_research("", "analyze").lower()
        assert "desktop" not in result


class TestDataModelingFailsHonestlyOnUnresolvableInput:
    def test_no_filename_in_request_reports_failure(self):
        result = handle_data_modeling("", "run an EDA for me")
        assert result.startswith("ERROR")

    def test_unresolvable_file_reports_failure_not_success(self, tmp_path):
        with patch("capabilities.developer.data_modeler._SEARCH_DIRS", [str(tmp_path)]):
            result = handle_data_modeling("nonexistent.csv", "")
        assert result.startswith("ERROR")

    def test_does_not_fabricate_results_on_failure(self):
        _assert_no_fabricated_claims(handle_data_modeling("", "run EDA"))

    def test_failure_path_never_mentions_correlation(self):
        """A correlation figure may only appear when one was genuinely
        computed from real data (see test_data_modeler.py for that case).
        On a failure path — no file resolved — it must never appear."""
        result = handle_data_modeling("", "run EDA").lower()
        assert "correlation" not in result


class TestSchedulerNeverFabricatesAPromise:
    """The most damaging old fabrication: a user told 'I will remind you'
    reasonably stops tracking the thing themselves, and finds out nothing
    was ever set at the moment it was needed. The new implementation
    persists real reminders but still does not send active notifications
    (see the module docstring) — so it must never claim it will actively
    remind the user, in either the plain-task or timed-reminder path."""

    def test_plain_task_never_claims_it_will_remind(self, isolated_memory):
        result = handle_scheduler("", "add buy milk to my list").lower()
        assert "i will remind" not in result
        assert "remind you" not in result

    def test_timed_reminder_never_claims_active_notification(self, isolated_memory):
        result = handle_scheduler("", "remind me to submit the thesis tomorrow at 9am").lower()
        assert "i will remind" not in result
        assert "don't yet send active notifications" in result

    def test_no_description_reports_failure_honestly(self, isolated_memory):
        result = handle_scheduler("", "")
        assert result.startswith("ERROR")


class TestPipelineClassifiesGenuineFailuresAsFailed:
    """The ERROR prefix is not cosmetic — it is what api_wrapper keys on to
    set execution='Failed'. Still holds for inputs where failure is the
    honestly correct outcome."""

    def test_error_prefix_on_unresolvable_inputs(self, tmp_path, isolated_memory):
        with patch("capabilities.developer.academic_research._SEARCH_DIRS", [str(tmp_path)]), \
             patch("capabilities.developer.data_modeler._SEARCH_DIRS", [str(tmp_path)]):
            results = (
                handle_academic_research("no_such_paper.pdf", ""),
                handle_data_modeling("no_such_data.csv", ""),
                handle_scheduler("", ""),
            )
        for result in results:
            assert isinstance(result, str)
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
