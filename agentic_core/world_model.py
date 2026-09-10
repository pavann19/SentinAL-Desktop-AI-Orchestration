# agentic_core/world_model.py
# S7 — live environment model (increments A1 sampler + A2 read API).
#
# "World context" for a desktop agent, scoped honestly (CONTAINMENT_ARCHITECTURE
# §10.3): the user's DIGITAL environment — running processes, the foreground
# window, time. NOT camera/microphone (a materially higher privacy category,
# deliberately excluded), NOT screenshots (cost — capture_state_snapshot()
# already avoids them).
#
# A1: sample_tick() is called once per resident event-bus tick. It records a
#     bounded, pruned rolling history in the env_state table, reusing
#     postcondition_observer.capture_state_snapshot() for the process list.
# A2: current_state() / changes_since() are pure reads the planner can query
#     ("what's open now", "what changed in the last 10 minutes"). This is what
#     turns memory from a log into a world model.
#
# Off unless SENTINAL_ENV_MODEL_ENABLED. Never raises — a sampling or read
# failure degrades to "no world model", never to a crashed background loop.

from __future__ import annotations

import hashlib
import json
import logging
import time

from config.world_model import (
    ENV_MAX_PROC_NAMES,
    ENV_MODEL_ENABLED,
    ENV_RETAIN_HOURS,
    ENV_RETAIN_ROWS,
    ENV_SAMPLE_MIN_INTERVAL_SECONDS,
)

_logger = logging.getLogger("WorldModel")

_mem = None
_last_sample_ts = 0.0


def _memory():
    global _mem
    if _mem is None:
        from agentic_core.memory_hook import MemoryManager
        _mem = MemoryManager()
    return _mem


# ── capture helpers (all non-raising) ──────────────────────────────────────

def _process_names() -> list[str]:
    """Sorted unique process names, via the observer's cheap snapshot."""
    try:
        from capabilities.system.postcondition_observer import capture_state_snapshot
        names = sorted({p for p in capture_state_snapshot().processes if p})
        return names[:ENV_MAX_PROC_NAMES]
    except Exception as e:
        _logger.debug(f"process snapshot failed (non-fatal): {e}")
        return []


def _foreground_window() -> tuple[str, str]:
    """(app_name, window_title) of the foreground window, ("","") on failure
    or on a non-Windows host."""
    try:
        import win32gui  # type: ignore
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "", ""
        title = win32gui.GetWindowText(hwnd) or ""
        app = ""
        try:
            import win32process  # type: ignore
            import psutil  # type: ignore
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid:
                app = psutil.Process(pid).name()
        except Exception:
            app = ""
        return app, title
    except Exception:
        return "", ""


# ── A1: sampler ───────────────────────────────────────────────────────────

def sample_tick(*, force: bool = False, now: float | None = None) -> bool:
    """Record one environment sample. Called once per resident event-bus tick.
    Throttled to ENV_SAMPLE_MIN_INTERVAL_SECONDS unless `force`. Returns True
    if a row was written. No-op (returns False) when disabled. Never raises."""
    global _last_sample_ts
    if not ENV_MODEL_ENABLED:
        return False
    ts = time.time() if now is None else now
    if not force and (ts - _last_sample_ts) < ENV_SAMPLE_MIN_INTERVAL_SECONDS:
        return False
    try:
        procs = _process_names()
        fg_app, fg_title = _foreground_window()
        proc_hash = hashlib.sha1(
            "\x00".join(procs).encode("utf-8", "replace")
        ).hexdigest()
        _memory().add_env_state(
            ts=ts,
            proc_hash=proc_hash,
            proc_count=len(procs),
            fg_app=fg_app or None,
            fg_title=fg_title or None,
            procs_json=json.dumps(procs, separators=(",", ":")),
        )
        _memory().prune_env_state(ENV_RETAIN_ROWS, ENV_RETAIN_HOURS * 3600.0, now=ts)
        _last_sample_ts = ts
        return True
    except Exception as e:
        _logger.debug(f"sample_tick failed (non-fatal): {e}")
        return False


# ── A2: read API ──────────────────────────────────────────────────────────

def _rows(limit: int) -> list[dict]:
    try:
        return _memory().recent_env_states(limit=limit)
    except Exception as e:
        _logger.debug(f"env_state read failed (non-fatal): {e}")
        return []


def _apps(row: dict) -> list[str]:
    try:
        return list(json.loads(row.get("procs_json") or "[]"))
    except Exception:
        return []


def current_state() -> dict:
    """The latest environment sample as a friendly dict, or {} when disabled
    or nothing has been sampled yet."""
    if not ENV_MODEL_ENABLED:
        return {}
    rows = _rows(1)
    if not rows:
        return {}
    r = rows[0]
    return {
        "ts": r["ts"],
        "age_seconds": max(0.0, time.time() - r["ts"]),
        "active_app": r.get("fg_app") or "",
        "active_title": r.get("fg_title") or "",
        "process_count": r.get("proc_count", 0),
        "open_apps": _apps(r),
    }


def changes_since(seconds: float, now: float | None = None) -> dict:
    """What changed between the oldest sample inside the window and the newest:
    apps opened/closed and how many times the foreground window switched.
    {} when disabled or fewer than two samples fall in the window."""
    if not ENV_MODEL_ENABLED or seconds <= 0:
        return {}
    cutoff = (time.time() if now is None else now) - seconds
    # pull enough rows to cover the window; retention already bounds this
    rows = [r for r in _rows(ENV_RETAIN_ROWS) if r["ts"] >= cutoff]
    if len(rows) < 2:
        return {}
    rows.sort(key=lambda r: r["ts"])  # oldest -> newest
    old, new = rows[0], rows[-1]
    old_apps, new_apps = set(_apps(old)), set(_apps(new))
    switches = 0
    last_fg = None
    for r in rows:
        fg = (r.get("fg_app") or "", r.get("fg_title") or "")
        if last_fg is not None and fg != last_fg:
            switches += 1
        last_fg = fg
    return {
        "window_seconds": new["ts"] - old["ts"],
        "samples": len(rows),
        "apps_opened": sorted(new_apps - old_apps),
        "apps_closed": sorted(old_apps - new_apps),
        "foreground_switches": switches,
    }
