# core/task_manager.py
# Centralized Task Manager for J.A.R.V.I.S.
# Ensures sequential execution, prevents overlapping TTS, and handles interrupts.

import asyncio
import os
import uuid
import traceback

class TaskManager:
    def __init__(self):
        self.queue = None
        self.current_task_id = None
        self.current_task_future = None
        self.cancel_event = None
        self._worker_task = None
        self._initialized = False
        self.MAX_QUEUE_SIZE = int(os.getenv("TASK_QUEUE_MAX", "20"))
        self.active_tasks = {} # Track id -> websocket


    def start(self):
        """Initializes the background worker loop in the event loop."""
        if not self._initialized:
            self.queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
            self.cancel_event = asyncio.Event()
            self._worker_task = asyncio.create_task(self._worker_loop())
            self._initialized = True
            print(f"[TaskManager] Centralized Execution Queue started (Capacity: {self.MAX_QUEUE_SIZE}).")


    async def submit_task(self, prompt: str, websocket, process_func):
        """
        Adds a new task to the queue. 
        """
        if not self._initialized:
            self.start()
            
        if self.queue.full():
            print(f"[TaskManager] REJECTED: Queue full ({self.MAX_QUEUE_SIZE}).")
            try:
                await websocket.send_json({"type": "system_overload", "message": "System busy, please wait for current missions to complete."})
            except Exception as e:
                print(f"[RELIABILITY ERROR] Failed to send overload message: {e}")
            return None

        task_id = str(uuid.uuid4())
        task_data = {
            "id": task_id,
            "prompt": prompt,
            "websocket": websocket,
            "func": process_func
        }
        await self.queue.put(task_data)
        self.active_tasks[task_id] = task_data
        print(f"[TaskManager] QUEUED: {task_id[:8]} - '{prompt}'")
        return task_id


    async def _worker_loop(self):
        while True:
            task_data = await self.queue.get()
            self.current_task_id = task_data["id"]
            self.cancel_event.clear()
            
            print(f"[TaskManager] RUNNING: {self.current_task_id[:8]}")
            
            try:
                # Wrap execution in an asyncio.Task so we can cancel it cleanly
                self.current_task_future = asyncio.create_task(
                    task_data["func"](
                        task_data["prompt"], 
                        task_data["websocket"], 
                        self.cancel_event
                    )
                )
                await self.current_task_future
            except asyncio.CancelledError:
                print(f"[TaskManager] CANCELLED: {self.current_task_id[:8]}")
                try:
                    from starlette.websockets import WebSocketState
                    if task_data["websocket"].client_state == WebSocketState.CONNECTED:
                        await task_data["websocket"].send_json({"type": "interrupted", "message": "Mission interrupted."})
                except Exception as e:
                    print(f"[RELIABILITY ERROR] Failed to send cancellation notice: {e}")
            except Exception as e:
                print(f"[TaskManager] FAULT in {self.current_task_id[:8]}: {e}")
                traceback.print_exc()
            finally:
                self.active_tasks.pop(self.current_task_id, None)
                self.current_task_id = None
                self.current_task_future = None
                self.queue.task_done()

                
    async def interrupt_current(self):
        """Halts the currently running task, including any TTS."""
        if self.current_task_id and self.current_task_future:
            print(f"[TaskManager] INTERRUPT TRIGGERED for: {self.current_task_id[:8]}")
            self.cancel_event.set()
            
            try:
                from interfaces.voice.tts_service import stop as tts_stop
                tts_stop()
            except Exception as e:
                print(f"[RELIABILITY ERROR] Failed to stop TTS: {e}")
            
            self.current_task_future.cancel()
        else:
            print("[TaskManager] INTERRUPT received, but queue is empty.")

    async def cancel_tasks_for_websocket(self, websocket):
        """Cleans up all tasks associated with a specific websocket."""
        # 1. Check if the current task belongs to this websocket
        if self.current_task_id:
            current_task = self.active_tasks.get(self.current_task_id)
            if current_task and current_task["websocket"] == websocket:
                print(f"[TaskManager] Dropping current task {self.current_task_id[:8]} due to client DC.")
                await self.interrupt_current()
        
        # 2. Filter queue (rebuilding it since asyncio.Queue isn't easily searchable)
        if self.queue:
            new_items = []
            drained_count = 0
            while not self.queue.empty():
                try:
                    item = self.queue.get_nowait()
                    drained_count += 1
                    if item["websocket"] != websocket:
                        new_items.append(item)
                    else:
                        print(f"[TaskManager] Purged queued task {item['id'][:8]} due to client DC.")
                        self.active_tasks.pop(item["id"], None)
                except asyncio.QueueEmpty:
                    break
            
            # Mark all drained items as done
            for _ in range(drained_count):
                self.queue.task_done()
            
            # Re-add surviving items
            for item in new_items:
                await self.queue.put(item)



# Singleton instance
task_manager = TaskManager()
