"""
Independent verification tests for capabilities/system/postcondition_observer.py (P1-2).

Written by an independent reviewer, not the original implementer, per
VERIFICATION_PROTOCOL.md Gate 2. Tests are written against the original design
spec, mocking the three underlying modules (process_manager, gui_resolver,
vision_module) so this suite is fast, deterministic, and does not depend on
real OS state or a running VLM.
"""
import pytest

from capabilities.system import postcondition_observer as pco


# ── Tier 1: process_name ──────────────────────────────────────────────────

def test_process_tier_verified_true_when_matching_process_found(monkeypatch):
    monkeypatch.setattr(
        pco.process_manager, "list_processes",
        lambda name_filter="": [{"name": "explorer.exe", "pid": 1234, "mem_kb": "1000"}],
    )
    obs = pco.observe_postcondition({"process_name": "explorer"})
    assert obs.verified is True
    assert obs.tier_used == "process"
    assert obs.confidence == 1.0
    assert "explorer.exe" in obs.detail
    assert obs.latency_ms >= 0


def test_process_tier_verified_false_when_no_match(monkeypatch):
    monkeypatch.setattr(pco.process_manager, "list_processes", lambda name_filter="": [])
    obs = pco.observe_postcondition({"process_name": "nonexistent_app"})
    assert obs.verified is False
    assert obs.tier_used == "process"


def test_process_tier_case_insensitive_match(monkeypatch):
    monkeypatch.setattr(
        pco.process_manager, "list_processes",
        lambda name_filter="": [{"name": "NOTEPAD.EXE", "pid": 1, "mem_kb": "1"}],
    )
    obs = pco.observe_postcondition({"process_name": "notepad"})
    assert obs.verified is True


def test_process_tier_exception_is_caught_not_raised(monkeypatch):
    def _raise(name_filter=""):
        raise RuntimeError("tasklist failed")
    monkeypatch.setattr(pco.process_manager, "list_processes", _raise)
    obs = pco.observe_postcondition({"process_name": "anything"})
    assert obs.verified is False
    assert obs.tier_used == "process"
    assert obs.confidence == 0.0
    assert "error" in obs.detail.lower()


# ── Tier 2: window_title ──────────────────────────────────────────────────

# NOTE: these patch gui_resolver.window_exists, not find_window_center. The window
# tier deliberately moved to the read-only probe — find_window_center() activates
# the window it finds, and an observer must not mutate what it observes (it would
# also steal focus on every tick once this tier is polled).

def test_window_tier_verified_true_when_window_found(monkeypatch):
    monkeypatch.setattr(pco.gui_resolver, "window_exists", lambda title: True)
    obs = pco.observe_postcondition({"window_title": "Notepad"})
    assert obs.verified is True
    assert obs.tier_used == "window"
    assert "Notepad" in obs.detail


def test_window_tier_verified_false_when_none_returned(monkeypatch):
    monkeypatch.setattr(pco.gui_resolver, "window_exists", lambda title: False)
    obs = pco.observe_postcondition({"window_title": "DoesNotExist"})
    assert obs.verified is False
    assert obs.tier_used == "window"


def test_window_tier_exception_is_caught_not_raised(monkeypatch):
    def _raise(title):
        raise RuntimeError("pygetwindow crashed")
    monkeypatch.setattr(pco.gui_resolver, "window_exists", _raise)
    obs = pco.observe_postcondition({"window_title": "Anything"})
    assert obs.verified is False
    assert obs.tier_used == "window"
    assert obs.confidence == 0.0


def test_window_tier_does_not_activate_the_window(monkeypatch):
    """Regression guard: observation must never focus a window. If this starts
    failing, the tier has been pointed back at find_window_center()."""
    called = {"activated": False}
    monkeypatch.setattr(
        pco.gui_resolver, "find_window_center",
        lambda title: called.__setitem__("activated", True) or (1, 1),
    )
    monkeypatch.setattr(pco.gui_resolver, "window_exists", lambda title: True)
    pco.observe_postcondition({"window_title": "Notepad"})
    assert called["activated"] is False


# ── Tier 4: vlm_query ──────────────────────────────────────────────────────

def test_vlm_tier_verified_true_yields_higher_confidence_than_false(monkeypatch):
    monkeypatch.setattr(pco.vision_module, "verify_screen_state", lambda q: True)
    obs_true = pco.observe_postcondition({"vlm_query": "is notepad open?"})
    monkeypatch.setattr(pco.vision_module, "verify_screen_state", lambda q: False)
    obs_false = pco.observe_postcondition({"vlm_query": "is notepad open?"})
    assert obs_true.verified is True
    assert obs_false.verified is False
    assert obs_true.tier_used == "vlm"
    assert obs_true.confidence > obs_false.confidence  # spec: 0.7 vs 0.3


def test_vlm_tier_exception_is_caught_not_raised(monkeypatch):
    def _raise(q):
        raise TimeoutError("VLM timed out")
    monkeypatch.setattr(pco.vision_module, "verify_screen_state", _raise)
    obs = pco.observe_postcondition({"vlm_query": "anything"})
    assert obs.verified is False
    assert obs.tier_used == "vlm"


# ── Priority order & edge cases ────────────────────────────────────────────

def test_process_tier_takes_priority_over_window_and_vlm_when_multiple_keys_present(monkeypatch):
    """Spec: check in priority order, stop at the first key present."""
    calls = {"process": False, "window": False, "vlm": False}
    monkeypatch.setattr(
        pco.process_manager, "list_processes",
        lambda name_filter="": calls.__setitem__("process", True) or [{"name": "x.exe", "pid": 1, "mem_kb": "1"}],
    )
    monkeypatch.setattr(
        pco.gui_resolver, "window_exists",
        lambda title: calls.__setitem__("window", True) or True,
    )
    monkeypatch.setattr(
        pco.vision_module, "verify_screen_state",
        lambda q: calls.__setitem__("vlm", True) or True,
    )
    obs = pco.observe_postcondition({
        "process_name": "x", "window_title": "y", "vlm_query": "z",
    })
    assert obs.tier_used == "process"
    assert calls == {"process": True, "window": False, "vlm": False}


@pytest.mark.parametrize("expected", [{}, None])
def test_empty_or_none_expectation_returns_none_tier(expected):
    obs = pco.observe_postcondition(expected)
    assert obs.verified is False
    assert obs.tier_used == "none"
    assert obs.confidence == 0.0


def test_unrecognized_keys_return_none_tier():
    obs = pco.observe_postcondition({"totally_unknown_key": "value"})
    assert obs.tier_used == "none"
    assert obs.verified is False


# ── State snapshot / diff ──────────────────────────────────────────────────

def test_capture_state_snapshot_returns_process_names(monkeypatch):
    monkeypatch.setattr(
        pco.process_manager, "list_processes",
        lambda name_filter="": [
            {"name": "a.exe", "pid": 1, "mem_kb": "1"},
            {"name": "b.exe", "pid": 2, "mem_kb": "2"},
        ],
    )
    snap = pco.capture_state_snapshot()
    assert set(snap.processes) == {"a.exe", "b.exe"}
    assert snap.timestamp_ms > 0


def test_capture_state_snapshot_fails_safe_on_exception(monkeypatch):
    def _raise(name_filter=""):
        raise RuntimeError("boom")
    monkeypatch.setattr(pco.process_manager, "list_processes", _raise)
    snap = pco.capture_state_snapshot()
    assert snap.processes == []


def test_diff_snapshots_detects_new_and_ended_processes():
    before = pco.StateSnapshot(processes=["a.exe", "b.exe"], timestamp_ms=1000.0)
    after = pco.StateSnapshot(processes=["b.exe", "c.exe"], timestamp_ms=1500.0)
    diff = pco.diff_snapshots(before, after)
    assert diff["new_processes"] == ["c.exe"]
    assert diff["ended_processes"] == ["a.exe"]
    assert diff["elapsed_ms"] == 500.0


def test_diff_snapshots_no_change_returns_empty_lists():
    before = pco.StateSnapshot(processes=["a.exe"], timestamp_ms=0.0)
    after = pco.StateSnapshot(processes=["a.exe"], timestamp_ms=100.0)
    diff = pco.diff_snapshots(before, after)
    assert diff["new_processes"] == []
    assert diff["ended_processes"] == []
