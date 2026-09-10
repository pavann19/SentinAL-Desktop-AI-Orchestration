# tests/test_self_improvement.py
# S9-1 store, S9-2 proposer, S9-3 shadow-eval orchestration, S9-4 review.
# Injected benchmark runner — no real benchmark run.

from __future__ import annotations

import pytest

from agentic_core import improvement_engine as eng
from agentic_core.improvement_store import ImprovementStore


@pytest.fixture
def store(tmp_path):
    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "si.db"))
    return ImprovementStore(memory=mm)


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(eng, "SELF_IMPROVEMENT_ENABLED", True)


# ── S9-1 store ───────────────────────────────────────────────────────────

def test_propose_and_current_lifecycle(store):
    vid = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 3, rationale="drift")
    assert vid and store.get(vid)["state"] == "proposed"
    assert store.current("param:EXECUTOR_MAX_REPLANS") is None   # not promoted yet
    store.record_shadow(vid, before=0.90, after=0.96, regressions=[])
    assert store.get(vid)["state"] == "shadow_passed"
    assert store.promote(vid) is True
    assert store.current("param:EXECUTOR_MAX_REPLANS") == "3"


def test_shadow_fail_on_regression(store):
    vid = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 2)
    store.record_shadow(vid, before=0.9, after=0.95, regressions=["task_x"])
    assert store.get(vid)["state"] == "shadow_failed"


def test_revert_steps_back_one_version(store):
    v1 = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 2)
    store.record_shadow(v1, before=0.9, after=0.95, regressions=[])
    store.promote(v1)
    assert store.current("param:EXECUTOR_MAX_REPLANS") == "2"
    assert store.revert("param:EXECUTOR_MAX_REPLANS") is True
    assert store.current("param:EXECUTOR_MAX_REPLANS") is None
    assert store.get(v1)["state"] == "reverted"


def test_malformed_target_rejected(store):
    assert store.propose("EXECUTOR_MAX_REPLANS", 1, 2) is None    # no 'param:' prefix


# ── S9-2 proposer ────────────────────────────────────────────────────────

def test_proposer_emits_only_under_hard_drift(store, monkeypatch):
    monkeypatch.setattr(eng, "_store", lambda: store)
    # no drift -> nothing
    assert eng.propose_from_outcomes(drift=[]) == []
    # soft drift below PROPOSE_DRIFT_MIN -> nothing
    assert eng.propose_from_outcomes(drift=[{"intent": "WebNavigationIntent", "drop": 0.1}]) == []
    # hard drift -> bounded param proposals
    vids = eng.propose_from_outcomes(drift=[{"intent": "WebNavigationIntent", "drop": 0.4}])
    assert vids
    for vid in vids:
        row = store.get(vid)
        assert row["target"].startswith("param:")
        assert row["proposed_by"] == "drift-proposer"


def test_proposer_noop_when_disabled(store, monkeypatch):
    monkeypatch.setattr(eng, "SELF_IMPROVEMENT_ENABLED", False)
    monkeypatch.setattr(eng, "_store", lambda: store)
    assert eng.propose_from_outcomes(drift=[{"intent": "X", "drop": 0.9}]) == []


# ── S9-3 shadow eval ─────────────────────────────────────────────────────

def test_shadow_eval_records_before_after(store, monkeypatch):
    monkeypatch.setattr(eng, "_store", lambda: store)
    vid = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 3)

    calls = {"n": 0}

    def fake_bench():
        calls["n"] += 1
        return (0.90, ["t1", "t2"]) if calls["n"] == 1 else (0.97, ["t1", "t2", "t3"])

    ev = eng.shadow_eval(vid, benchmark_runner=fake_bench)
    assert ev["before"] == 0.90 and ev["after"] == 0.97
    assert ev["regressions"] == []
    assert store.get(vid)["state"] == "shadow_passed"


def test_shadow_eval_no_runner_is_noop(store, monkeypatch):
    monkeypatch.setattr(eng, "_store", lambda: store)
    vid = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 3)
    assert eng.shadow_eval(vid) == {}
    assert store.get(vid)["state"] == "proposed"


def test_applied_context_restores_env(monkeypatch):
    monkeypatch.delenv("EXECUTOR_MAX_REPLANS", raising=False)
    with eng._applied("param:EXECUTOR_MAX_REPLANS", "3"):
        import os
        assert os.environ["EXECUTOR_MAX_REPLANS"] == "3"
    import os
    assert "EXECUTOR_MAX_REPLANS" not in os.environ


# ── S9-4 review ──────────────────────────────────────────────────────────

def test_review_promotes_on_gain_and_no_regressions(store, monkeypatch):
    monkeypatch.setattr(eng, "_store", lambda: store)
    vid = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 3)
    store.record_shadow(vid, before=0.90, after=0.97, regressions=[])
    assert eng.review(vid) == "promoted"
    assert store.current("param:EXECUTOR_MAX_REPLANS") == "3"


def test_review_rejects_small_gain(store, monkeypatch):
    monkeypatch.setattr(eng, "_store", lambda: store)
    vid = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 3)
    store.record_shadow(vid, before=0.90, after=0.92, regressions=[])   # +0.02 < 0.05
    assert eng.review(vid) == "rejected"
    assert store.get(vid)["state"] == "rejected"


def test_review_rejects_any_regression(store, monkeypatch):
    monkeypatch.setattr(eng, "_store", lambda: store)
    vid = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 3)
    store.record_shadow(vid, before=0.90, after=0.99, regressions=["t5"])
    assert eng.review(vid) == "rejected"


def test_review_no_evidence(store, monkeypatch):
    monkeypatch.setattr(eng, "_store", lambda: store)
    vid = store.propose("param:EXECUTOR_MAX_REPLANS", 1, 3)
    assert eng.review(vid) == "no_evidence"
