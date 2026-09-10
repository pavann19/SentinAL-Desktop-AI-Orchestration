# tests/test_world_model.py
# S7 world model — A1 sampler + A2 read API.
#
# _process_names / _foreground_window are stubbed so nothing touches the real
# OS: the tests drive a scripted sequence of environment states.

from __future__ import annotations

import importlib

import pytest

import agentic_core.world_model as wm


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINAL_ENV_MODEL_ENABLED", "true")
    monkeypatch.setenv("SENTINAL_ENV_SAMPLE_MIN_INTERVAL", "20.0")
    monkeypatch.setenv("SENTINAL_ENV_RETAIN_ROWS", "50")
    monkeypatch.setenv("SENTINAL_ENV_RETAIN_HOURS", "6.0")
    import config.world_model as cfg
    importlib.reload(cfg)
    mod = importlib.reload(wm)

    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "env.db"))
    monkeypatch.setattr(mod, "_memory", lambda: mm)
    mod._mem = mm
    mod._last_sample_ts = 0.0

    state = {"procs": ["explorer.exe", "code.exe"], "fg": ("code.exe", "world_model.py - VS Code")}
    monkeypatch.setattr(mod, "_process_names", lambda: sorted(state["procs"]))
    monkeypatch.setattr(mod, "_foreground_window", lambda: state["fg"])
    mod._state = state  # let tests mutate the scripted environment
    yield mod
    mod._mem = None
    importlib.reload(wm)


# ── A1 sampler ────────────────────────────────────────────────────────────

def test_sample_writes_a_row(model):
    assert model.sample_tick(now=1000.0) is True
    rows = model._memory().recent_env_states()
    assert len(rows) == 1
    assert rows[0]["proc_count"] == 2
    assert rows[0]["fg_app"] == "code.exe"


def test_sample_is_throttled(model):
    assert model.sample_tick(now=1000.0) is True
    assert model.sample_tick(now=1010.0) is False          # < 20 s later
    assert model.sample_tick(now=1025.0) is True           # 25 s later
    assert model.sample_tick(now=1025.0, force=True) is True  # force ignores throttle


def test_sample_is_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINAL_ENV_MODEL_ENABLED", "false")
    import config.world_model as cfg
    importlib.reload(cfg)
    mod = importlib.reload(wm)
    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "off.db"))
    monkeypatch.setattr(mod, "_memory", lambda: mm)
    mod._mem = mm
    assert mod.sample_tick(force=True) is False
    assert mm.recent_env_states() == []
    importlib.reload(wm)


def test_retention_prunes_by_row_count(model):
    for i in range(70):
        model.sample_tick(now=1000.0 + i * 30, force=True)
    rows = model._memory().recent_env_states(limit=1000)
    assert len(rows) == 50  # ENV_RETAIN_ROWS


def test_retention_prunes_by_age(model):
    model.sample_tick(now=1_000.0, force=True)
    # 7 h later — the first row is now older than ENV_RETAIN_HOURS (6)
    model.sample_tick(now=1_000.0 + 7 * 3600, force=True)
    rows = model._memory().recent_env_states(limit=1000)
    assert len(rows) == 1
    assert rows[0]["ts"] == pytest.approx(1_000.0 + 7 * 3600)


def test_sample_never_raises_on_capture_failure(model, monkeypatch):
    def boom():
        raise RuntimeError("win32 exploded")
    monkeypatch.setattr(model, "_foreground_window", boom)
    assert model.sample_tick(force=True) is False  # swallowed, no row, no raise


# ── A2 read API ───────────────────────────────────────────────────────────

def test_current_state_shape(model):
    model.sample_tick(now=2000.0, force=True)
    st = model.current_state()
    assert st["active_app"] == "code.exe"
    assert "code.exe" in st["open_apps"]
    assert st["process_count"] == 2
    assert st["age_seconds"] >= 0


def test_current_state_empty_when_nothing_sampled(model):
    assert model.current_state() == {}


def test_current_state_empty_when_disabled(model, monkeypatch):
    model.sample_tick(force=True)
    monkeypatch.setattr(model, "ENV_MODEL_ENABLED", False)
    assert model.current_state() == {}


def test_changes_since_reports_opened_closed_and_switches(model):
    model._state["procs"] = ["explorer.exe", "code.exe"]
    model._state["fg"] = ("code.exe", "a")
    model.sample_tick(now=5000.0, force=True)

    model._state["procs"] = ["explorer.exe", "code.exe", "chrome.exe"]
    model._state["fg"] = ("chrome.exe", "b")
    model.sample_tick(now=5030.0, force=True)

    model._state["procs"] = ["explorer.exe", "chrome.exe"]   # code closed
    model._state["fg"] = ("explorer.exe", "c")
    model.sample_tick(now=5060.0, force=True)

    ch = model.changes_since(120, now=5060.0)
    assert ch["apps_opened"] == ["chrome.exe"]
    assert ch["apps_closed"] == ["code.exe"]
    assert ch["foreground_switches"] == 2
    assert ch["samples"] == 3


def test_changes_since_empty_with_fewer_than_two_samples(model):
    model.sample_tick(now=6000.0, force=True)
    assert model.changes_since(120, now=6000.0) == {}


def test_changes_since_window_excludes_old_samples(model):
    model.sample_tick(now=7000.0, force=True)
    model.sample_tick(now=7999.0, force=True)
    # a 100 s window ending just after the newer sample catches only it -> {}
    assert model.changes_since(100, now=8005.0) == {}
