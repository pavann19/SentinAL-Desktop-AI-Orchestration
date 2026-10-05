"""The streaming transport must preserve the canonical pipeline's safety result."""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def muted_speech(monkeypatch):
    import interfaces.voice.tts_service as tts
    speak = Mock()
    monkeypatch.setattr(tts, "speak", speak)
    return speak


@pytest.mark.asyncio
@pytest.mark.parametrize("execution,frame", [("Success", "final_response"), ("Failed", "error"), ("Blocked", "error")])
async def test_stream_preserves_pipeline_verdict(monkeypatch, execution, frame, muted_speech):
    import main
    import capabilities.system.api_wrapper as api
    process = AsyncMock(return_value={"execution": execution, "response": "observed result"})
    send = AsyncMock()
    monkeypatch.setattr(api, "process_command", process)
    monkeypatch.setattr(main, "safe_send_json", send)
    cancelled = asyncio.Event()
    await main.execute_agent_task("hello", object(), cancelled, confirm_token="bound-token")
    process.assert_awaited_once_with("hello", confirm_token="bound-token", cancel_event=cancelled)
    verdict = [call.args[1] for call in send.call_args_list if call.args[1]["type"] == frame][-1]
    assert verdict["execution"] == execution
    if execution == "Success":
        muted_speech.assert_called_once_with("observed result", 1.0, cancelled, "HQ")
    else:
        muted_speech.assert_not_called()


@pytest.mark.asyncio
async def test_pending_confirmation_is_not_reported_as_success(monkeypatch):
    import main
    import capabilities.system.api_wrapper as api
    process = AsyncMock(return_value={"execution": "PendingConfirmation", "confirm_token": "bound-token", "response": "Review action"})
    send = AsyncMock()
    monkeypatch.setattr(api, "process_command", process)
    monkeypatch.setattr(main, "safe_send_json", send)
    await main.execute_agent_task("delete a file", object(), asyncio.Event())
    result = send.call_args.args[1]
    assert result["type"] == "confirmation_required"
    assert result["prompt"] == "delete a file"
    assert result["confirm_token"] == "bound-token"


@pytest.mark.asyncio
async def test_cancelled_command_does_not_enter_pipeline(monkeypatch):
    import main
    import capabilities.system.api_wrapper as api
    process = AsyncMock()
    monkeypatch.setattr(api, "process_command", process)
    cancelled = asyncio.Event()
    cancelled.set()
    await main.execute_agent_task("hello", object(), cancelled)
    process.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["format the C drive", "format the D drive", "format C:"])
async def test_disk_request_is_denied_even_when_extractor_returns_a_benign_target(monkeypatch, prompt):
    import agentic_core.processor as processor
    import agentic_core.executor as executor
    from capabilities.system.api_wrapper import process_command
    from unittest.mock import Mock
    monkeypatch.setattr(processor, "extract_intent", lambda *args, **kwargs: [
        {"intent": "FileDeletionIntent", "target": "unrelated.txt", "prompt": "benign model-generated text"}
    ])
    execute = Mock()
    monkeypatch.setattr(executor, "execute_pipeline_observed", execute)
    result = await process_command(prompt)
    assert result["validation"] == "Denied"
    assert result["execution"] == "Blocked"
    assert "confirm_token" not in result
    execute.assert_not_called()


def test_document_formatting_is_not_mistaken_for_disk_formatting():
    from agentic_core.validator import validate_steps
    assert validate_steps([{"intent": "GeneralizedOSIntent", "prompt": "format a report", "actions": []}])[0]
