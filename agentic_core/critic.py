# critic.py
# Resident Critic for SentinAL S5 Cognition Plane.
# Evaluates step and plan outcomes against real OS postcondition observations
# and bounds replanning loops to prevent runaway retries.

from __future__ import annotations

import logging
from dataclasses import dataclass

from agentic_core.executor import (
    _CANCELLATION_MESSAGE,
    FAILURE_CATEGORY_CANCELLED,
    FAILURE_CATEGORY_PIPELINE_ERROR,
    FAILURE_CATEGORY_POSTCONDITION_MISMATCH,
    FAILURE_CATEGORY_SUCCESS,
    MAX_REPLANS,
)
from agentic_core.goal_graph import GoalNode
from capabilities.system.postcondition_observer import Observation

_logger = logging.getLogger("Critic")


@dataclass
class CriticVerdict:
    """Verdict rendered by the resident critic for an executed step."""
    approved: bool
    needs_replan: bool
    failure_category: str
    reason: str
    feedback: str = ""


class ResidentCritic:
    """
    Resident Critic (P3 Cognition Plane).
    Reuses the existing postcondition observer to answer 'did this step actually work?'
    without duplicating verification machinery.
    """

    def __init__(self, max_replans: int = MAX_REPLANS):
        self.max_replans = max_replans

    def evaluate_step(
        self,
        node: GoalNode,
        execution_result: str,
        observation: Observation | None = None,
    ) -> CriticVerdict:
        """
        Evaluates a single step execution against its observed postcondition.

        Hierarchy of classification:
        1. Cancellation -> FAILURE_CATEGORY_CANCELLED, no replan.
        2. Execution string starts with 'ERROR' -> FAILURE_CATEGORY_PIPELINE_ERROR, no replan.
        3. Postcondition mismatch (checked tier unverified) -> FAILURE_CATEGORY_POSTCONDITION_MISMATCH, needs_replan=True.
        4. Verified / no negative observation -> FAILURE_CATEGORY_SUCCESS, approved=True.
        """
        # 1. Check cancellation
        if execution_result == _CANCELLATION_MESSAGE:
            return CriticVerdict(
                approved=False,
                needs_replan=False,
                failure_category=FAILURE_CATEGORY_CANCELLED,
                reason="Execution cancelled by system or user.",
                feedback="Step was cancelled. Do not retry.",
            )

        # 2. Check pipeline execution error
        if isinstance(execution_result, str) and execution_result.startswith("ERROR"):
            return CriticVerdict(
                approved=False,
                needs_replan=False,
                failure_category=FAILURE_CATEGORY_PIPELINE_ERROR,
                reason=f"Pipeline error: {execution_result}",
                feedback=f"Step execution encountered a hard error: {execution_result}",
            )

        # 3. Check postcondition observation
        if observation is not None and not observation.verified and observation.tier_used != "none":
            return CriticVerdict(
                approved=False,
                needs_replan=True,
                failure_category=FAILURE_CATEGORY_POSTCONDITION_MISMATCH,
                reason=(
                    f"Postcondition mismatch on tier '{observation.tier_used}': "
                    f"{observation.detail}"
                ),
                feedback=(
                    f"Postcondition check failed on tier '{observation.tier_used}'. "
                    f"Detail: {observation.detail}. Target state was not achieved."
                ),
            )

        # 4. Success / Verified
        detail = observation.detail if observation else "Execution reported success with no errors."
        return CriticVerdict(
            approved=True,
            needs_replan=False,
            failure_category=FAILURE_CATEGORY_SUCCESS,
            reason=f"Step verified successfully. {detail}",
            feedback="",
        )

    def should_replan(self, node: GoalNode, verdict: CriticVerdict) -> bool:
        """
        Determines whether a replan attempt should be triggered for a failed node.
        Strictly enforces the MAX_REPLANS ceiling to prevent infinite loops.
        """
        if not verdict.needs_replan:
            return False
        if verdict.failure_category != FAILURE_CATEGORY_POSTCONDITION_MISMATCH:
            return False
        return node.replan_count < self.max_replans


# Singleton resident critic
critic = ResidentCritic()
