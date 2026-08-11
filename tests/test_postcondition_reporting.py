"""
tests/test_postcondition_reporting.py

Regression tests for the observer's verdict reaching the user.

Found by benchmarks/run_benchmark.py on its first full run. The task
"i need to do some math, open the calculator" reported:

    execution = "Success"
    response  = "I have launched calculator."
    replanned = True
    failure_category = "postcondition_mismatch"

No calculator was running. The observer had done its job perfectly — it
checked real system state, saw nothing, and even burned a bounded replan
trying again. That verdict was then written to output["failure_category"] as
metadata and otherwise ignored, because execution/response were derived purely
from whether execute_pipeline() returned an ERROR string.

So the entire S1 postcondition effort could detect a silent failure and the
system would still tell the user it worked. These tests lock in that the
observer's verdict wins over the executor's optimism.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from agentic_core.executor import (
    FAILURE_CATEGORY_POSTCONDITION_MISMATCH,
    FAILURE_CATEGORY_SUCCESS,
)
from capabilities.system.api_wrapper import process_command

_STEP = [{"intent": "ApplicationLaunchIntent", "target": "calculator"}]


def _observed(category, result="I have launched calculator."):
    return {
        "result": result,
        "snapshot_diff": {},
        "step_observations": [],
        "failure_category": category,
        "attempts": 2 if category == FAILURE_CATEGORY_POSTCONDITION_MISMATCH else 1,
        "replanned": category == FAILURE_CATEGORY_POSTCONDITION_MISMATCH,
    }


async def _run(category, result="I have launched calculator."):
    with patch("agentic_core.processor.extract_intent", return_value=list(_STEP)), \
         patch("agentic_core.validator.validate_steps", return_value=(True, "Approved", False)), \
         patch("agentic_core.executor.execute_pipeline_observed", return_value=_observed(category, result)):
        return await process_command("i need to do some math, open the calculator")


class TestPostconditionMismatchIsReportedAsFailure:
    @pytest.mark.asyncio
    async def test_execution_is_failed_not_success(self):
        out = await _run(FAILURE_CATEGORY_POSTCONDITION_MISMATCH)
        assert out["execution"] == "Failed", (
            "The observer verified real system state and found the effect absent. "
            "Reporting Success anyway is the fabricated-success defect."
        )

    @pytest.mark.asyncio
    async def test_user_response_does_not_claim_the_action_happened(self):
        out = await _run(FAILURE_CATEGORY_POSTCONDITION_MISMATCH)
        assert "I have launched calculator." not in out["response"]

    @pytest.mark.asyncio
    async def test_response_tells_the_user_it_could_not_be_confirmed(self):
        out = await _run(FAILURE_CATEGORY_POSTCONDITION_MISMATCH)
        lowered = out["response"].lower()
        assert "couldn't confirm" in lowered or "could not confirm" in lowered

    @pytest.mark.asyncio
    async def test_unverified_claim_is_preserved_for_debugging(self):
        """The executor's original string is kept — it is useful for diagnosing
        WHY the check failed — but it is moved out of the user-facing field so
        it can never be read as a confirmation."""
        out = await _run(FAILURE_CATEGORY_POSTCONDITION_MISMATCH)
        assert out["unverified_claim"] == "I have launched calculator."

    @pytest.mark.asyncio
    async def test_failure_category_still_reported(self):
        out = await _run(FAILURE_CATEGORY_POSTCONDITION_MISMATCH)
        assert out["failure_category"] == FAILURE_CATEGORY_POSTCONDITION_MISMATCH
        assert out["replanned"] is True


class TestVerifiedSuccessIsUnaffected:
    """The fix must not make successful runs look like failures — that would
    trade one dishonest report for another."""

    @pytest.mark.asyncio
    async def test_success_still_reports_success(self):
        out = await _run(FAILURE_CATEGORY_SUCCESS)
        assert out["execution"] == "Success"
        assert out["response"] == "I have launched calculator."

    @pytest.mark.asyncio
    async def test_success_has_no_unverified_claim(self):
        out = await _run(FAILURE_CATEGORY_SUCCESS)
        assert "unverified_claim" not in out

    @pytest.mark.asyncio
    async def test_explicit_error_still_takes_precedence(self):
        """An ERROR result is execute_pipeline's own authoritative signal and
        must keep its specific message rather than being replaced by the
        generic postcondition wording."""
        out = await _run(FAILURE_CATEGORY_POSTCONDITION_MISMATCH, result="ERROR Step 1: boom")
        assert out["execution"] == "Failed"
        assert out["response"] == "ERROR Step 1: boom"
