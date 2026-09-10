# tests/test_skill_registry.py
# S8-2 — learned-skill registry + lifecycle. Isolated SQLite DB, no LLM.

from __future__ import annotations

import pytest

from agentic_core.skill_registry import SkillRegistry


def _template(fp="fp-abc", slots=1):
    return {
        "fingerprint": fp,
        "skeleton": [
            {"step_id": "step_1", "intent": "ApplicationLaunchIntent",
             "depends_on": [], "target_template": "notepad"},
            {"step_id": "step_2", "intent": "FileDeletionIntent",
             "depends_on": ["step_1"], "target_template": "C:/tmp/{path_slot}"},
        ],
        "slots": ([{"name": "path_slot", "type": "path", "node_step_id": "step_2",
                    "examples": ["a.txt"], "from_prompt": True}] if slots else []),
        "postcondition_kind": "file_absent",
        "origin": "learned",
        "n_instances": 4,
    }


@pytest.fixture
def reg(tmp_path):
    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "skills.db"))
    return SkillRegistry(memory=mm)


# ── registration ─────────────────────────────────────────────────────────

def test_register_is_idempotent(reg):
    sid1 = reg.register_candidate(_template())
    sid2 = reg.register_candidate(_template())
    assert sid1 == sid2
    assert len(reg.list()) == 1
    row = reg.get(sid1)
    assert row["state"] == "candidate"
    assert row["tier"] == "T1"
    assert row["origin"] == "learned"
    assert row["n_instances"] == 4


def test_register_refreshes_recipe_without_touching_state(reg):
    sid = reg.register_candidate(_template())
    reg.mark_validated(sid, 0.9)
    reg.activate(sid)
    assert reg.get(sid)["state"] == "active"
    # re-register (e.g. more instances observed)
    tpl = _template()
    tpl["n_instances"] = 9
    reg.register_candidate(tpl)
    row = reg.get(sid)
    assert row["state"] == "active"           # unchanged
    assert row["n_instances"] == 9            # refreshed


def test_malformed_template_returns_none(reg):
    assert reg.register_candidate({"fingerprint": "x"}) is None


# ── lifecycle ────────────────────────────────────────────────────────────

def test_cannot_activate_an_unvalidated_skill(reg):
    sid = reg.register_candidate(_template())
    assert reg.activate(sid) is False
    assert reg.get(sid)["state"] == "candidate"
    assert any(e["event"] == "activate_refused" for e in reg.events(sid))


def test_validate_below_floor_blocks_activation(reg):
    sid = reg.register_candidate(_template())
    assert reg.mark_validated(sid, 0.4) is False   # below SKILL_CONFIDENCE_FLOOR (0.6)
    assert reg.activate(sid) is False
    assert reg.get(sid)["confidence"] == 0.4


def test_validate_then_activate(reg):
    sid = reg.register_candidate(_template())
    assert reg.mark_validated(sid, 0.85) is True
    assert reg.activate(sid) is True
    row = reg.get(sid)
    assert row["state"] == "active"
    assert row["activated_ts"] is not None
    assert [e["event"] for e in reg.events(sid)] == [
        "registered", "validated", "activated"]


def test_demote_then_retire(reg):
    sid = reg.register_candidate(_template())
    reg.mark_validated(sid, 0.9)
    reg.activate(sid)
    assert reg.demote(sid, "rolling success 0.55 vs 0.9") is True
    assert reg.get(sid)["state"] == "demoted"
    assert reg.retire(sid, "still failing") is True
    assert reg.get(sid)["state"] == "retired"


def test_retired_skill_cannot_be_activated(reg):
    sid = reg.register_candidate(_template())
    reg.mark_validated(sid, 0.9)
    reg.retire(sid, "obsolete")
    assert reg.activate(sid) is False
    assert reg.get(sid)["state"] == "retired"


# ── reads ────────────────────────────────────────────────────────────────

def test_active_skills_parses_skeleton_and_slots(reg):
    sid = reg.register_candidate(_template())
    reg.mark_validated(sid, 0.9)
    reg.activate(sid)
    reg.register_candidate(_template(fp="fp-other"))  # stays candidate
    active = reg.active_skills()
    assert len(active) == 1
    assert active[0]["skill_id"] == sid
    assert isinstance(active[0]["skeleton"], list)
    assert active[0]["slots"][0]["name"] == "path_slot"


def test_by_fingerprint(reg):
    reg.register_candidate(_template(fp="fp-1"))
    reg.register_candidate(_template(fp="fp-2"))
    assert len(reg.by_fingerprint("fp-1")) == 1
    assert reg.by_fingerprint("fp-missing") == []


def test_audit_trail_records_every_transition(reg):
    sid = reg.register_candidate(_template())
    reg.mark_validated(sid, 0.9)
    reg.activate(sid)
    reg.demote(sid, "drift")
    events = [e["event"] for e in reg.events(sid)]
    assert events == ["registered", "validated", "activated", "demoted"]
