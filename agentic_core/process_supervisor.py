"""
agentic_core/process_supervisor.py

Supervises detached, long-running work that the request/response pipeline
cannot verify synchronously.

WHY THIS EXISTS
---------------
These launch work that outlives the request that started it, all via a
generated .ps1 with the same sentinel footer and a direct (no `start`
wrapper) list-form Popen, so Popen.pid is always the real process:

  CodeActIntent            -> writes a .ps1 and launches it in a visible
                              PowerShell window (codeact_engine.py)
  DependencyInstallIntent  -> npm/pip/etc. in a visible terminal
                              (capabilities/developer/dependency_installer.py)
  GeneralizedOSIntent      -> a literal shell command classified as a
                              visible install (agentic_core/executor.py,
                              the `is_visible_install` branch)

Before the fix, each of these launched through a `start`/`Start-Process`
shell wrapper, which spawns the visible console detached and returns
immediately — so Popen.pid was the transient wrapper process, not the real
one. Registering that pid as a watch would have reported "completed" almost
instantly regardless of whether the work had even started: a confident wrong
answer, worse than no observation at all.

WHY NOT JUST WAIT
-----------------
A bounded wait was considered and rejected: an npm install or a generated
script can legitimately run for minutes, so any timeout short enough to keep
the voice pipeline responsive is too short to actually observe completion.
Waiting also blocks the pipeline on work the user explicitly launched to run
in the background.

WHY NOT JUST WATCH THE PID
--------------------------
codeact_engine launches PowerShell with -NoExit specifically so the user can
read the output afterwards. The shell therefore stays alive indefinitely after
the script body finishes — process death is NOT completion. Watching the PID
alone would never resolve a CodeAct watch.

Hence two mechanisms, chosen per launch style:

  sentinel_path : for work SentinAL generates itself (a CodeAct script), a
                  completion footer is appended that writes a JSON marker when
                  the body finishes, regardless of the window staying open.
                  This is the accurate mechanism.

  pid           : for a raw command handed to a terminal, no footer can be
                  injected, so process disappearance is the only available
                  signal. Less precise (it cannot distinguish success from
                  failure), and reported as such.

SECURITY BOUNDARY
-----------------
This module OBSERVES and REPORTS. It does not act.

When a watch resolves as failed, the resolution is handed to a callback. It is
deliberately NOT wired to autonomously re-submit a corrective command: any
remediation must re-enter through the front of the pipeline (validation, risk,
authorization, policy, HITL, sandbox) exactly like a user-originated request.
A background component that could execute its own fixes would be a second
execution path around every one of those gates. The callback is the designed
extension point for that, and wiring it to anything that executes is a
security decision requiring explicit review — not a default.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid

from agentic_core.memory_hook import MemoryManager

_logger = logging.getLogger("ProcessSupervisor")

# How often the supervisor sweeps pending watches. Slow on purpose: this is
# background reconciliation, not a hot path, and every tick touches SQLite plus
# the filesystem.
POLL_INTERVAL_SECONDS = float(os.getenv("SUPERVISOR_POLL_INTERVAL", "5.0"))

# A watch that never resolves must not leak forever. Generous by default —
# npm installs and code generation legitimately take minutes.
WATCH_TIMEOUT_SECONDS = float(os.getenv("SUPERVISOR_WATCH_TIMEOUT", "900"))

# Resolved rows older than this are purged so the table cannot grow unbounded.
RESOLVED_RETENTION_SECONDS = float(os.getenv("SUPERVISOR_RETENTION", "86400"))

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed_out"

_memory = MemoryManager()


# ══════════════════════════════════════════════════════════════════════════════
# Sentinel footer — appended to scripts SentinAL generates
# ══════════════════════════════════════════════════════════════════════════════
def build_sentinel_footer(sentinel_path: str) -> str:
    """
    PowerShell appended to a generated script so it reports its own completion.

    Deliberately NOT a try/catch wrapper around the script body: wrapping would
    change scoping and break scripts that declare their own functions or param
    blocks. Clearing $Error first and inspecting it afterwards is non-invasive —
    two statements bracketing the body, no re-scoping.

    The sentinel is written when the script BODY finishes, which is the event we
    care about; the console window may stay open long afterwards (-NoExit).
    """
    escaped = sentinel_path.replace("'", "''")
    return (
        "\n\n"
        "# --- SentinAL completion sentinel (auto-appended) ---\n"
        "$__sentinal_status = if ($Error.Count -gt 0) { 'failed' } else { 'completed' }\n"
        "$__sentinal_detail = if ($Error.Count -gt 0) { [string]$Error[0] } else { '' }\n"
        "try {\n"
        "    [pscustomobject]@{ status = $__sentinal_status; detail = $__sentinal_detail } |\n"
        "        ConvertTo-Json -Compress |\n"
        f"        Set-Content -Path '{escaped}' -Encoding UTF8\n"
        "} catch { }\n"
    )


def build_sentinel_header() -> str:
    """Prepended to a generated script so $Error reflects only this run."""
    return "$Error.Clear()\n\n"


def new_sentinel_path(label: str) -> str:
    """Allocates a unique sentinel path in the same temp area CodeAct uses."""
    import tempfile
    base = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "SentinAL_Watches")
    os.makedirs(base, exist_ok=True)
    safe = "".join(c for c in label if c.isalnum() or c in "-_")[:40] or "watch"
    return os.path.join(base, f"{safe}_{uuid.uuid4().hex[:12]}.json")


# ══════════════════════════════════════════════════════════════════════════════
# Registration
# ══════════════════════════════════════════════════════════════════════════════
def register_watch(label: str, sentinel_path: str | None = None,
                   pid: int | None = None, expected_state: dict | None = None,
                   memory: MemoryManager | None = None) -> str:
    """
    Records a detached process for later reconciliation. Returns the watch id.

    Never raises: a failure to register a watch must not break the command the
    user actually asked for — the work still runs, it simply goes unobserved,
    which is the pre-existing behaviour this module improves on.
    """
    mem = memory or _memory
    watch_id = uuid.uuid4().hex
    try:
        mem.register_process_watch(
            watch_id=watch_id,
            label=label,
            registered_at=time.time(),
            sentinel_path=sentinel_path,
            pid=pid,
            expected_state=json.dumps(expected_state) if expected_state else None,
        )
        _logger.info(f"Registered watch {watch_id[:8]} for '{label}'")
    except Exception as e:
        _logger.warning(f"Could not register watch for '{label}' (non-fatal): {e}")
    return watch_id


# ══════════════════════════════════════════════════════════════════════════════
# Polling — synchronous and side-effect-scoped, so it is directly testable
# ══════════════════════════════════════════════════════════════════════════════
def _pid_alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except Exception:
        return True  # unknown -> assume still running, let the timeout decide


def _read_sentinel(path: str) -> dict | None:
    """Returns the parsed sentinel, or None if not yet written / unreadable.

    A malformed sentinel is treated as 'not yet written' rather than as a
    failure: the file is written non-atomically by an external process, so a
    partial read is an expected transient, not evidence the work failed.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8-sig") as fh:
            content = fh.read().strip()
        if not content:
            return None
        return json.loads(content)
    except Exception:
        return None


def evaluate_watch(watch: dict, now: float | None = None) -> tuple[str, str] | None:
    """
    Decides a single watch's fate. Returns (status, detail), or None if it is
    still legitimately pending.

    Pure apart from reading the sentinel file and the process table — no DB
    writes, no callbacks — so the whole decision matrix is unit-testable
    without spawning anything.
    """
    now = time.time() if now is None else now

    sentinel_path = watch.get("sentinel_path")
    if sentinel_path:
        payload = _read_sentinel(sentinel_path)
        if payload is not None:
            status = str(payload.get("status", "")).lower()
            detail = str(payload.get("detail", ""))
            if status == STATUS_FAILED:
                return STATUS_FAILED, detail or "script reported an error"
            return STATUS_COMPLETED, detail
        # sentinel not written yet -> fall through to the timeout check

    elif watch.get("pid"):
        if not _pid_alive(int(watch["pid"])):
            # PID-only watches cannot distinguish success from failure - the
            # process is simply gone. Reported honestly rather than assumed OK.
            return STATUS_COMPLETED, "process exited (exit status not observable)"

    age = now - float(watch.get("registered_at", now))
    if age >= WATCH_TIMEOUT_SECONDS:
        return STATUS_TIMED_OUT, f"no completion signal after {int(age)}s"

    return None


def poll_once(memory: MemoryManager | None = None, now: float | None = None) -> list[dict]:
    """
    Sweeps every pending watch once, resolving those that finished.

    Returns the resolutions produced by THIS sweep (each a dict with watch_id,
    label, status, detail) so a caller can notify on them. Returning them rather
    than invoking a callback internally keeps this function synchronous and
    trivially testable.
    """
    mem = memory or _memory
    resolutions: list[dict] = []

    try:
        pending = mem.get_pending_watches()
    except Exception as e:
        _logger.warning(f"Could not read pending watches: {e}")
        return resolutions

    for watch in pending:
        try:
            verdict = evaluate_watch(watch, now=now)
        except Exception as e:
            _logger.warning(f"evaluate_watch raised for {watch.get('watch_id')}: {e}")
            continue
        if verdict is None:
            continue

        status, detail = verdict
        resolved_at = time.time() if now is None else now
        try:
            mem.resolve_process_watch(watch["watch_id"], status, resolved_at, detail)
        except Exception as e:
            _logger.warning(f"Could not resolve watch {watch.get('watch_id')}: {e}")
            continue

        # Best-effort sentinel cleanup; a leftover file is harmless.
        if watch.get("sentinel_path"):
            with contextlib.suppress(Exception):
                os.remove(watch["sentinel_path"])

        resolution = {
            "watch_id": watch["watch_id"],
            "label": watch["label"],
            "status": status,
            "detail": detail,
        }
        resolutions.append(resolution)
        _logger.info(f"Watch {watch['watch_id'][:8]} '{watch['label']}' -> {status}")

    return resolutions


# ══════════════════════════════════════════════════════════════════════════════
# The background loop
# ══════════════════════════════════════════════════════════════════════════════
_supervisor_task: asyncio.Task | None = None


async def supervisor_loop(on_resolved=None, memory: MemoryManager | None = None,
                          interval: float | None = None) -> None:
    """
    Long-running sweep. Started once at application startup, not per request.

    on_resolved(resolution: dict) is invoked for each resolution. It may be a
    coroutine function or a plain callable. Exceptions from it are logged and
    swallowed — a failing notifier must not kill the supervisor and strand every
    subsequent watch.
    """
    tick = POLL_INTERVAL_SECONDS if interval is None else interval
    _logger.info(f"Process supervisor started (every {tick}s)")
    last_purge = 0.0

    while True:
        try:
            resolutions = await asyncio.to_thread(poll_once, memory)
            for resolution in resolutions:
                if on_resolved is None:
                    continue
                try:
                    result = on_resolved(resolution)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    _logger.warning(f"on_resolved callback failed (non-fatal): {e}")

            now = time.time()
            if now - last_purge > 3600:
                last_purge = now
                with contextlib.suppress(Exception):
                    mem = memory or _memory
                    await asyncio.to_thread(
                        mem.purge_resolved_watches, now - RESOLVED_RETENTION_SECONDS
                    )
        except asyncio.CancelledError:
            _logger.info("Process supervisor stopping")
            raise
        except Exception as e:
            # Never let an unexpected error terminate the loop permanently.
            _logger.error(f"Supervisor sweep error (continuing): {e}")

        await asyncio.sleep(tick)


def start_supervisor(on_resolved=None, memory: MemoryManager | None = None) -> asyncio.Task:
    """Starts the single global supervisor task. Idempotent."""
    global _supervisor_task
    if _supervisor_task and not _supervisor_task.done():
        return _supervisor_task
    _supervisor_task = asyncio.create_task(supervisor_loop(on_resolved, memory))
    return _supervisor_task


async def stop_supervisor() -> None:
    """Cancels the supervisor task if running."""
    global _supervisor_task
    if _supervisor_task and not _supervisor_task.done():
        _supervisor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _supervisor_task
    _supervisor_task = None
