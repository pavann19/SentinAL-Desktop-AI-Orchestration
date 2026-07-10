"""
tests/test_system_state.py
E2E Coverage Fix: Covers system_state.py which had 0% coverage.
Tests the singleton, state updates, callbacks, backward-compat, and snapshots.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import time
import pytest
from system_services.system_state import SystemState, state_manager


# FIX 10 (final): Always restore SystemState._instance to the module-level
# state_manager after each test. This guarantees:
#   (a) test_state_manager_is_singleton_instance always passes (state_manager IS SystemState())
#   (b) Mutated state (counters, callbacks, intents) doesn't bleed between tests
@pytest.fixture(autouse=True)
def reset_singleton():
    """Snapshot state before test; restore to state_manager with original state after."""
    import copy
    snap_state     = copy.deepcopy(state_manager.state)
    snap_callbacks = list(state_manager.callbacks)
    yield
    # Always make state_manager the singleton again
    SystemState._instance          = state_manager
    state_manager.state            = snap_state
    state_manager.callbacks        = snap_callbacks


class TestSystemStateSingleton:

    def test_singleton_returns_same_instance(self):
        """Calling SystemState() twice must return the exact same object."""
        a = SystemState()
        b = SystemState()
        assert a is b

    def test_state_manager_is_singleton_instance(self):
        """The module-level state_manager must be the same singleton."""
        assert state_manager is SystemState()

    def test_initial_state_has_required_keys(self):
        """Initial state dict must contain all required tracking fields."""
        snap = state_manager.get_snapshot()
        required = [
            "last_intent", "last_target", "last_execution_status",
            "active_task_id", "is_listening", "session_active",
            "last_interaction", "current_personality_tone",
            "session_start", "uptime_seconds", "total_commands_executed"
        ]
        for key in required:
            assert key in snap, f"Missing key: {key}"


class TestSystemStateUpdates:

    def test_update_changes_state(self):
        """update_state must persist values to the state dict."""
        state_manager.update_state(last_intent="TestIntent", last_target="chrome")
        snap = state_manager.get_snapshot()
        assert snap["last_intent"] == "TestIntent"
        assert snap["last_target"] == "chrome"

    def test_success_increments_command_counter(self):
        """update_state with last_execution_status='Success' must increment total_commands_executed."""
        snap_before = state_manager.get_snapshot()
        count_before = snap_before["total_commands_executed"]
        state_manager.update_state(last_execution_status="Success")
        snap_after = state_manager.get_snapshot()
        assert snap_after["total_commands_executed"] == count_before + 1

    def test_non_success_does_not_increment_counter(self):
        """update_state with status other than 'Success' must NOT increment command counter."""
        snap_before = state_manager.get_snapshot()
        count_before = snap_before["total_commands_executed"]
        state_manager.update_state(last_execution_status="Error")
        snap_after = state_manager.get_snapshot()
        assert snap_after["total_commands_executed"] == count_before

    def test_uptime_seconds_is_non_negative(self):
        """uptime_seconds must always be >= 0."""
        snap = state_manager.get_snapshot()
        assert snap["uptime_seconds"] >= 0

    def test_backward_compat_last_interaction_time_alias(self):
        """Passing last_interaction_time must be aliased to last_interaction without error."""
        old_val = time.time() - 100
        state_manager.update_state(last_interaction_time=old_val)
        snap = state_manager.get_snapshot()
        # Field must be mapped to the canonical key, not the alias
        assert "last_interaction" in snap
        assert "last_interaction_time" not in snap

    def test_stale_last_interaction_time_dropped_when_canonical_present(self):
        """If both keys are passed, last_interaction_time must be silently dropped."""
        canonical_val = time.time()
        state_manager.update_state(
            last_interaction=canonical_val,
            last_interaction_time=time.time() - 500
        )
        snap = state_manager.get_snapshot()
        assert "last_interaction_time" not in snap
        assert snap["last_interaction"] == canonical_val


class TestSystemStateCallbacks:

    def test_callback_is_invoked_on_update(self):
        """A registered callback must be called whenever update_state is called."""
        received = []
        state_manager.on_state_change(lambda s: received.append(s["last_intent"]))
        state_manager.update_state(last_intent="CallbackTestIntent")
        # The callback must have been triggered
        assert "CallbackTestIntent" in received

    def test_callback_receives_full_snapshot(self):
        """The callback argument must be a full state dict, not a partial update."""
        full_state = {}
        state_manager.on_state_change(lambda s: full_state.update(s))
        state_manager.update_state(last_intent="SnapshotCheck")
        assert "total_commands_executed" in full_state
        assert "uptime_seconds" in full_state

    def test_failing_callback_does_not_crash_system(self):
        """A callback that raises an exception must NOT propagate and crash the system."""
        def bad_callback(state):
            raise RuntimeError("Intentional test failure in callback")

        state_manager.on_state_change(bad_callback)
        # This must not raise
        try:
            state_manager.update_state(last_intent="ErrorResilienceTest")
        except RuntimeError:
            pytest.fail("Bad callback propagated an exception — system would crash")


class TestSystemStateSnapshot:

    def test_get_snapshot_returns_dict(self):
        """get_snapshot must always return a dict."""
        result = state_manager.get_snapshot()
        assert isinstance(result, dict)

    def test_snapshot_is_a_copy(self):
        """Modifying the returned snapshot must not affect the internal state."""
        snap = state_manager.get_snapshot()
        original_intent = snap["last_intent"]
        snap["last_intent"] = "MUTATED_EXTERNALLY"
        # Re-read from the live source
        fresh_snap = state_manager.get_snapshot()
        assert fresh_snap["last_intent"] != "MUTATED_EXTERNALLY"
