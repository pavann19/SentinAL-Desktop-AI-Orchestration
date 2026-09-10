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
