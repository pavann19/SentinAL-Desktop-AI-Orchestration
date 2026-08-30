# planner.py
# Goal Graph Planner for SentinAL S5 Cognition Plane.
# Decomposes multi-step goals into dependency-aware GoalGraphs (DAGs).
# Invoked ON-DEMAND only behind the multi-step signal; single-step requests bypass this entirely.

from __future__ import annotations

import logging
import os
import re
from typing import Any

from agentic_core.goal_graph import GoalGraph, GoalNode
from config.constants import ALLOWLIST_INTENTS
from config.prompts import PLANNER_SYSTEM_PROMPT
from config.settings import BrainConfig

_logger = logging.getLogger("Planner")

# Maximum allowed steps in a generated plan to bound cognition overhead
MAX_PLAN_STEPS = int(os.getenv("SENTINAL_PLANNER_MAX_STEPS", "10"))

# Connectors and sequential transition words signaling multi-step intent
_MULTISTEP_TRANSITIONS = (
    "and then", "then", "after that", "afterwards", "followed by",
    "and also", "and next", "subsequently", "first",
)

_ACTION_VERBS = (
    "open", "launch", "start", "run", "search", "find", "play", "listen",
    "delete", "remove", "erase", "close", "kill", "terminate", "type",
    "create", "make", "scaffold", "install", "add", "summarize", "plot",
)


def is_multistep_query(prompt: str) -> bool:
    """
    Deterministic gate to determine whether a query needs multi-step planning.
    Fast (pure string matching, zero LLM, sub-millisecond).

    Preserves the single-step fast path (~94% of traffic) so single commands
    pay zero added latency and zero LLM cost.
    """
    if not prompt or not prompt.strip():
        return False

    p = prompt.strip().lower()

    # Explicit multi-step transitional phrases
    if any(trans in p for trans in _MULTISTEP_TRANSITIONS):
        return True

    # Check for conjunction 'and' or comma separating multiple clauses/verbs
    if " and " in p or "," in p:
        # Split on conjunctions
        parts = [part.strip() for part in re.split(r'\band\b|,', p) if part.strip()]
        if len(parts) > 1:
            # Count parts that start with or contain an action verb
            action_parts_count = 0
            for part in parts:
                words = part.split()
                if not words:
                    continue
                if any(part.startswith(v) or (len(words) > 1 and words[0] in _ACTION_VERBS) for v in _ACTION_VERBS):
                    action_parts_count += 1
                elif len(words) >= 2:
                    action_parts_count += 1

            if action_parts_count >= 2:
                return True

    return False


def _safe_parse_plan_json(raw_text: str) -> list[dict] | None:
    """Safely extracts a JSON list of plan steps from LLM output."""
    if not raw_text or not raw_text.strip():
        return None

    from agentic_core.processor import clean_llm_json, safe_json_loads
    cleaned = clean_llm_json(raw_text)
    parsed = safe_json_loads(cleaned, context="Planner")
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict) and "steps" in parsed and isinstance(parsed["steps"], list):
        return [item for item in parsed["steps"] if isinstance(item, dict)]
    return None


def _deterministic_plan_fallback(prompt: str) -> GoalGraph:
    """
    Deterministic fallback: decomposes multi-step query using split_multistep()
    and sequential graph chaining when the LLM is unavailable or fails.
    Guarantees the system never crashes on planning failure.
    """
    from agentic_core.processor import extract_app_query, split_multistep
    from agentic_core.router import router

    _logger.info(f"[Planner] Using deterministic DAG fallback for: '{prompt}'")
    queries = split_multistep(prompt)
    graph = GoalGraph(goal_description=prompt)

    prev_step_id = ""
    for idx, step_query in enumerate(queries[:MAX_PLAN_STEPS]):
        step_id = f"step_{idx+1}"

        # Check deterministic app map / registry
        app_match = extract_app_query(step_query)
        if app_match:
            intent = "ApplicationLaunchIntent"
            target = app_match
        else:
            route_res = router.route(step_query)
            intent = route_res.get("intent", "GeneralizedOSIntent")
            target = step_query

        node = GoalNode(
            step_id=step_id,
            intent=intent,
            target=target,
            prompt=step_query,
            depends_on=[prev_step_id] if prev_step_id else [],
            extra={"speech_response": f"Executing step {idx+1}: {step_query}"},
        )
        graph.add_node(node)
        prev_step_id = step_id

    return graph


class GoalGraphPlanner:
    """
    Goal Graph Planner (P3 Cognition Plane).
    Decomposes multi-step user prompts into a dependency graph (GoalGraph).
    """

    def plan_goal(self, prompt: str, context: dict | None = None) -> GoalGraph:
        """
        Decomposes a multi-step user prompt into a GoalGraph.
        Returns a validated DAG with dependencies and resolved step envelopes.
        """
        if not is_multistep_query(prompt):
            # Single-step: wrap in a 1-node GoalGraph
            from agentic_core.router import router
            route_res = router.route(prompt)
            node = GoalNode(
                step_id="step_1",
                intent=route_res.get("intent", "UnknownIntent"),
                target=prompt,
                prompt=prompt,
                depends_on=[],
                extra={"speech_response": "Executing your request."},
            )
            graph = GoalGraph(goal_description=prompt)
            graph.add_node(node)
            return graph

        _logger.info(f"[Planner] Multi-step goal detected. Engaging Goal Graph Planner for: '{prompt}'")

        try:
            llm = BrainConfig.get_routed_llm(prompt, "Planner")
            plan_prompt = (
                f"{PLANNER_SYSTEM_PROMPT}\n\n"
                f"User Goal: '{prompt}'\n\n"
                f"Decompose this goal into a JSON array of step objects with step_id, "
                f"intent, target, prompt, depends_on, and speech_response."
            )
            response = llm.invoke([("system", plan_prompt)])
            steps_data = _safe_parse_plan_json(response.content)

            if not steps_data:
                _logger.warning("[Planner] LLM did not return a valid step array. Falling back to deterministic DAG.")
                return _deterministic_plan_fallback(prompt)

            # Construct GoalGraph
            graph = GoalGraph(goal_description=prompt)
            for idx, sdata in enumerate(steps_data[:MAX_PLAN_STEPS]):
                step_id = str(sdata.get("step_id", "") or f"step_{idx+1}")
                sdata["step_id"] = step_id

                # Validate intent
                intent = sdata.get("intent", "GeneralizedOSIntent")
                if intent not in ALLOWLIST_INTENTS:
                    sdata["intent"] = "GeneralizedOSIntent"

                node = GoalNode.from_dict(sdata)
                graph.add_node(node)

            # Check for cycles
            if graph.has_cycle():
                _logger.warning("[Planner] Cycle detected in LLM-generated plan. Breaking circular dependencies.")
                # Fallback: enforce linear chain to remove cycles
                prev_id = ""
                for nid, node in graph.nodes.items():
                    node.depends_on = [prev_id] if prev_id else []
                    prev_id = nid

            _logger.info(f"[Planner] GoalGraph successfully generated with {len(graph.nodes)} nodes.")
            return graph

        except Exception as e:
            _logger.error(f"[Planner] Planning failed with exception: {e}. Using deterministic fallback.")
            return _deterministic_plan_fallback(prompt)

    def replan_failed_node(
        self,
        graph: GoalGraph,
        failed_step_id: str,
        critic_feedback: str,
    ) -> GoalGraph:
        """
        Performs bounded replanning for a failed node and its downstream subgraph.
        Increments replan_count and adjusts step parameters.
        """
        if failed_step_id not in graph.nodes:
            return graph

        failed_node = graph.nodes[failed_step_id]
        failed_node.replan_count += 1
        _logger.info(
            f"[Planner] Replanning node '{failed_step_id}' (replan {failed_node.replan_count}) "
            f"with feedback: {critic_feedback}"
        )

        try:
            llm = BrainConfig.get_routed_llm(failed_node.prompt, "Planner")
            replan_prompt = (
                f"{PLANNER_SYSTEM_PROMPT}\n\n"
                f"Original Goal: '{graph.goal_description}'\n"
                f"Failed Step ID: '{failed_step_id}'\n"
                f"Failed Step Detail: Intent={failed_node.intent}, Target={failed_node.target}, Prompt='{failed_node.prompt}'\n"
                f"Critic Feedback: '{critic_feedback}'\n\n"
                f"Please generate a revised step object (or small array of replacement steps) to achieve "
                f"this step's objective successfully. Output ONLY valid JSON."
            )
            response = llm.invoke([("system", replan_prompt)])
            replacement_steps = _safe_parse_plan_json(response.content)

            if replacement_steps and len(replacement_steps) > 0:
                rep_data = replacement_steps[0]
                failed_node.intent = rep_data.get("intent", failed_node.intent)
                failed_node.target = rep_data.get("target", failed_node.target)
                if "actions" in rep_data:
                    failed_node.actions = rep_data["actions"]
                if "expected_state" in rep_data:
                    failed_node.expected_state = rep_data["expected_state"]
                failed_node.status = "pending"
                _logger.info(f"[Planner] Node '{failed_step_id}' revised by replanner.")
            else:
                # Reset status to pending for simple retry
                failed_node.status = "pending"

        except Exception as e:
            _logger.warning(f"[Planner] Replan LLM call failed ({e}). Resetting node for simple bounded retry.")
            failed_node.status = "pending"

        return graph


# Singleton planner
planner = GoalGraphPlanner()
