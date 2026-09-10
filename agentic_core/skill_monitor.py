# agentic_core/skill_monitor.py
# S8-5 — learned-skill monitoring -> demotion / retirement.
#
# CONTAINMENT_ARCHITECTURE §10.2 step 5: a learned skill whose live success
# rate drops below its validated confidence over a rolling window is
# automatically demoted, not silently kept. Same drift signal as S7 Half B's
# capability_health(), keyed by skill_id.
#
# Never raises.

from __future__ import annotations

import logging
import time

from config.skills import SKILL_DEMOTE_DROP

_logger = logging.getLogger("SkillMonitor")

_WINDOW = 15          # rolling outcomes considered
_MIN_SAMPLE = 6       # need this many before any verdict
_RETIRE_FLOOR = 0.2   # a demoted skill this bad over the window is retired


def _memory():
    from agentic_core.memory_hook import MemoryManager
    if not hasattr(_memory, "_m"):
        _memory._m = MemoryManager()
    return _memory._m


def _registry():
    from agentic_core.skill_registry import skill_registry
    return skill_registry


def skill_health(skill_id: str) -> dict:
    """Rolling live success rate for one skill vs. its validated confidence.
    {} on error. `drifted` only with >= _MIN_SAMPLE outcomes and a drop of at
    least SKILL_DEMOTE_DROP below confidence."""
    try:
        row = _registry().get(skill_id)
        if not row:
            return {}
        confidence = float(row.get("confidence") or 0.0)
        outs = _memory().recent_learned_skill_outcomes(skill_id, limit=_WINDOW)
        n = len(outs)
        if n == 0:
            return {"skill_id": skill_id, "n": 0, "rate": 0.0,
                    "confidence": confidence, "drifted": False}
        rate = sum(1 for o in outs if o["verified"]) / n
        drifted = n >= _MIN_SAMPLE and (confidence - rate) >= SKILL_DEMOTE_DROP
        return {
            "skill_id": skill_id, "n": n, "rate": round(rate, 3),
            "confidence": round(confidence, 3),
            "drop": round(confidence - rate, 3), "drifted": drifted,
        }
    except Exception as e:
        _logger.debug(f"skill_health failed (non-fatal): {e}")
        return {}


def _maybe_demote(skill_id: str) -> None:
    h = skill_health(skill_id)
    if not h:
        return
    row = _registry().get(skill_id)
    state = (row or {}).get("state")
    if state == "active" and h.get("drifted"):
        _registry().demote(
            skill_id,
            f"live success {h['rate']:.2f} vs validated {h['confidence']:.2f} "
            f"over {h['n']} runs",
        )
    elif state == "demoted" and h.get("n", 0) >= _MIN_SAMPLE and h.get("rate", 1.0) <= _RETIRE_FLOOR:
        _registry().retire(skill_id, f"still failing ({h['rate']:.2f}) after demotion")


def record_skill_run(skill_id: str, verified: bool) -> None:
    """Record one live run of a learned skill and re-check its health. Called
    from the pipeline after a learned-skill-sourced plan completes."""
    if not skill_id:
        return
    try:
        _memory().add_learned_skill_outcome(skill_id, bool(verified), time.time())
        _maybe_demote(skill_id)
    except Exception as e:
        _logger.debug(f"record_skill_run failed (non-fatal): {e}")


def sweep_active_skills() -> list[dict]:
    """Re-check every active + demoted skill. Returns the health dicts of any
    that were demoted or retired this pass. For a future scheduled call."""
    changed = []
    try:
        for row in _registry().list():
            if row["state"] not in ("active", "demoted"):
                continue
            before = row["state"]
            _maybe_demote(row["skill_id"])
            after = (_registry().get(row["skill_id"]) or {}).get("state")
            if after != before:
                changed.append({"skill_id": row["skill_id"], "from": before, "to": after})
    except Exception as e:
        _logger.debug(f"sweep_active_skills failed (non-fatal): {e}")
    return changed
