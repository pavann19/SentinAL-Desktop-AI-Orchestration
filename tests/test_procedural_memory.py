# tests/test_procedural_memory.py
# S6 procedural memory — deterministic recipe replay.
#
# Deterministic fake embedder (bag-of-words over a fixed vocabulary) so the
# real all-MiniLM-L6-v2 never loads: fast, hermetic, "more shared words ->
# higher cosine".

from __future__ import annotations

import importlib
import time

import numpy as np
import pytest

import agentic_core.procedural_memory as pm
import agentic_core.semantic_memory as sm

_VOCAB = [
    "open", "close", "file", "notepad", "browser", "delete", "create",
    "folder", "search", "weather", "email", "music", "screenshot", "python",
]
_DIM = len(_VOCAB)


class _FakeModel:
    def encode(self, texts):
        out = []
        for t in texts:
            toks = str(t).lower().split()
            v = np.zeros(_DIM, dtype=np.float32)
            for i, w in enumerate(_VOCAB):
                if w in toks:
                    v[i] = 1.0
            out.append(v)
        return np.asarray(out, dtype=np.float32)


def _graph_dict(steps, goal="do things"):
    """A GoalGraph.to_dict()-shaped dict from [(intent, target), ...]."""
    nodes = {}
    prev = ""
    for i, (intent, target) in enumerate(steps, 1):
        sid = f"step_{i}"
        nodes[sid] = {
            "intent": intent, "target": target, "prompt": target,
            "depends_on": [prev] if prev else [], "step_id": sid,
            "status": "completed", "result": "ok", "replan_count": 0,
        }
        prev = sid
    return {"goal_description": goal, "nodes": nodes}


_STEPS = [("ApplicationLaunchIntent", "notepad"), ("GeneralizedOSIntent", "type hello")]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINAL_PROCEDURAL_MEMORY_ENABLED", "true")
    monkeypatch.setenv("SENTINAL_PROCEDURAL_MIN_SUCCESSES", "3")
    monkeypatch.setenv("SENTINAL_PROCEDURAL_MIN_SIM", "0.75")
    importlib.reload(sm)
    mod = importlib.reload(pm)
    monkeypatch.setattr(sm, "_model", lambda: _FakeModel())

    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "proc.db"))
    monkeypatch.setattr(mod, "_memory", lambda: mm)
    mod._mem = mm
    yield mod
    mod._mem = None
    importlib.reload(pm)


# ── canonical + fingerprint ────────────────────────────────────────────────

def test_fingerprint_ignores_volatile_run_state(store):
    pre = _graph_dict(_STEPS)
    post = _graph_dict(_STEPS)
    for nd in post["nodes"].values():
        nd["status"] = "completed"
        nd["result"] = "different run output"
        nd["replan_count"] = 2
    assert store._fingerprint(store._canonical(pre)) == store._fingerprint(store._canonical(post))


def test_fingerprint_changes_on_structural_change(store):
    fp1 = store._fingerprint(store._canonical(_graph_dict(_STEPS)))
    fp2 = store._fingerprint(store._canonical(_graph_dict(
        _STEPS + [("GeneralizedOSIntent", "save")])))
    fp3 = store._fingerprint(store._canonical(_graph_dict(
        [("WebNavigationIntent", "notepad"), ("GeneralizedOSIntent", "type hello")])))
    assert len({fp1, fp2, fp3}) == 3


# ── promotion ──────────────────────────────────────────────────────────────

def test_below_threshold_is_not_recalled(store):
    for _ in range(2):
        store.record_success("open notepad create file", _graph_dict(_STEPS))
    assert store.recall_recipe("open notepad create file") is None


def test_at_threshold_is_recalled_with_provenance(store):
    for _ in range(3):
        store.record_success("open notepad create file", _graph_dict(_STEPS))
    graph = store.recall_recipe("open notepad create file")
    assert graph is not None
    assert len(graph.nodes) == 2
    assert store.plan_source_of(graph) == "procedural"
    assert store.recipe_fingerprint_of(graph)


def test_single_step_plans_are_never_recipes(store):
    for _ in range(5):
        store.record_success("open notepad", _graph_dict([("ApplicationLaunchIntent", "notepad")]))
    assert store.recall_recipe("open notepad") is None


# ── retirement ─────────────────────────────────────────────────────────────

def test_one_failure_retires_the_recipe(store):
    for _ in range(4):
        store.record_success("open notepad create file", _graph_dict(_STEPS))
    graph = store.recall_recipe("open notepad create file")
    fp = store.recipe_fingerprint_of(graph)
    store.record_failure(fp)
    assert store.recall_recipe("open notepad create file") is None


# ── recall gates ───────────────────────────────────────────────────────────

def test_recall_revalidates_against_current_allowlist(store, monkeypatch):
    for _ in range(3):
        store.record_success("open notepad create file", _graph_dict(_STEPS))
    import config.constants as cc
    monkeypatch.setattr(cc, "ALLOWLIST_INTENTS",
                        {i for i in cc.ALLOWLIST_INTENTS if i != "GeneralizedOSIntent"})
    assert store.recall_recipe("open notepad create file") is None


def test_recall_discards_over_long_recipe(store, monkeypatch):
    import agentic_core.planner as planner_mod
    monkeypatch.setattr(planner_mod, "MAX_PLAN_STEPS", 3)
    long_steps = [("GeneralizedOSIntent", f"cmd {i}") for i in range(6)]
    for _ in range(3):
        store.record_success("open close file notepad browser delete", _graph_dict(long_steps))
    assert store.recall_recipe("open close file notepad browser delete") is None


def test_stale_recipe_is_not_recalled(store, monkeypatch):
    # default PROC_MAX_AGE_DAYS is 30
    monkeypatch.setattr(store, "PROC_MAX_AGE_DAYS", 30.0)
    for _ in range(3):
        store.record_success("open notepad create file", _graph_dict(_STEPS))
    assert store.recall_recipe("open notepad create file") is not None
    # backdate last_success_ts by 40 days
    mm = store._memory()
    mm.cursor.execute("UPDATE memory_procedural SET last_success_ts = ?",
                      (time.time() - 40 * 86400,))
    mm.conn.commit()
    assert store.recall_recipe("open notepad create file") is None


def test_low_similarity_is_not_recalled(store):
    for _ in range(3):
        store.record_success("open notepad create file folder", _graph_dict(_STEPS))
    # shares 0 vocab tokens -> cosine 0
    assert store.recall_recipe("play some music") is None


def test_autonomous_never_replays(store):
    for _ in range(3):
        store.record_success("open notepad create file", _graph_dict(_STEPS))
    assert store.recall_recipe("open notepad create file", autonomous=True) is None


# ── flag off ───────────────────────────────────────────────────────────────

def test_flag_off_is_total_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINAL_PROCEDURAL_MEMORY_ENABLED", "false")
    importlib.reload(sm)
    mod = importlib.reload(pm)
    monkeypatch.setattr(sm, "_model", lambda: _FakeModel())
    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "off.db"))
    monkeypatch.setattr(mod, "_memory", lambda: mm)
    mod._mem = mm
    for _ in range(5):
        mod.record_success("open notepad create file", _graph_dict(_STEPS))
    assert mod.recall_recipe("open notepad create file") is None
    assert mm.recent_procedural_recipes() == []
    mod._mem = None
    importlib.reload(pm)
