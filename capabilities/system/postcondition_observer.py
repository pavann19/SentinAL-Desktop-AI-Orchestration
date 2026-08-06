import os
import time
from dataclasses import dataclass
from typing import Literal

from capabilities.system import gui_resolver, process_manager, vision_module


@dataclass
class Observation:
    verified: bool
    tier_used: Literal["process", "filesystem", "window", "vlm", "none"]
    confidence: float
    latency_ms: float
    detail: str

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

        if "window_title" in expected:
            window_title = expected["window_title"]
            start_time = time.time()
            try:
                center = gui_resolver.find_window_center(window_title)
                latency_ms = (time.time() - start_time) * 1000
                if center:
                    return Observation(verified=True, tier_used="window", confidence=1.0, latency_ms=latency_ms, detail=f"window '{window_title}' found at {center}")
                return Observation(verified=False, tier_used="window", confidence=1.0, latency_ms=latency_ms, detail=f"window containing '{window_title}' not found")
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
