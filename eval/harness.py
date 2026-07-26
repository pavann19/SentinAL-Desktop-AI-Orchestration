"""Task-success benchmark harness for the SentinAL command pipeline."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from capabilities.system.api_wrapper import process_command


def _step_has_intent(steps: Any, expected_intent: str) -> bool:
    return any(
        isinstance(step, dict) and step.get("intent") == expected_intent
        for step in (steps or [])
    )


async def run_task(task: dict) -> dict:
    """
    task = {id, prompt, expect_validation, expect_execution, expect_intent, must_contain}
    Calls process_command(task['prompt']); compares result to expectations.
    Returns {id, prompt, passed: bool, reasons: list[str], raw: dict, latency_ms: float}.
    """
    started = time.perf_counter()
    result = await process_command(task["prompt"])
    latency_ms = (time.perf_counter() - started) * 1000

    reasons: list[str] = []
    expected_validation = task.get("expect_validation")
    expected_execution = task.get("expect_execution")

    if result.get("validation") != expected_validation:
        reasons.append(
            f"validation expected {expected_validation!r}, got {result.get('validation')!r}"
        )

    if result.get("execution") != expected_execution:
        reasons.append(
            f"execution expected {expected_execution!r}, got {result.get('execution')!r}"
        )

    expected_intent = task.get("expect_intent")
    if expected_intent and not _step_has_intent(result.get("steps"), expected_intent):
        reasons.append(f"intent {expected_intent!r} not found in steps")

    must_contain = task.get("must_contain")
    if must_contain:
        response = str(result.get("response", ""))
        if must_contain.lower() not in response.lower():
            reasons.append(f"response missing substring {must_contain!r}")

    return {
        "id": task.get("id"),
        "prompt": task.get("prompt"),
        "passed": not reasons,
        "reasons": reasons,
        "raw": result,
        "latency_ms": latency_ms,
    }


async def run_suite(tasks: list[dict]) -> dict:
    """
    Returns {total, passed, failed, success_rate: float,
             results: list[<run_task output>], generated_at: str}.
    """
    results = []
    for task in tasks:
        results.append(await run_task(task))

    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    failed = total - passed

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "success_rate": (passed / total) if total else 0.0,
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
