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
    Fix [observe-wire]: derives a postcondition check so execute_pipeline_observed()'s
    verification (built in P1-1/P1-2/P1-4, but never actually invoked by the live
    pipeline until that fix — process_command called raw execute_pipeline() directly)
    can confirm a step ACTUALLY achieved its effect, not just that execute_pipeline()
    returned without raising.

    Centralized here rather than in agentic_core/processor.py because steps are
    constructed in several separate code paths there (the deterministic app-map fast
    path, the registry bypass inside the router loop, and the generic LLM-envelope
    path) — one centralized post-processing point is far easier to verify completely
    than chasing every construction site.

    ── Scope: deterministic postconditions only ──────────────────────────────────
    Only intents whose success can be checked with an immediate, unambiguous system
    query are wired here. That restriction is deliberate, and it is about blast
    radius, not caution for its own sake: a failed postcondition triggers a bounded
    WHOLE-PIPELINE replan in execute_pipeline_observed(), so a postcondition that
    reports a false mismatch does not merely mislog — it re-runs the pipeline and
    duplicates its side effects (a second browser tab, a second launch).

    So a check earns its place here only if a mismatch means the step genuinely
    failed. os.path.exists() and the process list qualify: they answer immediately
    and identically on every call. A browser window title does not — after
    webbrowser.open() the window may simply not have rendered yet, making "not
    found" indistinguishable from "still loading". WebNavigationIntent and
    MediaStreamingIntent are therefore left unwired until observe_postcondition()
    grows a settle/timeout mechanism (poll until deadline before declaring a
    mismatch); wiring them without it would trade silent failures for spurious
    duplicate actions, which is a worse bargain.

    Uses a bare basename for process checks, no extension guessing:
    observe_postcondition() does a case-insensitive SUBSTRING match
    (`process_name.lower() in p["name"].lower()`), so "notepad" already matches
    a running "notepad.exe" without needing to know the exact executable name.
    """
    if not isinstance(step, dict):
        return None

    intent = step.get("intent")
    target = str(step.get("target", "") or "").strip()

    # ── ApplicationLaunchIntent: the app's process must now exist ──────────────
    if intent == "ApplicationLaunchIntent":
        if not target:
            return None
        basename = os.path.basename(target.replace("\\", "/").rstrip("/\\"))
        return {"process_name": basename} if basename else None

    # ── FileDeletionIntent: the path must now be gone ─────────────────────────
    # Mirrors the executor's own resolution (abspath, cwd-relative if not
    # absolute) so the observer checks the exact path the executor acted on,
    # not a differently-resolved one that would spuriously "verify".
    if intent == "FileDeletionIntent":
        if not target:
            return None
        full_path = os.path.abspath(target) if os.path.isabs(target) else os.path.abspath(os.path.join(os.getcwd(), target))
        return {"path_absent": full_path}

    # ── ProcessManagementIntent: only "kill" has a verifiable postcondition ────
    # "list" is read-only — there is no state change to confirm, and asserting
    # one would be a fabricated check that could only ever produce noise.
    if intent == "ProcessManagementIntent":
        action = str(step.get("action", "list") or "list").lower().strip()
        if action == "kill" and target:
            return {"process_absent": target}
        return None

    # ── ProjectScaffoldIntent: the project directory must now exist ───────────
    if intent == "ProjectScaffoldIntent":
        project_name = str(step.get("project_name", "") or "").strip()
        if not project_name:
            return None
        location = str(step.get("location", "") or "").strip()
        base = location if location else os.getcwd()
        return {"path_exists": os.path.abspath(os.path.join(base, project_name))}

    return None


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
