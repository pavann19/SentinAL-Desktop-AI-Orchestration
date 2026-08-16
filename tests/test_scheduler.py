"""
tests/test_scheduler.py
Real tests for capabilities/system/scheduler.py's SchedulerIntent implementation.

Uses a real isolated MemoryManager (tmp_path SQLite db, same pattern as
tests/test_memory_hook_coverage.py) so persistence is genuinely exercised,
not mocked. dateparser is real too — no network calls, pure local parsing.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.memory_hook import MemoryManager
from capabilities.system.scheduler import handle_scheduler


@pytest.fixture()
def isolated_memory(tmp_path, monkeypatch):
    """Points scheduler.py's _memory() at an isolated tmp_path db instead of
    the real on-disk singleton, for the duration of the test."""
    m = MemoryManager(db_path=str(tmp_path / "test_scheduler.db"))
    monkeypatch.setattr("capabilities.system.scheduler._memory", lambda: m)
    yield m
    m.close()


class TestAddTask:
    def test_plain_task_is_saved_and_listed(self, isolated_memory):
        result = handle_scheduler("", "add buy milk to my list")
        assert not result.startswith("ERROR")
        assert "buy milk" in result.lower() or "milk to my list" in result.lower()
        assert len(isolated_memory.get_pending_scheduled_tasks()) == 1

    def test_reminder_leadin_is_stripped_from_stored_description(self, isolated_memory):
        handle_scheduler("", "remind me to call mom")
        pending = isolated_memory.get_pending_scheduled_tasks()
        assert pending[0]["description"] == "call mom"

    def test_target_is_preferred_over_prompt_when_present(self, isolated_memory):
        handle_scheduler("call mom", "remind me to call mom tonight")
        pending = isolated_memory.get_pending_scheduled_tasks()
        assert pending[0]["description"] == "call mom"

    def test_reminder_with_a_time_gets_a_due_at_and_says_no_active_alert(self, isolated_memory):
        result = handle_scheduler("", "remind me to call mom tomorrow at 9am")
        assert not result.startswith("ERROR")
        assert "don't yet send active notifications" in result
        pending = isolated_memory.get_pending_scheduled_tasks()
        assert pending[0]["due_at"] is not None

    def test_plain_task_with_no_time_gets_no_due_at(self, isolated_memory):
        handle_scheduler("", "add buy milk to my list")
        pending = isolated_memory.get_pending_scheduled_tasks()
        assert pending[0]["due_at"] is None

    def test_empty_request_returns_honest_error(self, isolated_memory):
        result = handle_scheduler("", "")
        assert result.startswith("ERROR")
        assert isolated_memory.get_pending_scheduled_tasks() == []


class TestListTasks:
    def test_empty_list_says_so_honestly(self, isolated_memory):
        result = handle_scheduler("", "what's on my schedule today")
        assert "empty" in result.lower()

    def test_pending_tasks_are_genuinely_listed(self, isolated_memory):
        isolated_memory.register_scheduled_task("t1", "call mom", None, time.time())
        isolated_memory.register_scheduled_task("t2", "buy milk", None, time.time())
        result = handle_scheduler("", "what do i have planned")
        assert "call mom" in result
        assert "buy milk" in result
        assert "2 pending" in result

    def test_completed_tasks_are_not_listed(self, isolated_memory):
        isolated_memory.register_scheduled_task("t1", "call mom", None, time.time())
        isolated_memory.complete_scheduled_task("t1", time.time())
        result = handle_scheduler("", "show my tasks")
        assert "call mom" not in result


class TestCancelTask:
    def test_unique_match_gets_cancelled(self, isolated_memory):
        isolated_memory.register_scheduled_task("t1", "call the dentist", None, time.time())
        result = handle_scheduler("dentist", "cancel my dentist reminder")
        assert "Cancelled" in result
        assert isolated_memory.get_pending_scheduled_tasks() == []

    def test_no_match_returns_honest_error(self, isolated_memory):
        result = handle_scheduler("dentist", "cancel my dentist reminder")
        assert result.startswith("ERROR")
        assert "couldn't find" in result

    def test_ambiguous_match_lists_options_instead_of_guessing(self, isolated_memory):
        isolated_memory.register_scheduled_task("t1", "call the dentist", None, time.time())
        isolated_memory.register_scheduled_task("t2", "email the dentist office", None, time.time())
        result = handle_scheduler("dentist", "cancel my dentist reminder")
        assert "matches 2 pending items" in result
        assert "call the dentist" in result
        assert "email the dentist office" in result
        # Neither was silently completed while we're asking the user to disambiguate.
        assert len(isolated_memory.get_pending_scheduled_tasks()) == 2

    def test_no_keyword_after_stripping_triggers_returns_honest_error(self, isolated_memory):
        result = handle_scheduler("", "cancel my reminder")
        assert result.startswith("ERROR")


class TestParseDueAt:
    def test_free_text_sentence_with_embedded_time_is_parsed(self):
        from capabilities.system.scheduler import _parse_due_at
        assert _parse_due_at("remind me to call mom tomorrow at 9am") is not None

    def test_plain_sentence_with_no_time_returns_none(self):
        from capabilities.system.scheduler import _parse_due_at
        assert _parse_due_at("add buy milk to my list") is None

    def test_ordinary_words_are_not_misread_as_dates(self):
        # Regression guard for dateparser.search's known false-positive
        # behavior on short common words ("me", "to") - this project's
        # narrower time-hint regex must not reproduce that failure mode.
        from capabilities.system.scheduler import _parse_due_at
        assert _parse_due_at("remind me to water the plants") is None

    def test_bare_tonight_is_understood_despite_dateparser_gap(self):
        # dateparser.parse("tonight") alone returns None even though it
        # handles "today"/"tomorrow" fine - regression guard for the
        # explicit "tonight" -> "today 8pm" mapping that works around it.
        from capabilities.system.scheduler import _parse_due_at
        assert _parse_due_at("remind me to submit the assignment tonight") is not None

    def test_for_n_minutes_timer_phrasing_is_understood(self):
        # dateparser understands "in 20 minutes" but not "for 20 minutes" -
        # regression guard for the preposition translation that works
        # around it, so "set a timer for 20 minutes" gets a real due_at
        # instead of silently degrading to an undated task.
        from capabilities.system.scheduler import _parse_due_at
        assert _parse_due_at("set a timer for 20 minutes") is not None
