"""
tests/test_goal_graph.py
Unit tests for S5 Goal Graph (DAG) data structure, topological sorting,
cycle detection, serialization, and dynamic data-chaining.
"""

import pytest
from agentic_core.goal_graph import GoalGraph, GoalNode


def test_goal_node_creation_and_serialization():
    """GoalNode must serialize to and deserialize from standard intent dictionaries."""
    node = GoalNode(
        step_id="step_1",
        intent="ApplicationLaunchIntent",
        target="notepad",
        prompt="open notepad",
        depends_on=[],
        expected_state={"process_name": "notepad"},
        extra={"speech_response": "Opening Notepad."},
    )
    d = node.to_dict()
    assert d["step_id"] == "step_1"
    assert d["intent"] == "ApplicationLaunchIntent"
    assert d["target"] == "notepad"
    assert d["speech_response"] == "Opening Notepad."
    assert d["expected_state"] == {"process_name": "notepad"}

    restored = GoalNode.from_dict(d)
    assert restored.step_id == node.step_id
    assert restored.intent == node.intent
    assert restored.target == node.target
    assert restored.expected_state == node.expected_state
    assert restored.extra.get("speech_response") == "Opening Notepad."


def test_goal_graph_topological_sort_linear():
    """Linear dependency chain step_1 -> step_2 -> step_3 must sort in order."""
    graph = GoalGraph("Open notepad, write text, save file")
    node1 = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent", target="notepad")
    node2 = GoalNode(step_id="step_2", intent="GeneralizedOSIntent", depends_on=["step_1"])
    node3 = GoalNode(step_id="step_3", intent="GeneralizedOSIntent", depends_on=["step_2"])

    # Add in scrambled order
    graph.add_node(node3)
    graph.add_node(node1)
    graph.add_node(node2)

    ordered = graph.topological_sort()
    ordered_ids = [n.step_id for n in ordered]
    assert ordered_ids == ["step_1", "step_2", "step_3"]


def test_goal_graph_diamond_dependency():
    r"""
    Diamond graph:
        step_1
       /      \
    step_2   step_3
       \      /
        step_4
    step_1 must run first, step_4 last.
    """
    graph = GoalGraph("Diamond task")
    graph.add_node(GoalNode(step_id="step_1", intent="InformationRetrievalIntent"))
    graph.add_node(GoalNode(step_id="step_2", intent="GeneralizedOSIntent", depends_on=["step_1"]))
    graph.add_node(GoalNode(step_id="step_3", intent="GeneralizedOSIntent", depends_on=["step_1"]))
    graph.add_node(GoalNode(step_id="step_4", intent="GeneralizedOSIntent", depends_on=["step_2", "step_3"]))

    ordered = graph.topological_sort()
    ids = [n.step_id for n in ordered]
    assert ids[0] == "step_1"
    assert ids[-1] == "step_4"
    assert set(ids[1:3]) == {"step_2", "step_3"}


def test_goal_graph_cycle_detection_raises_error():
    """A circular dependency step_1 -> step_2 -> step_1 must be detected and raise ValueError."""
    graph = GoalGraph("Cyclic task")
    graph.add_node(GoalNode(step_id="step_1", intent="A", depends_on=["step_2"]))
    graph.add_node(GoalNode(step_id="step_2", intent="B", depends_on=["step_1"]))

    assert graph.has_cycle() is True
    with pytest.raises(ValueError, match="Cycle detected"):
        graph.topological_sort()


def test_goal_graph_get_ready_nodes_and_completion():
    """get_ready_nodes() must only return nodes whose dependencies are completed."""
    graph = GoalGraph("Workflow")
    n1 = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent")
    n2 = GoalNode(step_id="step_2", intent="GeneralizedOSIntent", depends_on=["step_1"])
    graph.add_node(n1)
    graph.add_node(n2)

    ready = graph.get_ready_nodes()
    assert [n.step_id for n in ready] == ["step_1"]

    graph.mark_node_completed("step_1", result="Notepad opened")
    ready_after = graph.get_ready_nodes()
    assert [n.step_id for n in ready_after] == ["step_2"]


def test_goal_graph_data_dependency_resolution():
    """resolve_data_dependencies must replace {{LAST_RESULT}} and {{step_1.result}}."""
    graph = GoalGraph("Chained search and write")
    n1 = GoalNode(step_id="step_1", intent="InformationRetrievalIntent", target="AI News")
    n2 = GoalNode(
        step_id="step_2",
        intent="GeneralizedOSIntent",
        depends_on=["step_1"],
        actions=[{"type": "gui", "payload": "type", "value": "Summary: {{LAST_RESULT}} / {{step_1.result}}"}],
    )
    graph.add_node(n1)
    graph.add_node(n2)

    graph.mark_node_completed("step_1", result="Antigravity v2 Released")

    resolved = graph.resolve_data_dependencies(n2)
    action_val = resolved["actions"][0]["value"]
    assert action_val == "Summary: Antigravity v2 Released / Antigravity v2 Released"


def test_goal_graph_failure_blocks_downstream_dependents():
    """When a node fails, downstream dependent nodes must transition to 'blocked'."""
    graph = GoalGraph("Pipeline with failure")
    n1 = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent")
    n2 = GoalNode(step_id="step_2", intent="GeneralizedOSIntent", depends_on=["step_1"])
    graph.add_node(n1)
    graph.add_node(n2)

    graph.mark_node_failed("step_1", error="Process crash")
    assert graph.nodes["step_1"].status == "failed"
    assert graph.nodes["step_2"].status == "blocked"
    assert graph.has_failures() is True
    assert graph.is_complete() is True


def test_goal_graph_from_pipeline_and_to_pipeline():
    """Converting from a pipeline list to GoalGraph and back must preserve order and fields."""
    steps = [
        {"intent": "ApplicationLaunchIntent", "target": "notepad", "step_id": "step_1"},
        {"intent": "GeneralizedOSIntent", "actions": [{"type": "gui"}], "step_id": "step_2", "depends_on": ["step_1"]},
    ]
    graph = GoalGraph.from_pipeline(steps, goal_description="Test Goal")
    assert len(graph.nodes) == 2
    assert graph.nodes["step_2"].depends_on == ["step_1"]

    exported = graph.to_pipeline()
    assert len(exported) == 2
    assert exported[0]["step_id"] == "step_1"
    assert exported[1]["step_id"] == "step_2"
