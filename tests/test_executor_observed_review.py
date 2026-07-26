"""Second-party review tests for execute_pipeline_observed().

These tests intentionally live outside tests/test_executor_observed.py so the
Gate-2 review artifact is separate from the implementer's original tests.
"""

import pytest

from agentic_core import executor


@pytest.mark.parametrize(
    "raw_result",
    [
        "",
        "{{LAST_RESULT}}",
        "x" * 10000,
        "ERROR",
    ],
)
def test_observed_wrapper_preserves_edge_case_result_strings(monkeypatch, raw_result):
    monkeypatch.setattr(
        executor,
        "execute_pipeline",
        lambda steps, cancel_event=None: raw_result,
    )

    observed = executor.execute_pipeline_observed([{"intent": "ReviewIntent"}])

    assert observed["result"] == raw_result


def test_observed_wrapper_passes_nonstandard_cancel_event_through(monkeypatch):
    received = {}

    class CancelTokenWithoutIsSet:
        pass

    token = CancelTokenWithoutIsSet()

    def fake_execute_pipeline(steps, cancel_event=None):
        received["cancel_event"] = cancel_event
        return "ok"

    monkeypatch.setattr(executor, "execute_pipeline", fake_execute_pipeline)

    observed = executor.execute_pipeline_observed(
        [{"intent": "ReviewIntent"}],
        cancel_event=token,
    )

    assert observed["result"] == "ok"
    assert received["cancel_event"] is token


@pytest.mark.parametrize("step", ["not-a-dict", 123, None, ["list-step"]])
def test_observed_wrapper_ignores_non_dict_steps(monkeypatch, step):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "ok")

    observed = executor.execute_pipeline_observed([step])

    assert observed["result"] == "ok"
    assert observed["step_observations"] == []


@pytest.mark.parametrize(
    "expected_state",
    ["bad-shape", ["bad-shape"], True, None],
)
def test_observed_wrapper_does_not_crash_on_malformed_expected_state(
    monkeypatch,
    expected_state,
):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "ok")

    observed = executor.execute_pipeline_observed(
        [{"intent": "ReviewIntent", "expected_state": expected_state}]
    )

    assert observed["result"] == "ok"
    assert isinstance(observed["step_observations"], list)


def test_observed_wrapper_handles_empty_step_list(monkeypatch):
    received = {}

    def fake_execute_pipeline(steps, cancel_event=None):
        received["steps"] = steps
        return "empty-ok"

    monkeypatch.setattr(executor, "execute_pipeline", fake_execute_pipeline)

    observed = executor.execute_pipeline_observed([])

    assert received["steps"] == []
    assert observed["result"] == "empty-ok"
    assert observed["step_observations"] == []


# FIXED in the follow-up commit after this review (see agentic_core/executor.py
# "Fix P1-4.2" comment) — observe_postcondition() is now wrapped so a raised
# exception can no longer lose the already-completed execute_pipeline()
# result. Found during independent review, fixed by the implementer.
def test_observed_wrapper_preserves_result_if_observer_raises(monkeypatch):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "done")

    import capabilities.system.postcondition_observer as pco

    def broken_observer(expected):
        raise RuntimeError("observer regression")

    monkeypatch.setattr(pco, "observe_postcondition", broken_observer)

    observed = executor.execute_pipeline_observed(
        [{"intent": "ReviewIntent", "expected_state": {"process_name": "sentinel"}}]
    )

    assert observed["result"] == "done"
    assert observed["step_observations"][0]["observation"].verified is False


# FIXED in the follow-up commit after this review (see agentic_core/executor.py
# "Fix P1-4.3" comment) — capture_state_snapshot()'s "after" call and
# diff_snapshots() are now wrapped so a raised exception can no longer lose
# the already-completed execute_pipeline() result. Found during independent
# review, fixed by the implementer.
def test_observed_wrapper_preserves_result_if_snapshot_diff_raises(monkeypatch):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "done")

    import capabilities.system.postcondition_observer as pco

    def broken_diff(before, after):
        raise RuntimeError("diff regression")

    monkeypatch.setattr(pco, "diff_snapshots", broken_diff)

    observed = executor.execute_pipeline_observed([{"intent": "ReviewIntent"}])

    assert observed["result"] == "done"
    assert observed["snapshot_diff"]["error"] == "diff regression"


# FIXED immediately after this finding (see agentic_core/executor.py
# "Fix P1-4.4" comment) — _classify_result() now only treats an observation as
# a genuine postcondition mismatch when something concrete was actually
# checkable (tier_used != "none"). A malformed expected_state correctly falls
# through to tier_used="none" and no longer wastes a replan. Third finding in
# this independent review round, found after the first two were merged.
@pytest.mark.parametrize("expected_state", ["bad-shape", True])
def test_observed_wrapper_does_not_waste_replan_on_malformed_expected_state(monkeypatch, expected_state):
    monkeypatch.setattr(executor, "execute_pipeline", lambda steps, cancel_event=None: "ok")

    observed = executor.execute_pipeline_observed(
        [{"intent": "ReviewIntent", "expected_state": expected_state}]
    )

    assert observed["replanned"] is False
    assert observed["attempts"] == 1
