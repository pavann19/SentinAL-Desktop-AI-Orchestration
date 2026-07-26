"""
conftest.py — Shared fixtures and test infrastructure for entire SentinAL test suite.
Located at project root so all test files can import fixtures without repetition.
"""
import sys
import os
import asyncio
import threading
import tempfile
import pytest

# Ensure project root is always on the path — no matter where pytest is invoked from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Silence noisy third-party loggers during tests ───────────────────────────
import logging
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("torch").setLevel(logging.ERROR)


# ── Shared DB fixtures ────────────────────────────────────────────────────────
@pytest.fixture
def tmp_db_path(tmp_path):
    """Returns a path to a unique temp SQLite file per test."""
    return str(tmp_path / "test_sentinal.db")


@pytest.fixture
def memory_manager(tmp_db_path):
    """Fresh MemoryManager backed by a temp DB for each test."""
    from agentic_core.memory_hook import MemoryManager
    mgr = MemoryManager(db_path=tmp_db_path)
    yield mgr
    mgr.close()


@pytest.fixture
def capability_registry(tmp_path):
    """Fresh CapabilityRegistry backed by a temp DB for each test."""
    from agentic_core.capability_registry import CapabilityRegistry
    db_path = str(tmp_path / "caps.db")
    reg = CapabilityRegistry(db_path=db_path)
    yield reg
    reg.close()


@pytest.fixture
def privacy_router():
    """Fresh PrivacyRouter instance for each test."""
    from system_services.privacy_router import PrivacyRouter
    return PrivacyRouter()


@pytest.fixture
def system_state():
    """
    Returns a fresh SystemState with a clean slate.
    We reset the singleton between tests to avoid state leakage.
    """
    from system_services import system_state as ss_module
    # Reset the singleton for test isolation
    ss_module.SystemState._instance = None
    from system_services.system_state import SystemState
    state = SystemState()
    yield state
    # Reset again after test
    ss_module.SystemState._instance = None


@pytest.fixture
def conversation_manager_fresh():
    """Fresh ConversationManager with default timeout."""
    from interfaces.ui_bridge.conversation_manager import ConversationManager
    return ConversationManager()


# ── Async event loop ──────────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def event_loop():
    """Single event loop shared across all async tests in the session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
