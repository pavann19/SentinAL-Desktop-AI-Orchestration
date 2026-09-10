"""
tests/test_budget.py

Unit tests for agentic_core/budget.py + config/budgets.py (S4 containment
substrate — per-plan action + wall-time ceilings).

Covers: action accounting, would_exceed_actions()'s off-by-one boundary, the
wall-time gate (with a monkeypatched clock so no test actually sleeps),
check()'s reason strings, snapshot() shape, start() idempotency, and the
budget_for() factory (autonomous ceilings strictly tighter than direct).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import agentic_core.budget as budget_mod
from agentic_core.budget import (
    FAILURE_CATEGORY_BUDGET_EXCEEDED,
    PlanBudget,
    budget_for,
)


class TestActionAccounting:
    def test_starts_at_zero(self):
        b = PlanBudget(max_actions=5, max_wall_seconds=100)
        assert b.actions_used == 0

    def test_charge_action_increments(self):
        b = PlanBudget(max_actions=5, max_wall_seconds=100)
        b.charge_action()
        b.charge_action()
        assert b.actions_used == 2

    def test_would_exceed_is_false_until_the_last_allowed_action(self):
        b = PlanBudget(max_actions=3, max_wall_seconds=100)
        assert b.would_exceed_actions() is False  # 0 used, next is #1
        b.charge_action()
        assert b.would_exceed_actions() is False  # 1 used, next is #2
        b.charge_action()
        assert b.would_exceed_actions() is False  # 2 used, next is #3 (== max)
        b.charge_action()
        assert b.would_exceed_actions() is True   # 3 used, next would be #4 > max

    def test_check_reports_action_exhaustion(self):
        b = PlanBudget(max_actions=1, max_wall_seconds=100)
        b.charge_action()
        reason = b.check()
        assert reason is not None
        assert "action budget" in reason
        assert "1/1" in reason


class TestWallTimeGate:
    def test_not_started_reports_zero_elapsed(self):
        b = PlanBudget(max_actions=5, max_wall_seconds=100)
        assert b.elapsed() == 0.0
        assert b.time_exceeded() is False

    def test_time_exceeded_uses_the_monotonic_clock(self, monkeypatch):
        clock = {"t": 1000.0}
        monkeypatch.setattr(budget_mod.time, "monotonic", lambda: clock["t"])
        b = PlanBudget(max_actions=5, max_wall_seconds=10)
        b.start()
        clock["t"] = 1005.0
        assert b.time_exceeded() is False
        assert b.elapsed() == pytest.approx(5.0)
        clock["t"] = 1011.0
        assert b.time_exceeded() is True

    def test_check_reports_time_exhaustion_before_action_exhaustion(self, monkeypatch):
        clock = {"t": 0.0}
        monkeypatch.setattr(budget_mod.time, "monotonic", lambda: clock["t"])
        b = PlanBudget(max_actions=1, max_wall_seconds=10)
        b.start()
        b.charge_action()          # action ceiling also hit
        clock["t"] = 20.0          # time ceiling hit too
        reason = b.check()
        assert "wall-time budget" in reason  # time wins the reason string

    def test_start_is_idempotent(self, monkeypatch):
        clock = {"t": 100.0}
        monkeypatch.setattr(budget_mod.time, "monotonic", lambda: clock["t"])
        b = PlanBudget(max_actions=5, max_wall_seconds=10)
        b.start()
        clock["t"] = 105.0
        b.start()  # must NOT reset the clock
        assert b.elapsed() == pytest.approx(5.0)


class TestCheckPassesWhenUnderBudget:
    def test_fresh_budget_check_is_none(self):
        b = PlanBudget(max_actions=5, max_wall_seconds=100)
        b.start()
        assert b.check() is None

    def test_check_none_while_actions_remain_and_time_ok(self):
        b = PlanBudget(max_actions=5, max_wall_seconds=100)
        b.start()
        b.charge_action()
        b.charge_action()
        assert b.check() is None


class TestSnapshot:
    def test_snapshot_shape(self):
        b = PlanBudget(max_actions=7, max_wall_seconds=42, autonomous=True)
        b.start()
        b.charge_action()
        snap = b.snapshot()
        assert snap["actions_used"] == 1
        assert snap["max_actions"] == 7
        assert snap["max_wall_seconds"] == 42
        assert snap["autonomous"] is True
        assert "elapsed_seconds" in snap


class TestBudgetForFactory:
    def test_direct_and_autonomous_differ(self):
        direct = budget_for(autonomous=False)
        auto = budget_for(autonomous=True)
        assert direct.autonomous is False
        assert auto.autonomous is True

    def test_autonomous_ceilings_are_strictly_tighter(self):
        direct = budget_for(autonomous=False)
        auto = budget_for(autonomous=True)
        assert auto.max_actions < direct.max_actions
        assert auto.max_wall_seconds < direct.max_wall_seconds

    def test_default_is_direct(self):
        assert budget_for().autonomous is False

    def test_returns_plan_budget(self):
        assert isinstance(budget_for(), PlanBudget)


def test_failure_category_constant_is_a_stable_string():
    # execute_goal_graph_observed() surfaces this verbatim in its result.
    assert FAILURE_CATEGORY_BUDGET_EXCEEDED == "budget_exceeded"
