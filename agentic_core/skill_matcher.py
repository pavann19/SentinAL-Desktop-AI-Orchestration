# agentic_core/skill_matcher.py
# S8-4 (matching half) — select a validated, active learned skill for a goal.
#
# Mirrors procedural_memory.recall_recipe: if an ACTIVE learned skill's
# example goals are close to this prompt AND every slot can be filled from the
# prompt, return its filled GoalGraph (provenance-stamped). Otherwise None.
#
# Behind SENTINAL_LEARNED_SKILLS_ENABLED (default off); never for an
# autonomous goal (a background goal always gets a fresh plan). Every returned
# step is still allowlist / budget / cycle checked downstream — a skill graph
# is a plan shape, never an execution grant. Never raises.

from __future__ import annotations

import logging
import re

from config.skills import LEARNED_SKILLS_ENABLED

_logger = logging.getLogger("SkillMatcher")

_MATCH_SIM = 0.72  # prompt-vs-example cosine floor for a skill to fire

_PATH_RX = re.compile(r"""([A-Za-z]:[\\/][^\s"']+|~?[\\/][^\s"']+\.\w{1,6})""")
_URL_RX = re.compile(r"(https?://[^\s\"']+|\b[\w-]+\.(?:com|org|net|io|dev)\b[^\s\"']*)")
_TOKEN_RX = re.compile(r"\b([\w.-]{2,32})\b")


def _embed(text: str):
    try:
        from agentic_core.semantic_memory import _embed as _e
        return _e(text)
    except Exception:
        return None


def _best_example_sim(prompt: str, examples: list[str]) -> float:
    qv = _embed(prompt)
    if qv is None or not examples:
        return 0.0
    import numpy as np
    best = 0.0
    for ex in examples:
        ev = _embed(ex)
        if ev is None or getattr(ev, "shape", None) != getattr(qv, "shape", None):
            continue
        best = max(best, float(np.dot(qv, ev)))
    return best


def _extract_slot(prompt: str, slot: dict, target_template: str) -> str | None:
    """Pull the slot value out of the prompt. First try the target frame
    (prefix{slot}suffix) if both sides appear in the prompt; else fall back to
    a type-shaped regex."""
    name = slot["name"]
    marker = "{" + name + "}"
    if marker in target_template:
        pre, _, suf = target_template.partition(marker)
        # frame words that also occur in the prompt let us bracket the value
        pre_tail = pre.strip().split()[-2:] if pre.strip() else []
        suf_head = suf.strip().split()[:2] if suf.strip() else []
        if pre_tail and " ".join(pre_tail) in prompt:
            after = prompt.split(" ".join(pre_tail), 1)[1]
            val = after.split(" ".join(suf_head), 1)[0] if suf_head else after
            val = val.strip().strip("'\".,")
            if val:
                return val
    stype = slot.get("type", "text")
    if stype == "path":
        m = _PATH_RX.search(prompt)
        return m.group(1) if m else None
    if stype == "url":
        m = _URL_RX.search(prompt)
        return m.group(1) if m else None
    if stype in ("app", "text", "number"):
        m = _TOKEN_RX.findall(prompt)
        return m[-1] if m else None
    return None  # 'query' free text is not safely extractable in this cut


def match_skill(prompt: str, *, autonomous: bool = False):
    """A filled GoalGraph from an active learned skill, or None."""
    if not LEARNED_SKILLS_ENABLED or autonomous or not prompt:
        return None
    try:
        from agentic_core.skill_abstraction import fill_skeleton
        from agentic_core.skill_registry import skill_registry

        active = skill_registry.active_skills()
        if not active:
            return None

        best = None
        best_sim = _MATCH_SIM
        for sk in active:
            sim = _best_example_sim(prompt, sk.get("goal_examples") or [])
            if sim < best_sim:
                continue
            # can we fill every slot?
            tmpl_by_step = {n["step_id"]: n.get("target_template", "")
                            for n in sk.get("skeleton", [])}
            slot_values = {}
            ok = True
            for slot in sk.get("slots", []):
                tt = tmpl_by_step.get(slot.get("node_step_id"), "")
                v = _extract_slot(prompt, slot, tt)
                if not v:
                    ok = False
                    break
                slot_values[slot["name"]] = v
            if not ok:
                continue
            best, best_sim = (sk, slot_values), sim

        if best is None:
            return None
        sk, slot_values = best
        steps = fill_skeleton(
            {"skeleton": sk["skeleton"], "slots": sk["slots"]}, slot_values
        )
        if not steps:
            return None

        from agentic_core.goal_graph import GoalGraph
        graph = GoalGraph.from_pipeline(steps, goal_description=prompt)
        try:
            first = graph.topological_sort()[0]
            first.extra["_plan_source"] = "learned_skill"
            first.extra["_skill_id"] = sk["skill_id"]
        except Exception:
            pass
        _logger.info(f"[SkillMatcher] active skill {sk['skill_id'][:14]} matched (sim={best_sim:.3f})")
        return graph
    except Exception as e:
        _logger.debug(f"match_skill failed (non-fatal): {e}")
        return None


def skill_id_of(graph) -> str | None:
    try:
        for node in graph.nodes.values():
            sid = node.extra.get("_skill_id")
            if sid:
                return sid
    except Exception:
        pass
    return None
