"""
tests/test_planner_critic_integration.py
End-to-end integration tests for S5 Planner + Critic split, Goal Graph execution,
security validation boundary enforcement, and postcondition reflection.
"""

from unittest.mock import MagicMock, patch
import pytest

from agentic_core.goal_graph import GoalGraph, GoalNode
from agentic_core.processor import extract_goal_graph, extract_intent
from capabilities.system.api_wrapper import execute_goal_graph_observed, process_command
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


# ── process_command() -> execute_goal_graph_observed() wiring ─────────────────
# Regression guard for the exact gap a Gate-4 verification pass found: the
# critic-integrated goal-graph engine existed and was fully unit-tested in
# isolation, but process_command() — the actual live pipeline entry point —
# always flattened the planner's DAG via GoalGraph.to_pipeline() and ran it
# through the pre-existing execute_pipeline_observed(), never calling
# execute_goal_graph_observed() at all. That meant {{LAST_RESULT}} chaining
# (only resolved inside resolve_data_dependencies(), which only
# execute_goal_graph_observed() calls) silently passed through unresolved on
# a real request, and the Critic's per-step replan never ran live. These
# tests exercise the real seam — process_command() itself — not the engine
# in isolation, so they would have caught that gap.

class TestProcessCommandRoutesToGoalGraphEngine:

    @pytest.mark.asyncio
    async def test_multistep_prompt_resolves_last_result_chaining_end_to_end(self):
        """The concrete failure mode the gap produced: a chained placeholder
        reaching execution unresolved. Routes extract_intent() through a real
        (mocked-LLM) planner call so this exercises the actual live seam, not
        a hand-built graph."""
        graph = GoalGraph("search then paste")
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

        call_records = []

        def fake_run_and_observe(steps, cancel_event):
            step = steps[0]
            call_records.append(step)
            if step.get("intent") == "InformationRetrievalIntent":
                return "Found SentinAL Cognition Plane Spec", {}, [_obs(True, tier="none")]
            return "Pasted text successfully", {}, [_obs(True, tier="none")]

        with patch("agentic_core.planner.is_multistep_query", return_value=True), \
             patch("agentic_core.planner.planner.plan_goal", return_value=graph), \
             patch("agentic_core.executor._run_and_observe", side_effect=fake_run_and_observe):
            output = await process_command("search architecture and paste the result")

        assert output["validation"] == "Approved"
        assert output["execution"] == "Success"
        assert len(call_records) == 2
        # The whole point: step 2's action payload must carry the RESOLVED
        # value, not the literal "{{LAST_RESULT}}" template string a caller
        # would have seen before this seam was wired.
        assert call_records[1]["actions"][0]["value"] == "Result: Found SentinAL Cognition Plane Spec"
        assert "{{" not in call_records[1]["actions"][0]["value"]

    @pytest.mark.asyncio
    async def test_multistep_prompt_still_enforces_security_gate(self):
        """The seam must not bypass validate_steps() — same invariant as the
        isolated engine test above, proven through the real entry point."""
        graph = GoalGraph("attack via process_command")
        graph.add_node(GoalNode(
            step_id="step_1",
            intent="ApplicationLaunchIntent",
            target="C:\\Windows\\System32\\cmd.exe",
        ))

        with patch("agentic_core.planner.is_multistep_query", return_value=True), \
             patch("agentic_core.planner.planner.plan_goal", return_value=graph):
            output = await process_command("open cmd and then do something else")

        assert output["validation"] == "Denied"
        assert output["execution"] == "Blocked"

    @pytest.mark.asyncio
    async def test_single_step_prompt_does_not_use_goal_graph_response_shape(self):
        """Single-step traffic must keep the original execute_pipeline_observed()
        path untouched — this is the zero-added-latency guarantee S5's own
        design depends on. Checked here via the response shape: the old path
        sets output["attempts"], which execute_goal_graph_observed()'s
        response never includes. execute_pipeline_observed itself is mocked
        so this test stays hermetic regardless of what ConversationalIntent's
        real handler does."""
        with patch(
            "agentic_core.executor.execute_pipeline_observed",
            return_value={
                "result": "Hello!", "snapshot_diff": {}, "step_observations": [],
                "failure_category": "success", "attempts": 1, "replanned": False,
            },
        ):
            output = await process_command("what time is it")
        assert "attempts" in output
