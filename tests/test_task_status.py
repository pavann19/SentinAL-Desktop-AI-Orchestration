# tests/test_task_status.py
# Background-task-monitoring: pollable status for a detached process a
# capability launched, on top of process_supervisor's existing watch/resolve
# machinery. Pure reads — nothing here executes anything.

from __future__ import annotations

import time

import pytest

from agentic_core import process_supervisor as sup


@pytest.fixture
def mem(tmp_path):
    from agentic_core.memory_hook import MemoryManager
    return MemoryManager(db_path=str(tmp_path / "tasks.db"))


def _register(mem, label, status="pending", detail=""):
    wid = f"w-{label}-{time.time()}"
    mem.register_process_watch(wid, label, registered_at=time.time())
    if status != "pending":
        mem.resolve_process_watch(wid, status, time.time(), detail)
    return wid


# ── memory_hook.list_recent_process_watches ─────────────────────────────

def test_pending_and_resolved_both_listed(mem):
    p = _register(mem, "still-running")
    r = _register(mem, "done", status="completed", detail="ok")
    rows = mem.list_recent_process_watches(limit=10)
    ids = {r_["watch_id"] for r_ in rows}
    assert {p, r} <= ids


def test_pending_listed_before_resolved(mem):
    _register(mem, "done", status="completed")
    p = _register(mem, "running")
    rows = mem.list_recent_process_watches(limit=10)
    assert rows[0]["watch_id"] == p
    assert rows[0]["status"] == "pending"


def test_limit_is_respected(mem):
    for i in range(5):
        _register(mem, f"t{i}", status="completed")
    rows = mem.list_recent_process_watches(limit=3)
    assert len(rows) == 3


def test_empty_store_returns_empty_list(mem):
    assert mem.list_recent_process_watches() == []


# ── process_supervisor.get_task_status / list_tasks ─────────────────────

def test_get_task_status_returns_the_row(mem):
    wid = _register(mem, "my-task", status="failed", detail="boom")
    row = sup.get_task_status(wid, memory=mem)
    assert row is not None
    assert row["status"] == "failed"
    assert row["detail"] == "boom"


def test_get_task_status_unknown_id_returns_none(mem):
    assert sup.get_task_status("nope", memory=mem) is None


def test_get_task_status_never_raises_on_backend_error():
    class _Boom:
        def get_process_watch(self, _wid):
            raise RuntimeError("db exploded")

    assert sup.get_task_status("x", memory=_Boom()) is None


def test_list_tasks_delegates_to_memory(mem):
    _register(mem, "a", status="completed")
    _register(mem, "b")
    out = sup.list_tasks(limit=10, memory=mem)
    assert len(out) == 2


def test_list_tasks_never_raises_on_backend_error():
    class _Boom:
        def list_recent_process_watches(self, limit=50):
            raise RuntimeError("db exploded")

    assert sup.list_tasks(memory=_Boom()) == []
