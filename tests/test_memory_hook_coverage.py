"""
tests/test_memory_hook_coverage.py

Coverage for the uncovered branches in agentic_core/memory_hook.py.

tests/test_memory.py covers the URL-template happy paths and basic interaction
logging. This file targets what it does not reach: the path cache (Fix 2.9,
used by the executor's Explorer interceptor), the DB-error fallbacks, and the
intent-filtered context retrieval that processor.py depends on.

Every test uses an isolated in-memory or tmp_path database rather than the
module-level singleton, so nothing here touches the developer's real
sentinal_memory.db.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.memory_hook import MemoryManager


@pytest.fixture()
def mem(tmp_path):
    """Isolated DB per test — never the real on-disk singleton."""
    m = MemoryManager(db_path=str(tmp_path / "test_memory.db"))
    yield m
    m.close()


# ══════════════════════════════════════════════════════════════════════════════
# Path cache (Fix 2.9) — used by executor.py's Explorer interceptor
# ══════════════════════════════════════════════════════════════════════════════
class TestPathCache:
    def test_save_and_retrieve_an_existing_path(self, mem, tmp_path):
        real_dir = tmp_path / "Projects"
        real_dir.mkdir()
        mem.save_cached_path("projects", str(real_dir))
        assert mem.get_cached_path("projects") == str(real_dir)

    def test_lookup_is_case_and_whitespace_insensitive(self, mem, tmp_path):
        real_dir = tmp_path / "Downloads"
        real_dir.mkdir()
        mem.save_cached_path("  DoWnLoAdS  ", str(real_dir))
        assert mem.get_cached_path("downloads") == str(real_dir)
        assert mem.get_cached_path("DOWNLOADS") == str(real_dir)

    def test_uncached_folder_returns_none(self, mem):
        assert mem.get_cached_path("never_cached_folder") is None

    def test_cached_path_that_no_longer_exists_returns_none(self, mem, tmp_path):
        """The critical branch: a cached path is only useful if it still
        exists. Returning a stale path would send the executor's Explorer
        interceptor to a directory the user has since moved or deleted."""
        gone = tmp_path / "DeletedFolder"
        gone.mkdir()
        mem.save_cached_path("deleted", str(gone))
        assert mem.get_cached_path("deleted") == str(gone)

        gone.rmdir()
        assert mem.get_cached_path("deleted") is None

    def test_saving_the_same_folder_twice_overwrites(self, mem, tmp_path):
        first = tmp_path / "v1"
        second = tmp_path / "v2"
        first.mkdir()
        second.mkdir()
        mem.save_cached_path("target", str(first))
        mem.save_cached_path("target", str(second))
        assert mem.get_cached_path("target") == str(second)


# ══════════════════════════════════════════════════════════════════════════════
# get_context_for_prompt — intent filtering and failure fallback
# ══════════════════════════════════════════════════════════════════════════════
class TestContextRetrieval:
    def test_intent_filter_returns_only_matching_interactions(self, mem):
        mem.log_interaction("2026-01-01T00:00:00", "InformationRetrievalIntent", "weather", "sunny")
        mem.log_interaction("2026-01-01T00:01:00", "ApplicationLaunchIntent", "notepad", "opened")
        mem.log_interaction("2026-01-01T00:02:00", "InformationRetrievalIntent", "news", "headlines")

        context = mem.get_context_for_prompt(intent_filter="InformationRetrievalIntent")

        assert "weather" in context
        assert "news" in context
        assert "notepad" not in context

    def test_empty_history_returns_empty_string_not_a_header(self, mem):
        """Must return "" — a bare "[PAST INTERACTION CONTEXT]" header with no
        entries would be injected into the LLM prompt as meaningless noise."""
        assert mem.get_context_for_prompt() == ""

    def test_intent_filter_with_no_matches_returns_empty_string(self, mem):
        mem.log_interaction("2026-01-01T00:00:00", "ApplicationLaunchIntent", "notepad", "opened")
        assert mem.get_context_for_prompt(intent_filter="DataModelingIntent") == ""

    def test_db_error_during_retrieval_degrades_to_empty_string(self, mem):
        """Context injection is an enhancement, never a hard dependency — a
        broken read must not propagate an exception into the request path."""
        mem.log_interaction("2026-01-01T00:00:00", "ApplicationLaunchIntent", "notepad", "opened")
        mem.close()  # cursor now unusable
        assert mem.get_context_for_prompt() == ""

    def test_long_result_lines_are_truncated_to_150_chars(self, mem):
        mem.log_interaction("2026-01-01T00:00:00", "InformationRetrievalIntent", "x", "y" * 500)
        context = mem.get_context_for_prompt()
        body = [ln for ln in context.splitlines() if ln.startswith("- ")]
        assert body and all(len(ln) <= 150 for ln in body)

    def test_total_context_is_capped_and_marked_as_truncated(self, mem):
        for i in range(40):
            mem.log_interaction(f"2026-01-01T00:{i:02d}:00", "InformationRetrievalIntent", f"q{i}", "z" * 120)
        context = mem.get_context_for_prompt(limit=40)
        assert len(context) <= 1030  # 1000 + the truncation marker
        assert "context truncated" in context


# ══════════════════════════════════════════════════════════════════════════════
# get_recent_interactions
# ══════════════════════════════════════════════════════════════════════════════
class TestRecentInteractions:
    def test_returns_most_recent_first(self, mem):
        mem.log_interaction("2026-01-01T00:00:00", "ApplicationLaunchIntent", "first", "ok")
        mem.log_interaction("2026-01-01T00:01:00", "ApplicationLaunchIntent", "second", "ok")
        rows = mem.get_recent_interactions(limit=2)
        assert rows[0][2] == "second"

    def test_limit_is_respected(self, mem):
        for i in range(10):
            mem.log_interaction(f"2026-01-01T00:{i:02d}:00", "ApplicationLaunchIntent", f"t{i}", "ok")
        assert len(mem.get_recent_interactions(limit=3)) == 3

    def test_optional_fields_may_be_omitted(self, mem):
        """target/result/platform are all nullable — logging a bare intent
        must not fail, since executor.py logs some intents with no target."""
        mem.log_interaction("2026-01-01T00:00:00", "ConversationalIntent")
        rows = mem.get_recent_interactions(limit=1)
        assert rows[0][1] == "ConversationalIntent"


# ══════════════════════════════════════════════════════════════════════════════
# URL template validation — the security-relevant rejection branches
# ══════════════════════════════════════════════════════════════════════════════
class TestUrlTemplateValidation:
    @pytest.mark.parametrize("bad_template", [
        "http://insecure.com/search/{query}",      # not https
        "javascript:alert(1)/{query}",              # scheme injection
        "file:///c:/windows/{query}",               # local file scheme
        "data:text/html,{query}",                   # data URI
    ])
    def test_unsafe_schemes_are_rejected(self, mem, bad_template):
        """Cache poisoning guard: a malicious LLM-generated template would
        otherwise persist and be reused for every future request on that
        platform."""
        with pytest.raises(ValueError):
            mem.save_url_template("evil", bad_template)

    def test_template_without_query_placeholder_is_rejected(self, mem):
        with pytest.raises(ValueError, match="query"):
            mem.save_url_template("nosub", "https://example.com/search")

    def test_empty_template_is_rejected(self, mem):
        with pytest.raises(ValueError):
            mem.save_url_template("empty", "")

    def test_valid_https_template_with_placeholder_is_accepted(self, mem):
        mem.save_url_template("good", "https://example.com/search/{query}")
        assert mem.get_url_template("good") == "https://example.com/search/{query}"

    def test_platform_lookup_is_case_insensitive(self, mem):
        mem.save_url_template("YouTube", "https://youtube.com/results?q={query}")
        assert mem.get_url_template("youtube") is not None
        assert mem.get_url_template("YOUTUBE") is not None


# ══════════════════════════════════════════════════════════════════════════════
# Scheduled tasks / reminders — real persistence for SchedulerIntent
# ══════════════════════════════════════════════════════════════════════════════
class TestScheduledTasks:
    def test_registered_task_appears_in_pending_list(self, mem):
        mem.register_scheduled_task("t1", "call mom", None, 1000.0)
        pending = mem.get_pending_scheduled_tasks()
        assert len(pending) == 1
        assert pending[0]["description"] == "call mom"
        assert pending[0]["due_at"] is None

    def test_undated_tasks_sort_after_dated_ones(self, mem):
        mem.register_scheduled_task("t1", "someday task", None, 1000.0)
        mem.register_scheduled_task("t2", "urgent task", 500.0, 1000.0)
        pending = mem.get_pending_scheduled_tasks()
        assert [t["task_id"] for t in pending] == ["t2", "t1"]

    def test_dated_tasks_sort_soonest_first(self, mem):
        mem.register_scheduled_task("t1", "later", 2000.0, 1000.0)
        mem.register_scheduled_task("t2", "sooner", 1500.0, 1000.0)
        pending = mem.get_pending_scheduled_tasks()
        assert [t["task_id"] for t in pending] == ["t2", "t1"]

    def test_completed_task_does_not_appear_in_pending_list(self, mem):
        mem.register_scheduled_task("t1", "finish report", None, 1000.0)
        mem.complete_scheduled_task("t1", 2000.0)
        assert mem.get_pending_scheduled_tasks() == []

    def test_find_by_keyword_is_case_insensitive_substring_match(self, mem):
        mem.register_scheduled_task("t1", "call the DENTIST", None, 1000.0)
        matches = mem.find_pending_tasks_by_keyword("dentist")
        assert len(matches) == 1
        assert matches[0]["task_id"] == "t1"

    def test_find_by_keyword_excludes_completed_tasks(self, mem):
        mem.register_scheduled_task("t1", "call the dentist", None, 1000.0)
        mem.complete_scheduled_task("t1", 2000.0)
        assert mem.find_pending_tasks_by_keyword("dentist") == []

    def test_find_by_keyword_returns_multiple_real_matches(self, mem):
        mem.register_scheduled_task("t1", "call the dentist", None, 1000.0)
        mem.register_scheduled_task("t2", "email the dentist office", None, 1000.0)
        assert len(mem.find_pending_tasks_by_keyword("dentist")) == 2

    def test_registering_same_task_id_twice_overwrites(self, mem):
        mem.register_scheduled_task("t1", "first version", None, 1000.0)
        mem.register_scheduled_task("t1", "updated version", None, 1000.0)
        pending = mem.get_pending_scheduled_tasks()
        assert len(pending) == 1
        assert pending[0]["description"] == "updated version"
