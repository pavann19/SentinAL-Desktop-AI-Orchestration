# tests/test_verify_s4_script.py
# Light coverage for the S4 live-round-trip operator script — the parts that
# do NOT need a running Docker daemon (import, report plumbing, the routing
# assertion it makes against the real npm_install script builder).

from __future__ import annotations

import importlib
import json

import pytest

s4 = importlib.import_module("scripts.verify_s4_live_roundtrip")


def test_module_imports_and_exposes_main():
    assert callable(s4.main)
    assert s4.DEFAULT_PKG == "is-number"


def test_report_records_and_reports_status():
    r = s4.Report()
    r.add("a", "PASS", "ok")
    r.add("b", "FAIL", "nope")
    assert r.status("a") == "PASS"
    assert r.status("b") == "FAIL"
    assert r.status("missing") == "MISSING"
    assert [c["check"] for c in r.checks] == ["a", "b"]


def test_memwatch_collects_samples():
    with s4.MemWatch(interval=0.05) as mw:
        pass
    assert len(mw.samples) >= 2
    # min_gb is either a real positive number or -1.0 (psutil unavailable)
    assert mw.min_gb == -1.0 or mw.min_gb > 0


def test_routing_assertion_matches_real_builder(tmp_path):
    """The exact check main() performs at step 2 — kept in sync with
    dependency_installer._sandboxed_npm_script_body()."""
    from capabilities.developer.dependency_installer import (
        _DOCKER_NODE_IMAGE,
        _sandboxed_npm_script_body,
    )
    d = str(tmp_path)
    body = _sandboxed_npm_script_body(["is-number"], False, d)
    assert "docker run --rm" in body
    assert f'-v "{d}:/workspace"' in body
    assert _DOCKER_NODE_IMAGE in body
    assert "npm install is-number" in body


def test_finish_writes_a_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(s4, "REPORT_DIR", str(tmp_path))
    rep = s4.Report()
    rep.add("docker_daemon_reachable", "FAIL", "not reachable")
    rep.meta = {"package": "is-number"}

    class _Args:
        output = None

    rc = s4._finish(rep, started=0.0, args=_Args(), overall=False)
    assert rc == 1
    written = list(tmp_path.glob("s4_live_roundtrip_*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text(encoding="utf-8"))
    assert payload["kind"] == "s4_live_roundtrip"
    assert payload["overall_pass"] is False
    assert payload["checks"][0]["check"] == "docker_daemon_reachable"


def test_finish_returns_zero_on_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(s4, "REPORT_DIR", str(tmp_path))

    class _Args:
        output = str(tmp_path / "r.json")

    assert s4._finish(s4.Report(), 0.0, _Args(), overall=True) == 0
    assert (tmp_path / "r.json").is_file()


@pytest.mark.skip(reason="requires a running Docker daemon — run scripts/verify_s4_live_roundtrip.py directly")
def test_full_roundtrip_placeholder():
    pass
