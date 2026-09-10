"""
tests/test_planner.py
Unit tests for S5 Goal Graph Planner, multi-step gating, DAG generation,
and bounded replanning.
"""

from unittest.mock import MagicMock, patch
import pytest

from agentic_core.goal_graph import GoalGraph, GoalNode
from agentic_core.planner import (
    MAX_PLAN_STEPS,
    _deterministic_plan_fallback,
    is_multistep_query,
    planner,
)


# ── Gating: Fast Path Preservation ───────────────────────────────────────────

def test_is_multistep_query_single_step_returns_false():
    """Single-step requests must return False to preserve the zero-latency fast path."""
    single_step_prompts = [
        "open notepad",
        "launch calculator",
        "search for python tutorials",
        "what time is it",
        "delete file test.txt",
        "play jazz music",
        "show running processes",
        "hello",
    ]
    for prompt in single_step_prompts:
        assert is_multistep_query(prompt) is False, f"Expected False for '{prompt}'"


def test_is_multistep_query_multistep_returns_true():
    """Multi-step queries containing transition words or compound commands must return True."""
    multistep_prompts = [
        "open notepad and then open chrome",
        "search for AI news and paste into notepad",
        "open calculator and open notepad",
        "create a new react app and install axios",
        "first search for flights, then check weather",
    ]
    for prompt in multistep_prompts:
        assert is_multistep_query(prompt) is True, f"Expected True for '{prompt}'"


# ── Planning with LLM Mock ───────────────────────────────────────────────────

def test_plan_goal_with_llm_generates_dag():
    """plan_goal() with LLM returning JSON array must produce a validated GoalGraph."""
    mock_llm_response = MagicMock()
    mock_llm_response.content = """
    [
        {"step_id": "step_1", "intent": "InformationRetrievalIntent", "target": "SentinAL architecture", "prompt": "search architecture", "depends_on": []},
        {"step_id": "step_2", "intent": "ApplicationLaunchIntent", "target": "notepad", "prompt": "open notepad", "depends_on": ["step_1"]},
        {"step_id": "step_3", "intent": "GeneralizedOSIntent", "prompt": "paste result", "depends_on": ["step_2"], "actions": [{"type": "gui", "payload": "type", "value": "{{LAST_RESULT}}"}]}
    ]
    """
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_llm_response

    with patch("config.settings.BrainConfig.get_routed_llm", return_value=mock_llm):
        graph = planner.plan_goal("search architecture and paste into notepad")

    assert isinstance(graph, GoalGraph)
    assert len(graph.nodes) == 3
    assert graph.has_cycle() is False
    assert graph.nodes["step_2"].depends_on == ["step_1"]
    assert graph.nodes["step_3"].depends_on == ["step_2"]


def test_plan_goal_deterministic_fallback_on_llm_error():
    """If the LLM raises or returns malformed text, plan_goal() must fall back deterministically."""
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("LLM API Timeout")

    with patch("config.settings.BrainConfig.get_routed_llm", return_value=mock_llm):
        graph = planner.plan_goal("open notepad and open calculator")

    assert isinstance(graph, GoalGraph)
    assert len(graph.nodes) >= 1
    assert graph.has_cycle() is False


def test_plan_goal_breaks_cycles_if_llm_returns_circular_dag():
    """If LLM hallucinates a cyclic dependency, planner must detect and break the cycle."""
    mock_llm_response = MagicMock()
    mock_llm_response.content = """
    [
        {"step_id": "step_1", "intent": "ApplicationLaunchIntent", "target": "notepad", "depends_on": ["step_2"]},
        {"step_id": "step_2", "intent": "ApplicationLaunchIntent", "target": "calc", "depends_on": ["step_1"]}
    ]
    """
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_llm_response

    with patch("config.settings.BrainConfig.get_routed_llm", return_value=mock_llm):
        graph = planner.plan_goal("open notepad and calc")

    assert isinstance(graph, GoalGraph)
    assert graph.has_cycle() is False  # Cycle broken into linear chain


def test_plan_goal_bounds_max_steps():
    """Plans must be bounded by MAX_PLAN_STEPS to prevent runaway output."""
    many_steps = [
        {"step_id": f"step_{i+1}", "intent": "GeneralizedOSIntent", "depends_on": [f"step_{i}"] if i > 0 else []}
        for i in range(MAX_PLAN_STEPS + 5)
    ]
    import json
    mock_llm_response = MagicMock()
    mock_llm_response.content = json.dumps(many_steps)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_llm_response

    with patch("config.settings.BrainConfig.get_routed_llm", return_value=mock_llm):
        graph = planner.plan_goal("huge complex task")

    assert len(graph.nodes) <= MAX_PLAN_STEPS


# ── Bounded Replanning ───────────────────────────────────────────────────────

def test_replan_failed_node_increments_replan_count():
    """replan_failed_node() must increment replan_count and reset node status."""
    graph = GoalGraph("Test goal")
    node = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent", target="invalid_app", status="failed")
    graph.add_node(node)

    mock_llm_response = MagicMock()
    mock_llm_response.content = '[{"step_id": "step_1", "intent": "ApplicationLaunchIntent", "target": "notepad"}]'
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_llm_response

    with patch("config.settings.BrainConfig.get_routed_llm", return_value=mock_llm):
        updated_graph = planner.replan_failed_node(graph, "step_1", "Process not found")

    assert updated_graph.nodes["step_1"].replan_count == 1
    assert updated_graph.nodes["step_1"].target == "notepad"
    assert updated_graph.nodes["step_1"].status == "pending"


# ── S6 semantic memory (increment 2): advisory plan hint ─────────────────────

class TestSemanticPlanHint:
    """recall_plan() feeds the planner an advisory step-shape from a similar
    past success. Hint-only: it must reach the prompt, must be absent when
    there's no match, and must never bypass intent-allowlisting."""

    _RESP = MagicMock()
    _RESP.content = (
        '[{"step_id":"step_1","intent":"ApplicationLaunchIntent","target":"notepad","depends_on":[]}]'
    )

    def _mock_llm(self):
        m = MagicMock()
        m.invoke.return_value = self._RESP
        return m

    def test_hint_is_injected_into_the_plan_prompt(self):
        llm = self._mock_llm()
        with patch("config.settings.BrainConfig.get_routed_llm", return_value=llm), \
             patch("agentic_core.semantic_memory.recall_plan",
                   return_value=[{"intent": "ApplicationLaunchIntent", "target": "notepad"}]):
            planner.plan_goal("open notepad and open calculator")
        sent = llm.invoke.call_args[0][0][0][1]
        assert "[SIMILAR PAST PLAN]" in sent
        assert "ignore it" in sent

    def test_no_hint_when_recall_returns_none(self):
        llm = self._mock_llm()
        with patch("config.settings.BrainConfig.get_routed_llm", return_value=llm), \
             patch("agentic_core.semantic_memory.recall_plan", return_value=None):
            planner.plan_goal("open notepad and open calculator")
        sent = llm.invoke.call_args[0][0][0][1]
        assert "[SIMILAR PAST PLAN]" not in sent

    def test_recall_plan_raising_does_not_break_planning(self):
        llm = self._mock_llm()
        with patch("config.settings.BrainConfig.get_routed_llm", return_value=llm), \
             patch("agentic_core.semantic_memory.recall_plan",
                   side_effect=RuntimeError("boom")):
            graph = planner.plan_goal("open notepad and open calculator")
        assert isinstance(graph, GoalGraph)
        assert len(graph.nodes) >= 1

    def test_hint_cannot_smuggle_a_non_allowlisted_intent(self):
        # LLM echoes a bogus intent back as a step; the allowlist check must
        # still rewrite it to GeneralizedOSIntent regardless of the hint.
        resp = MagicMock()
        resp.content = '[{"step_id":"step_1","intent":"HackIntent","target":"x","depends_on":[]}]'
        llm = MagicMock()
        llm.invoke.return_value = resp
        with patch("config.settings.BrainConfig.get_routed_llm", return_value=llm), \
             patch("agentic_core.semantic_memory.recall_plan",
                   return_value=[{"intent": "HackIntent", "target": "x"}]):
            graph = planner.plan_goal("do a and do b")
        assert graph.nodes["step_1"].intent == "GeneralizedOSIntent"
