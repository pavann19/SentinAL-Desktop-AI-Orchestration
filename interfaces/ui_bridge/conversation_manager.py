import asyncio
import os
import time

from system_services.system_state import state_manager

# Fix 3.8: SESSION_TIMEOUT now configurable via env var
_SESSION_TIMEOUT = float(os.getenv("SESSION_TIMEOUT", "15.0"))


class ConversationManager:
    """
    Manages the lifecycle of an active conversational session.
    Handles timeouts and ensures the system knows when it's in a continuous state.

    V2.0 Fixes (Fix 3.8):
    - SESSION_TIMEOUT read from env (default 15s)
    - heartbeat() sleeps the exact remaining time instead of fixed 1s polling
    - start_session() has re-entrancy guard: just refreshes timer if already active
    """

    def __init__(self):
        self.last_interaction = time.time()

    @property
    def SESSION_TIMEOUT(self) -> float:
        return _SESSION_TIMEOUT

    def start_session(self):
        """Activates a continuous conversational window. Re-entrant: just refreshes if active."""
        # Fix 3.8: Re-entrancy guard — don't reset if already active, just refresh timer
        if self.is_session_valid():
            self.update_interaction()
            return

        self.last_interaction = time.time()
        state_manager.update_state(
            session_active=True,
            is_listening=True,
            last_interaction=self.last_interaction,
        )
        print("[Conversation] Session ACTIVATED.")

    def update_interaction(self):
        """Refreshes the session timer."""
        self.last_interaction = time.time()
        state_manager.update_state(last_interaction=self.last_interaction)

    def is_session_valid(self) -> bool:
        """Checks if the session is still active based on timeout."""
        snapshot = state_manager.get_snapshot()
        if not snapshot.get("session_active"):
            return False

        elapsed = time.time() - self.last_interaction
        if elapsed > self.SESSION_TIMEOUT:
            self.end_session()
            return False
        return True

    def end_session(self):
        """Safely closes the conversational window."""
        state_manager.update_state(session_active=False, is_listening=False)
        print("[Conversation] Session EXPIRED/CLOSED.")

    async def heartbeat(self):
        """
        Background timeout watcher.
        Fix 3.8: Sleeps exact remaining time instead of polling every 1s,
        so expiry fires precisely when the timeout elapses.
        """
        while True:
            snapshot = state_manager.get_snapshot()
            if snapshot.get("session_active"):
                elapsed  = time.time() - self.last_interaction
                remaining = max(0.2, self.SESSION_TIMEOUT - elapsed)
                await asyncio.sleep(remaining)
                self.is_session_valid()  # Auto-closes if expired
            else:
                await asyncio.sleep(1.0)  # Idle — check once per second


# Singleton Instance
conversation_manager = ConversationManager()
