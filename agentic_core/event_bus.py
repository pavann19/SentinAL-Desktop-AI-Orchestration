# agentic_core/event_bus.py
# ═══════════════════════════════════════════════════════════════════════════
# EVENT BUS — S6 proactive autonomy, increment 1: time triggers, notify-only
# ═══════════════════════════════════════════════════════════════════════════
#
# A single resident asyncio loop, started once from main.py's lifecycle
# alongside the process supervisor. Every tick it asks the memory store for
# scheduled_tasks rows whose due_at has passed and that have not yet been
# announced, and calls on_event(task) for each — then stamps the row notified
# so it fires exactly once.
#
# INCREMENT 1 IS DELIBERATELY NOTIFY-ONLY. on_event's job in main.py is to
# push a "reminder due" message on the telemetry websocket. It does NOT run
# the pipeline, take an action, or re-enter execution — same invariant the
# process supervisor's on_resolved has (see main.py's comment there).
# Autonomous action execution from a trigger is increment 2, separately gated,
# and is where the "week unattended, no unwanted action" gate actually bites.
#
# Mirrors agentic_core/process_supervisor.py's loop/start/stop shape on
# purpose — same failure handling (a bad callback is logged and swallowed, an
# unexpected sweep error is logged and the loop continues, CancelledError
# stops it cleanly), same idempotent start.

import asyncio
import contextlib
import logging
import os
import time

from agentic_core.memory_hook import MemoryManager

_logger = logging.getLogger("EventBus")

# Slow on purpose — this is background trigger reconciliation, not a hot path,
# and a reminder that fires 30 s late is fine.
POLL_INTERVAL_SECONDS = float(os.getenv("SENTINAL_EVENT_BUS_POLL_SECONDS", "30.0"))

# Master off switch. When false the loop starts, logs once, and no-ops every
# tick — so wiring in main.py can stay unconditional.
ENABLED = os.getenv("SENTINAL_EVENT_BUS_ENABLED", "true").strip().lower() not in ("0", "false", "no")

_memory = MemoryManager()
_bus_task: asyncio.Task | None = None


def _env_sample() -> None:
    """S7 world model rides this resident loop: one environment sample per
    tick. No-op unless SENTINAL_ENV_MODEL_ENABLED; never raises. Kept fully
    separate from the reminder sweep — it neither reads nor writes
    scheduled_tasks and cannot affect notify-only behaviour."""
    try:
        from agentic_core.world_model import sample_tick
        sample_tick()
    except Exception as e:  # pragma: no cover - defensive
        _logger.debug(f"world-model sample failed (non-fatal): {e}")


def _poll_once(memory: MemoryManager) -> list[dict]:
    """Fetch due-and-unnotified rows and stamp each notified. Returns the rows
    that were fired this tick. Runs off the event loop (called via to_thread)."""
    now = time.time()
    due = memory.get_due_scheduled_tasks(now)
    for task in due:
        with contextlib.suppress(Exception):
            memory.mark_scheduled_task_notified(task["task_id"], now)
    return due


async def event_bus_loop(on_event=None, memory: MemoryManager | None = None,
                         interval: float | None = None) -> None:
    """
    Long-running sweep. Started once at application startup, not per request.

    on_event(task: dict) is invoked for each newly-due reminder. It may be a
    coroutine function or a plain callable. Exceptions from it are logged and
    swallowed — a failing notifier must not kill the bus and strand every
    subsequent reminder.
    """
    mem = memory or _memory
    tick = POLL_INTERVAL_SECONDS if interval is None else interval

    if not ENABLED:
        _logger.info("Event bus disabled (SENTINAL_EVENT_BUS_ENABLED=false) — loop idle.")
        while True:
            try:
                # S7 world model still samples even with the reminder sweep off.
                await asyncio.to_thread(_env_sample)
                await asyncio.sleep(tick)
            except asyncio.CancelledError:
                raise

    _logger.info(f"Event bus started (every {tick}s, notify-only)")

    while True:
        try:
            await asyncio.to_thread(_env_sample)  # S7 world model sample
            due = await asyncio.to_thread(_poll_once, mem)
            for task in due:
                _logger.info(f"[event] reminder due: {task['task_id'][:8]} '{task['description']}'")
                if on_event is None:
                    continue
                try:
                    result = on_event(task)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    _logger.warning(f"on_event callback failed (non-fatal): {e}")
        except asyncio.CancelledError:
            _logger.info("Event bus stopping")
            raise
        except Exception as e:
            _logger.error(f"Event bus sweep error (continuing): {e}")

        await asyncio.sleep(tick)


def make_event_handler(*, broadcast, run_goal, autonomous_goals_on: bool):
    """
    Builds the event bus's on_event callback with the S6 kind-branch:

      kind == 'reminder' (default)            -> broadcast a 'reminder_due' msg
      kind == 'goal' AND autonomous_goals_on  -> await run_goal(description),
                                                 broadcast 'autonomous_goal_result'
      kind == 'goal' AND not enabled          -> broadcast 'reminder_due'
                                                 (degrades safe)

    broadcast(msg: dict)  -> awaitable, pushes to the telemetry clients.
    run_goal(desc: str)   -> awaitable returning the pipeline result dict.

    Kept here rather than inline in main.py's lifespan so the branch is
    unit-testable without booting the app.
    """
    async def on_event(task: dict) -> None:
        kind = str(task.get("kind") or "reminder").lower()
        if kind == "goal" and autonomous_goals_on:
            try:
                result = await run_goal(task.get("description", ""))
            except Exception as e:  # a raising goal must not strand the bus
                result = {"execution": "Error", "response": f"autonomous goal raised: {e}"}
            await broadcast({
                "type": "autonomous_goal_result",
                "task_id": task.get("task_id"),
                "description": task.get("description"),
                "execution": result.get("execution"),
                "response": result.get("response"),
                "capability_reason": result.get("capability_reason"),
                "timestamp": time.time(),
            })
            return
        await broadcast({
            "type": "reminder_due",
            "task_id": task.get("task_id"),
            "description": task.get("description"),
            "due_at": task.get("due_at"),
            "kind": kind,
            "timestamp": time.time(),
        })

    return on_event


def start_event_bus(on_event=None, memory: MemoryManager | None = None) -> asyncio.Task:
    """Starts the single global event-bus task. Idempotent."""
    global _bus_task
    if _bus_task and not _bus_task.done():
        return _bus_task
    _bus_task = asyncio.create_task(event_bus_loop(on_event, memory))
    return _bus_task


async def stop_event_bus() -> None:
    """Cancels the event-bus task if running."""
    global _bus_task
    if _bus_task and not _bus_task.done():
        _bus_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _bus_task
    _bus_task = None
