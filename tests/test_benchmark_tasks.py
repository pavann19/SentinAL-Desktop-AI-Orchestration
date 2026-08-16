"""
tests/test_benchmark_tasks.py

Real unit tests for benchmarks/tasks.py's helper functions backing the
scheduler/research categories that replaced the old "unimplemented capability
refusal" category — DataModelingIntent, AcademicResearchIntent, and
SchedulerIntent are genuinely implemented now (see capabilities/), so the
benchmark verifies real positive outcomes (a file appeared, a row persisted)
instead of asserting refusal. These are the cheap, fast guard rails around
that verification logic; benchmarks/run_benchmark.py remains the real
end-to-end check.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from benchmarks.tasks import (
    CAT_RESEARCH,
    CAT_SCHED,
    _make_csv,
    _make_minimal_pdf,
    _newer_file_exists,
    _scheduler_task_persisted,
    build_research_tasks,
    build_scheduler_tasks,
)


class TestMakeMinimalPdf:
    def test_produces_a_real_pypdf_extractable_pdf(self, tmp_path):
        pdf_path = tmp_path / "test.pdf"
        _make_minimal_pdf(str(pdf_path), "attention mechanisms and transformers")
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        text = reader.pages[0].extract_text()
        assert "attention mechanisms and transformers" in text

    def test_creates_parent_directory_if_missing(self, tmp_path):
        pdf_path = tmp_path / "nested" / "dir" / "test.pdf"
        _make_minimal_pdf(str(pdf_path), "hello")
        assert pdf_path.exists()


class TestMakeCsv:
    def test_produces_a_real_pandas_readable_csv_with_numeric_columns(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        _make_csv(str(csv_path))
        import pandas as pd
        df = pd.read_csv(str(csv_path))
        assert len(df) > 0
        assert df.select_dtypes(include="number").shape[1] >= 2


class TestNewerFileExists:
    def test_true_when_a_matching_recent_file_exists(self, tmp_path):
        since = time.time()
        (tmp_path / "SentinAL_Summary_foo.txt").write_text("x")
        assert _newer_file_exists(str(tmp_path), "SentinAL_Summary_", since) is True

    def test_false_when_no_matching_file_exists(self, tmp_path):
        (tmp_path / "unrelated.txt").write_text("x")
        assert _newer_file_exists(str(tmp_path), "SentinAL_Summary_", time.time()) is False

    def test_false_when_matching_file_predates_the_since_timestamp(self, tmp_path):
        old_file = tmp_path / "SentinAL_Summary_old.txt"
        old_file.write_text("x")
        # Backdate the file so it looks like it existed well before "since" -
        # a stale leftover from a previous run must not count as evidence
        # that THIS run produced anything.
        old_time = time.time() - 3600
        os.utime(old_file, (old_time, old_time))
        assert _newer_file_exists(str(tmp_path), "SentinAL_Summary_", time.time()) is False

    def test_false_for_a_nonexistent_directory(self, tmp_path):
        assert _newer_file_exists(str(tmp_path / "does_not_exist"), "prefix_", time.time()) is False


class TestSchedulerTaskPersisted:
    def test_true_when_a_matching_task_was_really_saved(self, tmp_path, monkeypatch):
        from agentic_core.memory_hook import MemoryManager
        m = MemoryManager(db_path=str(tmp_path / "db.sqlite"))
        monkeypatch.setattr("capabilities.system.scheduler._memory", lambda: m)
        m.register_scheduled_task("t1", "submit my thesis", None, time.time())
        assert _scheduler_task_persisted("thesis") is True
        m.close()

    def test_false_when_nothing_matches(self, tmp_path, monkeypatch):
        from agentic_core.memory_hook import MemoryManager
        m = MemoryManager(db_path=str(tmp_path / "db.sqlite"))
        monkeypatch.setattr("capabilities.system.scheduler._memory", lambda: m)
        assert _scheduler_task_persisted("thesis") is False
        m.close()


class TestBuildSchedulerTasks:
    def test_returns_two_tasks_in_the_scheduler_category(self):
        tasks = build_scheduler_tasks()
        assert len(tasks) == 2
        assert all(t.category == CAT_SCHED for t in tasks)
        assert {t.id for t in tasks} == {"sched_reminder", "sched_timer"}


class TestBuildResearchTasks:
    def test_returns_two_tasks_in_the_research_category_with_real_scratch_paths(self):
        """Regression guard for the file_ops path-derivation bug (see the
        comment in build_file_tasks()): the prompt must embed a real,
        already-resolved path at BUILD time, not something computed lazily
        inside setup() after prompt_for() has already been called."""
        tasks = build_research_tasks()
        assert len(tasks) == 2
        assert all(t.category == CAT_RESEARCH for t in tasks)
        pdf_task = next(t for t in tasks if t.id == "research_pdf_summary")
        csv_task = next(t for t in tasks if t.id == "research_dataset_eda")
        assert pdf_task.prompt.strip().lower().endswith(".pdf")
        assert csv_task.prompt.strip().lower().endswith(".csv")
        assert pdf_task.setup is not None
        assert csv_task.setup is not None
