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

# How long observe_postcondition() may poll before calling a browser navigation
# failed. Configurable like the executor's other timing knobs (EXECUTOR_STEP_DELAY,
# GUI_FOCUS_WAIT, EXECUTOR_MAX_REPLANS) so it can be tuned per machine, and set to
# 0 to disable the browser checks entirely without a code change. A verified result
# returns immediately, so this is the cost of a FAILURE, not of normal operation.
_BROWSER_SETTLE_MS = float(os.getenv("OBSERVER_BROWSER_SETTLE_MS", "6000"))

# Same reasoning as the browser settle window, needed for a different failure
# mode: benchmark task multi_open_two_apps ("open notepad and calculator", two
# ApplicationLaunchIntent steps back-to-back) failed 0/3 on effect_not_observed.
# A single launch is normally fast enough to beat a single postcondition check;
# two launches in quick succession shift that timing enough for the second
# check to fire before its process has actually appeared. Kept separate from
# _BROWSER_SETTLE_MS (rather than reusing it) since process startup and page
# rendering are different costs with no reason to share one tuning knob.
_APP_LAUNCH_SETTLE_MS = float(os.getenv("OBSERVER_APP_LAUNCH_SETTLE_MS", "5000"))


def _site_label(target: str) -> str | None:
    """
    Reduces a URL or mnemonic to the label a browser window title is likely to
    contain: "https://www.youtube.com/watch?v=x" -> "youtube", "github" -> "github".

    Deliberately returns the bare second-level label rather than the full host.
    Window titles are page titles ("YouTube", "GitHub · Where software is built"),
    which contain the brand but essentially never the full hostname, so matching
    on "www.youtube.com" would fail on a page that is plainly open.
    """
    if not target:
        return None
    raw = target.strip()

    host = raw
    if "//" in host:
        host = host.split("//", 1)[1]
    host = host.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
    if not host:
        return None

    parts = [p for p in host.split(".") if p and p.lower() != "www"]
    if not parts:
        return None

    # Drop the TLD only when there is something else to keep, so a bare mnemonic
    # ("github", "spotify") survives intact while "youtube.com" -> "youtube".
    label = parts[-2] if len(parts) >= 2 else parts[0]
    return label.lower() or None


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

    ── Scope: a mismatch must mean the step genuinely failed ────────────────────
    A failed postcondition triggers a bounded WHOLE-PIPELINE replan in
    execute_pipeline_observed(), so a check that reports a false mismatch does not
    merely mislog — it re-runs the pipeline and duplicates its side effects (a
    second browser tab, a second launch). A check therefore earns its place here
    only if "not verified" reliably means "did not happen".

    Two classes of check qualify, for different reasons:

    1. Immediate/deterministic — os.path.exists() and the process list answer
       identically on every call, so a single check is conclusive.
    2. Timing-sensitive but bounded — a browser window title is NOT conclusive on
       the first check (after webbrowser.open() the window may not have rendered
       yet, making "not found" indistinguishable from "still loading"), but it
       becomes conclusive once observe_postcondition() polls until a deadline.
       These pass settle_timeout_ms so the observer waits before declaring a
       mismatch. Verified results still return immediately, so the timeout is paid
       only when something actually went wrong.

    Known limitation on the browser checks: if a window matching the site is
    ALREADY open, the check verifies without the new navigation having succeeded.
    That is a false negative for detection (a failure we miss), which is no worse
    than the blind execution it replaces — unlike a false positive, which would
    open a duplicate tab. The asymmetry is why this trade is acceptable.

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
        return (
            {"process_name": basename, "settle_timeout_ms": _APP_LAUNCH_SETTLE_MS}
            if basename else None
        )

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

    # ── Browser intents: a window for the site must appear within the settle window ──
    if intent == "WebNavigationIntent":
        label = _site_label(target)
        return {"window_title": label, "settle_timeout_ms": _BROWSER_SETTLE_MS} if label else None

    if intent == "MediaStreamingIntent":
        # Platform lives in step["value"], defaulting to youtube — mirrors
        # executor._resolve_url_template(step, default_platform="youtube") so the
        # observer looks for the site the executor actually opened.
        platform = str(step.get("value", "") or "youtube").lower().strip()
        label = _site_label(platform)
        return {"window_title": label, "settle_timeout_ms": _BROWSER_SETTLE_MS} if label else None

    # ── WindowManagementIntent: only the screenshot branch is verifiable ───────
    # The handler picks its action via an LLM classification at EXECUTION time,
    # so this derivation site cannot generally know what will happen. The one
    # safe exception is an explicit "screenshot" in the request: that is the same
    # signal handle_window_management()'s own no-LLM fallback keys on
    # (action = "screenshot" if "screenshot" in prompt_text.lower()), so deriving
    # from it cannot disagree with the handler more often than the handler
    # disagrees with itself. Snap/minimize/maximize leave no durable artifact to
    # check and are deliberately left alone.
    if intent == "WindowManagementIntent":
        request = f"{step.get('prompt', '') or ''} {target}".lower()
        if "screenshot" not in request:
            return None
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        return {
            "glob_recent": os.path.join(desktop, "SentinAL_Screenshot_*.png"),
            "within_seconds": 120,
            "settle_timeout_ms": 3000,
        }

    return None


async def process_command(prompt: str) -> dict[str, Any]:
    """
    Async pipeline entry point. Wraps the synchronous executor in a thread
    so it does not block the ASGI event loop (Fix 3.12).
    """
    from agentic_core.executor import (
        FAILURE_CATEGORY_POSTCONDITION_MISMATCH,
        execute_pipeline_observed,
    )
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

            elif observed["failure_category"] == FAILURE_CATEGORY_POSTCONDITION_MISMATCH:
                # The postcondition observer checked real system state after the
                # run (and after any bounded replan) and the expected effect was
                # NOT there. execute_pipeline() returned a cheerful string anyway
                # because it only knows whether its own calls raised.
                #
                # Found by benchmarks/run_benchmark.py: "i need to do some math,
                # open the calculator" reported execution="Success" with the
                # response "I have launched calculator." while no calculator was
                # running. The observer had already caught it - replanned=True,
                # failure_category="postcondition_mismatch" - but that verdict
                # was recorded as metadata and then discarded here, so the user
                # was still told it worked.
                #
                # That is the same defect as the fabricated-success stubs fixed
                # in 24aad7f, and worse in one respect: the system had already
                # detected the failure and reported success regardless. Honest
                # reporting is the entire point of building the observer, so the
                # observer's verdict has to win over the executor's optimism.
                #
                # Safe to fail closed here precisely because _derive_expected_state()
                # only attaches postconditions whose mismatch reliably means "did
                # not happen" - deterministic system queries, plus browser checks
                # that poll a settle window first.
                output["execution"] = "Failed"
                output["response"] = (
                    "I tried, but I couldn't confirm it actually worked — the "
                    "expected result wasn't there when I checked. Please verify "
                    "before relying on it."
                )
                output["unverified_claim"] = execution_result
            else:
                output["execution"] = "Success"
                output["response"] = execution_result

    except Exception as e:
        output["validation"] = "Error"
        output["execution"] = "Error"
        output["response"] = f"Pipeline Integration Error: {e!s}"

    return output
