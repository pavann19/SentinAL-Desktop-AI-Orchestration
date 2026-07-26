"""
tests/test_api_wrapper.py
Async integration tests for capabilities/system/api_wrapper.py.
Tests the full extract→validate→execute pipeline with mocked sub-layers.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock


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
