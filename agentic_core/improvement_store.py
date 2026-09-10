# agentic_core/improvement_store.py
# S9-1 — versioned self-improvement change store.
#
# Every candidate tuning change (a param tweak or a heuristic flip proposed by
# the cognition plane) is a row here. Lifecycle:
#
#   proposed -> shadow_passed / shadow_failed -> promoted / rejected
#   promoted -> reverted   (one step back; the previous promoted value for the
#                           same target becomes current again)
#
# current(target) is the newest promoted-and-not-reverted value. Nothing in
# the live pipeline reads current() yet — wiring that in is the S9 activation
# step, gated on a real shadow-eval run existing.
#
# CONTAINMENT_ARCHITECTURE §10.1: the store records; the control-plane review
# (improvement_engine.review) is the only thing that moves a row to 'promoted',
# and only against fixed criteria.

from __future__ import annotations

import hashlib
import json
import logging
import time

_logger = logging.getLogger("ImprovementStore")

_VALID_TARGET_PREFIXES = ("param:", "heuristic:", "prompt:")


def _version_id(target: str, to_value: str, ts: float) -> str:
    blob = f"{target}|{to_value}|{ts}"
    return "tv_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class ImprovementStore:
    def __init__(self, memory=None):
        self._mem = memory

    def _memory(self):
        if self._mem is None:
            from agentic_core.memory_hook import MemoryManager
            self._mem = MemoryManager()
        return self._mem

    # ── writes ───────────────────────────────────────────────────────────

    def propose(self, target: str, from_value, to_value, *,
                proposed_by: str = "proposer", rationale: str = "") -> str | None:
        """Register a candidate change. `target` is 'param:<NAME>' /
        'heuristic:<NAME>' / 'prompt:<NAME>'. Returns the version_id."""
        if not any(target.startswith(p) for p in _VALID_TARGET_PREFIXES):
            _logger.debug(f"rejecting malformed target {target!r}")
            return None
        ts = time.time()
        vid = _version_id(target, str(to_value), ts)
        try:
            self._memory().add_tuning_version(
                version_id=vid, target=target,
                from_value=None if from_value is None else str(from_value),
                to_value=str(to_value), proposed_by=proposed_by,
                rationale=rationale, ts=ts,
            )
            return vid
        except Exception as e:
            _logger.debug(f"propose failed (non-fatal): {e}")
            return None

    def record_shadow(self, version_id: str, *, before: float, after: float,
                      regressions: list) -> None:
        evidence = json.dumps({
            "before": round(before, 4), "after": round(after, 4),
            "delta": round(after - before, 4), "regressions": list(regressions),
        }, separators=(",", ":"))
        state = "shadow_passed" if (after >= before and not regressions) else "shadow_failed"
        self._memory().set_tuning_version_state(version_id, state, evidence_json=evidence)

    def promote(self, version_id: str) -> bool:
        row = self.get(version_id)
        if not row or row["state"] not in ("shadow_passed", "proposed"):
            return False
        self._memory().set_tuning_version_state(version_id, "promoted", decided_ts=time.time())
        return True

    def reject(self, version_id: str, reason: str = "") -> bool:
        row = self.get(version_id)
        if not row:
            return False
        ev = row.get("evidence_json")
        merged = json.dumps({**(json.loads(ev) if ev else {}), "reject_reason": reason},
                            separators=(",", ":"))
        self._memory().set_tuning_version_state(version_id, "rejected",
                                                evidence_json=merged, decided_ts=time.time())
        return True

    def revert(self, target: str) -> bool:
        """Roll the newest promoted change for `target` back one step."""
        promoted = [r for r in self._memory().list_tuning_versions(target=target)
                    if r["state"] == "promoted"]
        if not promoted:
            return False
        self._memory().set_tuning_version_state(promoted[0]["version_id"], "reverted",
                                                decided_ts=time.time())
        return True

    # ── reads ────────────────────────────────────────────────────────────

    def get(self, version_id: str) -> dict | None:
        return self._memory().get_tuning_version(version_id)

    def list(self, target: str | None = None, state: str | None = None) -> list[dict]:
        return self._memory().list_tuning_versions(target=target, state=state)

    def current(self, target: str):
        """Newest promoted-and-not-reverted to_value for `target`, or None."""
        for r in self._memory().list_tuning_versions(target=target):
            if r["state"] == "promoted":
                return r["to_value"]
        return None


improvement_store = ImprovementStore()
