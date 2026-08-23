import os
import time
from dataclasses import dataclass
from typing import Literal

from capabilities.system import gui_resolver, process_manager, vision_module


@dataclass
class Observation:
    verified: bool
    tier_used: Literal["process", "filesystem", "window", "vlm", "memory", "none"]
    confidence: float
    latency_ms: float
    detail: str

# ── Settle/timeout polling ───────────────────────────────────────────────────
# Default interval between poll attempts. Kept small enough to return promptly
# once the condition holds, large enough not to spin the CPU on process-list
# enumeration (the most expensive of the cheap tiers).
_POLL_INTERVAL_MS = 250

# Tiers that must never be polled. The VLM tier takes a screenshot and runs model
# inference per call — polling it for several seconds would cost many inferences
# to answer one question, so it gets exactly one attempt regardless of any
# settle_timeout_ms the caller passes.
_NON_POLLABLE_KEYS = frozenset({"vlm_query"})


def _settle_timeout_ms(expected: dict) -> float:
    """Reads the per-expectation settle window. Default 0 = single check, which
    is byte-for-byte the pre-settle behaviour — polling is strictly opt-in, set
    by the derivation site that knows the action is timing-sensitive."""
    try:
        return max(0.0, float(expected.get("settle_timeout_ms", 0) or 0))
    except (TypeError, ValueError):
        return 0.0


def _poll_until_verified(check, timeout_ms: float) -> Observation:
    """
    Calls check() repeatedly until it returns a verified Observation or the
    deadline passes; returns the last Observation either way.

    The asymmetry is deliberate and is the whole point: a verified result returns
    IMMEDIATELY, so a successful action pays no added latency. Only an unverified
    result waits — and an unverified result is exactly the case where "not yet"
    and "never" are worth telling apart, because misreading the former as the
    latter triggers a whole-pipeline replan and duplicates the side effect.
    """
    observation = check()
    if observation.verified or timeout_ms <= 0:
        return observation

    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        remaining = deadline - time.time()
        time.sleep(min(_POLL_INTERVAL_MS / 1000.0, max(0.0, remaining)))
        if time.time() >= deadline:
            break
        observation = check()
        if observation.verified:
            return observation
    return observation


def observe_postcondition(expected: dict) -> Observation:
    """
    expected may contain ANY ONE of these keys (check in this priority order,
    stop at the first one present):
      - "process_name": str        -> Tier 1: process_manager.list_processes(name_filter=...)
                                       verified = True if any process name contains it (case-insensitive)
      - "process_absent": str      -> Tier 1b: the inverse — verified = True if NO running
                                       process name contains it. For kill/terminate actions,
                                       where "it worked" means the process is GONE.
      - "path_exists": str         -> Tier 1c: os.path.exists(...) is True
      - "path_absent": str         -> Tier 1d: os.path.exists(...) is False (deletion succeeded)
      - "window_title": str        -> Tier 2: gui_resolver.find_window_center(...)
                                       verified = True if a tuple (not None) is returned
      - "vlm_query": str           -> Tier 4: vision_module.verify_screen_state(...)
                                       verified = result of that call directly
      - "task_description_recent": str -> Tier 5: a PENDING scheduled task whose
                                       description contains this (case-insensitive
                                       substring), created within "within_seconds"
                                       (default 120) -> verified True
      - "task_cancelled": str      -> Tier 5b: the inverse — verified = True if NO
                                       PENDING scheduled task's description contains
                                       this substring (cancel/complete succeeded)
    If expected has none of these keys, or expected is empty/None:
      return Observation(verified=False, tier_used="none", confidence=0.0,
                          latency_ms=0.0, detail="no verifiable expectation provided")
    Never raise — any exception from an underlying call must be caught and
    turned into Observation(verified=False, tier_used=<tier attempted>, ...,
    detail=f"error: {exception}").
    Measure latency_ms around the actual underlying call, not the whole function.

    Why the filesystem tier is deterministic and the browser-window one is not:
    os.path.exists() answers immediately and unambiguously, so a mismatch is a
    REAL failure. A browser window title, by contrast, may simply not have
    settled yet when checked — treating that as a mismatch would trigger a
    whole-pipeline replan and open a second tab. Timing-sensitive tiers need a
    settle/timeout mechanism before they can be wired safely; see the follow-up
    note in api_wrapper._derive_expected_state().
    """
    if not expected:
        return Observation(verified=False, tier_used="none", confidence=0.0, latency_ms=0.0, detail="no verifiable expectation provided")

    # Settle polling wraps whichever tier fires below. Opt-in per expectation
    # (default 0 = single check); never applied to the VLM tier, see
    # _NON_POLLABLE_KEYS.
    timeout_ms = _settle_timeout_ms(expected)
    if timeout_ms > 0 and not any(k in expected for k in _NON_POLLABLE_KEYS):
        settle_free = {k: v for k, v in expected.items() if k != "settle_timeout_ms"}
        return _poll_until_verified(lambda: observe_postcondition(settle_free), timeout_ms)

    try:
        if "process_name" in expected:
            process_name = expected["process_name"]
            start_time = time.time()
            try:
                processes = process_manager.list_processes(name_filter=process_name)
                latency_ms = (time.time() - start_time) * 1000
                if processes:
                    # Look for case-insensitive match just to be safe
                    matching = [p for p in processes if process_name.lower() in p["name"].lower()]
                    if matching:
                        return Observation(verified=True, tier_used="process", confidence=1.0, latency_ms=latency_ms, detail=f"process '{matching[0]['name']}' found (pid {matching[0]['pid']})")
                return Observation(verified=False, tier_used="process", confidence=1.0, latency_ms=latency_ms, detail=f"process containing '{process_name}' not found")
            except Exception as e:
                return Observation(verified=False, tier_used="process", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")

        if "process_absent" in expected:
            process_absent = expected["process_absent"]
            start_time = time.time()
            try:
                processes = process_manager.list_processes(name_filter=process_absent)
                latency_ms = (time.time() - start_time) * 1000
                matching = [p for p in processes if process_absent.lower() in p["name"].lower()]
                if matching:
                    return Observation(verified=False, tier_used="process", confidence=1.0, latency_ms=latency_ms, detail=f"process '{matching[0]['name']}' (pid {matching[0]['pid']}) still running")
                return Observation(verified=True, tier_used="process", confidence=1.0, latency_ms=latency_ms, detail=f"no process containing '{process_absent}' is running")
            except Exception as e:
                return Observation(verified=False, tier_used="process", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")

        if "path_exists" in expected:
            path = expected["path_exists"]
            start_time = time.time()
            try:
                found = os.path.exists(path)
                latency_ms = (time.time() - start_time) * 1000
                return Observation(
                    verified=found, tier_used="filesystem", confidence=1.0, latency_ms=latency_ms,
                    detail=f"path {'exists' if found else 'does not exist'}: {path}",
                )
            except Exception as e:
                return Observation(verified=False, tier_used="filesystem", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")

        if "path_absent" in expected:
            path = expected["path_absent"]
            start_time = time.time()
            try:
                still_there = os.path.exists(path)
                latency_ms = (time.time() - start_time) * 1000
                return Observation(
                    verified=not still_there, tier_used="filesystem", confidence=1.0, latency_ms=latency_ms,
                    detail=f"path {'still exists' if still_there else 'is gone'}: {path}",
                )
            except Exception as e:
                return Observation(verified=False, tier_used="filesystem", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")

        if "glob_recent" in expected:
            # For actions whose output filename is generated at execution time
            # (e.g. a screenshot stamped with the current time), so the derivation
            # site cannot know the exact path in advance. Freshness matters: a
            # screenshot from last week matching the same pattern must NOT count
            # as evidence that this step just took one.
            pattern = expected["glob_recent"]
            start_time = time.time()
            try:
                within_s = float(expected.get("within_seconds", 120) or 120)
            except (TypeError, ValueError):
                within_s = 120.0
            try:
                import glob as _glob

                now = time.time()
                fresh = [
                    p for p in _glob.glob(pattern)
                    if (now - os.path.getmtime(p)) <= within_s
                ]
                latency_ms = (time.time() - start_time) * 1000
                if fresh:
                    newest = max(fresh, key=os.path.getmtime)
                    age = now - os.path.getmtime(newest)
                    return Observation(
                        verified=True, tier_used="filesystem", confidence=1.0, latency_ms=latency_ms,
                        detail=f"found {os.path.basename(newest)} ({age:.1f}s old) matching {pattern}",
                    )
                return Observation(
                    verified=False, tier_used="filesystem", confidence=1.0, latency_ms=latency_ms,
                    detail=f"no file newer than {within_s:.0f}s matching {pattern}",
                )
            except Exception as e:
                return Observation(verified=False, tier_used="filesystem", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")

        if "task_description_recent" in expected:
            # For SchedulerIntent's "add" action: the row is written synchronously
            # inside handle_scheduler() before execute_pipeline() returns, so no
            # settle window is needed by default — but freshness still matters,
            # the same reasoning as glob_recent: a task added last week matching
            # the same keyword must not count as evidence this step just added one.
            keyword = expected["task_description_recent"]
            start_time = time.time()
            try:
                within_s = float(expected.get("within_seconds", 120) or 120)
            except (TypeError, ValueError):
                within_s = 120.0
            try:
                from capabilities.system.scheduler import _memory as _scheduler_memory

                now = time.time()
                matches = _scheduler_memory().find_pending_tasks_by_keyword(keyword)
                fresh = [m for m in matches if (now - m["created_at"]) <= within_s]
                latency_ms = (time.time() - start_time) * 1000
                if fresh:
                    newest = max(fresh, key=lambda m: m["created_at"])
                    age = now - newest["created_at"]
                    return Observation(
                        verified=True, tier_used="memory", confidence=1.0, latency_ms=latency_ms,
                        detail=f"found pending task '{newest['description']}' ({age:.1f}s old) matching '{keyword}'",
                    )
                return Observation(
                    verified=False, tier_used="memory", confidence=1.0, latency_ms=latency_ms,
                    detail=f"no pending task newer than {within_s:.0f}s matching '{keyword}'",
                )
            except Exception as e:
                return Observation(verified=False, tier_used="memory", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")

        if "task_cancelled" in expected:
            keyword = expected["task_cancelled"]
            start_time = time.time()
            try:
                from capabilities.system.scheduler import _memory as _scheduler_memory

                matches = _scheduler_memory().find_pending_tasks_by_keyword(keyword)
                latency_ms = (time.time() - start_time) * 1000
                if matches:
                    return Observation(
                        verified=False, tier_used="memory", confidence=1.0, latency_ms=latency_ms,
                        detail=f"{len(matches)} pending task(s) still match '{keyword}': {matches[0]['description']}",
                    )
                return Observation(
                    verified=True, tier_used="memory", confidence=1.0, latency_ms=latency_ms,
                    detail=f"no pending task matches '{keyword}' — cancelled",
                )
            except Exception as e:
                return Observation(verified=False, tier_used="memory", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")

        if "window_title" in expected:
            window_title = expected["window_title"]
            start_time = time.time()
            try:
                # gui_resolver.window_exists(), NOT find_window_center(): the latter
                # activates the window it finds. Focusing a window is a mutation, and
                # an observer must not mutate what it observes — doubly so now that
                # this tier is polled, which would have stolen the user's focus on
                # every tick of the settle window.
                found = gui_resolver.window_exists(window_title)
                latency_ms = (time.time() - start_time) * 1000
                return Observation(
                    verified=found, tier_used="window", confidence=1.0, latency_ms=latency_ms,
                    detail=f"window containing '{window_title}' {'found' if found else 'not found'}",
                )
            except Exception as e:
                return Observation(verified=False, tier_used="window", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")

        if "vlm_query" in expected:
            vlm_query = expected["vlm_query"]
            start_time = time.time()
            try:
                verified = vision_module.verify_screen_state(vlm_query)
                latency_ms = (time.time() - start_time) * 1000
                confidence = 0.7 if verified else 0.3
                return Observation(verified=verified, tier_used="vlm", confidence=confidence, latency_ms=latency_ms, detail=f"vlm answered {verified} for query '{vlm_query}'")
            except Exception as e:
                return Observation(verified=False, tier_used="vlm", confidence=0.0, latency_ms=(time.time() - start_time) * 1000, detail=f"error: {e}")
                
        return Observation(verified=False, tier_used="none", confidence=0.0, latency_ms=0.0, detail="no verifiable expectation provided")
        
    except Exception as outer_e:
        return Observation(verified=False, tier_used="none", confidence=0.0, latency_ms=0.0, detail=f"error: {outer_e}")

@dataclass
class StateSnapshot:
    processes: list[str]
    timestamp_ms: float

def capture_state_snapshot() -> StateSnapshot:
    """Cheap snapshot (process list only, NO screenshot — screenshots are
    reserved for observe_postcondition's Tier 4). Used by the caller to diff
    before/after a step even when no specific expectation was declared."""
    start_ms = time.time() * 1000
    try:
        # Use empty filter to get all processes
        procs = process_manager.list_processes(name_filter="")
        names = [p["name"] for p in procs]
        return StateSnapshot(processes=names, timestamp_ms=start_ms)
    except Exception:
        return StateSnapshot(processes=[], timestamp_ms=start_ms)

def diff_snapshots(before: StateSnapshot, after: StateSnapshot) -> dict:
    """Returns {"new_processes": list[str], "ended_processes": list[str],
    "elapsed_ms": float}. Pure computation, no I/O."""
    before_set = set(before.processes)
    after_set = set(after.processes)
    
    return {
        "new_processes": list(after_set - before_set),
        "ended_processes": list(before_set - after_set),
        "elapsed_ms": after.timestamp_ms - before.timestamp_ms
    }
