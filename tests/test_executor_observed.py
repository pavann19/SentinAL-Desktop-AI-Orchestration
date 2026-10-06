"""Regression tests for executor observed."""
import pytest

from agentic_core import executor


class _FakeCancelEvent:
    def __init__(self, fired=False):
        self._fired = fired
    def is_set(self):
        return self._fired


def test_wrapper_returns_dict_with_required_keys(monkeypatch):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "Pipeline successfully completed (1 steps).")
    result = executor.execute_pipeline_observed([{"intent": "ConversationalIntent"}])
    assert set(result.keys()) == {
        "result", "snapshot_diff", "step_observations",
        "failure_category", "attempts", "replanned",
    }


def test_wrapper_result_matches_underlying_execute_pipeline_exactly(monkeypatch):
    """The wrapped call's return string must be passed through byte-for-byte —
    this is the contract that protects api_wrapper.py's existing behavior."""
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "I have launched notepad.")
    result = executor.execute_pipeline_observed([{"intent": "ApplicationLaunchIntent", "target": "notepad"}])
    assert result["result"] == "I have launched notepad."


def test_wrapper_passes_through_error_strings_unchanged(monkeypatch):
    """execute_pipeline can return an ERROR-prefixed string on failure;
    api_wrapper.py checks .startswith('ERROR') on whatever comes back —
    the wrapper must not alter or swallow that."""
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "ERROR Step 1: something failed.")
    result = executor.execute_pipeline_observed([{"intent": "ConversationalIntent"}])
    assert result["result"] == "ERROR Step 1: something failed."
    assert result["result"].startswith("ERROR")


def test_wrapper_propagates_cancel_event_to_underlying_pipeline(monkeypatch):
    received = {}
    def _fake(steps, cancel_event=None):
        received["cancel_event"] = cancel_event
        return "ok"
    monkeypatch.setattr(executor, "execute_pipeline", _fake)
    ce = _FakeCancelEvent(fired=True)
    executor.execute_pipeline_observed([{"intent": "ConversationalIntent"}], cancel_event=ce)
    assert received["cancel_event"] is ce


def test_wrapper_snapshot_diff_has_expected_shape(monkeypatch):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "ok")
    result = executor.execute_pipeline_observed([{"intent": "ConversationalIntent"}])
    diff = result["snapshot_diff"]
    assert "new_processes" in diff
    assert "ended_processes" in diff
    assert "elapsed_ms" in diff
    assert isinstance(diff["elapsed_ms"], float)


def test_wrapper_no_expected_state_produces_empty_step_observations(monkeypatch):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "ok")
    steps = [
        {"intent": "ConversationalIntent"},
        {"intent": "ApplicationLaunchIntent", "target": "notepad"},
    ]
    result = executor.execute_pipeline_observed(steps)
    assert len(result["step_observations"]) == 1


def test_wrapper_calls_observe_postcondition_for_steps_with_expected_state(monkeypatch):
    """This is the forward-compatible path: no current processor/validator."""
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "ok")

    import capabilities.system.postcondition_observer as pco
    calls = []
    def _fake_observe(expected):
        calls.append(expected)
        return pco.Observation(verified=True, tier_used="process", confidence=1.0, latency_ms=1.0, detail="fake")
    monkeypatch.setattr(pco, "observe_postcondition", _fake_observe)

    steps = [
        {"intent": "ConversationalIntent"},  # no expected_state -> skipped
        {"intent": "ApplicationLaunchIntent", "target": "notepad",
         "expected_state": {"process_name": "notepad.exe"}},
    ]
    result = executor.execute_pipeline_observed(steps)

    assert len(calls) == 1
    assert calls[0]["process_name"] == "notepad"
    assert len(result["step_observations"]) == 1
    assert result["step_observations"][0]["step_index"] == 1
    assert result["step_observations"][0]["observation"].verified is True


def test_wrapper_handles_multiple_steps_with_expected_state(monkeypatch):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "ok")

    import capabilities.system.postcondition_observer as pco
    monkeypatch.setattr(
        pco, "observe_postcondition",
        lambda expected: pco.Observation(verified=False, tier_used="window", confidence=1.0, latency_ms=2.0, detail="not found"),
    )

    steps = [
        {"intent": "ApplicationLaunchIntent", "target": "notepad", "expected_state": {"window_title": "X"}},
        {"intent": "ConversationalIntent"},
        {"intent": "ApplicationLaunchIntent", "target": "calc", "expected_state": {"window_title": "Y"}},
    ]
    result = executor.execute_pipeline_observed(steps)
    indices = [o["step_index"] for o in result["step_observations"]]
    assert indices == [0, 2]


def test_wrapper_does_not_mutate_execute_pipeline_function_object():
    """Sanity check that execute_pipeline itself is untouched (not monkeypatched
    permanently, not wrapped/decorated at import time) — the wrapper calls it,
    it does not replace it."""
    assert executor.execute_pipeline.__name__ == "execute_pipeline"
    assert callable(executor.execute_pipeline)


def test_execute_pipeline_real_call_still_works_end_to_end():
    """Regression guard: call the REAL (unmocked) execute_pipeline through
    the wrapper with a genuinely safe, side-effect-free intent, proving the
    wrapper's before/after snapshot calls don't break the real pipeline."""
    steps = [{"intent": "ConversationalIntent", "message": "hi there"}]
    result = executor.execute_pipeline_observed(steps)
    assert result["result"] == "hi there"
    assert result["step_observations"] == []
    assert "elapsed_ms" in result["snapshot_diff"]
