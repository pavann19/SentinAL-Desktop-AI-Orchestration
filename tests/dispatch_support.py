"""Explicit human approval for dispatcher unit tests with mocked OS effects.

Security-boundary tests call the real executor directly without this helper.
Validation, capability derivation and dispatch checks remain enabled.
"""
from agentic_core.execution_authority import ExecutionAuthority, action_fingerprint, execution_scope


def execute_confirmed_pipeline(steps, cancel_event=None):
    from agentic_core.executor import execute_pipeline
    authority = ExecutionAuthority(autonomous=False, confirmed_actions=frozenset(action_fingerprint(s) for s in steps))
    with execution_scope(authority):
        return execute_pipeline(steps, cancel_event)


def execute_confirmed_graph(graph, cancel_event=None, budget=None):
    from capabilities.system.api_wrapper import execute_goal_graph_observed
    steps = graph.to_pipeline()
    authority = ExecutionAuthority(autonomous=False, confirmed_actions=frozenset(action_fingerprint(s) for s in steps))
    with execution_scope(authority):
        return execute_goal_graph_observed(graph, cancel_event, budget)
