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
    DRIFT_BASELINE,
    DRIFT_DROP,
    DRIFT_MIN_SAMPLE,
    DRIFT_WINDOW,
    ENV_MAX_PROC_NAMES,
    ENV_MODEL_ENABLED,
    ENV_RETAIN_HOURS,
    ENV_RETAIN_ROWS,
    ENV_SAMPLE_MIN_INTERVAL_SECONDS,
    OUTCOME_RETAIN_DAYS,
    OUTCOME_RETAIN_ROWS,
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
            import psutil  # type: ignore
            import win32process  # type: ignore
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


def format_for_prompt(state: dict | None = None, *, max_apps: int = 12) -> str:
    """A short, clearly-labelled advisory block for the planner prompt (S7 A3).
    '' when the model is off or empty. Framed as context, not instruction —
    the planner still decides."""
    st = current_state() if state is None else state
    if not st:
        return ""
    active = st.get("active_app") or ""
    title = (st.get("active_title") or "")[:80]
    apps = [a for a in st.get("open_apps", []) if a][:max_apps]
    lines = [
        (
            "[CURRENT ENVIRONMENT] Advisory only — use it to resolve references "
            "like 'this window' / 'close it'; ignore it if the goal is unrelated."
        ),
    ]
    if active:
        lines.append(f"- foreground: {active}" + (f" ({title})" if title else ""))
    if apps:
        lines.append(f"- open apps: {', '.join(apps)}")
    out = "\n".join(lines)
    return out[:600] + "... [context truncated]" if len(out) > 600 else out


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


# ── Half B: capability outcome recording + drift detection ─────────────────

def record_outcome(intent: str, verified: bool, *, failure_category: str | None = None,
                   latency_ms: float | None = None, tier: str | None = None,
                   now: float | None = None) -> bool:
    """Record one capability outcome. No-op (False) unless ENV_MODEL_ENABLED.
    Never raises."""
    if not ENV_MODEL_ENABLED or not intent:
        return False
    try:
        ts = time.time() if now is None else now
        m = _memory()
        m.add_capability_outcome(ts, intent, verified, failure_category, latency_ms, tier)
        m.prune_capability_outcomes(OUTCOME_RETAIN_ROWS, OUTCOME_RETAIN_DAYS * 86400.0, now=ts)
        return True
    except Exception as e:
        _logger.debug(f"record_outcome failed (non-fatal): {e}")
        return False


def record_run(output: dict, *, latency_ms: float | None = None,
               now: float | None = None) -> int:
    """Record one outcome per DISTINCT intent in a completed run. `verified`
    is the whole-run success. Skips non-terminal runs (Blocked / Pending /
    Error) — those are upstream rejections, not capability performance.
    Returns the number of rows written."""
    if not ENV_MODEL_ENABLED:
        return 0
    execution = (output or {}).get("execution")
    if execution not in ("Success", "Failed"):
        return 0
    verified = execution == "Success"
    fc = output.get("failure_category")
    tier = output.get("capability_tier")
    seen = []
    for s in output.get("steps") or []:
        if isinstance(s, dict):
            it = s.get("intent")
            if it and it != "UnknownIntent" and it not in seen:
                seen.append(it)
    written = 0
    for it in seen:
        if record_outcome(it, verified, failure_category=fc,
                          latency_ms=latency_ms, tier=tier, now=now):
            written += 1
    return written


def capability_health(intent: str, window: int | None = None) -> dict:
    """Rolling success rate for one capability vs. its own baseline.
    {} when disabled. `drifted` is True only when both sides have at least
    DRIFT_MIN_SAMPLE outcomes and the rolling rate is DRIFT_DROP or more
    below the baseline rate."""
    if not ENV_MODEL_ENABLED or not intent:
        return {}
    win = DRIFT_WINDOW if window is None else window
    try:
        rows = _memory().recent_capability_outcomes(intent, limit=OUTCOME_RETAIN_ROWS)
    except Exception as e:
        _logger.debug(f"capability_health read failed (non-fatal): {e}")
        return {}
    if not rows:
        return {"intent": intent, "n": 0, "drifted": False, "reason": "no outcomes"}

    chrono = list(reversed(rows))  # oldest -> newest
    baseline = chrono[:DRIFT_BASELINE]
    recent = chrono[-win:]

    def _rate(rs):
        return (sum(1 for r in rs if r["verified"]) / len(rs)) if rs else 0.0

    b_rate, r_rate = _rate(baseline), _rate(recent)
    drifted = (
        len(baseline) >= DRIFT_MIN_SAMPLE
        and len(recent) >= DRIFT_MIN_SAMPLE
        and (b_rate - r_rate) >= DRIFT_DROP
    )
    return {
        "intent": intent,
        "n": len(chrono),
        "rate": round(r_rate, 3),
        "window_n": len(recent),
        "baseline_rate": round(b_rate, 3),
        "baseline_n": len(baseline),
        "drop": round(b_rate - r_rate, 3),
        "drifted": drifted,
        "reason": (
            f"rolling {r_rate:.2f} vs baseline {b_rate:.2f} over {len(recent)} recent"
            if drifted else "within tolerance"
        ),
    }


def drift_report() -> list[dict]:
    """Every capability currently flagged as drifted, worst drop first.
    [] when disabled."""
    if not ENV_MODEL_ENABLED:
        return []
    try:
        rows = _memory().recent_capability_outcomes(None, limit=OUTCOME_RETAIN_ROWS)
    except Exception as e:
        _logger.debug(f"drift_report read failed (non-fatal): {e}")
        return []
    intents = []
    for r in rows:
        if r["intent"] not in intents:
            intents.append(r["intent"])
    flagged = [h for i in intents if (h := capability_health(i)).get("drifted")]
    flagged.sort(key=lambda h: h.get("drop", 0.0), reverse=True)
    return flagged
