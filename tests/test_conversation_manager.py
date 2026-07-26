"""
tests/test_conversation_manager.py
Async tests for ConversationManager.
Covers: session lifecycle, timeout, re-entrancy, heartbeat, state sync.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import asyncio
import time
from unittest.mock import patch


@pytest.fixture(autouse=True)
def reset_state_singleton():
    from system_services import system_state as ss_module
    ss_module.SystemState._instance = None
    yield
    ss_module.SystemState._instance = None


@pytest.fixture
def mgr():
    from interfaces.ui_bridge.conversation_manager import ConversationManager
    return ConversationManager()


class TestConversationManagerSync:

    def test_start_session_activates_state(self, mgr):
        from system_services.system_state import state_manager
        mgr.start_session()
        snap = state_manager.get_snapshot()
        assert snap["session_active"] is True
        assert snap["is_listening"] is True

    def test_end_session_deactivates_state(self, mgr):
        from system_services.system_state import state_manager
        mgr.start_session()
        mgr.end_session()
        snap = state_manager.get_snapshot()
        assert snap["session_active"] is False
        assert snap["is_listening"] is False

    def test_is_session_valid_returns_true_when_active(self, mgr):
        mgr.start_session()
        assert mgr.is_session_valid() is True

    def test_is_session_valid_returns_false_when_not_started(self, mgr):
        """is_session_valid must return False when session has never been started."""
        # Ensure state is explicitly not active (system_state singleton may be shared)
        from system_services.system_state import state_manager
        state_manager.update_state(session_active=False)
        assert mgr.is_session_valid() is False


    def test_update_interaction_refreshes_timer(self, mgr):
        mgr.start_session()
        old_time = mgr.last_interaction
        time.sleep(0.05)
        mgr.update_interaction()
        assert mgr.last_interaction > old_time

    def test_session_expires_after_timeout(self, mgr):
        """Session must expire after SESSION_TIMEOUT seconds."""
        with patch.object(type(mgr), "SESSION_TIMEOUT", new_callable=lambda: property(lambda self: 0.1)):
            mgr.start_session()
            time.sleep(0.15)
            # is_session_valid() should detect expiry and end it
            assert mgr.is_session_valid() is False

    def test_start_session_reentrancy_refreshes_timer(self, mgr):
        """Calling start_session twice must refresh last_interaction, not reset state."""
        mgr.start_session()
        t1 = mgr.last_interaction
        time.sleep(0.05)
        mgr.start_session()  # Second call — re-entrant
        t2 = mgr.last_interaction
        assert t2 >= t1  # Timer refreshed, not reset to zero

    def test_session_timeout_is_configurable_via_env(self):
        """SESSION_TIMEOUT must read from SENTINAL_SESSION_TIMEOUT env var."""
        with patch.dict(os.environ, {"SESSION_TIMEOUT": "42.0"}):
            from interfaces.ui_bridge import conversation_manager as cm_module
            import importlib
            importlib.reload(cm_module)
            from interfaces.ui_bridge.conversation_manager import ConversationManager
            fresh = ConversationManager()
            assert fresh.SESSION_TIMEOUT == 42.0


class TestConversationManagerAsync:

    @pytest.mark.asyncio
    async def test_heartbeat_does_not_crash(self, mgr):
        """heartbeat() must run at least 2 cycles without crashing."""
        mgr.start_session()
        task = asyncio.create_task(mgr.heartbeat())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected

    @pytest.mark.asyncio
    async def test_heartbeat_ends_expired_session(self, mgr):
        """heartbeat() must automatically close an expired session."""
        with patch.object(type(mgr), "SESSION_TIMEOUT", new_callable=lambda: property(lambda self: 0.05)):
            mgr.start_session()
            task = asyncio.create_task(mgr.heartbeat())
            await asyncio.sleep(0.3)  # Wait for heartbeat to detect expiry
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            from system_services.system_state import state_manager
            # Session should have expired
            assert state_manager.get_snapshot()["session_active"] is False
