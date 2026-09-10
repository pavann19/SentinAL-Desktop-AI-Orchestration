# api_wrapper.py
# Deterministic Backend Interface for SentinAL
# Replaces the ReAct agent with a strict extracted intent pipeline.
# V2.0 — Fix 3.12: process_command is now async to avoid blocking the ASGI event loop.
# V2.1 — Fix [observe-wire]: STAGE 3 now calls execute_pipeline_observed()
#         instead of execute_pipeline() directly — see comment at that call site.

import asyncio
import os
import re
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


def _mkdir_target_from_command(command: str) -> str | None:
    """Extracts the one path operand from simple Windows mkdir/md commands."""
    if not command:
        return None

    command = os.path.expandvars(command.strip())
    match = re.match(
        r"^(?:mkdir|md)\s+(?P<path>\"[^\"]+\"|'[^']+'|.+?)\s*$",
        command,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    raw_path = match.group("path").strip()
    if not raw_path.startswith(('"', "'")) and any(ch.isspace() for ch in raw_path):
        return None
    path = raw_path.strip('"').strip("'")
    if not path:
        return None
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(os.getcwd(), path))


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

    # ── GeneralizedOSIntent: only simple directory creation is verifiable ─────
    # This intent can run arbitrary shell and GUI actions, so most effects are
    # not safe to infer here. The narrow safe case is a single shell action whose
    # command is exactly mkdir/md with one path operand: the executor runs that
    # command synchronously, and the directory's existence is a deterministic OS
    # fact. Other shell commands, GUI actions, Explorer opens, and visible
    # install commands are deliberately left uncovered because "not verified"
    # would not reliably mean "did not happen".
    if intent == "GeneralizedOSIntent":
        actions = step.get("actions")
        if not isinstance(actions, list) or len(actions) != 1:
            return None
        action = actions[0]
        if not isinstance(action, dict) or str(action.get("type", "") or "").lower().strip() != "shell":
            return None
        payload = str(action.get("payload", "") or "").strip()
        value = str(action.get("value", "") or "").strip()
        if value:
            command_value = os.path.expandvars(value)
            if " " in command_value and not command_value.startswith(('"', "'")):
                command_value = f'"{command_value}"'
            command = f"{payload} {command_value}".strip()
        else:
            command = payload
        mkdir_target = _mkdir_target_from_command(command)
        return {"path_exists": mkdir_target} if mkdir_target else None

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

    # ── DataModelingIntent: the EDA handler saves a real heatmap PNG to DATA_DIR ──
    # Same shape as the WindowManagementIntent screenshot check below: the exact
    # filename embeds a stem derived from the resolved CSV path plus a call-time
    # timestamp, which this derivation site cannot recompute without duplicating
    # the handler's own filename resolution (_safe_stem + _resolve_csv_path) — and
    # a second, independently-arrived-at resolution could disagree with the
    # handler's, which is the same trap SysUtilityIntent is skipped for below. A
    # wildcard glob scoped to the intent's fixed filename prefix, with freshness
    # bounded by settle/within_seconds, is conclusive without that duplication.
    if intent == "DataModelingIntent":
        from config.paths import DATA_DIR
        return {
            "glob_recent": os.path.join(DATA_DIR, "SentinAL_EDA_*.png"),
            "within_seconds": 120,
            "settle_timeout_ms": 3000,
        }

    # ── AcademicResearchIntent: the summarizer saves a real .txt to DATA_DIR ────
    # Same reasoning and same wildcard-by-prefix approach as DataModelingIntent
    # above — see capabilities/developer/academic_research.py's own docstring,
    # which anticipated this: "the postcondition is a filesystem check on the
    # summary."
    if intent == "AcademicResearchIntent":
        from config.paths import DATA_DIR
        return {
            "glob_recent": os.path.join(DATA_DIR, "SentinAL_Summary_*.txt"),
            "within_seconds": 120,
            "settle_timeout_ms": 3000,
        }

    # ── SchedulerIntent: routes deterministically on prompt keywords, same as ──
    # the handler itself (handle_scheduler() checks _LIST_TRIGGERS, then
    # _CANCEL_TRIGGERS, else falls through to add) — reusing that exact
    # precedence and those exact trigger lists means this cannot disagree with
    # the handler more often than the handler disagrees with itself, the same
    # principle WindowManagementIntent's screenshot check relies on above.
    # "list" is read-only, like ProcessManagementIntent's list action — no
    # postcondition. "cancel"/"add" reuse scheduler.py's own keyword-cleaning
    # (_cancel_keyword, _clean_description) rather than re-deriving it, so a
    # second, independently-arrived-at cleaning can't drift from the one the
    # handler actually searches with.
    if intent == "SchedulerIntent":
        from capabilities.system.scheduler import (
            _CANCEL_TRIGGERS,
            _LIST_TRIGGERS,
            _cancel_keyword,
            _clean_description,
        )
        prompt_text = str(step.get("prompt", "") or "").lower()

        if any(trigger in prompt_text for trigger in _LIST_TRIGGERS):
            return None

        if any(trigger in prompt_text for trigger in _CANCEL_TRIGGERS):
            keyword = _cancel_keyword(target, step.get("prompt", "") or "")
            return {"task_cancelled": keyword} if keyword else None

        description = _clean_description(target, step.get("prompt", "") or "")
        return {"task_description_recent": description, "within_seconds": 30} if description else None

    # Evaluated and intentionally skipped:
    # SysUtilityIntent: action is classified inside the handler at execution time; deriving registry checks from prompt text could disagree and duplicate side effects.
    # MediaControlIntent: volume/playback virtual keys leave no durable OS-state fact where "not verified" reliably means the keypress failed.
    # DictationIntent: typed text lands in whichever app has focus, with no reliable generic OS-state readback.
    # DependencyInstallIntent: supervised asynchronously via the process supervisor (sentinel + real PID), not the synchronous postcondition observer this function feeds — see capabilities/developer/dependency_installer.py.
    # CodeActIntent: completion is already supervised by the same sentinel-file mechanism, so a second postcondition layer would duplicate it.
    # InformationRetrievalIntent, ConversationalIntent, ContinuationIntent: read-only/conversational outputs have no durable OS-state postcondition.
    return None


def _paths_for_step(step: dict) -> list[str]:
    """
    The host filesystem path(s) a step is about to write to, when that is
    reliably derivable from the step dict — for the S4 pre-action snapshot.
    Returns [] when the write target can't be known in advance (arbitrary
    shell, GUI actions, CodeAct — the same unpredictability
    _derive_expected_state() already declines to guess at).

    Reuses the exact resolution _derive_expected_state() uses so the snapshot
    covers the path the executor actually touches, not a differently-resolved
    one.
    """
    if not isinstance(step, dict):
        return []
    intent = step.get("intent")
    target = str(step.get("target", "") or "").strip()

    if intent == "FileDeletionIntent" and target:
        full = os.path.abspath(target) if os.path.isabs(target) else os.path.abspath(os.path.join(os.getcwd(), target))
        return [full]

    if intent == "ProjectScaffoldIntent":
        project_name = str(step.get("project_name", "") or "").strip()
        if not project_name:
            return []
        location = str(step.get("location", "") or "").strip()
        base = location if location else os.getcwd()
        return [os.path.abspath(os.path.join(base, project_name))]

    if intent == "GeneralizedOSIntent":
        actions = step.get("actions")
        if isinstance(actions, list) and len(actions) == 1 and isinstance(actions[0], dict):
            a = actions[0]
            if str(a.get("type", "") or "").lower().strip() == "shell":
                payload = str(a.get("payload", "") or "").strip()
                value = str(a.get("value", "") or "").strip()
                if value:
                    cv = os.path.expandvars(value)
                    if " " in cv and not cv.startswith(('"', "'")):
                        cv = f'"{cv}"'
                    command = f"{payload} {cv}".strip()
                else:
                    command = payload
                tgt = _mkdir_target_from_command(command)
                return [tgt] if tgt else []
        return []

    if intent in ("DataModelingIntent", "AcademicResearchIntent"):
        # These append a timestamped file to DATA_DIR — snapshot the directory
        # (entry manifest), so rollback removes exactly the file the step added.
        from config.paths import DATA_DIR
        return [DATA_DIR]

    return []


async def process_command(prompt: str, *, autonomous: bool = False,
                          confirm_token: str | None = None) -> dict[str, Any]:
    """
    Async pipeline entry point. Wraps the synchronous executor in a thread
    so it does not block the ASGI event loop (Fix 3.12).

    autonomous=False (every direct caller — REST, voice, benchmark): the
    capability broker's tier/confirmation decision is surfaced. It is
    ENFORCED only when SENTINAL_REQUIRE_CONFIRMATION is on — then a T2/T3
    plan returns execution="PendingConfirmation" with a one-time confirm
    token, and the caller resends the same prompt with confirm_token set to
    proceed. With the switch off (default), behaviour is unchanged: the
    flag is informational, execution runs.

    autonomous=True (S6 event bus running a background goal — no human in the
    loop): the broker's decision IS enforced unconditionally. A plan whose
    highest tier is T2 or T3 is denied outright ("no human -> cannot
    confirm -> deny"), nothing runs, and the multi-step path runs under the
    tighter autonomous PlanBudget.

    validate_steps() still runs first and unconditionally in every case.
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

            # ── STAGE 1a: CAPABILITY BROKER — risk-tier decision (S4) ──────────
            # Surfaces the containment tier + confirmation need for any consumer
            # that wants to gate on it. For a direct human command
            # (autonomous=False) it is informational only — non-blocking,
            # because there is no confirmation-provision channel and blocking a
            # T3 request would break FileDeletionIntent etc. For an autonomous
            # background goal (autonomous=True, S6 event bus) it is ENFORCED:
            # a denied decision stops here, nothing runs.
            #
            # Runs before validate_steps() — it never loosens the validator's
            # own allow/deny, which still runs below and wins.
            from agentic_core.capability_broker import grant_all

            grant_decision = grant_all(steps, autonomous=autonomous)
            output["capability_tier"] = grant_decision.tier
            output["requires_confirmation"] = grant_decision.requires_confirmation
            output["capability_reason"] = grant_decision.reason
            output["autonomous"] = autonomous

            if autonomous and not grant_decision.allowed:
                output["validation"] = "Denied"
                output["execution"] = "Blocked"
                output["response"] = (
                    f"Autonomous goal blocked by containment policy: {grant_decision.reason}"
                )
                return output

            # ── STAGE 1a': DIRECT-HUMAN CONFIRMATION GATE (P2-5) ───────────────
            # Only when SENTINAL_REQUIRE_CONFIRMATION is on. A T2/T3 direct-human
            # request either presents a valid one-time token bound to THIS exact
            # request (consume it, continue) or gets a PendingConfirmation
            # result with a fresh token and nothing runs. Off by default so
            # existing REST callers / the benchmark are unaffected. The
            # autonomous path never reaches here — it already returned Blocked
            # for T2/T3 above.
            if not autonomous and grant_decision.requires_confirmation:
                from agentic_core.confirmation import (
                    REQUIRE_CONFIRMATION,
                    pending_confirmations,
                    summarize,
                )
                if REQUIRE_CONFIRMATION:
                    if pending_confirmations.check_and_consume(prompt, steps, confirm_token):
                        output["confirmation"] = "provided"
                    else:
                        token = pending_confirmations.issue(prompt, steps, grant_decision.tier)
                        output["validation"] = "Approved"
                        output["execution"] = "PendingConfirmation"
                        output["confirm_token"] = token
                        output["response"] = summarize(
                            steps, grant_decision.tier, grant_decision.reason
                        )
                        return output

            # ── STAGE 1b: S5 GOAL GRAPH ROUTING (multi-step only) ──────────────
            # Fix [S5-wire]: execute_goal_graph_observed() — the critic-integrated,
            # per-step-replan, data-chaining-aware execution engine built for S5 —
            # was added to this module but never actually called from here. The
            # planner still ran (extract_intent() engages it for a multi-step
            # prompt), but its output was flattened via GoalGraph.to_pipeline()
            # and handed to the plain execute_pipeline_observed() below, same as
            # before S5 existed — meaning {{LAST_RESULT}}/{{step_id.result}}
            # placeholders were never resolved (that only happens inside
            # resolve_data_dependencies(), which only execute_goal_graph_observed()
            # calls), and the Critic's per-step postcondition-aware replan never
            # ran on a real request. This is that missing call site.
            #
            # steps already carry depends_on (GoalNode.to_dict() includes it), so
            # reconstructing a GoalGraph from the flattened list is lossless —
            # it's the same DAG the planner built, not a re-derived one.
            #
            # Single-step requests (~94% of traffic, per S5's own gating design)
            # are untouched: len(steps) == 1 keeps using execute_pipeline_observed()
            # exactly as before, so this adds zero latency/behavior change for the
            # dominant case.
            if len(steps) > 1:
                from agentic_core.budget import budget_for
                from agentic_core.goal_graph import GoalGraph

                # An autonomous background goal runs under the tighter
                # autonomous ceilings (12 actions / 120 s vs 24 / 300 s).
                plan_budget = budget_for(autonomous=autonomous)

                with traced_step("execute_goal_graph", step_count=len(steps)):
                    graph = GoalGraph.from_pipeline(steps, goal_description=prompt)
                    goal_observed = await asyncio.to_thread(
                        execute_goal_graph_observed, graph, None, plan_budget,
                    )

                output["validation"] = goal_observed["validation"]
                output["execution"] = goal_observed["execution"]
                output["response"] = goal_observed["response"]
                output["failure_category"] = goal_observed["failure_category"]
                output["replanned"] = goal_observed["replanned"]
                output["results"] = goal_observed.get("results")
                output["budget"] = goal_observed.get("budget")
                output["snapshots"] = goal_observed.get("snapshots")
                _remember_interaction(prompt, output)
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

    _remember_interaction(prompt, output)
    return output


def _remember_interaction(prompt: str, output: dict) -> None:
    """S6 semantic memory: embed this request for retrieval by meaning. No-op
    unless SENTINAL_SEMANTIC_MEMORY_ENABLED; never raises; skips error/blocked
    outcomes so the store isn't polluted with non-events.

    Increment 2: for a SUCCESSFUL multi-step run, also records the step-shape
    ([{intent, target}, ...]) so the planner can be shown how a similar past
    goal was decomposed. Single-step and failed runs record no plan."""
    if output.get("execution") not in ("Success", "Failed"):
        return
    try:
        from agentic_core.semantic_memory import remember
        steps = output.get("steps") or []
        first = steps[0] if steps and isinstance(steps[0], dict) else {}
        plan = None
        if output.get("execution") == "Success" and len(steps) > 1:
            plan = [
                {"intent": s.get("intent"), "target": s.get("target")}
                for s in steps if isinstance(s, dict)
            ]
        remember(prompt, {
            "intent": first.get("intent"),
            "target": first.get("target"),
            "result": output.get("response"),
            "plan": plan,
        })
    except Exception:
        pass


def execute_goal_graph_observed(graph: Any, cancel_event=None, budget: Any = None) -> dict[str, Any]:
    """
    S5 Goal Graph Execution Engine: Plan -> Act -> Observe -> Reflect (Critic).
    Executes a GoalGraph node-by-node in dependency-respecting topological order.

    Security & Verification Invariants:
    1. Every step emitted by the planner MUST pass through validate_steps() before execution.
    2. Postcondition observer checks real OS state after each step.
    3. Resident Critic evaluates the observation and bounds replans to MAX_REPLANS.
    4. Data chaining ({{LAST_RESULT}}, {{step_id.result}}) is resolved dynamically as parent steps complete.
    5. S4 budget: the whole plan runs under a PlanBudget (action count + wall time).
       When it's spent, the plan stops cleanly — remaining nodes are marked
       skipped, not executed. Defaults to the direct-human ceiling; S6 passes a
       tighter autonomous one.
    6. S4 snapshot: before a step with a derivable write target runs, the prior
       state of that path is captured. On plan SUCCESS the captures are
       discarded; on ANY failure (a step failed, budget spent, cancelled,
       validation denied mid-plan) they are restored, newest first — a
       half-done plan does not leave half-done filesystem changes.
    """
    from agentic_core.budget import FAILURE_CATEGORY_BUDGET_EXCEEDED, budget_for
    from agentic_core.critic import critic
    from agentic_core.executor import (
        FAILURE_CATEGORY_CANCELLED,
        FAILURE_CATEGORY_PIPELINE_ERROR,
        FAILURE_CATEGORY_POSTCONDITION_MISMATCH,
        FAILURE_CATEGORY_SUCCESS,
        _run_and_observe,
    )
    from agentic_core.goal_graph import GoalGraph
    from agentic_core.planner import planner
    from agentic_core.snapshot import capture, new_snapshot
    from agentic_core.validator import validate_steps

    if budget is None:
        budget = budget_for(autonomous=False)

    if not isinstance(graph, GoalGraph):
        if isinstance(graph, list):
            graph = GoalGraph.from_pipeline(graph)
        else:
            return {
                "validation": "Error",
                "execution": "Error",
                "response": "Invalid graph provided.",
                "failure_category": FAILURE_CATEGORY_PIPELINE_ERROR,
                "replanned": False,
            }

    results: list[dict[str, Any]] = []
    replanned_any = False
    final_failure_category = FAILURE_CATEGORY_SUCCESS
    overall_response = ""

    try:
        ordered_nodes = graph.topological_sort()
    except ValueError as e:
        return {
            "validation": "Denied",
            "execution": "Blocked",
            "response": f"Goal graph validation error: {e}",
            "failure_category": FAILURE_CATEGORY_PIPELINE_ERROR,
            "replanned": False,
        }

    budget.start()
    plan_snapshot = new_snapshot(graph.goal_description or "plan")

    def _finish(payload: dict, *, ok: bool) -> dict:
        """Discard captures on success, restore them on any failure, then
        attach the snapshot summary to the result."""
        if ok:
            plan_snapshot.discard()
        else:
            plan_snapshot.restore()
        payload["snapshots"] = plan_snapshot.summary()
        return payload

    for node in ordered_nodes:
        # ── S4 BUDGET GATE: stop the plan cleanly if its ceiling is spent ─────
        budget_reason = budget.check()
        if budget_reason:
            for pending in graph.nodes.values():
                if pending.status in ("pending", "running"):
                    pending.status = "skipped"
            results.append({"step_id": node.step_id, "status": "skipped",
                            "detail": f"Plan budget: {budget_reason}"})
            return _finish({
                "validation": "Approved",
                "execution": "Failed",
                "response": f"Stopped: {budget_reason}. Remaining steps were not run.",
                "failure_category": FAILURE_CATEGORY_BUDGET_EXCEEDED,
                "replanned": replanned_any,
                "results": results,
                "budget": budget.snapshot(),
                "graph": graph.to_dict(),
            }, ok=False)

        # Check cancellation before starting node
        if cancel_event and cancel_event.is_set():
            graph.mark_node_failed(node.step_id, "Cancelled by user/system")
            return _finish({
                "validation": "Approved",
                "execution": "Failed",
                "response": "Execution cancelled by user.",
                "failure_category": FAILURE_CATEGORY_CANCELLED,
                "replanned": replanned_any,
                "budget": budget.snapshot(),
                "graph": graph.to_dict(),
            }, ok=False)

        # Check if node was blocked by a failed parent dependency
        if node.status == "blocked":
            results.append({
                "step_id": node.step_id,
                "status": "blocked",
                "detail": "Blocked due to dependency failure.",
            })
            continue

        # Dynamic data resolution (e.g. {{LAST_RESULT}})
        resolved_step = graph.resolve_data_dependencies(node)

        # ── DETERMINISTIC SECURITY GATE: validate_steps() MUST RUN FIRST ─────
        is_valid, validation_msg, _ = validate_steps([resolved_step])
        if not is_valid:
            graph.mark_node_failed(node.step_id, f"Validation denied: {validation_msg}")
            return _finish({
                "validation": "Denied",
                "execution": "Blocked",
                "response": f"Step '{node.step_id}' blocked by security validation: {validation_msg}",
                "failure_category": FAILURE_CATEGORY_PIPELINE_ERROR,
                "replanned": replanned_any,
                "budget": budget.snapshot(),
                "graph": graph.to_dict(),
            }, ok=False)

        # Attach expected_state if not already attached
        if "expected_state" not in resolved_step or not resolved_step["expected_state"]:
            derived = _derive_expected_state(resolved_step)
            if derived:
                resolved_step["expected_state"] = derived
                node.expected_state = derived

        # ── S4 SNAPSHOT: capture the prior state of this step's write target ──
        # (no-op for steps with no derivable target — read-only, GUI, arbitrary
        # shell). Idempotent per path across replans of the same node.
        capture(plan_snapshot, _paths_for_step(resolved_step))

        # ── EXECUTION & OBSERVATION PASS ──────────────────────────────────────
        node.status = "running"
        result_str, snapshot_diff, step_obs = _run_and_observe([resolved_step], cancel_event)
        budget.charge_action()
        observation = None
        if step_obs:
            first_obs = step_obs[0]
            observation = first_obs.get("observation") if isinstance(first_obs, dict) else first_obs

        # ── RESIDENT CRITIC VERDICT ───────────────────────────────────────────
        verdict = critic.evaluate_step(node, result_str, observation)

        # ── BOUNDED REPLAN ON POSTCONDITION MISMATCH ──────────────────────────
        while critic.should_replan(node, verdict):
            # A replan attempt is another action — do not start one the budget
            # cannot pay for. The node's replan_count still bounds this loop
            # (MAX_REPLANS) independently.
            if budget.would_exceed_actions():
                verdict = critic.evaluate_step(
                    node, f"ERROR plan action budget exhausted before replan ({budget.actions_used}/{budget.max_actions})",
                )
                break

            replanned_any = True
            graph = planner.replan_failed_node(graph, node.step_id, verdict.feedback)
            node = graph.nodes[node.step_id]

            resolved_step = graph.resolve_data_dependencies(node)
            is_valid, validation_msg, _ = validate_steps([resolved_step])
            if not is_valid:
                graph.mark_node_failed(node.step_id, f"Replanned step denied: {validation_msg}")
                verdict = critic.evaluate_step(node, f"ERROR validation: {validation_msg}")
                break

            if "expected_state" not in resolved_step or not resolved_step["expected_state"]:
                derived = _derive_expected_state(resolved_step)
                if derived:
                    resolved_step["expected_state"] = derived
                    node.expected_state = derived

            # A replan may point the step at a new path — capture that too
            # (idempotent for a path already snapshotted).
            capture(plan_snapshot, _paths_for_step(resolved_step))

            result_str, snapshot_diff, step_obs = _run_and_observe([resolved_step], cancel_event)
            budget.charge_action()
            observation = None
            if step_obs:
                first_obs = step_obs[0]
                observation = first_obs.get("observation") if isinstance(first_obs, dict) else first_obs
            verdict = critic.evaluate_step(node, result_str, observation)

        # Record node outcome
        if verdict.approved:
            graph.mark_node_completed(node.step_id, result=result_str, observation=observation)
            results.append({
                "step_id": node.step_id,
                "status": "completed",
                "result": result_str,
                "observation": observation,
            })
            overall_response = result_str
        else:
            graph.mark_node_failed(node.step_id, error=result_str, observation=observation)
            final_failure_category = verdict.failure_category
            results.append({
                "step_id": node.step_id,
                "status": "failed",
                "result": result_str,
                "observation": observation,
                "reason": verdict.reason,
            })
            overall_response = (
                f"Step '{node.step_id}' failed: {verdict.reason}"
                if verdict.failure_category != FAILURE_CATEGORY_POSTCONDITION_MISMATCH
                else "I tried, but I couldn't confirm the action took effect on system state."
            )
            break

    all_completed = graph.is_complete() and not graph.has_failures()
    return _finish({
        "validation": "Approved",
        "execution": "Success" if all_completed else "Failed",
        "response": overall_response,
        "failure_category": final_failure_category if not all_completed else FAILURE_CATEGORY_SUCCESS,
        "replanned": replanned_any,
        "results": results,
        "budget": budget.snapshot(),
        "graph": graph.to_dict(),
    }, ok=all_completed)

