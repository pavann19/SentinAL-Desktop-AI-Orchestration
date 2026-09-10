# tests/test_skill_pipeline.py
# S8-3 (replay-validation), S8-4 (promotion + matcher), S8-5 (monitor).
# Injected runners / stubbed embedder — no real desktop, no LLM.

from __future__ import annotations

import numpy as np
import pytest

from agentic_core import skill_matcher, skill_monitor, skill_validator
from agentic_core.skill_registry import SkillRegistry


def _template(fp="fp-s8", slot_type="path"):
    return {
        "fingerprint": fp,
        "goal_examples": ["open notepad then delete C:/tmp/a.txt"],
        "skeleton": [
            {"step_id": "step_1", "intent": "ApplicationLaunchIntent",
             "depends_on": [], "target_template": "notepad"},
            {"step_id": "step_2", "intent": "FileDeletionIntent",
             "depends_on": ["step_1"], "target_template": "C:/tmp/{p_slot}"},
        ],
        "slots": [{"name": "p_slot", "type": slot_type, "node_step_id": "step_2",
                   "examples": ["a.txt"], "from_prompt": True}],
        "postcondition_kind": "file_absent",
        "origin": "learned", "n_instances": 4,
    }


@pytest.fixture
def reg(tmp_path):
    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "s8.db"))
    return SkillRegistry(memory=mm)


# ── S8-3 replay validation ───────────────────────────────────────────────

def test_validate_skill_all_pass():
    seen = []
    conf = skill_validator.validate_skill(
        _template(), variants=3, runner=lambda steps: seen.append(steps) or True)
    assert conf == 1.0
    assert len(seen) == 3
    # each replay got a concrete (slot-filled) step list
    assert all("{" not in s[1]["target"] for s in seen)


def test_validate_skill_partial():
    calls = {"n": 0}

    def flaky(_steps):
        calls["n"] += 1
        return calls["n"] != 2      # 2nd variant fails

    assert skill_validator.validate_skill(_template(), variants=3, runner=flaky) == pytest.approx(0.667)


def test_validate_skill_never_raises():
    assert skill_validator.validate_skill({"slots": []}, runner=lambda s: 1 / 0) == 0.0


# ── S8-4 promotion path ──────────────────────────────────────────────────

def test_promote_if_ready_activates_on_clean_validation(reg):
    tpl = _template()
    sid = reg.register_candidate(tpl)
    out = skill_validator.promote_if_ready(sid, tpl, variants=3,
                                           runner=lambda s: True, registry=reg)
    assert out == "activated"
    assert reg.get(sid)["state"] == "active"
    assert reg.get(sid)["confidence"] == 1.0


def test_promote_if_ready_blocks_below_floor(reg):
    tpl = _template()
    sid = reg.register_candidate(tpl)
    out = skill_validator.promote_if_ready(sid, tpl, variants=4,
                                           runner=lambda s: False, registry=reg)
    assert out == "validated_below_floor"
    assert reg.get(sid)["state"] == "candidate"


def test_promote_if_ready_needs_instances(reg):
    tpl = _template()
    tpl["n_instances"] = 1
    sid = reg.register_candidate(tpl)
    assert skill_validator.promote_if_ready(sid, tpl, runner=lambda s: True,
                                            registry=reg) == "not_enough_instances"


# ── S8-4 matcher ─────────────────────────────────────────────────────────

class _FakeEmb:
    """cosine 1.0 for identical strings, ~0 otherwise (word-set overlap)."""

    def __call__(self, text):
        toks = set(str(text).lower().split())
        vocab = ["open", "notepad", "delete", "close", "file", "tmp", "then"]
        v = np.array([1.0 if w in toks else 0.0 for w in vocab], dtype=np.float32)
        n = np.linalg.norm(v)
        return v / n if n else v


@pytest.fixture
def matcher_env(reg, monkeypatch):
    monkeypatch.setattr(skill_matcher, "LEARNED_SKILLS_ENABLED", True)
    monkeypatch.setattr(skill_matcher, "_embed", _FakeEmb())
    monkeypatch.setattr("agentic_core.skill_registry.skill_registry", reg, raising=False)
    tpl = _template()
    sid = reg.register_candidate(tpl)
    reg.mark_validated(sid, 0.9)
    reg.activate(sid)
    return reg, sid


def test_match_skill_fills_slot_from_prompt(matcher_env):
    reg, sid = matcher_env
    g = skill_matcher.match_skill("open notepad then delete C:/tmp/report.csv")
    assert g is not None
    assert skill_matcher.skill_id_of(g) == sid
    targets = [n.target for n in g.topological_sort()]
    assert targets[0] == "notepad"
    assert targets[1] == "C:/tmp/report.csv"


def test_match_skill_none_when_disabled(matcher_env, monkeypatch):
    monkeypatch.setattr(skill_matcher, "LEARNED_SKILLS_ENABLED", False)
    assert skill_matcher.match_skill("open notepad then delete C:/tmp/x.txt") is None


def test_match_skill_none_for_autonomous(matcher_env):
    assert skill_matcher.match_skill("open notepad then delete C:/tmp/x.txt",
                                     autonomous=True) is None


# ── S8-5 monitor ─────────────────────────────────────────────────────────

@pytest.fixture
def mon(reg, monkeypatch):
    monkeypatch.setattr(skill_monitor, "_registry", lambda: reg)
    monkeypatch.setattr(skill_monitor, "_memory", lambda: reg._memory())
    return reg


def _activate(reg, conf=0.9):
    tpl = _template()
    sid = reg.register_candidate(tpl)
    reg.mark_validated(sid, conf)
    reg.activate(sid)
    return sid


def test_healthy_skill_is_not_demoted(mon):
    sid = _activate(mon)
    for _ in range(10):
        skill_monitor.record_skill_run(sid, True)
    assert mon.get(sid)["state"] == "active"


def test_sustained_failure_demotes(mon):
    sid = _activate(mon, conf=0.95)
    for _ in range(6):        # 6 == _MIN_SAMPLE: demotes on the 6th, retire needs a 7th
        skill_monitor.record_skill_run(sid, False)
    assert mon.get(sid)["state"] == "demoted"
    assert any(e["event"] == "demoted" for e in mon.events(sid))


def test_demoted_and_still_failing_retires(mon):
    sid = _activate(mon, conf=0.95)
    for _ in range(8):
        skill_monitor.record_skill_run(sid, False)   # -> demoted
    for _ in range(8):
        skill_monitor.record_skill_run(sid, False)   # -> retired
    assert mon.get(sid)["state"] == "retired"


def test_min_sample_guard(mon):
    sid = _activate(mon, conf=0.95)
    for _ in range(4):                                # below _MIN_SAMPLE
        skill_monitor.record_skill_run(sid, False)
    assert mon.get(sid)["state"] == "active"
