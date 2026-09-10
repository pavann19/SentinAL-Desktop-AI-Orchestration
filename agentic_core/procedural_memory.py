# agentic_core/procedural_memory.py
# S6 proactive autonomy — procedural memory.
#
# Semantic memory increment 2 shows the planner an ADVISORY hint but still
# calls the planning LLM every time. Procedural memory is the deterministic
# step: when a multi-step goal is a near-verbatim match for one that has
# SUCCEEDED organically several times with the same plan structure, replay the
# stored GoalGraph and skip the planner LLM entirely.
#
# The recipe is a PLAN SHAPE ONLY. The replayed graph still enters
# execute_goal_graph_observed(), which re-runs validate_steps() -> risk ->
# authorization -> policy -> HITL -> sandbox on every step. A recipe can never
# be an execution grant, and every step's intent is re-checked against
# ALLOWLIST_INTENTS at load time so a recipe stored before an allowlist change
# cannot smuggle a now-forbidden intent.
#
# Own flag, default OFF (this one changes execution by skipping an LLM call, so
# it must not ride on SENTINAL_SEMANTIC_MEMORY_ENABLED). Never raises. An
# autonomous background goal NEVER replays a cached recipe — the world may have
# drifted and there is no human to catch a bad replay.

from __future__ import annotations

import hashlib
import json
import logging
import os
import time

import numpy as np

_logger = logging.getLogger("ProceduralMemory")

ENABLED = os.getenv("SENTINAL_PROCEDURAL_MEMORY_ENABLED", "false").strip().lower() not in ("0", "false", "no", "")
# Organic successes before a structure becomes eligible for replay.
PROC_MIN_SUCCESSES = int(os.getenv("SENTINAL_PROCEDURAL_MIN_SUCCESSES", "3"))
# Cosine floor for "near-verbatim" — deliberately stricter than the plan-hint
# floor (0.55) and the loose-recall floor (0.35).
PROC_MIN_SIM = float(os.getenv("SENTINAL_PROCEDURAL_MIN_SIM", "0.75"))
# A recipe not successfully used within this window is treated as stale.
PROC_MAX_AGE_DAYS = float(os.getenv("SENTINAL_PROCEDURAL_MAX_AGE_DAYS", "30"))
MAX_ROWS = int(os.getenv("SENTINAL_PROCEDURAL_MAX_ROWS", "2000"))

_EMB_DTYPE = np.float32


def _embed(text: str):
    """Reuse semantic_memory's embedder (the router's already-loaded MiniLM),
    so there is exactly one model in the process. None if unavailable."""
    try:
        from agentic_core.semantic_memory import _embed as _sm_embed
        return _sm_embed(text)
    except Exception:
        return None


_mem = None


def _memory():
    global _mem
    if _mem is None:
        from agentic_core.memory_hook import MemoryManager
        _mem = MemoryManager()
    return _mem


# ── canonical structure + fingerprint ──────────────────────────────────────

_STRUCTURAL_NODE_KEYS = ("intent", "target", "prompt", "depends_on", "actions", "expected_state")


def _canonical(graph_dict: dict) -> dict:
    """Reduce a GoalGraph.to_dict() to structural fields only — drop the
    volatile run state (status / result / observation / replan_count) so the
    pre-run graph and its post-run form reduce identically."""
    nodes = graph_dict.get("nodes", {})
    out_nodes = {}
    if isinstance(nodes, dict):
        for nid, nd in nodes.items():
            if not isinstance(nd, dict):
                continue
            keep = {}
            for k in _STRUCTURAL_NODE_KEYS:
                if k in nd and nd[k] not in (None, [], {}):
                    keep[k] = nd[k]
            out_nodes[str(nid)] = keep
    return {
        "goal_description": str(graph_dict.get("goal_description", "") or ""),
        "nodes": out_nodes,
    }


def _fingerprint(canonical: dict) -> str:
    """Stable hash of the plan structure: the ordered (intent, target,
    depends_on) of every node. Ignores goal_description wording so two
    differently-phrased goals with the same plan share a recipe."""
    shape = [
        {
            "intent": nd.get("intent"),
            "target": nd.get("target", ""),
            "depends_on": list(nd.get("depends_on", [])),
        }
        for _, nd in sorted(canonical.get("nodes", {}).items())
    ]
    blob = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── record ─────────────────────────────────────────────────────────────────

def record_success(prompt: str, graph_dict: dict) -> None:
    """One organic success for this plan structure. No-op unless ENABLED.
    A planner-sourced success counts toward promotion just like a replay."""
    if not ENABLED or not prompt or not isinstance(graph_dict, dict):
        return
    try:
        canonical = _canonical(graph_dict)
        if len(canonical["nodes"]) < 2:
            return  # single-step plans are not recipes
        fp = _fingerprint(canonical)
        vec = _embed(prompt)
        if vec is None:
            return
        _memory().upsert_procedural_recipe(
            fingerprint=fp,
            goal_text=prompt,
            embedding_blob=np.asarray(vec, dtype=_EMB_DTYPE).tobytes(),
            graph_json=json.dumps(canonical, separators=(",", ":")),
            ts=time.time(),
        )
    except Exception as e:
        _logger.debug(f"record_success failed (non-fatal): {e}")


def record_failure(fingerprint: str | None) -> None:
    """A replay of this recipe then failed — retire it."""
    if not ENABLED or not fingerprint:
        return
    try:
        _memory().bump_procedural_failure(fingerprint)
        _logger.info(f"[ProceduralMemory] recipe {fingerprint[:12]} retired after a failed replay")
    except Exception as e:
        _logger.debug(f"record_failure failed (non-fatal): {e}")


# ── recall ─────────────────────────────────────────────────────────────────

def _revalidate(graph):
    """Re-check a reconstructed recipe against current policy: every intent
    still allowlisted, step count within bound, no cycle. Returns the graph or
    None."""
    try:
        from config.constants import ALLOWLIST_INTENTS
        from agentic_core.planner import MAX_PLAN_STEPS
    except Exception:
        return None
    if not graph.nodes or len(graph.nodes) > MAX_PLAN_STEPS:
        return None
    for node in graph.nodes.values():
        if node.intent not in ALLOWLIST_INTENTS:
            _logger.info(f"[ProceduralMemory] recipe discarded — intent no longer allowlisted: {node.intent}")
            return None
    if graph.has_cycle():
        return None
    return graph


def recall_recipe(prompt: str, *, autonomous: bool = False):
    """The stored GoalGraph for a near-verbatim, repeatedly-successful past
    goal — or None. Hint-free: this REPLACES the planner LLM call, so the gate
    is strict. Never raises.

    Returns None for an autonomous goal unconditionally: a background goal
    always gets a fresh plan."""
    if not ENABLED or autonomous or not prompt:
        return None
    try:
        qv = _embed(prompt)
        if qv is None:
            return None
        qv = np.asarray(qv, dtype=_EMB_DTYPE)
        rows = _memory().recent_procedural_recipes(limit=MAX_ROWS)
    except Exception as e:
        _logger.debug(f"recall scan failed (non-fatal): {e}")
        return None
    if not rows:
        return None

    cutoff = time.time() - PROC_MAX_AGE_DAYS * 86400.0
    best = None
    best_sim = -1.0
    for r in rows:
        if r["success_count"] < PROC_MIN_SUCCESSES:
            continue
        if r["failure_count"] > 0:
            continue
        if r["last_success_ts"] < cutoff:
            continue
        try:
            v = np.frombuffer(r["embedding"], dtype=_EMB_DTYPE)
            if v.shape != qv.shape:
                continue
            sim = float(np.dot(qv, v))
        except Exception:
            continue
        if sim > best_sim:
            best_sim = sim
            best = r

    if best is None or best_sim < PROC_MIN_SIM:
        return None

    try:
        from agentic_core.goal_graph import GoalGraph
        graph = GoalGraph.from_dict(json.loads(best["graph_json"]))
    except Exception as e:
        _logger.debug(f"recipe rehydrate failed (non-fatal): {e}")
        return None

    graph = _revalidate(graph)
    if graph is None:
        return None

    # Stamp provenance on the first node (topological order) so the caller can
    # tell a replay from a planned graph after the pipeline flatten/rebuild.
    try:
        first = graph.topological_sort()[0]
        first.extra["_plan_source"] = "procedural"
        first.extra["_recipe_fp"] = best["fingerprint"]
    except Exception:
        pass

    _logger.info(
        f"[ProceduralMemory] hit — replaying recipe {best['fingerprint'][:12]} "
        f"(sim={best_sim:.3f}, successes={best['success_count']})"
    )
    return graph


def plan_source_of(graph) -> str:
    """'procedural' if this graph came from recall_recipe(), else 'planner'."""
    try:
        for node in graph.nodes.values():
            if node.extra.get("_plan_source") == "procedural":
                return "procedural"
    except Exception:
        pass
    return "planner"


def recipe_fingerprint_of(graph) -> str | None:
    try:
        for node in graph.nodes.values():
            fp = node.extra.get("_recipe_fp")
            if fp:
                return fp
    except Exception:
        pass
    return None
