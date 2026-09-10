# agentic_core/budget.py
# Per-plan resource budget for SentinAL's S4 containment substrate.
#
# A PlanBudget is created once per goal-graph execution and threaded through it.
# It tracks how many actions the plan has spent and how long it has been
# running, and reports when either ceiling is hit. It never raises — the caller
# checks check() / would_exceed_actions() and stops the plan cleanly, the same
# non-raising style as capabilities/system/postcondition_observer.py.
#
# The ceilings themselves live in config/budgets.py (env-overridable), with a
# tighter set for autonomous/background callers (S6) than for a direct human
# command.

from __future__ import annotations

import time
from dataclasses import dataclass

from config.budgets import (
    PLAN_MAX_ACTIONS,
    PLAN_MAX_ACTIONS_AUTONOMOUS,
    PLAN_MAX_WALL_SECONDS,
    PLAN_MAX_WALL_SECONDS_AUTONOMOUS,
)

# Failure category for a plan stopped by its budget. Defined here rather than in
# agentic_core/executor.py so that security-critical file stays untouched; the
# goal-graph engine surfaces this string in its result's failure_category.
FAILURE_CATEGORY_BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class PlanBudget:
    """Resource ceilings for one plan, plus its running consumption."""
    max_actions: int
    max_wall_seconds: float
    autonomous: bool = False
    actions_used: int = 0
    _started_at: float | None = None

    def start(self) -> None:
        """Marks the plan's start. Idempotent — a second call is ignored so a
        retry/resume does not reset the wall-clock ceiling."""
        if self._started_at is None:
            self._started_at = time.monotonic()

    def elapsed(self) -> float:
        """Seconds since start(); 0.0 if start() was never called."""
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def charge_action(self) -> None:
        """Records that one action (one _run_and_observe call) was spent."""
        self.actions_used += 1

    def would_exceed_actions(self) -> bool:
        """True if spending one more action would go over the ceiling."""
        return self.actions_used + 1 > self.max_actions

    def time_exceeded(self) -> bool:
        """True if the wall-clock ceiling has already passed."""
        return self.elapsed() > self.max_wall_seconds

    def check(self) -> str | None:
        """
        Pre-step gate: returns a human-readable reason if the plan may not
        continue (time ceiling passed, or the next action would exceed the
        action ceiling), else None.
        """
        if self.time_exceeded():
            return (
                f"plan wall-time budget exceeded "
                f"({self.elapsed():.1f}s > {self.max_wall_seconds:.0f}s"
                f"{', autonomous' if self.autonomous else ''})"
            )
        if self.would_exceed_actions():
            return (
                f"plan action budget exhausted "
                f"({self.actions_used}/{self.max_actions} used"
                f"{', autonomous' if self.autonomous else ''})"
            )
        return None

    def snapshot(self) -> dict:
        """Serialisable consumption summary for a result payload."""
        return {
            "actions_used": self.actions_used,
            "max_actions": self.max_actions,
            "elapsed_seconds": round(self.elapsed(), 2),
            "max_wall_seconds": self.max_wall_seconds,
            "autonomous": self.autonomous,
        }


def budget_for(autonomous: bool = False) -> PlanBudget:
    """Builds a PlanBudget from config defaults for the given caller context."""
    if autonomous:
        return PlanBudget(
            max_actions=PLAN_MAX_ACTIONS_AUTONOMOUS,
            max_wall_seconds=PLAN_MAX_WALL_SECONDS_AUTONOMOUS,
            autonomous=True,
        )
    return PlanBudget(
        max_actions=PLAN_MAX_ACTIONS,
        max_wall_seconds=PLAN_MAX_WALL_SECONDS,
        autonomous=False,
    )
