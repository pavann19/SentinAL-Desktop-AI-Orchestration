"""
tests/test_event_bus.py

Unit tests for the S6 event bus:
  - increment 1 (time triggers, notify-only): get_due_scheduled_tasks /
    mark_scheduled_task_notified, _poll_once, the resident event_bus_loop
  - increment 2 (autonomous goals): the scheduled_tasks.kind column and
    make_event_handler's reminder-vs-goal branch

Real isolated SQLite (tmp_path), same fixture pattern as tests/test_scheduler.py.
The loop is infinite, so loop tests run it with a tiny interval, sleep briefly,
then cancel — nothing here sleeps for real time.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import agentic_core.event_bus as eb
from agentic_core.event_bus import _poll_once, event_bus_loop, make_event_handler
from agentic_core.memory_hook import MemoryManager


@pytest.fixture()
def mem(tmp_path):
    m = MemoryManager(db_path=str(tmp_path / "event_bus.db"))
    yield m
    m.close()


def _add(m, task_id, desc, due_at):
    m.register_scheduled_task(task_id, desc, due_at, time.time())


class TestGetDueScheduledTasks:

    def test_a_past_due_unnotified_task_is_returned(self, mem):
        _add(mem, "t1", "call the dentist", time.time() - 60)
        due = mem.get_due_scheduled_tasks(time.time())
        assert [t["task_id"] for t in due] == ["t1"]

    def test_a_future_task_is_not_returned(self, mem):
        _add(mem, "t1", "later", time.time() + 3600)
        assert mem.get_due_scheduled_tasks(time.time()) == []

    def test_an_undated_task_is_not_returned(self, mem):
        _add(mem, "t1", "no time on this one", None)
        assert mem.get_due_scheduled_tasks(time.time()) == []

    def test_a_completed_task_is_not_returned(self, mem):
        _add(mem, "t1", "done already", time.time() - 60)
        mem.complete_scheduled_task("t1", time.time())
        assert mem.get_due_scheduled_tasks(time.time()) == []

    def test_an_already_notified_task_is_not_returned(self, mem):
        _add(mem, "t1", "announced once", time.time() - 60)
        mem.mark_scheduled_task_notified("t1", time.time())
        assert mem.get_due_scheduled_tasks(time.time()) == []

    def test_results_are_ordered_soonest_due_first(self, mem):
        now = time.time()
        _add(mem, "later", "b", now - 10)
        _add(mem, "earlier", "a", now - 100)
        due = mem.get_due_scheduled_tasks(now)
        assert [t["task_id"] for t in due] == ["earlier", "later"]


class TestMarkNotified:

    def test_marking_notified_makes_the_row_stop_matching(self, mem):
        _add(mem, "t1", "x", time.time() - 5)
        assert mem.get_due_scheduled_tasks(time.time())
        mem.mark_scheduled_task_notified("t1", time.time())
        assert mem.get_due_scheduled_tasks(time.time()) == []

    def test_marking_notified_does_not_complete_the_task(self, mem):
        _add(mem, "t1", "x", time.time() - 5)
        mem.mark_scheduled_task_notified("t1", time.time())
        # still pending — the user hasn't acted on the reminder
        assert any(t["task_id"] == "t1" for t in mem.get_pending_scheduled_tasks())


class TestPollOnce:

    def test_poll_returns_due_rows_and_stamps_them(self, mem):
        _add(mem, "t1", "one", time.time() - 30)
        _add(mem, "t2", "two", time.time() - 20)

        first = _poll_once(mem)
        assert {t["task_id"] for t in first} == {"t1", "t2"}

        # second poll: nothing new, they were stamped notified
        assert _poll_once(mem) == []


class TestEventBusLoop:

    @pytest.mark.asyncio
    async def test_loop_fires_on_event_once_per_due_task_and_not_again(self, mem):
        _add(mem, "t1", "ring me", time.time() - 10)
        seen = []

        task = asyncio.create_task(
            event_bus_loop(on_event=lambda t: seen.append(t["task_id"]), memory=mem, interval=0.01)
        )
        await asyncio.sleep(0.08)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert seen == ["t1"]  # exactly once despite many ticks

    @pytest.mark.asyncio
    async def test_a_raising_callback_does_not_kill_the_loop(self, mem):
        _add(mem, "t1", "first", time.time() - 10)
        calls = {"n": 0}

        def boom(_task):
            calls["n"] += 1
            raise RuntimeError("notifier is broken")

        task = asyncio.create_task(event_bus_loop(on_event=boom, memory=mem, interval=0.01))
        await asyncio.sleep(0.05)
        # loop is still alive: add a second due task, it should still get picked up
        _add(mem, "t2", "second", time.time() - 5)
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert calls["n"] == 2  # both tasks reached the (broken) callback; loop survived

    @pytest.mark.asyncio
    async def test_disabled_loop_never_polls(self, mem, monkeypatch):
        monkeypatch.setattr(eb, "ENABLED", False)
        _add(mem, "t1", "should be ignored", time.time() - 10)
        seen = []

        task = asyncio.create_task(
            event_bus_loop(on_event=lambda t: seen.append(t), memory=mem, interval=0.01)
        )
        await asyncio.sleep(0.06)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert seen == []
        # and the row was never stamped
        assert mem.get_due_scheduled_tasks(time.time())

    @pytest.mark.asyncio
    async def test_cancellation_stops_the_loop_cleanly(self, mem):
        task = asyncio.create_task(event_bus_loop(on_event=None, memory=mem, interval=0.01))
        await asyncio.sleep(0.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()


class TestKindColumn:

    def test_default_kind_is_reminder(self, mem):
        _add(mem, "t1", "call mom", time.time() - 5)
        due = mem.get_due_scheduled_tasks(time.time())
        assert due[0]["kind"] == "reminder"

    def test_goal_kind_round_trips(self, mem):
        mem.register_scheduled_task("g1", "summarize downloads", time.time() - 5,
                                    time.time(), kind="goal")
        due = mem.get_due_scheduled_tasks(time.time())
        assert due[0]["kind"] == "goal"


class TestMakeEventHandler:

    def _handler(self, *, autonomous_goals_on, run_goal=None):
        self.broadcasts = []
        self.goal_calls = []

        async def broadcast(msg):
            self.broadcasts.append(msg)

        async def default_run_goal(desc):
            self.goal_calls.append(desc)
            return {"execution": "Success", "response": "did it", "capability_reason": "T1 ok"}

        return make_event_handler(
            broadcast=broadcast,
            run_goal=run_goal or default_run_goal,
            autonomous_goals_on=autonomous_goals_on,
        )

    @pytest.mark.asyncio
    async def test_reminder_kind_only_notifies(self):
        h = self._handler(autonomous_goals_on=True)
        await h({"task_id": "t1", "description": "call mom", "due_at": 1.0, "kind": "reminder"})
        assert self.goal_calls == []
        assert self.broadcasts[0]["type"] == "reminder_due"

    @pytest.mark.asyncio
    async def test_goal_kind_runs_when_enabled(self):
        h = self._handler(autonomous_goals_on=True)
        await h({"task_id": "g1", "description": "tidy up", "kind": "goal"})
        assert self.goal_calls == ["tidy up"]
        assert self.broadcasts[0]["type"] == "autonomous_goal_result"
        assert self.broadcasts[0]["execution"] == "Success"

    @pytest.mark.asyncio
    async def test_goal_kind_only_notifies_when_disabled(self):
        h = self._handler(autonomous_goals_on=False)
        await h({"task_id": "g1", "description": "tidy up", "kind": "goal"})
        assert self.goal_calls == []                       # NOT run
        assert self.broadcasts[0]["type"] == "reminder_due"  # degraded to notify

    @pytest.mark.asyncio
    async def test_a_raising_goal_still_broadcasts_a_result(self):
        async def boom(_desc):
            raise RuntimeError("goal blew up")
        h = self._handler(autonomous_goals_on=True, run_goal=boom)
        await h({"task_id": "g1", "description": "x", "kind": "goal"})
        assert self.broadcasts[0]["type"] == "autonomous_goal_result"
        assert self.broadcasts[0]["execution"] == "Error"
