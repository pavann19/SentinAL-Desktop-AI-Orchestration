# config/skills.py
# S8 skill-learning configuration.

import os

# Gates the PLANNER's use of learned skills (S8-4). The registry and
# abstraction (S8-1/S8-2) are inert data structures — nothing reads them for
# execution until this is on. Default off: a learned skill's graph re-enters
# the pipeline like any plan, but its selection still changes behaviour, so
# opt in then flip once validated.
LEARNED_SKILLS_ENABLED = os.getenv("SENTINAL_LEARNED_SKILLS_ENABLED", "false").strip().lower() not in ("0", "false", "no", "")

# How many successful concrete instances of one plan structure before
# abstraction into a typed-slot skeleton is attempted.
SKILL_MIN_INSTANCES = int(os.getenv("SENTINAL_SKILL_MIN_INSTANCES", "3"))

# A validated skill needs at least this replay-validation success rate to be
# promotable to 'active' (S8-3/S8-4).
SKILL_CONFIDENCE_FLOOR = float(os.getenv("SENTINAL_SKILL_CONFIDENCE_FLOOR", "0.6"))

# Rolling live success rate this far below the validated confidence demotes an
# active skill (S8-5) — reuses S7 Half B's capability_health() shape.
SKILL_DEMOTE_DROP = float(os.getenv("SENTINAL_SKILL_DEMOTE_DROP", "0.25"))

# Learned skills are ALWAYS registered at this tier, regardless of what a
# hand-written equivalent would carry (CONTAINMENT_ARCHITECTURE §10.2 step 4).
LEARNED_SKILL_TIER = "T1"

# Valid lifecycle states.
SKILL_STATES = ("candidate", "active", "demoted", "retired")
