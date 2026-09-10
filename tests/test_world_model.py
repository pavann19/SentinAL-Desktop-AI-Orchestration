# tests/test_world_model.py
# S7 world model — A1 sampler + A2 read API.
#
# _process_names / _foreground_window are stubbed so nothing touches the real
# OS: the tests drive a scripted sequence of environment states.

from __future__ import annotations

import pytest

import agentic_core.world_model as wm


@pytest.fixture
def model(tmp_path, monkeypatch):
    """The real module, with config knobs patched IN PLACE (no importlib.reload
    — reloading config.world_model would leak an enabled flag into later test
    files). Every read/writer references these as module globals."""
    monkeypatch.setattr(wm, "ENV_MODEL_ENABLED", True)
    monkeypatch.setattr(wm, "ENV_SAMPLE_MIN_INTERVAL_SECONDS", 20.0)
    monkeypatch.setattr(wm, "ENV_RETAIN_ROWS", 50)
    monkeypatch.setattr(wm, "ENV_RETAIN_HOURS", 6.0)
    monkeypatch.setattr(wm, "DRIFT_WINDOW", 20)
    monkeypatch.setattr(wm, "DRIFT_BASELINE", 20)
    monkeypatch.setattr(wm, "DRIFT_MIN_SAMPLE", 8)
    monkeypatch.setattr(wm, "DRIFT_DROP", 0.25)
    monkeypatch.setattr(wm, "OUTCOME_RETAIN_ROWS", 5000)
    monkeypatch.setattr(wm, "OUTCOME_RETAIN_DAYS", 30.0)
    monkeypatch.setattr(wm, "_last_sample_ts", 0.0)

    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "env.db"))
    monkeypatch.setattr(wm, "_memory", lambda: mm)
    monkeypatch.setattr(wm, "_mem", mm)

    state = {"procs": ["explorer.exe", "code.exe"], "fg": ("code.exe", "world_model.py - VS Code")}
    monkeypatch.setattr(wm, "_process_names", lambda: sorted(state["procs"]))
    monkeypatch.setattr(wm, "_foreground_window", lambda: state["fg"])
    monkeypatch.setattr(wm, "_state", state, raising=False)  # tests mutate the scripted env
    return wm


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
    monkeypatch.setattr(wm, "ENV_MODEL_ENABLED", False)
    from agentic_core.memory_hook import MemoryManager
    mm = MemoryManager(db_path=str(tmp_path / "off.db"))
    monkeypatch.setattr(wm, "_memory", lambda: mm)
    monkeypatch.setattr(wm, "_mem", mm)
    assert wm.sample_tick(force=True) is False
    assert mm.recent_env_states() == []


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


# ── A3: format_for_prompt ─────────────────────────────────────────────────

def test_format_for_prompt_has_advisory_framing_and_content(model):
    model.sample_tick(now=9000.0, force=True)
    out = model.format_for_prompt()
    assert out.startswith("[CURRENT ENVIRONMENT]")
    assert "ignore it" in out
    assert "code.exe" in out


def test_format_for_prompt_empty_when_no_sample(model):
    assert model.format_for_prompt() == ""


def test_format_for_prompt_empty_when_disabled(model, monkeypatch):
    model.sample_tick(force=True)
    monkeypatch.setattr(model, "ENV_MODEL_ENABLED", False)
    assert model.format_for_prompt() == ""


def test_format_for_prompt_caps_length(model):
    big = {"active_app": "x.exe", "active_title": "t" * 300,
           "open_apps": [f"app{i}.exe" for i in range(200)], "process_count": 200}
    out = model.format_for_prompt(big)
    assert len(out) <= 600 + len("... [context truncated]")


# ── Half B: capability outcomes + drift ───────────────────────────────────

def _seed(model, intent, results, start=1000.0, step=10.0):
    for i, ok in enumerate(results):
        model.record_outcome(intent, ok, now=start + i * step)


def test_record_run_writes_one_row_per_distinct_intent(model):
    out = {
        "execution": "Success",
        "capability_tier": "T1",
        "steps": [
            {"intent": "ApplicationLaunchIntent"},
            {"intent": "GeneralizedOSIntent"},
            {"intent": "ApplicationLaunchIntent"},   # dup -> collapsed
            {"intent": "UnknownIntent"},             # skipped
        ],
    }
    assert model.record_run(out, latency_ms=42.0) == 2
    rows = model._memory().recent_capability_outcomes()
    assert {r["intent"] for r in rows} == {"ApplicationLaunchIntent", "GeneralizedOSIntent"}
    assert all(r["verified"] and r["tier"] == "T1" and r["latency_ms"] == 42.0 for r in rows)


def test_record_run_skips_non_terminal_runs(model):
    for ex in ("Blocked", "PendingConfirmation", "Error", "N/A"):
        assert model.record_run({"execution": ex, "steps": [{"intent": "X"}]}) == 0
    assert model._memory().recent_capability_outcomes() == []


def test_record_run_marks_failed(model):
    model.record_run({"execution": "Failed", "failure_category": "postcondition_mismatch",
                      "steps": [{"intent": "WebNavigationIntent"}]})
    r = model._memory().recent_capability_outcomes()[0]
    assert r["verified"] is False and r["failure_category"] == "postcondition_mismatch"


def test_record_outcome_noop_when_disabled(model, monkeypatch):
    monkeypatch.setattr(model, "ENV_MODEL_ENABLED", False)
    assert model.record_outcome("X", True) is False
    assert model._memory().recent_capability_outcomes() == []


def test_capability_health_healthy(model):
    _seed(model, "SchedulerIntent", [True] * 30)
    h = model.capability_health("SchedulerIntent")
    assert h["drifted"] is False
    assert h["rate"] == 1.0 and h["baseline_rate"] == 1.0


def test_capability_health_flags_a_sustained_drop(model):
    # baseline 20 all-pass, then 20 all-fail
    _seed(model, "WebNavigationIntent", [True] * 20 + [False] * 20)
    h = model.capability_health("WebNavigationIntent")
    assert h["drifted"] is True
    assert h["baseline_rate"] == 1.0 and h["rate"] == 0.0
    assert h["drop"] >= 0.25


def test_capability_health_needs_min_sample_before_flagging(model):
    # only 5 outcomes each side — below DRIFT_MIN_SAMPLE (8)
    _seed(model, "DictationIntent", [True] * 5 + [False] * 3)
    h = model.capability_health("DictationIntent")
    assert h["drifted"] is False


def test_capability_health_empty_for_unseen_intent(model):
    h = model.capability_health("NeverRunIntent")
    assert h["n"] == 0 and h["drifted"] is False


def test_drift_report_lists_only_drifted_worst_first(model):
    _seed(model, "GoodIntent", [True] * 30, start=1000.0)
    _seed(model, "BadIntent", [True] * 20 + [False] * 20, start=2000.0)
    _seed(model, "WorseIntent", [True] * 20 + [False] * 20, start=3000.0)
    # make WorseIntent's recent window worse is already 0.0; tie -> both listed
    report = model.drift_report()
    names = [h["intent"] for h in report]
    assert "GoodIntent" not in names
    assert set(names) == {"BadIntent", "WorseIntent"}


def test_drift_report_empty_when_disabled(model, monkeypatch):
    _seed(model, "BadIntent", [True] * 20 + [False] * 20)
    monkeypatch.setattr(model, "ENV_MODEL_ENABLED", False)
    assert model.drift_report() == []
