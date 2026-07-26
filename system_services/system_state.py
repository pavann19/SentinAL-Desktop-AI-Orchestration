# system_state.py
# Reactive State Awareness Layer for SentinAL.
# V2.0 — Fix 3.11: Removed redundant `last_interaction_time` duplicate field.
#         Single canonical field is `last_interaction`.

import threading
import time


class SystemState:
    """
    Thread-safe singleton tracking the current operational context of the OS.
    Supports reactive hooks (callbacks) that trigger whenever the state changes.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialize()
            return cls._instance

    def _initialize(self):
        self.state = {
            "last_intent": "Idle",
            "last_target": None,
            "last_execution_status": "Idle",
            "active_task_id": None,
            "is_listening": False,
            "session_active": False,
            "last_interaction": time.time(),   # Canonical single field (removed duplicate)
            "current_personality_tone": "warm_minimal",
            "session_start": time.time(),
            "uptime_seconds": 0,
            "total_commands_executed": 0
        }
        self.callbacks = []
        self.state_lock = threading.Lock()

    def update_state(self, **kwargs):
        """
        Updates the global system state and notifies all registered subscribers.
        """
        with self.state_lock:
            # Fix 3.11: Removed dual-field sync logic — single canonical `last_interaction` field
            # Backwards compat: if callers pass last_interaction_time, map it to last_interaction
            if "last_interaction_time" in kwargs and "last_interaction" not in kwargs:
                kwargs["last_interaction"] = kwargs.pop("last_interaction_time")
            else:
                kwargs.pop("last_interaction_time", None)  # drop stale duplicate

            self.state.update(kwargs)
            self.state["uptime_seconds"] = int(time.time() - self.state["session_start"])

            # Increment command counter on successful execution
            if kwargs.get("last_execution_status") == "Success":
                self.state["total_commands_executed"] += 1

            # Snapshot for callbacks (outside lock prevents deadlocks)
            current_state = self.state.copy()

        # Notify subscribers (outside the lock to prevent deadlocks)
        for callback in self.callbacks:
            try:
                callback(current_state)
            except Exception as e:
                print(f"[State] Callback hook failed: {e}")

    def on_state_change(self, callback):
        """
        Registers a hook that will be notified on every state change.
        Example: on_state_change(lambda s: print(f"New state: {s['last_intent']}"))
        """
        with self.state_lock:
            self.callbacks.append(callback)

    def get_snapshot(self):
        """Returns a stable snapshot of the current state."""
        with self.state_lock:
            self.state["uptime_seconds"] = int(time.time() - self.state["session_start"])
            return self.state.copy()

# Singleton Instance
state_manager = SystemState()
