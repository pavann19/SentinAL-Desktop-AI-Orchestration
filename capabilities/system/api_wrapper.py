# api_wrapper.py
# Deterministic Backend Interface for SentinAL
# Replaces the ReAct agent with a strict extracted intent pipeline.
# V2.0 — Fix 3.12: process_command is now async to avoid blocking the ASGI event loop.
# V2.1 — Fix [observe-wire]: STAGE 3 now calls execute_pipeline_observed()
#         instead of execute_pipeline() directly — see comment at that call site.

import asyncio
import os
from typing import Any

from agentic_core.tracing import traced_step


def _derive_expected_state(step: dict) -> dict | None:
    """
    Fix [observe-wire]: derives a postcondition check for ApplicationLaunchIntent
    steps so execute_pipeline_observed()'s verification (built in P1-1/P1-2/P1-4,
    but never actually invoked by the live pipeline until this fix — process_command
    called raw execute_pipeline() directly) can confirm the app ACTUALLY started,
    not just that execute_pipeline() returned without raising.

    Centralized here rather than in agentic_core/processor.py because
    ApplicationLaunchIntent steps are constructed in at least 3 separate code
    paths there (the deterministic app-map fast path, the registry bypass inside
    the router loop, and the generic LLM-envelope path) — one centralized
    post-processing point is far easier to verify completely than chasing every
    construction site.

    Uses a bare basename, no extension guessing: postcondition_observer's
    observe_postcondition() does a case-insensitive SUBSTRING match
    (`process_name.lower() in p["name"].lower()`), so "notepad" already matches
    a running "notepad.exe" without needing to know the exact executable name.
    """
    if not isinstance(step, dict) or step.get("intent") != "ApplicationLaunchIntent":
        return None
    target = step.get("target", "")
    if not target:
        return None
    basename = os.path.basename(str(target).replace("\\", "/").rstrip("/\\"))
    if not basename:
        return None
    return {"process_name": basename}


async def process_command(prompt: str) -> dict[str, Any]:
    """
    Async pipeline entry point. Wraps the synchronous executor in a thread
    so it does not block the ASGI event loop (Fix 3.12).
    """
    from agentic_core.executor import execute_pipeline_observed
    from agentic_core.processor import extract_intent
    from agentic_core.validator import validate_steps

    # 1. Initialize output structure
    output = {
        "input": prompt,
        "steps": [],
        "validation": "N/A",
        "execution": "N/A",
        "response": ""
    }

    try:
        with traced_step("pipeline.process_command", prompt_len=len(prompt)):
            # ── STAGE 1: INTENT EXTRACTION ──
            with traced_step("extract_intent", prompt_len=len(prompt)):
                steps = extract_intent(prompt)
            output["steps"] = steps

            if any(s.get("intent") == "UnknownIntent" for s in steps):
                output["validation"] = "Error"
                output["execution"] = "Error"
                output["response"] = steps[0].get("target", "Extraction failed.")
                return output

            # ── STAGE 2: VALIDATION ──
            with traced_step("validate_steps", step_count=len(steps)):
                is_valid, validation_msg, _requires_confirm = validate_steps(steps)

            if not is_valid:
                output["validation"] = "Denied"
                output["execution"] = "Blocked"
                output["response"] = validation_msg
                return output

            output["validation"] = "Approved"

            # Fix [observe-wire]: attach expected_state for ApplicationLaunchIntent
            # steps so the postcondition observer (P1-2) has something to check.
            # Purely additive — steps that already carry expected_state, or that
            # aren't ApplicationLaunchIntent, are untouched.
            for step in steps:
                if isinstance(step, dict) and "expected_state" not in step:
                    derived = _derive_expected_state(step)
                    if derived:
                        step["expected_state"] = derived

            # ── STAGE 3: EXECUTION ── (run in thread pool — Fix 3.12)
            # Fix [observe-wire]: execute_pipeline_observed() (P1-1/P1-4) wraps the
            # original execute_pipeline() with a before/after state snapshot, a
            # postcondition check for any step carrying expected_state, a failure
            # taxonomy, and one bounded whole-pipeline replan on postcondition
            # mismatch. This mechanism was built and unit-tested in a prior
            # session but NEVER WIRED IN — process_command called raw
            # execute_pipeline() directly, meaning the entire mechanism was dead
            # from the live system's perspective. This call site is the fix.
            # `.result` is exactly what execute_pipeline() itself would have
            # returned — the ERROR-prefix check and response assignment below
            # are UNCHANGED from before this fix, preserving 100% backward
            # compatibility for every existing caller/test.
            with traced_step("execute_pipeline", step_count=len(steps)):
                observed = await asyncio.to_thread(execute_pipeline_observed, steps)
            execution_result = observed["result"]

            # Additive fields — new for any caller that wants them; existing
            # consumers checking only input/steps/validation/execution/response
            # are completely unaffected.
            output["failure_category"] = observed["failure_category"]
            output["replanned"] = observed["replanned"]
            output["attempts"] = observed["attempts"]

            if isinstance(execution_result, str) and execution_result.startswith("ERROR"):
                output["execution"] = "Failed"
                output["response"] = execution_result
            else:
                output["execution"] = "Success"
                output["response"] = execution_result

    except Exception as e:
        output["validation"] = "Error"
        output["execution"] = "Error"
        output["response"] = f"Pipeline Integration Error: {e!s}"

    return output
