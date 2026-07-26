"""
tests/test_capability_registry.py
E2E Coverage Fix: Tests for the CapabilityRegistry to achieve 100% coverage on this file.
Uses an in-memory SQLite database to prevent disk IO and isolate tests.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sqlite3
import pytest
import tempfile
from agentic_core.capability_registry import CapabilityRegistry


@pytest.fixture
def memory_registry():
    """Fixture to provide a clean in-memory CapabilityRegistry for each test."""
    reg = CapabilityRegistry(":memory:")
    yield reg
    reg.close()


def test_init_creates_table(memory_registry):
    """Initialization must create the capabilities table."""
    cursor = memory_registry.conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='capabilities'"
    )
    assert cursor.fetchone()[0] == 1


def test_seed_defaults(memory_registry):
    """seed_defaults must populate both the provided app_map and the default web routes."""
    app_map = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe"
    }
    memory_registry.seed_defaults(app_map)
    
    # Check app mapping
    res = memory_registry.lookup("notepad")
    assert res is not None
    assert res[0] == "application"
    assert res[1] == "notepad.exe"
    
    # Check default web routes
    res_web = memory_registry.lookup("google")
    assert res_web is not None
    assert res_web[0] == "web"
    assert "google.com" in res_web[1]


def test_seed_defaults_is_idempotent(memory_registry):
    """Calling seed_defaults multiple times must not crash or duplicate entries."""
    app_map = {"test_app": "test.exe"}
    memory_registry.seed_defaults(app_map)
    
    # Must run without UNIQUE constraint errors due to INSERT OR IGNORE
    memory_registry.seed_defaults(app_map)
    
    cursor = memory_registry.conn.execute("SELECT count(*) FROM capabilities WHERE name='test_app'")
    assert cursor.fetchone()[0] == 1


def test_lookup_ignores_case_and_whitespace(memory_registry):
    """lookup must be case-insensitive and handle whitespace padding."""
    memory_registry.add_capability("MyApp", "application", "myapp.exe")
    res = memory_registry.lookup("  mYaPp  ")
    assert res is not None
    assert res[1] == "myapp.exe"


def test_lookup_nonexistent_returns_none(memory_registry):
    """lookup must return None if the capability does not exist."""
    res = memory_registry.lookup("ghost_app")
    assert res is None


def test_add_capability_upserts(memory_registry):
    """add_capability must support overwriting existing entries via UPSERT behavior."""
    memory_registry.add_capability("editor", "application", "vim.exe")
    res1 = memory_registry.lookup("editor")
    assert res1[1] == "vim.exe"
    
    # Update the value
    memory_registry.add_capability("editor", "application", "vscode.exe")
    res2 = memory_registry.lookup("editor")
    assert res2[1] == "vscode.exe"


def test_get_by_type(memory_registry):
    """get_by_type must return a dict of only caps matching the requested type."""
    memory_registry.add_capability("app1", "application", "1.exe")
    memory_registry.add_capability("app2", "application", "2.exe")
    memory_registry.add_capability("site1", "web", "1.com")
    
    res_apps = memory_registry.get_by_type("application")
    assert len(res_apps) == 2
    assert res_apps["app1"] == "1.exe"
    assert "site1" not in res_apps
    
    res_web = memory_registry.get_by_type("web")
    assert len(res_web) == 1
    assert res_web["site1"] == "1.com"


def test_init_makes_directory():
    """Initialization must create the parent directory if it does not exist."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "nested", "test_registry.db")
        assert not os.path.exists(os.path.dirname(db_path))
        
        reg = CapabilityRegistry(db_path)
        assert os.path.exists(os.path.dirname(db_path))
        reg.close()
