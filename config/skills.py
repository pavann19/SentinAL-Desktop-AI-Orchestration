
import os

LEARNED_SKILLS_ENABLED = os.getenv("SENTINAL_LEARNED_SKILLS_ENABLED", "false").strip().lower() not in ("0", "false", "no", "")

# How many successful concrete instances of one plan structure before
# abstraction into a typed-slot skeleton is attempted.
SKILL_MIN_INSTANCES = int(os.getenv("SENTINAL_SKILL_MIN_INSTANCES", "3"))

SKILL_CONFIDENCE_FLOOR = float(os.getenv("SENTINAL_SKILL_CONFIDENCE_FLOOR", "0.6"))

SKILL_DEMOTE_DROP = float(os.getenv("SENTINAL_SKILL_DEMOTE_DROP", "0.25"))

# Learned skills are ALWAYS registered at this tier, regardless of what a
# hand-written equivalent would carry (CONTAINMENT_ARCHITECTURE §10.2 step 4).
LEARNED_SKILL_TIER = "T1"

# Valid lifecycle states.
SKILL_STATES = ("candidate", "active", "demoted", "retired")
