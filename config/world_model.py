# config/world_model.py
# S7 — live environment model configuration.

import os

# Master switch. Off by default: the sampler feeds the planner's context
# (increment A3) and a shifting context can move intent extraction, so opt in
# then flip once validated. When off, sample_tick() and every read are no-ops.
ENV_MODEL_ENABLED = os.getenv("SENTINAL_ENV_MODEL_ENABLED", "false").strip().lower() not in ("0", "false", "no", "")

# Even though the event-bus loop ticks every ~30 s, guard against a faster
# caller (a test, a future second caller) hammering the sampler.
ENV_SAMPLE_MIN_INTERVAL_SECONDS = float(os.getenv("SENTINAL_ENV_SAMPLE_MIN_INTERVAL", "20.0"))

# Retention — pruned on every write, whichever bound bites first.
ENV_RETAIN_ROWS = int(os.getenv("SENTINAL_ENV_RETAIN_ROWS", "500"))
ENV_RETAIN_HOURS = float(os.getenv("SENTINAL_ENV_RETAIN_HOURS", "6.0"))

# Cap the stored process-name list so a busy machine can't bloat a row.
ENV_MAX_PROC_NAMES = int(os.getenv("SENTINAL_ENV_MAX_PROC_NAMES", "400"))
