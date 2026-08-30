"""
tests/test_critic.py
Unit tests for S5 Resident Critic: postcondition evaluation, failure categorization,
and bounded replan checks.
"""

from agentic_core.critic import ResidentCritic, critic
from agentic_core.executor import (
    FAILURE_CATEGORY_CANCELLED,
    FAILURE_CATEGORY_PIPELINE_ERROR,
    FAILURE_CATEGORY_POSTCONDITION_MISMATCH,
    FAILURE_CATEGORY_SUCCESS,
    _CANCELLATION_MESSAGE,
)
from agentic_core.goal_graph import GoalNode
from capabilities.system.postcondition_observer import Observation


def _make_obs(verified: bool, tier: str = "process", detail: str = "test"):
    return Observation(
        verified=verified,
        tier_used=tier,
        confidence=1.0 if verified else 0.0,
        latency_ms=1.5,
        detail=detail,
    )


def test_critic_evaluates_verified_step_as_approved():
    """Verified postcondition must yield approved=True and failure_category=SUCCESS."""
    node = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent", target="notepad")
    obs = _make_obs(verified=True, tier="process", detail="process 'notepad.exe' found")

    verdict = critic.evaluate_step(node, "I have launched notepad.", obs)
    assert verdict.approved is True
    assert verdict.needs_replan is False
    assert verdict.failure_category == FAILURE_CATEGORY_SUCCESS


def test_critic_evaluates_postcondition_mismatch_as_needs_replan():
    """Unverified postcondition with active tier must flag POSTCONDITION_MISMATCH and needs_replan=True."""
    node = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent", target="notepad")
    obs = _make_obs(verified=False, tier="process", detail="process 'notepad' not found")

    verdict = critic.evaluate_step(node, "I have launched notepad.", obs)
    assert verdict.approved is False
    assert verdict.needs_replan is True
    assert verdict.failure_category == FAILURE_CATEGORY_POSTCONDITION_MISMATCH
    assert "process 'notepad' not found" in verdict.reason


def test_critic_evaluates_pipeline_error_without_replan():
    """Hard pipeline errors (starts with ERROR) must NOT trigger replan."""
    node = GoalNode(step_id="step_1", intent="GeneralizedOSIntent")
    verdict = critic.evaluate_step(node, "ERROR Step 1: Access is denied.")

    assert verdict.approved is False
    assert verdict.needs_replan is False
    assert verdict.failure_category == FAILURE_CATEGORY_PIPELINE_ERROR


def test_critic_evaluates_cancellation_without_replan():
    """Cancelled execution must yield CANCELLED category and no replan."""
    node = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent")
    verdict = critic.evaluate_step(node, _CANCELLATION_MESSAGE)

    assert verdict.approved is False
    assert verdict.needs_replan is False
    assert verdict.failure_category == FAILURE_CATEGORY_CANCELLED


def test_critic_should_replan_strictly_bounds_to_max_replans():
    """should_replan must return False once replan_count hits max_replans."""
    res_critic = ResidentCritic(max_replans=2)
    node = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent", replan_count=0)
    obs = _make_obs(verified=False, tier="process", detail="not found")
    verdict = res_critic.evaluate_step(node, "I have launched notepad.", obs)

    # Replan 0 -> 1 allowed
    assert res_critic.should_replan(node, verdict) is True

    node.replan_count = 1
    # Replan 1 -> 2 allowed
    assert res_critic.should_replan(node, verdict) is True

    node.replan_count = 2
    # Replan 2 -> 3 BLOCKED by ceiling
    assert res_critic.should_replan(node, verdict) is False
