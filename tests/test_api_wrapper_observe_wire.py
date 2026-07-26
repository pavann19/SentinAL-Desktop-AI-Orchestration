"""
Independent verification tests for the observe-wire fix in
capabilities/system/api_wrapper.py.

FINDING: agentic_core/executor.py::execute_pipeline_observed() (built and
unit-tested in a prior session, P1-1/P1-2/P1-4) was NEVER actually invoked by
the live system — process_command() called raw execute_pipeline() directly,
meaning the whole observe-act-replan mechanism was dead code from the live
pipeline's perspective despite being tested and merged. This fix wires it in.

This is the highest-blast-radius change of the session (api_wrapper.py is the
literal entry point for every pipeline-integration test and the real HTTP
API), so it gets thorough, careful coverage: backward compatibility for every
existing behavior, the new expected_state derivation logic in isolation, and
the new additive output fields.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from capabilities.system.api_wrapper import _derive_expected_state, process_command


# ── _derive_expected_state() — pure function, no mocking needed ────────────

def test_derive_expected_state_bare_app_name():
    step = {"intent": "ApplicationLaunchIntent", "target": "notepad"}
    assert _derive_expected_state(step) == {"process_name": "notepad"}


def test_derive_expected_state_full_windows_path():
    step = {"intent": "ApplicationLaunchIntent", "target": "C:\\Program Files\\App\\app.exe"}
    assert _derive_expected_state(step) == {"process_name": "app.exe"}


def test_derive_expected_state_forward_slash_path():
    step = {"intent": "ApplicationLaunchIntent", "target": "C:/apps/thing.exe"}
    assert _derive_expected_state(step) == {"process_name": "thing.exe"}


def test_derive_expected_state_non_launch_intent_returns_none():
    step = {"intent": "WebNavigationIntent", "target": "youtube.com"}
    assert _derive_expected_state(step) is None


def test_derive_expected_state_missing_target_returns_none():
    step = {"intent": "ApplicationLaunchIntent"}
    assert _derive_expected_state(step) is None


def test_derive_expected_state_empty_target_returns_none():
    step = {"intent": "ApplicationLaunchIntent", "target": ""}
    assert _derive_expected_state(step) is None


def test_derive_expected_state_non_dict_step_returns_none():
    assert _derive_expected_state("not a dict") is None
    assert _derive_expected_state(None) is None


# ── process_command() backward compatibility ────────────────────────────────
# These mirror the EXACT assertions in the pre-existing tests/test_api_wrapper.py
# to prove nothing about the public contract changed, just written against the
# new internals so a break here is caught independently.

@pytest.mark.asyncio
async def test_greeting_still_returns_conversational_success():
    result = await process_command("hello")
    assert result["input"] == "hello"
    assert result["validation"] == "Approved"
    assert result["execution"] == "Success"
    assert isinstance(result["response"], str) and len(result["response"]) > 0


@pytest.mark.asyncio
async def test_empty_prompt_still_returns_error():
    result = await process_command("  ")
    assert result["validation"] == "Error"
    assert result["execution"] == "Error"


@pytest.mark.asyncio
async def test_output_still_has_all_original_required_keys():
    result = await process_command("hello")
    for key in ("input", "steps", "validation", "execution", "response"):
        assert key in result


@pytest.mark.asyncio
async def test_blocked_system32_still_denied():
    with patch("agentic_core.processor.extract_intent") as mock_extract:
        mock_extract.return_value = [{
            "intent": "ApplicationLaunchIntent",
            "target": "C:\\windows\\system32\\cmd.exe",
        }]
        result = await process_command("open system32")
    assert result["validation"] == "Denied"
    assert result["execution"] == "Blocked"


@pytest.mark.asyncio
async def test_pipeline_error_still_returns_clean_error_dict():
    with patch("agentic_core.processor.extract_intent", side_effect=RuntimeError("LLM crashed")):
        result = await process_command("do something complex")
    assert result["validation"] == "Error"
    assert result["execution"] == "Error"
    assert "Pipeline Integration Error" in result["response"]


# ── New behavior: additive output fields + real execute_pipeline_observed call ──

@pytest.mark.asyncio
async def test_new_additive_fields_present_on_success():
    """The new failure_category/replanned/attempts fields must be present
    without disturbing the original fields."""
    result = await process_command("hello")
    assert result["failure_category"] == "success"
    assert result["replanned"] is False
    assert result["attempts"] == 1


@pytest.mark.asyncio
async def test_execute_pipeline_observed_is_actually_called_not_raw_execute_pipeline():
    """The core assertion of this fix: process_command must call
    execute_pipeline_observed, not execute_pipeline directly."""
    with patch("agentic_core.executor.execute_pipeline_observed") as mock_observed:
        mock_observed.return_value = {
            "result": "I have launched notepad.",
            "snapshot_diff": {},
            "step_observations": [],
            "failure_category": "success",
            "attempts": 1,
            "replanned": False,
        }
        with patch("agentic_core.processor.extract_intent") as mock_extract:
            mock_extract.return_value = [{"intent": "ApplicationLaunchIntent", "target": "notepad"}]
            result = await process_command("open notepad")

    mock_observed.assert_called_once()
    called_steps = mock_observed.call_args[0][0]
    assert called_steps[0]["expected_state"] == {"process_name": "notepad"}
    assert result["response"] == "I have launched notepad."
    assert result["execution"] == "Success"


@pytest.mark.asyncio
async def test_step_with_preexisting_expected_state_is_not_overwritten():
    with patch("agentic_core.executor.execute_pipeline_observed") as mock_observed:
        mock_observed.return_value = {
            "result": "ok", "snapshot_diff": {}, "step_observations": [],
            "failure_category": "success", "attempts": 1, "replanned": False,
        }
        with patch("agentic_core.processor.extract_intent") as mock_extract:
            mock_extract.return_value = [{
                "intent": "ApplicationLaunchIntent",
                "target": "notepad",
                "expected_state": {"process_name": "already_set.exe"},
            }]
            await process_command("open notepad")

    called_steps = mock_observed.call_args[0][0]
    assert called_steps[0]["expected_state"] == {"process_name": "already_set.exe"}


@pytest.mark.asyncio
async def test_replan_result_surfaces_correctly_in_output():
    """If execute_pipeline_observed reports a replan happened, that must be
    visible in the final output dict."""
    with patch("agentic_core.executor.execute_pipeline_observed") as mock_observed:
        mock_observed.return_value = {
            "result": "I have launched notepad.",
            "snapshot_diff": {}, "step_observations": [],
            "failure_category": "success", "attempts": 2, "replanned": True,
        }
        with patch("agentic_core.processor.extract_intent") as mock_extract:
            mock_extract.return_value = [{"intent": "ApplicationLaunchIntent", "target": "notepad"}]
            result = await process_command("open notepad")

    assert result["replanned"] is True
    assert result["attempts"] == 2
