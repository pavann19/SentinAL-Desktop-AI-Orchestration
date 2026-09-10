# config/budgets.py
# Per-plan resource ceilings for SentinAL's S4 containment substrate.
#
# A "plan" is a multi-step goal graph executed by
# capabilities/system/api_wrapper.py::execute_goal_graph_observed(). A budget
# bounds two things across the WHOLE plan (not per step):
#   - actions:  how many times _run_and_observe() may fire (initial executions
#               plus every bounded replan attempt). The planner already caps a
#               DAG at MAX_PLAN_STEPS (10) nodes and each node at MAX_REPLANS
#               (1) replan, so the natural worst case is ~20; the ceiling adds
#               headroom over that and, more importantly, is the thing a future
#               autonomous/background goal (S6) runs under.
#   - wall time: total elapsed seconds for the plan, so a plan that stalls on a
#               slow step (or a runaway LLM) is stopped rather than hanging.
#
# Autonomous callers (S6 background goals — not built yet) run under tighter
# ceilings than a direct human command: a person watching a multi-step request
# can interrupt it; an unattended goal cannot.
#
# Not applied to the flat single-step path (executor.py's
# execute_pipeline_observed): one step is one action, inherently bounded, and
# that path has its own per-mechanism timeouts.

import os

# ── Direct-human plans (every caller today) ─────────────────────────────────
PLAN_MAX_ACTIONS = int(os.getenv("SENTINAL_PLAN_MAX_ACTIONS", "24"))
PLAN_MAX_WALL_SECONDS = float(os.getenv("SENTINAL_PLAN_MAX_WALL_SECONDS", "300"))

# ── Autonomous / background plans (S6 — deliberately tighter) ────────────────
PLAN_MAX_ACTIONS_AUTONOMOUS = int(os.getenv("SENTINAL_PLAN_MAX_ACTIONS_AUTONOMOUS", "12"))
PLAN_MAX_WALL_SECONDS_AUTONOMOUS = float(os.getenv("SENTINAL_PLAN_MAX_WALL_SECONDS_AUTONOMOUS", "120"))
