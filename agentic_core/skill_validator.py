# agentic_core/skill_validator.py
# S8-3 — replay-validation gate.
#
# A learned skill (skill_abstraction -> skill_registry candidate) is promoted
# only after it replays successfully on held-out slot fillings — in the
# containment overlay, never on the live system unguarded
# (CONTAINMENT_ARCHITECTURE §10.2 step 3).
#
# "Overlay" for host actions = the S4 pre-action snapshot (agentic_core/
# snapshot.py): capture the write targets, run the filled plan, check it
# succeeded and its postcondition verified, then RESTORE so the validation
# leaves no trace. (The verified npm/Docker overlay is the overlay for the
# code-execution capability specifically; multi-step GoalGraphs of allowlisted
# GUI/file intents run on the host under snapshot/restore, which is S4's
# reversal mechanism.)
#
# The step runner is injectable so this module is unit-testable without a real
# desktop; the production default runs the real observed goal-graph executor.
# Never raises.

from __future__ import annotations

import logging
import os
import tempfile

from config.skills import SKILL_MIN_INSTANCES

_logger = logging.getLogger("SkillValidator")

_SAFE_APPS = ["notepad", "calc", "mspaint"]


def _held_out_values(slot: dict, k: int) -> list:
    """k conservative held-out fillings for one slot, by type. Filesystem
    values point at throwaway paths the caller creates/cleans."""
    stype = slot.get("type", "text")
    if stype == "app":
        return [_SAFE_APPS[i % len(_SAFE_APPS)] for i in range(k)]
    if stype == "number":
        return [str(7 + i) for i in range(k)]
    if stype == "url":
        return [f"https://example.{c}/" for c in ("com", "org", "net")][:k]
    if stype == "path":
        base = tempfile.mkdtemp(prefix="sentinal_skillval_")
        return [os.path.join(base, f"heldout_{i}.txt") for i in range(k)]
    if stype == "query":
        return [f"held out validation query {i}" for i in range(k)]
    return [f"heldout{i}" for i in range(k)]


def _default_runner(steps: list[dict]) -> bool:
    """Production runner: execute the filled plan under a fresh snapshot and
    report success-AND-postcondition-verified. Restores unconditionally."""
    try:
        from agentic_core.goal_graph import GoalGraph
        from agentic_core.snapshot import capture, new_snapshot
        from capabilities.system.api_wrapper import (
            _paths_for_step,
            execute_goal_graph_observed,
        )
    except Exception as e:  # pragma: no cover - import guard
        _logger.debug(f"runner import failed: {e}")
        return False

    snap = new_snapshot("skill-validation")
    try:
        for s in steps:
            try:
                capture(snap, _paths_for_step(s))
            except Exception:
                pass
        graph = GoalGraph.from_pipeline(steps, goal_description="skill validation replay")
        observed = execute_goal_graph_observed(graph, None, None)
        return observed.get("execution") == "Success"
    except Exception as e:
        _logger.debug(f"replay failed (non-fatal): {e}")
        return False
    finally:
        try:
            snap.restore()
        except Exception:
            pass


def validate_skill(template: dict, *, variants: int = 3, runner=None,
                   prep=None, cleanup=None) -> float:
    """Replay `template` on `variants` held-out slot fillings. Returns the
    pass rate in [0.0, 1.0]. `runner(steps) -> bool` is injectable;
    `prep(slot_values)` / `cleanup(slot_values)` let a caller stage and tear
    down throwaway targets. Never raises."""
    try:
        from agentic_core.skill_abstraction import fill_skeleton

        run = runner or _default_runner
        slots = template.get("slots", [])
        k = max(1, int(variants))

        per_slot = {s["name"]: _held_out_values(s, k) for s in slots}
        passed = 0
        for i in range(k):
            slot_values = {name: vals[i] for name, vals in per_slot.items()}
            steps = fill_skeleton(template, slot_values)
            if steps is None:
                continue
            if prep:
                try:
                    prep(slot_values)
                except Exception:
                    pass
            try:
                ok = bool(run(steps))
            finally:
                if cleanup:
                    try:
                        cleanup(slot_values)
                    except Exception:
                        pass
            passed += 1 if ok else 0
        return round(passed / k, 3)
    except Exception as e:
        _logger.debug(f"validate_skill failed (non-fatal): {e}")
        return 0.0


def validate_and_record(skill_id: str, template: dict, *, variants: int = 3,
                        runner=None, registry=None) -> float:
    """Run validate_skill and write the result to the registry via
    mark_validated(). Returns the measured confidence."""
    conf = validate_skill(template, variants=variants, runner=runner)
    try:
        reg = registry
        if reg is None:
            from agentic_core.skill_registry import skill_registry as reg
        reg.mark_validated(skill_id, conf)
    except Exception as e:
        _logger.debug(f"mark_validated failed (non-fatal): {e}")
    return conf


def enough_instances(template: dict) -> bool:
    """True once a template has been abstracted from at least
    SKILL_MIN_INSTANCES concrete successful runs."""
    return int(template.get("n_instances", 0)) >= SKILL_MIN_INSTANCES


def promote_if_ready(skill_id: str, template: dict, *, variants: int = 3,
                     runner=None, registry=None) -> str:
    """S8-4: gate a candidate through the full promotion path —
    replay-validate, record the confidence, and activate() it if the
    registry accepts. Returns 'activated' | 'validated_below_floor' |
    'not_enough_instances' | 'activate_refused'. Never raises."""
    try:
        reg = registry
        if reg is None:
            from agentic_core.skill_registry import skill_registry as reg
        if not enough_instances(template):
            return "not_enough_instances"
        conf = validate_and_record(skill_id, template, variants=variants,
                                   runner=runner, registry=reg)
        from config.skills import SKILL_CONFIDENCE_FLOOR
        if conf < SKILL_CONFIDENCE_FLOOR:
            return "validated_below_floor"
        return "activated" if reg.activate(skill_id) else "activate_refused"
    except Exception as e:
        _logger.debug(f"promote_if_ready failed (non-fatal): {e}")
        return "activate_refused"
