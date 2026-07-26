"""
Tests for P1-4: failure taxonomy + bounded replan on postcondition mismatch,
implemented as an extension of agentic_core.executor.execute_pipeline_observed().

Same process note as tests/test_executor_observed.py (P1-1): the integrator
role is both implementer and test-author here (task never delegated,
security-critical). A second-party review of P1-1 has been dispatched
separately; the same review should eventually cover this P1-4 extension too
since it lives in the same function.
"""
import capabilities.system.postcondition_observer as pco
from agentic_core import executor


def _obs(verified, tier="process", detail="x"):
    return pco.Observation(verified=verified, tier_used=tier, confidence=1.0, latency_ms=1.0, detail=detail)


# ── Failure taxonomy classification ────────────────────────────────────────

def test_classify_cancelled_takes_priority():
    category = executor._classify_result(
        "Mission interrupted by system.",
        [{"step_index": 0, "observation": _obs(False)}],
    )
    assert category == executor.FAILURE_CATEGORY_CANCELLED


def test_classify_pipeline_error_takes_priority_over_mismatch():
    category = executor._classify_result(
        "ERROR Step 1: something failed.",
        [{"step_index": 0, "observation": _obs(False)}],
    )
    assert category == executor.FAILURE_CATEGORY_PIPELINE_ERROR


def test_classify_postcondition_mismatch_when_result_looks_ok_but_unverified():
    category = executor._classify_result(
        "I have launched notepad.",
        [{"step_index": 0, "observation": _obs(False)}],
    )
    assert category == executor.FAILURE_CATEGORY_POSTCONDITION_MISMATCH


def test_classify_success_when_all_observations_verified():
    category = executor._classify_result(
        "I have launched notepad.",
        [{"step_index": 0, "observation": _obs(True)}],
    )
    assert category == executor.FAILURE_CATEGORY_SUCCESS


def test_classify_success_when_no_observations_at_all():
    category = executor._classify_result("Pipeline successfully completed (1 steps).", [])
    assert category == executor.FAILURE_CATEGORY_SUCCESS


# ── Bounded replan behavior ────────────────────────────────────────────────

def test_replan_triggers_once_on_mismatch_then_succeeds(monkeypatch):
    """First run: mismatch. Second run (replan): verified. Must stop at 2 attempts."""
    call_count = {"n": 0}

    def _fake_run_and_observe(steps, cancel_event):
        call_count["n"] += 1
        verified = call_count["n"] >= 2  # fails first time, succeeds on replan
        return (
            "I have launched notepad.",
            {"new_processes": [], "ended_processes": [], "elapsed_ms": 1.0},
            [{"step_index": 0, "observation": _obs(verified)}],
        )

    monkeypatch.setattr(executor, "_run_and_observe", _fake_run_and_observe)
    result = executor.execute_pipeline_observed([{"intent": "ApplicationLaunchIntent", "expected_state": {"process_name": "notepad.exe"}}])

    assert call_count["n"] == 2
    assert result["attempts"] == 2
    assert result["replanned"] is True
    assert result["failure_category"] == executor.FAILURE_CATEGORY_SUCCESS


def test_replan_capped_at_max_replans_even_if_still_mismatched(monkeypatch):
    """Every attempt mismatches. Must stop at 1 + MAX_REPLANS total calls, not loop forever."""
    call_count = {"n": 0}

    def _fake_run_and_observe(steps, cancel_event):
        call_count["n"] += 1
        return (
            "I have launched notepad.",
            {"new_processes": [], "ended_processes": [], "elapsed_ms": 1.0},
            [{"step_index": 0, "observation": _obs(False)}],
        )

    monkeypatch.setattr(executor, "_run_and_observe", _fake_run_and_observe)
    result = executor.execute_pipeline_observed([{"intent": "X", "expected_state": {"process_name": "y"}}])

    assert call_count["n"] == 1 + executor.MAX_REPLANS
    assert result["attempts"] == 1 + executor.MAX_REPLANS
    assert result["replanned"] is True
    assert result["failure_category"] == executor.FAILURE_CATEGORY_POSTCONDITION_MISMATCH


def test_no_replan_on_pipeline_error(monkeypatch):
    """A genuine ERROR result must NOT trigger a replan — re-running a pipeline
    that already errored partway through risks duplicate side effects."""
    call_count = {"n": 0}

    def _fake_run_and_observe(steps, cancel_event):
        call_count["n"] += 1
        return ("ERROR Step 1: failed.", {"new_processes": [], "ended_processes": [], "elapsed_ms": 1.0}, [])

    monkeypatch.setattr(executor, "_run_and_observe", _fake_run_and_observe)
    result = executor.execute_pipeline_observed([{"intent": "X"}])

    assert call_count["n"] == 1
    assert result["replanned"] is False
    assert result["failure_category"] == executor.FAILURE_CATEGORY_PIPELINE_ERROR


def test_no_replan_on_cancellation(monkeypatch):
    call_count = {"n": 0}

    def _fake_run_and_observe(steps, cancel_event):
        call_count["n"] += 1
        return ("Mission interrupted by system.", {"new_processes": [], "ended_processes": [], "elapsed_ms": 1.0}, [])

    monkeypatch.setattr(executor, "_run_and_observe", _fake_run_and_observe)
    result = executor.execute_pipeline_observed([{"intent": "X"}])

    assert call_count["n"] == 1
    assert result["replanned"] is False
    assert result["failure_category"] == executor.FAILURE_CATEGORY_CANCELLED


def test_no_replan_on_immediate_success(monkeypatch):
    call_count = {"n": 0}

    def _fake_run_and_observe(steps, cancel_event):
        call_count["n"] += 1
        return ("ok", {"new_processes": [], "ended_processes": [], "elapsed_ms": 1.0}, [{"step_index": 0, "observation": _obs(True)}])

    monkeypatch.setattr(executor, "_run_and_observe", _fake_run_and_observe)
    result = executor.execute_pipeline_observed([{"intent": "X"}])

    assert call_count["n"] == 1
    assert result["replanned"] is False
    assert result["attempts"] == 1


# ── Pre-emptive hardening: observe_postcondition raising unexpectedly ──────

def test_observe_postcondition_raising_does_not_lose_execute_pipeline_result(monkeypatch):
    """The exact risk category flagged in the independent P1-1 review pack:
    if observe_postcondition() raises AFTER execute_pipeline() already ran
    (and may have mutated real system state), the wrapper must not crash and
    lose that already-completed result."""
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "I have launched notepad.")

    def _raise(expected):
        raise RuntimeError("simulated violation of the never-raises contract")
    monkeypatch.setattr(pco, "observe_postcondition", _raise)

    steps = [{"intent": "ApplicationLaunchIntent", "expected_state": {"process_name": "notepad.exe"}}]
    result = executor.execute_pipeline_observed(steps)

    # Must not raise. Must still carry the real execute_pipeline result through.
    assert result["result"] == "I have launched notepad."
    assert len(result["step_observations"]) == 1
    obs = result["step_observations"][0]["observation"]
    assert obs.verified is False
    assert "raised unexpectedly" in obs.detail
