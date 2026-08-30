"""
tests/test_planner_critic_integration.py
End-to-end integration tests for S5 Planner + Critic split, Goal Graph execution,
security validation boundary enforcement, and postcondition reflection.
"""

from unittest.mock import MagicMock, patch
import pytest

from agentic_core.goal_graph import GoalGraph, GoalNode
from agentic_core.processor import extract_goal_graph, extract_intent
from capabilities.system.api_wrapper import execute_goal_graph_observed
from capabilities.system.postcondition_observer import Observation


def _obs(verified: bool, tier: str = "process", detail: str = "test"):
    return Observation(
        verified=verified,
        tier_used=tier,
        confidence=1.0 if verified else 0.0,
        latency_ms=1.0,
        detail=detail,
    )


# ── Fast Path Zero-Cost Regression Guard ──────────────────────────────────────

def test_single_step_request_bypasses_planner():
    """Single-step commands must not invoke the Planner LLM at all."""
    with patch("agentic_core.planner.planner.plan_goal") as mock_planner:
        steps = extract_intent("what time is it")
        assert len(steps) == 1
        assert steps[0]["intent"] == "ConversationalIntent"
        mock_planner.assert_not_called()


# ── Full Goal Graph Execution through Security Boundary ───────────────────────

def test_execute_goal_graph_enforces_validator_security_gate():
    """
    CRITICAL SECURITY INVARIANT: If any node contains an illegal target (e.g. system32),
    validate_steps() MUST block it and halt the goal graph.
    """
    graph = GoalGraph("Attack scenario")
    node = GoalNode(
        step_id="step_1",
        intent="ApplicationLaunchIntent",
        target="C:\\Windows\\System32\\cmd.exe",
    )
    graph.add_node(node)

    result = execute_goal_graph_observed(graph)
    assert result["validation"] == "Denied"
    assert result["execution"] == "Blocked"
    assert "security validation" in result["response"]
    assert graph.nodes["step_1"].status == "failed"


def test_execute_goal_graph_successful_multi_step_with_data_chaining():
    """
    Successful multi-step DAG execution:
    step_1 (search) -> step_2 (paste result into notepad)
    Must validate, execute, observe, and propagate data correctly.
    """
    graph = GoalGraph("Search and paste workflow")
    graph.add_node(GoalNode(
        step_id="step_1",
        intent="InformationRetrievalIntent",
        target="SentinAL S5 Design",
        prompt="search architecture",
    ))
    graph.add_node(GoalNode(
        step_id="step_2",
        intent="GeneralizedOSIntent",
        prompt="paste result",
        depends_on=["step_1"],
        actions=[{"type": "gui", "payload": "type", "value": "Result: {{LAST_RESULT}}"}],
    ))

    # Mock _run_and_observe to simulate real step outputs
    call_records = []

    def fake_run_and_observe(steps, cancel_event):
        step = steps[0]
        call_records.append(step)
        if step.get("intent") == "InformationRetrievalIntent":
            return "Found SentinAL Cognition Plane Spec", {}, [_obs(True, tier="none")]
        else:
            return "Pasted text successfully", {}, [_obs(True, tier="none")]

    with patch("agentic_core.executor._run_and_observe", side_effect=fake_run_and_observe):
        res = execute_goal_graph_observed(graph)

    assert res["validation"] == "Approved"
    assert res["execution"] == "Success"
    assert len(call_records) == 2
    # Verify {{LAST_RESULT}} was substituted in step 2's action payload
    assert call_records[1]["actions"][0]["value"] == "Result: Found SentinAL Cognition Plane Spec"
    assert graph.is_complete() is True
    assert not graph.has_failures()


def test_execute_goal_graph_bounded_replan_on_postcondition_mismatch():
    """
    When a step's postcondition check fails, the Critic must trigger a bounded replan.
    If the replanned step succeeds, the graph completes.
    """
    graph = GoalGraph("Launch and confirm")
    graph.add_node(GoalNode(
        step_id="step_1",
        intent="ApplicationLaunchIntent",
        target="notepad",
        expected_state={"process_name": "notepad"},
    ))

    attempts = {"count": 0}

    def fake_run_and_observe(steps, cancel_event):
        attempts["count"] += 1
        # First attempt fails postcondition, second attempt succeeds
        verified = attempts["count"] >= 2
        obs_detail = "notepad found" if verified else "notepad not found"
        return "I have launched notepad.", {}, [{"step_index": 0, "observation": _obs(verified, "process", obs_detail)}]

    with patch("agentic_core.executor._run_and_observe", side_effect=fake_run_and_observe):
        res = execute_goal_graph_observed(graph)

    assert res["validation"] == "Approved"
    assert res["execution"] == "Success"
    assert res["replanned"] is True
    assert attempts["count"] == 2
    assert graph.nodes["step_1"].status == "completed"
    assert graph.nodes["step_1"].replan_count == 1
