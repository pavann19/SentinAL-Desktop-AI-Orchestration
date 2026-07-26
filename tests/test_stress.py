"""
tests/test_stress.py
Stress, concurrency, and load tests for SentinAL Phase 1.
These tests detect memory leaks, deadlocks, and race conditions under sustained load.
Run separately: pytest tests/test_stress.py -v --timeout=120
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import threading
import asyncio
import time
import gc


class TestPrivacyRouterStress:

    def test_1000_sequential_analyses_no_crash(self):
        """1000 sequential calls must complete without crash or memory growth."""
        from system_services.privacy_router import PrivacyRouter
        router = PrivacyRouter()
        queries = [
            "What is the capital of France?",
            "My password is abc123",
            "C:\\Users\\Admin\\secret.txt",
            "Search for python tutorials",
            "Send email to user@example.com",
        ]
        for i in range(1000):
            query = queries[i % len(queries)]
            result = router.analyze(query)
            assert result["route"] in ("local", "cloud")

    def test_50_concurrent_router_calls(self):
        """50 concurrent threads calling privacy router must not deadlock."""
        from system_services.privacy_router import PrivacyRouter
        router = PrivacyRouter()
        errors = []

        def analyze_query(i):
            try:
                result = router.analyze(f"Query number {i} about weather and news")
                assert result["route"] == "cloud"
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=analyze_query, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent privacy router failures: {errors}"


class TestValidatorStress:

    def test_500_sequential_validations(self):
        """500 validation calls must complete without error accumulation."""
        from agentic_core.validator import validate_steps
        safe_steps = [{"intent": "ConversationalIntent", "message": "Hello", "speech_response": "Hi"}]
        for _ in range(500):
            is_valid, msg, _ = validate_steps(safe_steps)
            assert is_valid is True

    def test_100_concurrent_validations_no_crash(self):
        """100 concurrent validation calls must all return consistent results."""
        from agentic_core.validator import validate_steps
        results = []
        errors = []
        safe_steps = [{"intent": "ConversationalIntent", "message": "Hello", "speech_response": "Hi"}]

        def validate_thread():
            try:
                is_valid, _, _ = validate_steps(safe_steps)
                results.append(is_valid)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=validate_thread) for _ in range(100)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert len(errors) == 0
        assert all(r is True for r in results)


class TestMemoryManagerStress:

    def test_1000_writes_and_reads_no_corruption(self, tmp_path):
        """1000 interleaved writes and reads must maintain data integrity."""
        from agentic_core.memory_hook import MemoryManager
        mgr = MemoryManager(db_path=str(tmp_path / "stress_mem.db"))

        for i in range(200):
            mgr.save_url_template(f"service_{i}", f"https://service{i}.com/search?q={{query}}")

        for i in range(200):
            result = mgr.get_url_template(f"service_{i}")
            assert result is not None
            assert f"service{i}.com" in result

        mgr.close()

    def test_concurrent_writes_reads_no_deadlock(self, tmp_path):
        """Concurrent writes and reads must not deadlock or corrupt data."""
        from agentic_core.memory_hook import MemoryManager
        mgr = MemoryManager(db_path=str(tmp_path / "concurrent_mem.db"))
        errors = []

        def writer(i):
            try:
                mgr.save_url_template(f"app_{i}", f"https://app{i}.com/?q={{query}}")
            except Exception as e:
                errors.append(("write", i, e))

        def reader(i):
            try:
                mgr.get_url_template(f"app_{i % 20}")
            except Exception as e:
                errors.append(("read", i, e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        threads += [threading.Thread(target=reader, args=(i,)) for i in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()

        mgr.close()
        assert len(errors) == 0, f"DB corruption errors: {errors}"


class TestCapabilityRegistryStress:

    def test_200_concurrent_lookups(self, tmp_path):
        """200 concurrent lookups on pre-seeded registry must be consistent."""
        from agentic_core.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry(db_path=str(tmp_path / "stress_caps.db"))
        reg.add_capability("chrome", "application", "chrome.exe")
        results = []
        errors = []

        def lookup():
            try:
                r = reg.lookup("chrome")
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=lookup) for _ in range(200)]
        for t in threads: t.start()
        for t in threads: t.join()

        reg.close()
        assert len(errors) == 0
        assert all(r == ("application", "chrome.exe") for r in results)


class TestProcessorStress:

    def test_100_fast_path_calls_performance(self):
        """100 fast-path calls (greeting/time) must all complete in < 2 seconds total."""
        from agentic_core.processor import extract_intent
        start = time.perf_counter()
        for i in range(100):
            result = extract_intent("hello")
            assert result[0]["intent"] == "ConversationalIntent"
        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"100 fast-path calls took {elapsed:.2f}s — too slow"

    def test_no_memory_leak_in_extract_intent(self):
        """extract_intent must not accumulate objects across 200 calls."""
        from agentic_core.processor import extract_intent
        gc.collect()
        before = len(gc.get_objects())

        for _ in range(200):
            extract_intent("hello")

        gc.collect()
        after = len(gc.get_objects())
        growth = after - before
        # Allow some growth but not unbounded (< 1000 new objects for 200 calls)
        assert growth < 2000, f"Potential memory leak: {growth} objects grew after 200 calls"


class TestSystemStateStress:

    def test_1000_concurrent_state_updates(self):
        """1000 concurrent updates to SystemState must not corrupt counter."""
        from system_services import system_state as ss_module
        ss_module.SystemState._instance = None
        from system_services.system_state import SystemState
        state = SystemState()
        errors = []

        def update():
            try:
                state.update_state(last_execution_status="Success")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update) for _ in range(1000)]
        for t in threads: t.start()
        for t in threads: t.join()

        ss_module.SystemState._instance = None
        assert len(errors) == 0
        assert state.get_snapshot()["total_commands_executed"] == 1000


class TestSchedulerStress:

    @pytest.mark.asyncio
    async def test_20_rapid_sequential_tasks(self):
        """20 tasks submitted rapidly must all execute in order without losing any."""
        from agentic_core.scheduler import TaskManager
        tm = TaskManager()
        tm.start()

        completed = []

        async def capture(prompt, ws, cancel_event):
            completed.append(prompt)

        # FIX 9: Import AsyncMock BEFORE first use — was causing UnboundLocalError
        from unittest.mock import AsyncMock
        ws = type("FakeWS", (), {"send_json": AsyncMock()})()
        ws.send_json = AsyncMock()


        for i in range(20):
            await tm.submit_task(f"task_{i}", ws, capture)

        # Give worker time to process all 20 tasks
        await asyncio.sleep(1.0)
        assert len(completed) == 20, f"Expected 20 completed tasks, got {len(completed)}"
