
import os

SELF_IMPROVEMENT_ENABLED = os.getenv("SENTINAL_SELF_IMPROVEMENT_ENABLED", "false").strip().lower() not in ("0", "false", "no", "")

# Control-plane acceptance criteria (fixed, human-set — never self-tuned).
MIN_BENCHMARK_GAIN = float(os.getenv("SENTINAL_SI_MIN_GAIN", "0.05"))   # >= +5% overall
ALLOW_REGRESSIONS = False                                              # zero new task regressions

TUNABLE_PARAMS = {
    # name -> (env var, min, max) — proposer may suggest a value in [min, max]
    "SENTINAL_PLANNER_MAX_STEPS": (2, 12),
    "EXECUTOR_MAX_REPLANS": (0, 3),
    "OBSERVER_BROWSER_SETTLE_MS": (2000, 12000),
}
TUNABLE_HEURISTICS = (
    # boolean flags the proposer may flip
    "SENTINAL_SEMANTIC_MEMORY_ENABLED",
    "SENTINAL_ENV_MODEL_ENABLED",
)

# A capability's rolling success must be at least this far below its baseline
# before the proposer will suggest anything for it (reuses drift semantics).
PROPOSE_DRIFT_MIN = float(os.getenv("SENTINAL_SI_PROPOSE_DRIFT_MIN", "0.2"))
