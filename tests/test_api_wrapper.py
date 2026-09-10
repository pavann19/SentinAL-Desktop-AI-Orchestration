"""
tests/test_api_wrapper.py
Async integration tests for capabilities/system/api_wrapper.py.
Tests the full extract→validate→execute pipeline with mocked sub-layers.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch


class TestApiWrapperGreeting:

    @pytest.mark.asyncio
    async def test_greeting_returns_conversational(self):
        """'hello' hits greeting bypass → ConversationalIntent → returns message."""
        from capabilities.system.api_wrapper import process_command
        result = await process_command("hello")
        assert result["input"] == "hello"
        assert result["validation"] == "Approved"
        assert result["execution"] == "Success"
        assert isinstance(result["response"], str)
        assert len(result["response"]) > 0

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_unknown(self):
        """Empty prompt → UnknownIntent → Error response."""
        from capabilities.system.api_wrapper import process_command
        result = await process_command("  ")
        assert result["validation"] == "Error"
        assert result["execution"] == "Error"

    @pytest.mark.asyncio
    async def test_time_query_returns_success(self):
        """Fast-path time query must complete successfully."""
        from capabilities.system.api_wrapper import process_command
        result = await process_command("what time is it")
        assert result["validation"] == "Approved"
        assert "time" in result["response"].lower() or ":" in result["response"]

    @pytest.mark.asyncio
    async def test_output_always_has_required_keys(self):
        """Every response must have: input, steps, validation, execution, response."""
        from capabilities.system.api_wrapper import process_command
        result = await process_command("hello")
        for key in ("input", "steps", "validation", "execution", "response"):
            assert key in result, f"Missing key: '{key}'"

    @pytest.mark.asyncio
    async def test_blocked_system32_command_denied(self):
        """A command targeting system32 must be blocked by validation."""
        from capabilities.system.api_wrapper import process_command
        with patch("agentic_core.processor.extract_intent") as mock_extract:
            mock_extract.return_value = [{
                "intent": "ApplicationLaunchIntent",
                "target": "C:\\windows\\system32\\cmd.exe"
            }]
            result = await process_command("open system32")
        assert result["validation"] == "Denied"
        assert result["execution"] == "Blocked"

    @pytest.mark.asyncio
    async def test_pipeline_error_returns_error_response(self):
        """If extract_intent raises, the wrapper must return a clean error dict."""
        from capabilities.system.api_wrapper import process_command
        with patch("agentic_core.processor.extract_intent", side_effect=RuntimeError("LLM crashed")):
            result = await process_command("do something complex")
        assert result["validation"] == "Error"
        assert result["execution"] == "Error"
        assert "Pipeline Integration Error" in result["response"]

    @pytest.mark.asyncio
    async def test_steps_field_is_list(self):
        """'steps' field must always be a list."""
        from capabilities.system.api_wrapper import process_command
        result = await process_command("good morning")
        assert isinstance(result["steps"], list)


class TestCapabilityBrokerWiring:
    """S4: the broker surfaces a risk tier + confirmation flag on every response,
    without newly blocking any direct-human request (autonomous=False)."""

    @pytest.mark.asyncio
    async def test_conversational_request_is_t0_no_confirmation(self):
        from capabilities.system.api_wrapper import process_command
        result = await process_command("hello")
        assert result["capability_tier"] == "T0"
        assert result["requires_confirmation"] is False

    @pytest.mark.asyncio
    async def test_file_deletion_is_t3_and_flags_confirmation_but_is_not_blocked(self):
        """FileDeletionIntent is T3 — it must be flagged for confirmation, but a
        direct human command still reaches validation/execution (not blocked by
        the broker itself). This is the behaviour that would break if the broker
        hard-blocked T3 without a confirmation channel. extract_intent and the
        executor are mocked so this stays hermetic and fast."""
        from capabilities.system.api_wrapper import process_command
        step = {"intent": "FileDeletionIntent", "target": "bench_broker_nonexistent_xyz.txt"}
        with patch("agentic_core.processor.extract_intent", return_value=[step]), \
             patch(
                 "agentic_core.executor.execute_pipeline_observed",
                 return_value={
                     "result": "Deleted.", "snapshot_diff": {}, "step_observations": [],
                     "failure_category": "success", "attempts": 1, "replanned": False,
                 },
             ):
            result = await process_command("delete bench_broker_nonexistent_xyz.txt")
        assert result["capability_tier"] == "T3"
        assert result["requires_confirmation"] is True
        # Not blocked by the broker: validation still ran and approved it.
        assert result["validation"] == "Approved"

    @pytest.mark.asyncio
    async def test_capability_fields_present_even_on_denied_request(self):
        """The broker runs before validate_steps(), so its fields are on the
        output even when validation later denies the request."""
        from capabilities.system.api_wrapper import process_command
        result = await process_command("open system32")
        assert result["validation"] == "Denied"
        assert "capability_tier" in result
        assert "requires_confirmation" in result


class TestAutonomousMode:
    """S6 increment 2: process_command(prompt, autonomous=True) — the broker's
    tier decision is ENFORCED (no human -> can't confirm -> T2/T3 denied),
    the tighter autonomous budget applies, and validate_steps() still runs
    first and unconditionally."""

    @pytest.mark.asyncio
    async def test_autonomous_t3_plan_is_blocked_and_nothing_runs(self):
        from capabilities.system.api_wrapper import process_command
        step = {"intent": "FileDeletionIntent", "target": "some_file.txt"}
        with patch("agentic_core.processor.extract_intent", return_value=[step]), \
             patch("agentic_core.executor.execute_pipeline_observed") as mock_exec:
            result = await process_command("delete some_file.txt", autonomous=True)
        assert result["execution"] == "Blocked"
        assert result["validation"] == "Denied"
        assert "containment policy" in result["response"].lower()
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_direct_human_t3_is_NOT_blocked_by_the_broker(self):
        """Same T3 step, autonomous=False -> flagged, not blocked (regression:
        the confirm flag path must be unchanged)."""
        from capabilities.system.api_wrapper import process_command
        step = {"intent": "FileDeletionIntent", "target": "some_file.txt"}
        with patch("agentic_core.processor.extract_intent", return_value=[step]), \
             patch(
                 "agentic_core.executor.execute_pipeline_observed",
                 return_value={"result": "Deleted.", "snapshot_diff": {}, "step_observations": [],
                              "failure_category": "success", "attempts": 1, "replanned": False},
             ):
            result = await process_command("delete some_file.txt", autonomous=False)
        assert result["validation"] == "Approved"
        assert result["requires_confirmation"] is True
        assert result["capability_tier"] == "T3"

    @pytest.mark.asyncio
    async def test_autonomous_t0_plan_runs(self):
        from capabilities.system.api_wrapper import process_command
        step = {"intent": "ConversationalIntent", "message": "hi", "speech_response": "hi"}
        with patch("agentic_core.processor.extract_intent", return_value=[step]), \
             patch(
                 "agentic_core.executor.execute_pipeline_observed",
                 return_value={"result": "hi", "snapshot_diff": {}, "step_observations": [],
                              "failure_category": "success", "attempts": 1, "replanned": False},
             ):
            result = await process_command("say hi", autonomous=True)
        assert result["execution"] == "Success"
        assert result["autonomous"] is True

    @pytest.mark.asyncio
    async def test_autonomous_still_hits_the_validator_first(self):
        """A goal that would touch system32 is blocked at validate_steps(),
        not only at the broker — the security gate is unconditional."""
        from capabilities.system.api_wrapper import process_command
        step = {"intent": "ApplicationLaunchIntent", "target": r"C:\Windows\System32\cmd.exe"}
        with patch("agentic_core.processor.extract_intent", return_value=[step]), \
             patch("agentic_core.executor.execute_pipeline_observed") as mock_exec:
            result = await process_command("launch cmd from system32", autonomous=True)
        assert result["execution"] in ("Blocked",)
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_autonomous_multistep_uses_the_tighter_budget(self):
        from capabilities.system.api_wrapper import process_command
        from agentic_core.budget import budget_for
        auto_actions = budget_for(autonomous=True).max_actions
        graph_steps = [
            {"intent": "ConversationalIntent", "message": "a", "step_id": "s1"},
            {"intent": "ConversationalIntent", "message": "b", "step_id": "s2", "depends_on": ["s1"]},
        ]
        def fake_rao(steps, cancel_event):
            from capabilities.system.postcondition_observer import Observation
            return "ok", {}, [Observation(verified=True, tier_used="none", confidence=1.0,
                                          latency_ms=1.0, detail="x")]
        with patch("agentic_core.processor.extract_intent", return_value=graph_steps), \
             patch("agentic_core.executor._run_and_observe", side_effect=fake_rao):
            result = await process_command("do a then b", autonomous=True)
        assert result["budget"]["autonomous"] is True
        assert result["budget"]["max_actions"] == auto_actions


class TestDirectHumanConfirmChannel:
    """P2-5: SENTINAL_REQUIRE_CONFIRMATION on -> a T2/T3 direct-human request
    returns PendingConfirmation with a one-time token; resend with the token
    to proceed. Off (default) -> unchanged."""

    _T3_STEP = {"intent": "FileDeletionIntent", "target": "confirm_test_file.txt"}
    _EXEC_OK = {"result": "Deleted.", "snapshot_diff": {}, "step_observations": [],
                "failure_category": "success", "attempts": 1, "replanned": False}

    @pytest.mark.asyncio
    async def test_disabled_by_default_t3_runs_without_a_token(self):
        from capabilities.system.api_wrapper import process_command
        with patch("agentic_core.processor.extract_intent", return_value=[self._T3_STEP]), \
             patch("agentic_core.executor.execute_pipeline_observed", return_value=self._EXEC_OK):
            result = await process_command("delete confirm_test_file.txt")
        assert result["execution"] == "Success"
        assert "confirm_token" not in result

    @pytest.mark.asyncio
    async def test_enabled_t3_returns_pending_confirmation_and_does_not_run(self):
        from capabilities.system.api_wrapper import process_command
        with patch("agentic_core.confirmation.REQUIRE_CONFIRMATION", True), \
             patch("agentic_core.processor.extract_intent", return_value=[self._T3_STEP]), \
             patch("agentic_core.executor.execute_pipeline_observed") as mock_exec:
            result = await process_command("delete confirm_test_file.txt")
        assert result["execution"] == "PendingConfirmation"
        assert result["confirm_token"]
        assert "FileDeletionIntent" in result["response"]
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_resend_with_the_token_runs(self):
        from capabilities.system.api_wrapper import process_command
        with patch("agentic_core.confirmation.REQUIRE_CONFIRMATION", True), \
             patch("agentic_core.processor.extract_intent", return_value=[self._T3_STEP]), \
             patch("agentic_core.executor.execute_pipeline_observed", return_value=self._EXEC_OK):
            first = await process_command("delete confirm_test_file.txt")
            second = await process_command("delete confirm_test_file.txt",
                                           confirm_token=first["confirm_token"])
        assert second["execution"] == "Success"
        assert second.get("confirmation") == "provided"

    @pytest.mark.asyncio
    async def test_enabled_a_token_from_a_different_request_is_rejected(self):
        from capabilities.system.api_wrapper import process_command
        step_a = {"intent": "FileDeletionIntent", "target": "file_a.txt"}
        step_b = {"intent": "FileDeletionIntent", "target": "file_b.txt"}
        with patch("agentic_core.confirmation.REQUIRE_CONFIRMATION", True), \
             patch("agentic_core.executor.execute_pipeline_observed") as mock_exec:
            with patch("agentic_core.processor.extract_intent", return_value=[step_a]):
                a = await process_command("delete file_a.txt")
            # try to use A's token to confirm a DELETE of file_b
            with patch("agentic_core.processor.extract_intent", return_value=[step_b]):
                b = await process_command("delete file_b.txt", confirm_token=a["confirm_token"])
        assert b["execution"] == "PendingConfirmation"   # re-challenged, not run
        mock_exec.assert_not_called()

    @pytest.mark.asyncio
    async def test_enabled_t0_request_never_needs_confirmation(self):
        from capabilities.system.api_wrapper import process_command
        step = {"intent": "ConversationalIntent", "message": "hi", "speech_response": "hi"}
        with patch("agentic_core.confirmation.REQUIRE_CONFIRMATION", True), \
             patch("agentic_core.processor.extract_intent", return_value=[step]), \
             patch("agentic_core.executor.execute_pipeline_observed",
                   return_value={**self._EXEC_OK, "result": "hi"}):
            result = await process_command("say hi")
        assert result["execution"] == "Success"
        assert "confirm_token" not in result

    @pytest.mark.asyncio
    async def test_enabled_autonomous_t3_still_blocked_not_pending(self):
        """The autonomous path returns Blocked upstream and never reaches the
        confirm gate — a confirm token must not be a way to run a T3 goal
        autonomously."""
        from capabilities.system.api_wrapper import process_command
        with patch("agentic_core.confirmation.REQUIRE_CONFIRMATION", True), \
             patch("agentic_core.processor.extract_intent", return_value=[self._T3_STEP]), \
             patch("agentic_core.executor.execute_pipeline_observed") as mock_exec:
            result = await process_command("delete confirm_test_file.txt", autonomous=True)
        assert result["execution"] == "Blocked"
        mock_exec.assert_not_called()


class TestProceduralOutcomeRecording:
    """_record_procedural_outcome(): a successful multi-step run reinforces its
    structure; a failed run that was itself a recipe replay retires it."""

    def _graph(self, plan_source=None):
        from agentic_core.goal_graph import GoalGraph, GoalNode
        g = GoalGraph(goal_description="g")
        n1 = GoalNode(step_id="step_1", intent="ApplicationLaunchIntent", target="notepad")
        if plan_source:
            n1.extra["_plan_source"] = plan_source
            n1.extra["_recipe_fp"] = "deadbeef"
        g.add_node(n1)
        g.add_node(GoalNode(step_id="step_2", intent="GeneralizedOSIntent",
                            target="type hi", depends_on=["step_1"]))
        return g

    def test_success_records_and_failed_replay_retires(self):
        from capabilities.system.api_wrapper import _record_procedural_outcome
        with patch("agentic_core.procedural_memory.record_success") as rs, \
             patch("agentic_core.procedural_memory.record_failure") as rf:
            _record_procedural_outcome("open notepad and type hi", self._graph(),
                                       {"execution": "Success"})
            rs.assert_called_once()
            rf.assert_not_called()

        with patch("agentic_core.procedural_memory.record_success") as rs, \
             patch("agentic_core.procedural_memory.record_failure") as rf:
            _record_procedural_outcome("open notepad and type hi",
                                       self._graph(plan_source="procedural"),
                                       {"execution": "Failed", "plan_source": "procedural"})
            rs.assert_not_called()
            rf.assert_called_once_with("deadbeef")

    def test_failed_planner_sourced_run_records_nothing(self):
        from capabilities.system.api_wrapper import _record_procedural_outcome
        with patch("agentic_core.procedural_memory.record_success") as rs, \
             patch("agentic_core.procedural_memory.record_failure") as rf:
            _record_procedural_outcome("x", self._graph(),
                                       {"execution": "Failed", "plan_source": "planner"})
            rs.assert_not_called()
            rf.assert_not_called()

    def test_plan_source_of_reads_provenance(self):
        from capabilities.system.api_wrapper import _plan_source_of
        assert _plan_source_of(self._graph(plan_source="procedural")) == "procedural"
        assert _plan_source_of(self._graph()) == "planner"


class TestCapabilityOutcomeRecording:
    """_record_capability_outcomes() forwards a completed run to the world
    model's drift tracker; disabled/non-terminal runs write nothing."""

    def test_terminal_run_is_forwarded(self):
        from capabilities.system.api_wrapper import _record_capability_outcomes
        seen = {}
        with patch("agentic_core.world_model.record_run",
                   side_effect=lambda out, **kw: seen.update(out=out, kw=kw)):
            _record_capability_outcomes(
                {"execution": "Success", "steps": [{"intent": "SchedulerIntent"}]}, t0=None)
        assert seen["out"]["execution"] == "Success"
        assert "latency_ms" in seen["kw"]

    def test_record_helper_never_raises(self):
        from capabilities.system.api_wrapper import _record_capability_outcomes
        with patch("agentic_core.world_model.record_run", side_effect=RuntimeError("boom")):
            _record_capability_outcomes({"execution": "Failed", "steps": []}, t0=None)
