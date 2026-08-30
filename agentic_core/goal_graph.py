# goal_graph.py
# Goal Graph (DAG) Engine for SentinAL S5 Planner/Critic Architecture.
# Represents multi-step execution plans with explicit dependencies, topological sorting,
# cycle detection, and data-chaining without external framework dependencies.

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger("GoalGraph")


@dataclass
class GoalNode:
    """
    Represents an atomic step/node in a goal execution graph.
    Carries standard SentinAL intent fields alongside DAG dependency metadata.
    """
    step_id: str
    intent: str
    target: str = ""
    prompt: str = ""
    actions: list[dict] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    expected_state: dict | None = None
    status: str = "pending"  # "pending", "running", "completed", "failed", "skipped", "blocked"
    result: Any = None
    observation: Any = None
    replan_count: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serializes the node into a standard pipeline intent envelope."""
        envelope: dict[str, Any] = {
            "intent": self.intent,
            "target": self.target,
            "prompt": self.prompt,
            "step_id": self.step_id,
            "depends_on": list(self.depends_on),
            "status": self.status,
            "replan_count": self.replan_count,
        }
        if self.actions:
            envelope["actions"] = self.actions
        if self.expected_state:
            envelope["expected_state"] = self.expected_state
        if self.result is not None:
            envelope["result"] = self.result
        if self.observation is not None:
            envelope["observation"] = self.observation

        # Merge any extra metadata (speech_response, confidence, framework, etc.)
        for k, v in self.extra.items():
            if k not in envelope:
                envelope[k] = v
        return envelope

    @classmethod
    def from_dict(cls, data: dict) -> GoalNode:
        """Constructs a GoalNode from a dictionary envelope."""
        data_copy = dict(data)
        step_id = str(data_copy.pop("step_id", "") or "")
        intent = str(data_copy.pop("intent", "UnknownIntent") or "UnknownIntent")
        target = str(data_copy.pop("target", "") or "")
        prompt = str(data_copy.pop("prompt", "") or "")
        actions = data_copy.pop("actions", [])
        if not isinstance(actions, list):
            actions = []
        depends_on = data_copy.pop("depends_on", [])
        if not isinstance(depends_on, list):
            depends_on = []
        expected_state = data_copy.pop("expected_state", None)
        status = str(data_copy.pop("status", "pending") or "pending")
        result = data_copy.pop("result", None)
        observation = data_copy.pop("observation", None)
        replan_count = int(data_copy.pop("replan_count", 0) or 0)

        return cls(
            step_id=step_id,
            intent=intent,
            target=target,
            prompt=prompt,
            actions=actions,
            depends_on=[str(dep) for dep in depends_on],
            expected_state=expected_state if isinstance(expected_state, dict) else None,
            status=status,
            result=result,
            observation=observation,
            replan_count=replan_count,
            extra=data_copy,
        )


class GoalGraph:
    """
    Directed Acyclic Graph (DAG) of GoalNodes.
    Provides dependency resolution, topological ordering, cycle validation,
    and data-chaining for multi-step goals.
    """

    def __init__(self, goal_description: str = ""):
        self.goal_description = goal_description
        self.nodes: dict[str, GoalNode] = {}

    def add_node(self, node: GoalNode) -> None:
        """Adds a GoalNode to the graph. Assigns a step_id if absent."""
        if not node.step_id:
            node.step_id = f"step_{len(self.nodes) + 1}"
        self.nodes[node.step_id] = node

    def add_edge(self, parent_id: str, child_id: str) -> None:
        """Declares that child_id depends on parent_id."""
        if child_id not in self.nodes:
            raise KeyError(f"Child node '{child_id}' does not exist in graph.")
        if parent_id not in self.nodes:
            raise KeyError(f"Parent node '{parent_id}' does not exist in graph.")
        if parent_id not in self.nodes[child_id].depends_on:
            self.nodes[child_id].depends_on.append(parent_id)

    def get_dependencies(self, step_id: str) -> list[str]:
        """Returns direct dependency IDs for a given step."""
        if step_id not in self.nodes:
            return []
        return list(self.nodes[step_id].depends_on)

    def get_dependents(self, step_id: str) -> list[str]:
        """Returns IDs of nodes that directly depend on the given step."""
        return [nid for nid, node in self.nodes.items() if step_id in node.depends_on]

    def has_cycle(self) -> bool:
        """Checks if the graph contains any circular dependencies."""
        try:
            self.topological_sort()
            return False
        except ValueError:
            return True

    def topological_sort(self) -> list[GoalNode]:
        """
        Returns nodes in dependency-respecting topological order using Kahn's algorithm.
        Raises ValueError if a cycle is detected.
        """
        # Calculate in-degrees based on existing node dependencies
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        adj: dict[str, list[str]] = {nid: [] for nid in self.nodes}

        for nid, node in self.nodes.items():
            for dep in node.depends_on:
                if dep in self.nodes:
                    adj[dep].append(nid)
                    in_degree[nid] += 1

        # Queue nodes with in-degree 0 (preserve insertion order where tied)
        queue = [nid for nid in self.nodes if in_degree[nid] == 0]
        sorted_nodes: list[GoalNode] = []

        while queue:
            current_id = queue.pop(0)
            sorted_nodes.append(self.nodes[current_id])

            for dependent_id in adj[current_id]:
                in_degree[dependent_id] -= 1
                if in_degree[dependent_id] == 0:
                    queue.append(dependent_id)

        if len(sorted_nodes) != len(self.nodes):
            unresolved = [nid for nid, deg in in_degree.items() if deg > 0]
            raise ValueError(f"Cycle detected in GoalGraph involving nodes: {unresolved}")

        return sorted_nodes

    def get_ready_nodes(self) -> list[GoalNode]:
        """
        Returns all nodes whose dependencies have status == 'completed'
        and whose own status is 'pending'.
        """
        ready: list[GoalNode] = []
        for node in self.nodes.values():
            if node.status != "pending":
                continue
            deps_satisfied = True
            for dep_id in node.depends_on:
                dep_node = self.nodes.get(dep_id)
                if not dep_node or dep_node.status != "completed":
                    deps_satisfied = False
                    break
            if deps_satisfied:
                ready.append(node)
        return ready

    def mark_node_completed(self, step_id: str, result: Any = None, observation: Any = None) -> None:
        """Marks a node as completed and records its result and observation."""
        if step_id in self.nodes:
            self.nodes[step_id].status = "completed"
            self.nodes[step_id].result = result
            self.nodes[step_id].observation = observation

    def mark_node_failed(self, step_id: str, error: Any = None, observation: Any = None) -> None:
        """Marks a node as failed and blocks downstream dependents."""
        if step_id in self.nodes:
            self.nodes[step_id].status = "failed"
            self.nodes[step_id].result = error
            self.nodes[step_id].observation = observation

            # Mark downstream dependents as blocked
            for dep_id in self.get_dependents(step_id):
                if self.nodes[dep_id].status == "pending":
                    self.nodes[dep_id].status = "blocked"

    def resolve_data_dependencies(self, node: GoalNode) -> dict:
        """
        Replaces data placeholders in the node's fields:
          - '{{LAST_RESULT}}': replaced by the output of the most recent completed dependency
          - '{{<step_id>.result}}' or '{{<step_id>}}': replaced by specific parent step output
        Returns a resolved step dictionary suitable for validation/execution.
        """
        step_dict = node.to_dict()

        # Find candidate parent outputs
        last_result_val = ""
        parent_results: dict[str, str] = {}

        for dep_id in node.depends_on:
            parent = self.nodes.get(dep_id)
            if parent and parent.result is not None:
                res_str = str(parent.result)
                parent_results[dep_id] = res_str
                last_result_val = res_str

        def _substitute_text(text: str) -> str:
            if not isinstance(text, str) or "{{" not in text:
                return text
            out = text.replace("{{LAST_RESULT}}", last_result_val)
            for pid, res in parent_results.items():
                out = out.replace("{{" + pid + ".result}}", res)
                out = out.replace("{{" + pid + "}}", res)
            return out

        def _deep_substitute(obj: Any) -> Any:
            if isinstance(obj, str):
                return _substitute_text(obj)
            if isinstance(obj, list):
                return [_deep_substitute(elem) for elem in obj]
            if isinstance(obj, dict):
                return {k: _deep_substitute(v) for k, v in obj.items()}
            return obj

        return _deep_substitute(step_dict)

    def to_pipeline(self) -> list[dict]:
        """
        Converts the graph into an ordered list of step envelopes (topological order).
        """
        ordered = self.topological_sort()
        return [n.to_dict() for n in ordered]

    @classmethod
    def from_pipeline(cls, steps: list[dict], goal_description: str = "") -> GoalGraph:
        """
        Constructs a GoalGraph from a list of intent dictionaries.
        Preserves sequential linear dependencies if no explicit depends_on is declared.
        """
        graph = cls(goal_description=goal_description)
        prev_id = ""
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("step_id", "") or f"step_{i+1}")
            step_copy = dict(step)
            step_copy["step_id"] = step_id

            # If no explicit dependencies, chain to immediately preceding step
            if "depends_on" not in step_copy and prev_id:
                step_copy["depends_on"] = [prev_id]

            node = GoalNode.from_dict(step_copy)
            graph.add_node(node)
            prev_id = step_id

        return graph

    def to_dict(self) -> dict:
        """Full serialization of graph to dict."""
        return {
            "goal_description": self.goal_description,
            "nodes": {nid: node.to_dict() for nid, node in self.nodes.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> GoalGraph:
        """Full deserialization of graph from dict."""
        graph = cls(goal_description=str(data.get("goal_description", "") or ""))
        nodes_data = data.get("nodes", {})
        if isinstance(nodes_data, dict):
            for nid, ndict in nodes_data.items():
                if isinstance(ndict, dict):
                    if "step_id" not in ndict:
                        ndict["step_id"] = nid
                    graph.add_node(GoalNode.from_dict(ndict))
        return graph

    def is_complete(self) -> bool:
        """Returns True if all nodes are in a terminal state (completed, failed, skipped, blocked)."""
        return all(n.status in {"completed", "failed", "skipped", "blocked"} for n in self.nodes.values())

    def has_failures(self) -> bool:
        """Returns True if any node has status == 'failed'."""
        return any(n.status == "failed" for n in self.nodes.values())
