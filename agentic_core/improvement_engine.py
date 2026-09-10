# agentic_core/improvement_engine.py
# S9-2 proposer + S9-3 shadow-eval orchestration + S9-4 control-plane review.
#
# CONTAINMENT_ARCHITECTURE §10.1: the cognition plane PROPOSES; the control
# plane EVALUATES against fixed, human-set criteria and PROMOTES. The proposer
# here is deliberately tiny and safe — it may only suggest a param value
# inside a declared range or flip a heuristic from a fixed list. It never
# touches the policy engine, capability tiers, the allowlist, or these
# criteria. Nothing is applied to the live system by this module.
#
# Never raises out of the public functions.

from __future__ import annotations

import logging
import os

from config.self_improvement import (
    ALLOW_REGRESSIONS,
    MIN_BENCHMARK_GAIN,
    PROPOSE_DRIFT_MIN,
    SELF_IMPROVEMENT_ENABLED,
    TUNABLE_PARAMS,
)

_logger = logging.getLogger("ImprovementEngine")


def _store():
    from agentic_core.improvement_store import improvement_store
    return improvement_store


# ── S9-2: proposer ────────────────────────────────────────────────────────

def propose_from_outcomes(drift=None) -> list[str]:
    """Read the drift report (S7 Half B) and emit conservative candidate
    changes. Returns the list of version_ids created. Applies nothing."""
    if not SELF_IMPROVEMENT_ENABLED:
        return []
    try:
        if drift is None:
            from agentic_core.world_model import drift_report
            drift = drift_report()
    except Exception:
        drift = []

    created: list[str] = []
    st = _store()

    # A capability drifting hard -> propose more replan headroom + a longer
    # observer settle window. Both are bounded, reversible, benign.
    hard_drift = [d for d in (drift or []) if d.get("drop", 0.0) >= PROPOSE_DRIFT_MIN]
    if hard_drift:
        names = ", ".join(sorted({d["intent"] for d in hard_drift}))
        for pname, (lo, hi) in TUNABLE_PARAMS.items():
            cur = _param_value(pname)
            nxt = _nudge(pname, cur, lo, hi)
            if nxt is not None and nxt != cur:
                vid = st.propose(
                    f"param:{pname}", cur, nxt,
                    proposed_by="drift-proposer",
                    rationale=f"sustained drift on {names} (drop>={PROPOSE_DRIFT_MIN})",
                )
                if vid:
                    created.append(vid)
    return created


def _param_value(name: str):
    from agentic_core.improvement_store import improvement_store
    cur = improvement_store.current(f"param:{name}")
    if cur is not None:
        return _coerce_int(cur)
    return _coerce_int(os.getenv(name))


def _coerce_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _nudge(name: str, cur, lo: int, hi: int):
    """One conservative step. Replan headroom and settle windows go UP under
    drift; step size is small and clamped."""
    base = cur if cur is not None else (lo + hi) // 2
    step = max(1, (hi - lo) // 4)
    return min(hi, base + step)


# ── S9-3: shadow evaluation (orchestration only) ──────────────────────────

def shadow_eval(version_id: str, *, benchmark_runner=None) -> dict:
    """Replay the candidate against the fixed benchmark OFFLINE and record the
    before/after. `benchmark_runner() -> (overall_rate, passed_task_ids)` is
    injectable; the real one needs a live desktop and is out of scope on this
    machine. Returns the evidence dict; {} on error / disabled."""
    if not SELF_IMPROVEMENT_ENABLED:
        return {}
    st = _store()
    row = st.get(version_id)
    if not row:
        return {}
    if benchmark_runner is None:
        _logger.info("shadow_eval: no benchmark_runner supplied — needs a live desktop; skipping")
        return {}
    try:
        before_rate, before_pass = benchmark_runner()  # baseline config
        with _applied(row["target"], row["to_value"]):
            after_rate, after_pass = benchmark_runner()  # candidate config
        regressions = sorted(set(before_pass) - set(after_pass))
        st.record_shadow(version_id, before=before_rate, after=after_rate,
                         regressions=regressions)
        return {"before": before_rate, "after": after_rate, "regressions": regressions}
    except Exception as e:
        _logger.debug(f"shadow_eval failed (non-fatal): {e}")
        return {}


class _applied:
    """Context manager: apply a candidate change to the process env for the
    duration of one shadow run, then restore. Only touches os.environ — never
    a config file or the running policy."""

    def __init__(self, target: str, to_value: str):
        self.kind, _, self.name = target.partition(":")
        self.to_value = to_value
        self._old = None
        self._had = False

    def __enter__(self):
        if self.kind in ("param", "heuristic"):
            self._had = self.name in os.environ
            self._old = os.environ.get(self.name)
            os.environ[self.name] = str(self.to_value)
        return self

    def __exit__(self, *_exc):
        if self.kind in ("param", "heuristic"):
            if self._had:
                os.environ[self.name] = self._old
            else:
                os.environ.pop(self.name, None)


# ── S9-4: control-plane review ───────────────────────────────────────────

def review(version_id: str) -> str:
    """Apply the fixed acceptance criteria to a shadow-evaluated candidate.
    Returns 'promoted' | 'rejected' | 'no_evidence' | 'disabled'. This is the
    ONLY path that promotes."""
    if not SELF_IMPROVEMENT_ENABLED:
        return "disabled"
    import json
    st = _store()
    row = st.get(version_id)
    if not row or not row.get("evidence_json"):
        return "no_evidence"
    ev = json.loads(row["evidence_json"])
    gain = ev.get("after", 0.0) - ev.get("before", 0.0)
    regressions = ev.get("regressions", [])
    if gain >= MIN_BENCHMARK_GAIN and (ALLOW_REGRESSIONS or not regressions):
        st.promote(version_id)
        _logger.info(f"[review] PROMOTED {version_id}: +{gain:.3f}, {len(regressions)} regressions")
        return "promoted"
    st.reject(version_id, reason=f"gain {gain:+.3f} < {MIN_BENCHMARK_GAIN} "
              f"or {len(regressions)} regression(s)")
    return "rejected"
