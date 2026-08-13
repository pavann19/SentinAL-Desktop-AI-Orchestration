"""
tests/test_process_supervisor.py

Tests for agentic_core/process_supervisor.py — the background reconciler for
detached work (CodeAct scripts, installs) that the request/response cycle
returns too early to observe.

The supervisor's decision logic is deliberately split into a synchronous,
side-effect-scoped core (evaluate_watch / poll_once) and a thin async loop
around it, so the entire decision matrix is testable here without spawning a
single real process or running an event loop.
"""
import json
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.memory_hook import MemoryManager
from agentic_core.process_supervisor import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_TIMED_OUT,
    build_sentinel_footer,
    build_sentinel_header,
    evaluate_watch,
    new_sentinel_path,
    poll_once,
    register_watch,
)


@pytest.fixture()
def mem(tmp_path):
    m = MemoryManager(db_path=str(tmp_path / "supervisor_test.db"))
    yield m
    m.close()


def _write_sentinel(path, status, detail=""):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"status": status, "detail": detail}, fh)


# ══════════════════════════════════════════════════════════════════════════════
# Sentinel footer generation
# ══════════════════════════════════════════════════════════════════════════════
class TestSentinelScriptGeneration:
    def test_footer_writes_to_the_given_path(self, tmp_path):
        path = str(tmp_path / "s.json")
        footer = build_sentinel_footer(path)
        assert path in footer
        assert "Set-Content" in footer

    def test_footer_escapes_single_quotes_in_the_path(self):
        """A path containing an apostrophe would otherwise terminate the
        PowerShell string literal and corrupt the emitted script."""
        footer = build_sentinel_footer(r"C:\Users\O'Brien\s.json")
        assert "O''Brien" in footer

    def test_footer_does_not_wrap_the_script_body(self):
        """Wrapping the user's script in try/catch would change scoping and
        break scripts declaring their own functions or param blocks. The footer
        must only bracket it, never enclose it."""
        footer = build_sentinel_footer("x.json")
        assert "try {" in footer  # only around the sentinel WRITE itself
        assert footer.strip().startswith("#")  # begins as a comment, not a wrapper

    def test_header_clears_error_so_only_this_run_counts(self):
        assert "$Error.Clear()" in build_sentinel_header()

    def test_new_sentinel_paths_are_unique(self):
        a = new_sentinel_path("codeact")
        b = new_sentinel_path("codeact")
        assert a != b

    def test_new_sentinel_path_sanitises_the_label(self):
        path = new_sentinel_path("evil/../label with spaces")
        assert ".." not in os.path.basename(path)
        assert " " not in os.path.basename(path)


# ══════════════════════════════════════════════════════════════════════════════
# evaluate_watch — the full decision matrix, no real processes
# ══════════════════════════════════════════════════════════════════════════════
class TestEvaluateWatchSentinelMode:
    def test_absent_sentinel_is_still_pending(self, tmp_path):
        watch = {"sentinel_path": str(tmp_path / "never.json"), "registered_at": time.time()}
        assert evaluate_watch(watch) is None

    def test_sentinel_reporting_completed_resolves_completed(self, tmp_path):
        path = str(tmp_path / "s.json")
        _write_sentinel(path, "completed")
        status, _ = evaluate_watch({"sentinel_path": path, "registered_at": time.time()})
        assert status == STATUS_COMPLETED

    def test_sentinel_reporting_failed_resolves_failed_with_detail(self, tmp_path):
        path = str(tmp_path / "s.json")
        _write_sentinel(path, "failed", "Cannot find path 'C:\\nope'")
        status, detail = evaluate_watch({"sentinel_path": path, "registered_at": time.time()})
        assert status == STATUS_FAILED
        assert "nope" in detail

    def test_failed_sentinel_without_detail_still_gets_a_reason(self, tmp_path):
        path = str(tmp_path / "s.json")
        _write_sentinel(path, "failed", "")
        status, detail = evaluate_watch({"sentinel_path": path, "registered_at": time.time()})
        assert status == STATUS_FAILED
        assert detail  # never an empty explanation

    def test_partially_written_sentinel_is_treated_as_pending_not_failed(self, tmp_path):
        """The file is written non-atomically by an external process, so a
        truncated read is an expected transient — treating it as failure would
        produce spurious failures on every slightly-unlucky poll."""
        path = str(tmp_path / "s.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"status": "comp')  # torn write
        assert evaluate_watch({"sentinel_path": path, "registered_at": time.time()}) is None

    def test_empty_sentinel_file_is_pending(self, tmp_path):
        path = str(tmp_path / "s.json")
        open(path, "w").close()
        assert evaluate_watch({"sentinel_path": path, "registered_at": time.time()}) is None

    def test_sentinel_with_utf8_bom_is_parsed(self, tmp_path):
        """PowerShell's Set-Content -Encoding UTF8 emits a BOM on Windows
        PowerShell; a plain utf-8 read would choke on it."""
        path = str(tmp_path / "s.json")
        with open(path, "w", encoding="utf-8-sig") as fh:
            json.dump({"status": "completed", "detail": ""}, fh)
        status, _ = evaluate_watch({"sentinel_path": path, "registered_at": time.time()})
        assert status == STATUS_COMPLETED


class TestEvaluateWatchPidMode:
    def test_live_pid_is_still_pending(self):
        watch = {"pid": os.getpid(), "registered_at": time.time()}
        assert evaluate_watch(watch) is None

    def test_dead_pid_resolves_completed_but_says_status_is_unknown(self):
        """A PID-only watch genuinely cannot tell success from failure. The
        detail must say so rather than implying the work succeeded."""
        with patch("agentic_core.process_supervisor._pid_alive", return_value=False):
            status, detail = evaluate_watch({"pid": 999999, "registered_at": time.time()})
        assert status == STATUS_COMPLETED
        assert "not observable" in detail

    def test_unknown_pid_liveness_falls_back_to_pending_not_completed(self):
        """If psutil is unavailable or errors, assuming the process died would
        fabricate a completion. It must stay pending and let the timeout decide."""
        with patch("agentic_core.process_supervisor.psutil", create=True, side_effect=ImportError):
            watch = {"pid": os.getpid(), "registered_at": time.time()}
            assert evaluate_watch(watch) is None


class TestEvaluateWatchTimeout:
    def test_watch_older_than_the_timeout_times_out(self, tmp_path):
        import agentic_core.process_supervisor as ps
        watch = {
            "sentinel_path": str(tmp_path / "never.json"),
            "registered_at": time.time() - (ps.WATCH_TIMEOUT_SECONDS + 10),
        }
        status, detail = evaluate_watch(watch)
        assert status == STATUS_TIMED_OUT
        assert "no completion signal" in detail

    def test_a_written_sentinel_wins_over_an_expired_timeout(self, tmp_path):
        """Ordering matters: work that finished (even late) must be reported by
        its real outcome, not silently downgraded to a timeout."""
        import agentic_core.process_supervisor as ps
        path = str(tmp_path / "s.json")
        _write_sentinel(path, "failed", "late but real")
        status, detail = evaluate_watch({
            "sentinel_path": path,
            "registered_at": time.time() - (ps.WATCH_TIMEOUT_SECONDS + 10),
        })
        assert status == STATUS_FAILED
        assert "late but real" in detail


# ══════════════════════════════════════════════════════════════════════════════
# Registration + persistence
# ══════════════════════════════════════════════════════════════════════════════
class TestRegistration:
    def test_registering_a_watch_makes_it_pending(self, mem, tmp_path):
        watch_id = register_watch("codeact", sentinel_path=str(tmp_path / "s.json"), memory=mem)
        pending = mem.get_pending_watches()
        assert any(w["watch_id"] == watch_id for w in pending)

    def test_expected_state_round_trips_as_json(self, mem, tmp_path):
        watch_id = register_watch(
            "codeact", sentinel_path=str(tmp_path / "s.json"),
            expected_state={"script_path": "C:\\x.ps1"}, memory=mem,
        )
        stored = mem.get_process_watch(watch_id)
        assert json.loads(stored["expected_state"])["script_path"] == "C:\\x.ps1"

    def test_registration_failure_never_raises_into_the_caller(self, tmp_path):
        """Registering a watch is an observability enhancement. If it fails, the
        user's actual command must still proceed — unobserved is acceptable,
        crashed is not."""
        class _BrokenMemory:
            def register_process_watch(self, **kwargs):
                raise RuntimeError("db gone")

        watch_id = register_watch("codeact", memory=_BrokenMemory())
        assert isinstance(watch_id, str) and watch_id  # still returns an id


# ══════════════════════════════════════════════════════════════════════════════
# poll_once — the sweep
# ══════════════════════════════════════════════════════════════════════════════
class TestPollOnce:
    def test_pending_watch_produces_no_resolution(self, mem, tmp_path):
        register_watch("codeact", sentinel_path=str(tmp_path / "never.json"), memory=mem)
        assert poll_once(memory=mem) == []

    def test_completed_watch_is_resolved_and_reported_once(self, mem, tmp_path):
        path = str(tmp_path / "s.json")
        watch_id = register_watch("codeact", sentinel_path=path, memory=mem)
        _write_sentinel(path, "completed", "all good")

        first = poll_once(memory=mem)
        assert len(first) == 1
        assert first[0]["watch_id"] == watch_id
        assert first[0]["status"] == STATUS_COMPLETED

        # Second sweep must not re-report it — otherwise every subsequent tick
        # would re-notify the user about the same finished job.
        assert poll_once(memory=mem) == []

    def test_failed_watch_is_reported_with_its_detail(self, mem, tmp_path):
        path = str(tmp_path / "s.json")
        register_watch("codeact", sentinel_path=path, memory=mem)
        _write_sentinel(path, "failed", "npm ERR! code E404")

        resolutions = poll_once(memory=mem)
        assert resolutions[0]["status"] == STATUS_FAILED
        assert "E404" in resolutions[0]["detail"]

    def test_resolution_is_persisted_not_just_returned(self, mem, tmp_path):
        path = str(tmp_path / "s.json")
        watch_id = register_watch("codeact", sentinel_path=path, memory=mem)
        _write_sentinel(path, "completed")
        poll_once(memory=mem)

        stored = mem.get_process_watch(watch_id)
        assert stored["status"] == STATUS_COMPLETED
        assert stored["resolved_at"] is not None

    def test_sentinel_file_is_cleaned_up_after_resolution(self, mem, tmp_path):
        path = str(tmp_path / "s.json")
        register_watch("codeact", sentinel_path=path, memory=mem)
        _write_sentinel(path, "completed")
        poll_once(memory=mem)
        assert not os.path.exists(path)

    def test_multiple_watches_resolve_independently(self, mem, tmp_path):
        done_path = str(tmp_path / "done.json")
        pending_path = str(tmp_path / "pending.json")
        register_watch("finished", sentinel_path=done_path, memory=mem)
        register_watch("still-going", sentinel_path=pending_path, memory=mem)
        _write_sentinel(done_path, "completed")

        resolutions = poll_once(memory=mem)
        assert [r["label"] for r in resolutions] == ["finished"]
        assert len(mem.get_pending_watches()) == 1

    def test_one_broken_watch_does_not_abort_the_whole_sweep(self, mem, tmp_path):
        """A single malformed row must not strand every other pending watch."""
        good_path = str(tmp_path / "good.json")
        register_watch("broken", sentinel_path=str(tmp_path / "b.json"), memory=mem)
        register_watch("good", sentinel_path=good_path, memory=mem)
        _write_sentinel(good_path, "completed")

        real_evaluate = evaluate_watch

        def _flaky(watch, now=None):
            if watch["label"] == "broken":
                raise RuntimeError("corrupt row")
            return real_evaluate(watch, now=now)

        with patch("agentic_core.process_supervisor.evaluate_watch", _flaky):
            resolutions = poll_once(memory=mem)

        assert [r["label"] for r in resolutions] == ["good"]

    def test_db_read_failure_returns_empty_rather_than_raising(self):
        class _BrokenMemory:
            def get_pending_watches(self):
                raise RuntimeError("db gone")

        assert poll_once(memory=_BrokenMemory()) == []


# ══════════════════════════════════════════════════════════════════════════════
# Retention
# ══════════════════════════════════════════════════════════════════════════════
class TestPurge:
    def test_old_resolved_watches_are_purged(self, mem, tmp_path):
        path = str(tmp_path / "s.json")
        watch_id = register_watch("codeact", sentinel_path=path, memory=mem)
        _write_sentinel(path, "completed")
        poll_once(memory=mem)

        removed = mem.purge_resolved_watches(time.time() + 1)
        assert removed == 1
        assert mem.get_process_watch(watch_id) is None

    def test_pending_watches_are_never_purged(self, mem, tmp_path):
        """A still-running job must survive cleanup regardless of age — the
        spawned process does not die just because its record got old."""
        watch_id = register_watch("codeact", sentinel_path=str(tmp_path / "s.json"), memory=mem)
        mem.purge_resolved_watches(time.time() + 10_000)
        assert mem.get_process_watch(watch_id) is not None
