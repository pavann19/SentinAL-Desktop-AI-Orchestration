
import os

# ── Direct-human plans (every caller today) ─────────────────────────────────
PLAN_MAX_ACTIONS = int(os.getenv("SENTINAL_PLAN_MAX_ACTIONS", "24"))
PLAN_MAX_WALL_SECONDS = float(os.getenv("SENTINAL_PLAN_MAX_WALL_SECONDS", "300"))

PLAN_MAX_ACTIONS_AUTONOMOUS = int(os.getenv("SENTINAL_PLAN_MAX_ACTIONS_AUTONOMOUS", "12"))
PLAN_MAX_WALL_SECONDS_AUTONOMOUS = float(os.getenv("SENTINAL_PLAN_MAX_WALL_SECONDS_AUTONOMOUS", "120"))
