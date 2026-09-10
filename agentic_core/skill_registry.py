# agentic_core/skill_registry.py
# S8-2 — learned-skill registry + lifecycle.
#
# A learned skill (from skill_abstraction.abstract_skill) lives here through
# its lifecycle:
#
#   candidate  registered, not yet replay-validated
#      │  mark_validated(confidence >= SKILL_CONFIDENCE_FLOOR)   [S8-3]
#      ▼
#   candidate (validated)
#      │  activate()                                             [S8-4]
#      ▼
#   active     the planner may select it (behind SENTINAL_LEARNED_SKILLS_ENABLED)
#      │  demote(reason)  — rolling success dropped              [S8-5]
#      ▼
#   demoted    no longer offered; can be re-validated & re-activated
#      │  retire(reason)
#      ▼
#   retired    dead
#
# Invariants enforced here, not by convention:
#   - origin is always "learned"; tier is always T1 (§10.2 step 4)
#   - activate() refuses a skill that has not been validated
#   - a retired skill cannot be activated
#   - every transition is written to the append-only audit trail
#
# The registry is inert data until S8-4 wires it into the planner. Nothing
# reads it for execution here.

from __future__ import annotations

import hashlib
import json
import logging
import time

from config.skills import LEARNED_SKILL_TIER, SKILL_CONFIDENCE_FLOOR

_logger = logging.getLogger("SkillRegistry")


def _skill_id(fingerprint: str, skeleton: list[dict]) -> str:
    blob = fingerprint + "|" + json.dumps(skeleton, sort_keys=True, separators=(",", ":"))
    return "skill_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class SkillRegistry:
    def __init__(self, memory=None):
        self._mem = memory

    def _memory(self):
        if self._mem is None:
            from agentic_core.memory_hook import MemoryManager
            self._mem = MemoryManager()
        return self._mem

    # ── registration ─────────────────────────────────────────────────────

    def register_candidate(self, template: dict) -> str | None:
        """Register (or refresh) a learned skill as a candidate. Returns its
        skill_id, or None if the template is malformed. Idempotent — a repeat
        call updates the abstracted recipe + instance count but never touches
        state / tier / confidence / timestamps."""
        try:
            fp = template["fingerprint"]
            skeleton = template["skeleton"]
            sid = _skill_id(fp, skeleton)
            self._memory().upsert_learned_skill(
                skill_id=sid,
                fingerprint=fp,
                skeleton_json=json.dumps(skeleton, separators=(",", ":")),
                slots_json=json.dumps(template.get("slots", []), separators=(",", ":")),
                postcondition_kind=template.get("postcondition_kind"),
                n_instances=int(template.get("n_instances", 0)),
                ts=time.time(),
            )
            self._event(sid, "registered", f"{len(template.get('slots', []))} slot(s), "
                        f"{template.get('n_instances', 0)} instances")
            return sid
        except Exception as e:
            _logger.debug(f"register_candidate failed (non-fatal): {e}")
            return None

    # ── lifecycle transitions ────────────────────────────────────────────

    def mark_validated(self, skill_id: str, confidence: float) -> bool:
        """Record a replay-validation result (S8-3). Keeps state 'candidate'
        but stamps validated_ts + confidence. A confidence below the floor is
        recorded but leaves the skill un-promotable."""
        row = self.get(skill_id)
        if not row or row["state"] == "retired":
            return False
        self._memory().set_learned_skill_state(
            skill_id, state="candidate", ts_field="validated_ts", ts=time.time(),
            confidence=round(float(confidence), 3),
        )
        ok = confidence >= SKILL_CONFIDENCE_FLOOR
        self._event(skill_id, "validated",
                    f"confidence={confidence:.3f} ({'promotable' if ok else 'below floor'})")
        return ok

    def activate(self, skill_id: str) -> bool:
        """Promote a validated candidate to 'active'. Refuses if not validated,
        already retired, or confidence is below the floor."""
        row = self.get(skill_id)
        if not row:
            return False
        if row["state"] == "retired":
            self._event(skill_id, "activate_refused", "retired")
            return False
        if not row.get("validated_ts") or (row.get("confidence") or 0) < SKILL_CONFIDENCE_FLOOR:
            self._event(skill_id, "activate_refused", "not validated / below confidence floor")
            return False
        self._memory().set_learned_skill_state(
            skill_id, state="active", ts_field="activated_ts", ts=time.time(),
        )
        self._event(skill_id, "activated", f"tier={LEARNED_SKILL_TIER}")
        return True

    def demote(self, skill_id: str, reason: str) -> bool:
        row = self.get(skill_id)
        if not row or row["state"] not in ("active", "candidate"):
            return False
        self._memory().set_learned_skill_state(skill_id, state="demoted")
        self._event(skill_id, "demoted", reason)
        return True

    def retire(self, skill_id: str, reason: str) -> bool:
        row = self.get(skill_id)
        if not row or row["state"] == "retired":
            return False
        self._memory().set_learned_skill_state(skill_id, state="retired")
        self._event(skill_id, "retired", reason)
        return True

    # ── reads ────────────────────────────────────────────────────────────

    def get(self, skill_id: str) -> dict | None:
        return self._memory().get_learned_skill(skill_id)

    def by_fingerprint(self, fingerprint: str) -> list[dict]:
        return [s for s in self._memory().list_learned_skills() if s["fingerprint"] == fingerprint]

    def list(self, state: str | None = None) -> list[dict]:
        return self._memory().list_learned_skills(state=state)

    def active_skills(self) -> list[dict]:
        """Active skills with their skeleton + slots parsed — the S8-4 planner
        consults this."""
        out = []
        for s in self._memory().list_learned_skills(state="active"):
            try:
                s = dict(s)
                s["skeleton"] = json.loads(s["skeleton_json"])
                s["slots"] = json.loads(s["slots_json"])
                out.append(s)
            except Exception:
                continue
        return out

    def events(self, skill_id: str) -> list[dict]:
        return self._memory().learned_skill_events(skill_id)

    # ── internal ─────────────────────────────────────────────────────────

    def _event(self, skill_id: str, event: str, detail: str | None = None) -> None:
        try:
            self._memory().add_learned_skill_event(skill_id, event, detail, time.time())
        except Exception:
            pass


skill_registry = SkillRegistry()
