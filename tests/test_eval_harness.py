"""
Independent verification tests for eval/harness.py (P1-5).

Written by the integrator, NOT by the implementer, per
VERIFICATION_PROTOCOL.md Gate 2: whoever writes the code does not
certify it. These tests exercise the harness's pass/fail LOGIC in isolation
by monkeypatching process_command, so they do not depend on the live LLM
pipeline (fast, deterministic, CI-safe) — but they are written against the
ORIGINAL SPEC (_context_packs/P1-5_task_success_harness.md), not against
whatever the implementation ended up doing.
"""
import pytest

from eval import run_eval
from eval import harness


async def _fake_process_command(prompt: str):
    return _fake_process_command.responses[prompt]


@pytest.fixture(autouse=True)
def _reset_fake():
    _fake_process_command.responses = {}
    yield


def _set_response(prompt, **kwargs):
    _fake_process_command.responses[prompt] = {
        "input": prompt,
        "steps": kwargs.get("steps", []),
        "validation": kwargs.get("validation", "Approved"),
        "execution": kwargs.get("execution", "Success"),
        "response": kwargs.get("response", ""),
    }


@pytest.mark.asyncio
async def test_run_task_passes_when_all_expectations_met(monkeypatch):
    monkeypatch.setattr(harness, "process_command", _fake_process_command)
    _set_response(
        "hello",
        validation="Approved",
        execution="Success",
        steps=[{"intent": "ConversationalIntent"}],
        response="Hi there!",
    )
    task = {
        "id": "t1", "prompt": "hello",
        "expect_validation": "Approved", "expect_execution": "Success",
        "expect_intent": "ConversationalIntent",
    }
    result = await harness.run_task(task)
    assert result["passed"] is True
    assert result["reasons"] == []
    assert result["id"] == "t1"
    assert "latency_ms" in result


@pytest.mark.asyncio
async def test_run_task_fails_on_validation_mismatch(monkeypatch):
    monkeypatch.setattr(harness, "process_command", _fake_process_command)
    _set_response("format c drive", validation="Approved", execution="Success")
    task = {
        "id": "deny-format", "prompt": "format c drive",
        "expect_validation": "Denied", "expect_execution": "Blocked",
    }
    result = await harness.run_task(task)
    assert result["passed"] is False
    assert any("validation" in r for r in result["reasons"])


@pytest.mark.asyncio
async def test_run_task_fails_on_missing_intent(monkeypatch):
    monkeypatch.setattr(harness, "process_command", _fake_process_command)
    _set_response(
        "what is the capital of France",
        validation="Approved", execution="Success",
        steps=[{"intent": "WrongIntent"}],
    )
    task = {
        "id": "info-capital", "prompt": "what is the capital of France",
        "expect_validation": "Approved", "expect_execution": "Success",
        "expect_intent": "InformationRetrievalIntent",
    }
    result = await harness.run_task(task)
    assert result["passed"] is False
    assert any("intent" in r for r in result["reasons"])


@pytest.mark.asyncio
async def test_run_task_fails_on_missing_must_contain_substring(monkeypatch):
    monkeypatch.setattr(harness, "process_command", _fake_process_command)
    _set_response(
        "hello", validation="Approved", execution="Success",
        response="Goodbye!",
    )
    task = {
        "id": "t2", "prompt": "hello",
        "expect_validation": "Approved", "expect_execution": "Success",
        "must_contain": "hello",
    }
    result = await harness.run_task(task)
    assert result["passed"] is False
    assert any("substring" in r for r in result["reasons"])


@pytest.mark.asyncio
async def test_run_suite_aggregates_correctly(monkeypatch):
    monkeypatch.setattr(harness, "process_command", _fake_process_command)
    _set_response("a", validation="Approved", execution="Success")
    _set_response("b", validation="Denied", execution="Blocked")

    tasks = [
        {"id": "pass1", "prompt": "a", "expect_validation": "Approved", "expect_execution": "Success"},
        {"id": "fail1", "prompt": "b", "expect_validation": "Approved", "expect_execution": "Success"},
    ]
    report = await harness.run_suite(tasks)
    assert report["total"] == 2
    assert report["passed"] == 1
    assert report["failed"] == 1
    assert report["success_rate"] == 0.5
    assert "generated_at" in report
    assert len(report["results"]) == 2


@pytest.mark.asyncio
async def test_run_suite_empty_list_reports_zero_not_divide_by_zero(monkeypatch):
    monkeypatch.setattr(harness, "process_command", _fake_process_command)
    report = await harness.run_suite([])
    assert report["total"] == 0
    assert report["success_rate"] == 0.0


def test_run_eval_git_metadata_records_commit(monkeypatch):
    def _fake_check_output(args, **kwargs):
        if args[-2:] == ["--short", "HEAD"]:
            return "abc1234\n"
        return "abc1234def5678\n"

    monkeypatch.setattr(run_eval.subprocess, "check_output", _fake_check_output)

    assert run_eval._git_metadata() == {
        "commit_sha": "abc1234def5678",
        "commit_short": "abc1234",
    }


@pytest.mark.asyncio
async def test_run_eval_report_includes_top_level_git_commit(monkeypatch, tmp_path):
    async def _fake_run_suite(tasks):
        return {
            "total": 1,
            "passed": 1,
            "failed": 0,
            "success_rate": 1.0,
            "results": [],
            "generated_at": "2026-10-01T00:00:00+00:00",
        }

    monkeypatch.setattr(run_eval, "load_tasks", lambda path: [
        {"id": "t1", "prompt": "hello", "expect_validation": "Approved", "expect_execution": "Success"}
    ])
    monkeypatch.setattr(run_eval, "run_suite", _fake_run_suite)
    monkeypatch.setattr(run_eval, "_git_metadata", lambda: {
        "commit_sha": "abc1234def5678",
        "commit_short": "abc1234",
    })

    args = type("Args", (), {
        "tasks": tmp_path / "tasks.yaml",
        "task_id": [],
        "include_skip_in_ci": False,
        "report_dir": tmp_path,
        "run_id": "demo",
    })()

    exit_code = await run_eval._main_async(args)
    report = __import__("json").loads((tmp_path / "report_demo.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["git_commit"] == "abc1234def5678"
    assert report["git"]["commit_short"] == "abc1234"
