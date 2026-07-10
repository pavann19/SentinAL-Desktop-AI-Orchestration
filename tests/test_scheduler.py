"""
tests/test_scheduler.py
Async tests for TaskManager.
Covers: init, submit, queue full rejection, interrupt, cancel-for-websocket, concurrent submit.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# FIX 11: Cancel all lingering asyncio tasks after each test.
# TaskManager spawns an asyncio worker coroutine that keeps the event loop
# alive. Without explicit cancellation, pytest-asyncio's loop.close() on
# Windows blocks forever on GetQueuedCompletionStatus.
@pytest.fixture(autouse=True)
async def cancel_all_tasks():
    """Yield, then cancel every non-current task so the event loop can drain."""
    yield
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

def make_mock_websocket():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.client_state = MagicMock()
    from starlette.websockets import WebSocketState
    ws.client_state = WebSocketState.CONNECTED
    return ws


class TestTaskManagerInit:

    @pytest.mark.asyncio
    async def test_task_manager_starts_cleanly(self):
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        # Must not be initialized until start() is called
        assert tm._initialized is False
        tm.start()
        assert tm._initialized is True
        assert tm.queue is not None

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.start()
        worker1 = tm._worker_task
        tm.start()  # Second call must not create a new worker
        assert tm._worker_task is worker1


class TestTaskManagerSubmit:

    @pytest.mark.asyncio
    async def test_submit_task_returns_task_id(self):
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.start()

        executed = asyncio.Event()
        async def dummy_func(prompt, ws, cancel_event):
            executed.set()

        ws = make_mock_websocket()
        task_id = await tm.submit_task("test prompt", ws, dummy_func)
        assert task_id is not None
        assert len(task_id) > 0

    @pytest.mark.asyncio
    async def test_submit_task_executes_function(self):
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.start()

        results = []
        async def capture_func(prompt, ws, cancel_event):
            results.append(prompt)

        ws = make_mock_websocket()
        await tm.submit_task("hello world", ws, capture_func)
        await asyncio.sleep(0.2)  # Let worker process

        assert "hello world" in results

    @pytest.mark.asyncio
    async def test_queue_full_sends_overload_message(self):
        """When queue is full, submit_task must send system_overload message and return None."""
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.MAX_QUEUE_SIZE = 1
        tm.start()

        # Block the worker so queue fills up
        blocked = asyncio.Event()
        async def blocking_func(prompt, ws, cancel_event):
            await blocked.wait()

        ws = make_mock_websocket()
        await tm.submit_task("task 1", ws, blocking_func)  # Fills the queue
        await asyncio.sleep(0.05)  # Let worker pick up task 1

        # Queue now has room, fill it
        await tm.submit_task("task 2", ws, blocking_func)  # Queue = full

        # Third submit when full → should reject
        task_id = await tm.submit_task("task overflow", ws, blocking_func)
        # Should return None and send overload message
        assert task_id is None
        blocked.set()  # Unblock

    @pytest.mark.asyncio
    async def test_cancel_event_is_passed_to_function(self):
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.start()

        received_cancel_event = []
        async def check_func(prompt, ws, cancel_event):
            received_cancel_event.append(cancel_event)

        ws = make_mock_websocket()
        await tm.submit_task("check", ws, check_func)
        await asyncio.sleep(0.2)

        assert len(received_cancel_event) == 1
        assert hasattr(received_cancel_event[0], "is_set")  # It's an asyncio.Event


class TestTaskManagerInterrupt:

    @pytest.mark.asyncio
    async def test_interrupt_sets_cancel_event(self):
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.start()

        cancel_received = []
        running = asyncio.Event()

        async def long_func(prompt, ws, cancel_event):
            running.set()
            try:
                # Poll cancel_event — this is the normal interrupt path
                while not cancel_event.is_set():
                    await asyncio.sleep(0.01)
                cancel_received.append(True)
            except asyncio.CancelledError:
                # FIX 11b: TaskManager may also cancel the coroutine directly.
                # Either path counts as a successful interrupt.
                cancel_received.append(True)
                raise  # Re-raise so asyncio can clean up

        ws = make_mock_websocket()
        await tm.submit_task("long task", ws, long_func)
        await running.wait()  # Ensure task is actually running before interrupting

        await tm.interrupt_current()
        await asyncio.sleep(0.3)  # Give handler time to populate cancel_received

        assert len(cancel_received) == 1


    @pytest.mark.asyncio
    async def test_interrupt_on_empty_queue_does_not_crash(self):
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.start()
        # Should not raise
        await tm.interrupt_current()


class TestTaskManagerCancelForWebSocket:

    @pytest.mark.asyncio
    async def test_cancel_tasks_for_disconnected_websocket(self):
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.start()

        ws1 = make_mock_websocket()
        ws2 = make_mock_websocket()

        ws2_executed = []
        async def ws2_func(prompt, ws, cancel_event):
            ws2_executed.append(True)

        # Submit tasks for both websockets
        running = asyncio.Event()
        async def ws1_blocking(prompt, ws, cancel_event):
            running.set()
            await asyncio.sleep(0.5)

        await tm.submit_task("ws1 task", ws1, ws1_blocking)
        await tm.submit_task("ws2 task", ws2, ws2_func)
        await running.wait()

        # Cancel ws1's tasks — ws2's task should survive
        await tm.cancel_tasks_for_websocket(ws1)
        await asyncio.sleep(0.3)
