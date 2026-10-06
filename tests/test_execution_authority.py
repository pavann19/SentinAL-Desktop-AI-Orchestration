"""Authorization and observation regressions with all desktop effects mocked."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agentic_core.execution_authority import (
    AuthorizationDenied, ExecutionAuthority, action_fingerprint, authorize_action,
    execution_scope, trusted_postconditions,
)
from agentic_core.confirmation import PendingConfirmations
from capabilities.system.api_wrapper import process_command
from capabilities.system.postcondition_observer import Observation


def observation(verified):
    return [{"observation": Observation(verified=verified, tier_used="process", confidence=1,
                                        latency_ms=0, detail="controlled observation")}]


@pytest.mark.asyncio
@pytest.mark.parametrize("autonomous,initial,replacement", [
    (True, {"intent": "ApplicationLaunchIntent", "target": "notepad"},
     {"intent": "FileDeletionIntent", "target": "review-delete.txt"}),
    (False, {"intent": "DictationIntent", "target": "original text"},
     {"intent": "FileDeletionIntent", "target": "review-delete.txt"}),
    (False, {"intent": "FileDeletionIntent", "target": "review-a.txt"},
     {"intent": "FileDeletionIntent", "target": "review-b.txt"}),
    (False, {"intent": "GeneralizedOSIntent", "actions": [{"type": "shell", "payload": "echo original"}]},
     {"intent": "GeneralizedOSIntent", "actions": [{"type": "shell", "payload": "echo changed"}]}),
])
async def test_real_replanner_cannot_reuse_initial_authorization(monkeypatch, autonomous, initial, replacement):
    from agentic_core import executor, processor, planner, confirmation

    steps = [dict(initial, step_id="one"),
             {"intent": "ConversationalIntent", "target": "done", "step_id": "two", "depends_on": ["one"]}]
    monkeypatch.setattr(processor, "extract_intent", lambda *args, **kwargs: [dict(s) for s in steps])
    monkeypatch.setattr(confirmation, "REQUIRE_CONFIRMATION", True)
    monkeypatch.setattr(confirmation, "pending_confirmations", PendingConfirmations())
    llm = Mock()
    llm.invoke.return_value = SimpleNamespace(content=json.dumps([replacement]))
    monkeypatch.setattr(planner.BrainConfig, "get_routed_llm", lambda *args: llm)
    executed = []

    def effects(actions, cancel_event):
        executed.extend(actions)
        return "Execution returned", {}, observation(False)

    monkeypatch.setattr(executor, "_run_and_observe", effects)
    token = None
    if not autonomous:
        pending = await process_command("review workflow", autonomous=False)
        assert pending["execution"] == "PendingConfirmation"
        assert executed == []
        token = pending["confirm_token"]
    result = await process_command("review workflow", autonomous=autonomous, confirm_token=token)
    assert result["execution"] == "Blocked", result
    assert result["replanned"] is True
    assert len(executed) == 1
    assert executed[0]["intent"] == initial["intent"]
    llm.invoke.assert_called_once()


@pytest.mark.parametrize("changes", [
    {"target": "b.txt"}, {"value": "changed"}, {"arguments": ["--force"]},
    {"resource": "other"}, {"resolved_x": 100},
])
def test_confirmation_binds_every_executable_argument(changes):
    store = PendingConfirmations()
    action = {"intent": "FileDeletionIntent", "target": "a.txt"}
    token = store.issue("delete", [action], "T3")
    assert not store.check_and_consume("delete", [dict(action, **changes)], token)
    assert store.check_and_consume("delete", [action], token)


def test_planner_cannot_understate_capability():
    with pytest.raises(AuthorizationDenied):
        authorize_action({"intent": "FileDeletionIntent", "target": "a.txt", "tier": "T0"})


def test_direct_privileged_executor_and_gui_calls_fail_closed(monkeypatch):
    from agentic_core import executor
    remove = Mock()
    click = Mock()
    monkeypatch.setattr(executor.os, "remove", remove)
    monkeypatch.setattr(executor.pyautogui, "click", click)
    assert "ERROR authorization" in executor.execute_pipeline([{"intent": "FileDeletionIntent", "target": "a.txt"}])
    assert "ERROR authorization" in executor.execute_gui_command({"action": "click", "target": "1,2"})
    remove.assert_not_called()
    click.assert_not_called()


def test_retry_rechecks_changed_action(monkeypatch):
    from agentic_core import executor
    action = {"intent": "GeneralizedOSIntent", "actions": [{"type": "shell", "payload": "echo safe"}]}
    authority = ExecutionAuthority(autonomous=False, confirmed_actions=frozenset({action_fingerprint(action)}))
    decisions = []
    def effects(steps, cancel_event):
        try:
            authorize_action(steps[0])
            decisions.append("allowed")
        except AuthorizationDenied:
            decisions.append("denied")
            return "ERROR authorization", {}, []
        steps[0]["actions"][0]["payload"] = "echo changed"
        return "returned", {}, observation(False)
    monkeypatch.setattr(executor, "_run_and_observe", effects)
    with execution_scope(authority):
        result = executor.execute_pipeline_observed([action])
    assert decisions == ["allowed", "denied"]
    assert result["failure_category"] == executor.FAILURE_CATEGORY_PIPELINE_ERROR


def test_unrelated_existing_file_cannot_verify_failed_launch(monkeypatch, tmp_path):
    from agentic_core import executor
    from capabilities.system import postcondition_observer as observer
    unrelated = tmp_path / "already-exists.txt"
    unrelated.write_text("unrelated")
    monkeypatch.setattr(executor, "execute_pipeline", lambda *args, **kwargs: "Launch returned")
    monkeypatch.setattr(observer, "capture_state_snapshot", lambda: {})
    monkeypatch.setattr(observer, "diff_snapshots", lambda *args: {})
    monkeypatch.setattr(observer.process_manager, "list_processes", lambda **kwargs: [])
    action = {"intent": "ApplicationLaunchIntent", "target": "notepad",
              "expected_state": {"path_exists": str(unrelated)}}
    _, _, observations = executor._run_and_observe([action], None)
    assert observations
    assert observations[0]["observation"].verified is False
    assert trusted_postconditions(action)["expected_state"]["process_name"] == "notepad"


def test_unverifiable_action_does_not_adopt_planner_predicate(tmp_path):
    resolved = trusted_postconditions({"intent": "ConversationalIntent", "expected_state": {"path_exists": str(tmp_path)}})
    assert "expected_state" not in resolved
    assert "planner_hint" in resolved


def test_authority_does_not_leak_between_requests():
    action = {"intent": "FileDeletionIntent", "target": "a.txt"}
    with execution_scope(ExecutionAuthority(autonomous=False, confirmed_actions=frozenset({action_fingerprint(action)}))):
        assert authorize_action(action)["target"].endswith("a.txt")
    with pytest.raises(AuthorizationDenied):
        authorize_action(action)


@pytest.mark.parametrize("target", ["python", "cmd.exe", "powershell.exe", "payload.bat", r"C:\untrusted\notepad.exe"])
def test_arbitrary_launch_target_cannot_inherit_t1(target):
    with pytest.raises(AuthorizationDenied):
        authorize_action({"intent": "ApplicationLaunchIntent", "target": target, "tier": "T1"})


@pytest.mark.asyncio
async def test_repeated_real_replanning_still_denies_escalation(monkeypatch):
    from agentic_core import executor, processor, planner
    from agentic_core.critic import critic
    monkeypatch.setattr(critic, "max_replans", 3)
    monkeypatch.setattr(processor, "extract_intent", lambda *args, **kwargs: [
        {"intent": "ApplicationLaunchIntent", "target": "notepad", "step_id": "one"},
        {"intent": "ConversationalIntent", "step_id": "two", "depends_on": ["one"]},
    ])
    llm = Mock()
    llm.invoke.side_effect = [
        SimpleNamespace(content=json.dumps([{"intent": "ApplicationLaunchIntent", "target": "calc"}])),
        SimpleNamespace(content=json.dumps([{"intent": "FileDeletionIntent", "target": "review.txt"}])),
    ]
    monkeypatch.setattr(planner.BrainConfig, "get_routed_llm", lambda *args: llm)
    effects = Mock(return_value=("returned", {}, observation(False)))
    monkeypatch.setattr(executor, "_run_and_observe", effects)
    result = await process_command("review repeated replans", autonomous=True)
    assert result["execution"] == "Blocked"
    assert effects.call_count == 2
    assert [call.args[0][0]["intent"] for call in effects.call_args_list] == ["ApplicationLaunchIntent"] * 2
    assert llm.invoke.call_count == 2


@pytest.mark.asyncio
async def test_streaming_real_pipeline_blocks_replan_escalation(monkeypatch):
    import asyncio
    import main
    from agentic_core import executor, processor, planner
    from interfaces.voice import tts_service
    from unittest.mock import AsyncMock
    monkeypatch.setattr(processor, "extract_intent", lambda *args, **kwargs: [
        {"intent": "ApplicationLaunchIntent", "target": "notepad", "step_id": "one"},
        {"intent": "ConversationalIntent", "step_id": "two", "depends_on": ["one"]},
    ])
    llm = Mock()
    llm.invoke.return_value = SimpleNamespace(content=json.dumps([{"intent": "FileDeletionIntent", "target": "review.txt"}]))
    monkeypatch.setattr(planner.BrainConfig, "get_routed_llm", lambda *args: llm)
    effects = Mock(return_value=("returned", {}, observation(False)))
    monkeypatch.setattr(executor, "_run_and_observe", effects)
    send = AsyncMock()
    monkeypatch.setattr(main, "safe_send_json", send)
    monkeypatch.setattr(tts_service, "speak", Mock())
    await main.execute_agent_task("review stream", object(), asyncio.Event())
    assert effects.call_count == 1
    assert any(call.args[1].get("type") == "error" for call in send.call_args_list)


def test_confirm_token_is_consumed_once_under_concurrency():
    from concurrent.futures import ThreadPoolExecutor
    store = PendingConfirmations()
    steps = [{"intent": "FileDeletionIntent", "target": "a.txt"}]
    token = store.issue("delete", steps, "T3")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.check_and_consume("delete", steps, token), range(32)))
    assert sum(results) == 1


def test_utility_resolution_cannot_turn_light_mode_into_recycle_bin(monkeypatch):
    from capabilities.system import sys_utility
    run = Mock()
    monkeypatch.setattr(sys_utility.subprocess, "run", run)
    assert sys_utility.resolve_system_action("switch to light mode") == "light_mode"
    assert sys_utility.resolve_system_action("light mode and empty recycle bin") == "unknown"
    assert sys_utility.handle_sys_utility("light mode and empty recycle bin").startswith("ERROR")
    run.assert_not_called()


def test_observer_failure_is_unverified_without_repeating_action(monkeypatch):
    from agentic_core import executor
    from capabilities.system import postcondition_observer as observer
    effects = Mock(return_value="Launch returned")
    monkeypatch.setattr(executor, "execute_pipeline", effects)
    monkeypatch.setattr(observer, "capture_state_snapshot", lambda: {})
    monkeypatch.setattr(observer, "diff_snapshots", lambda *args: {})
    monkeypatch.setattr(observer, "observe_postcondition", Mock(side_effect=RuntimeError("observer unavailable")))
    result = executor.execute_pipeline_observed([{"intent": "ApplicationLaunchIntent", "target": "notepad"}])
    assert result["failure_category"] == "observation_unavailable"
    assert result["replanned"] is False
    effects.assert_called_once()
