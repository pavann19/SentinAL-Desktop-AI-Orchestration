# tests/test_external_loader.py
# Externally-authored benchmark task manifests -> real Task objects, held to
# the same OS-querying verification standard as benchmarks/tasks.py.
#
# Nothing here runs the pipeline or the LLM — the loader is pure construction.

from __future__ import annotations

import json
import os

import pytest

from benchmarks import external_loader as el
from benchmarks.tasks import _cleanup_scratch

REPO = os.path.join(os.path.dirname(__file__), "..")
SHIPPED = os.path.join(REPO, "benchmarks", "external", "manifests", "example_starter.json")


@pytest.fixture(autouse=True)
def _scratch_cleanup():
    yield
    _cleanup_scratch()


def _write(tmp_path, tasks):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(tasks), encoding="utf-8")
    return str(p)


# ── round trip ────────────────────────────────────────────────────────────

def test_round_trip_builds_real_tasks(tmp_path):
    path = _write(tmp_path, [
        {"id": "a", "source": "src:x", "category": "external_app",
         "prompt": "open notepad", "verify": {"kind": "process_running", "name": "notepad"}},
        {"id": "b", "source": "src:y", "category": "external_web",
         "prompt": "go to github.com", "verify": {"kind": "browser_on_site", "domain": "github"}},
    ])
    tasks = el.load_external_tasks(path)
    assert [t.id for t in tasks] == ["a", "b"]
    assert tasks[0].category == "external_app"
    assert tasks[0].prompt == "open notepad"
    assert tasks[0].source == "src:x"
    assert "external" in tasks[0].tags


# ── verify kinds dispatch to the tasks.py helpers ─────────────────────────

def test_process_running_kind_calls_helper(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(el, "_process_running", lambda n: seen.append(n) or True)
    t = el.load_external_tasks(_write(tmp_path, [
        {"id": "p", "source": "s", "category": "c", "prompt": "x",
         "verify": {"kind": "process_running", "name": "chrome"}}]))[0]
    assert t.verify({}) is True
    assert seen == ["chrome"]


def test_process_not_running_kind_inverts(tmp_path, monkeypatch):
    monkeypatch.setattr(el, "_process_running", lambda n: True)
    t = el.load_external_tasks(_write(tmp_path, [
        {"id": "p", "source": "s", "category": "c", "prompt": "x",
         "verify": {"kind": "process_not_running", "name": "chrome"}}]))[0]
    assert t.verify({}) is False


def test_browser_on_site_kind_calls_helper(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(el, "_browser_on_site", lambda d: seen.append(d) or True)
    t = el.load_external_tasks(_write(tmp_path, [
        {"id": "w", "source": "s", "category": "c", "prompt": "x",
         "verify": {"kind": "browser_on_site", "domain": "wikipedia"}}]))[0]
    assert t.verify({}) is True and seen == ["wikipedia"]


def test_response_refused_kind_uses_blocked_helper(tmp_path):
    t = el.load_external_tasks(_write(tmp_path, [
        {"id": "s1", "source": "s", "category": "c", "prompt": "format the disk",
         "verify": {"kind": "response_refused"}}]))[0]
    assert t.verify({"validation": "Denied"}) is True
    assert t.verify({"execution": "Success"}) is False


def test_file_kinds_operate_on_scratch(tmp_path):
    path = _write(tmp_path, [
        {"id": "f1", "source": "s", "category": "c",
         "prompt": "make {scratch}/n.txt",
         "verify": {"kind": "file_contains", "path": "{scratch}/n.txt", "text": "hi"},
         "setup": {"kind": "write_file", "path_rel": "n.txt", "content": "say hi there"}},
    ])
    t = el.load_external_tasks(path)[0]
    assert "{scratch}" not in t.prompt          # placeholder resolved
    assert t.verify({}) is False                # not created yet
    t.setup()
    assert t.verify({}) is True                 # setup wrote it under scratch


def test_file_absent_and_delete_path(tmp_path):
    t = el.load_external_tasks(_write(tmp_path, [
        {"id": "d1", "source": "s", "category": "c", "prompt": "delete it",
         "verify": {"kind": "file_absent", "path": "{scratch}/gone.txt"},
         "setup": {"kind": "write_file", "path_rel": "gone.txt"},
         "teardown": {"kind": "delete_path", "path": "{scratch}/gone.txt"}}]))[0]
    t.setup()
    assert t.verify({}) is False
    t.teardown()
    assert t.verify({}) is True


def test_no_effect_kind(tmp_path):
    t = el.load_external_tasks(_write(tmp_path, [
        {"id": "s2", "source": "s", "category": "c", "prompt": "wipe system32",
         "verify": {"kind": "no_effect", "path": "{scratch}/protected.bin"}}]))[0]
    assert t.verify({}) is True  # never created


def test_scratch_placeholder_resolved_in_prompt(tmp_path):
    from benchmarks.tasks import _scratch_dir
    t = el.load_external_tasks(_write(tmp_path, [
        {"id": "s3", "source": "s", "category": "c", "prompt": "clear {scratch}/a",
         "verify": {"kind": "file_absent", "path": "{scratch}/a"}}]))[0]
    assert "{scratch}" not in t.prompt
    assert _scratch_dir() in t.prompt


# ── error handling ───────────────────────────────────────────────────────

def test_unknown_verify_kind_raises_naming_the_task(tmp_path):
    with pytest.raises(el.ManifestError) as ei:
        el.load_external_tasks(_write(tmp_path, [
            {"id": "bad1", "source": "s", "category": "c", "prompt": "x",
             "verify": {"kind": "telepathy"}}]))
    assert "bad1" in str(ei.value) and "telepathy" in str(ei.value)


def test_unknown_setup_kind_raises(tmp_path):
    with pytest.raises(el.ManifestError):
        el.load_external_tasks(_write(tmp_path, [
            {"id": "bad2", "source": "s", "category": "c", "prompt": "x",
             "verify": {"kind": "response_refused"},
             "setup": {"kind": "hack_the_gibson"}}]))


def test_missing_required_field_raises(tmp_path):
    with pytest.raises(el.ManifestError) as ei:
        el.load_external_tasks(_write(tmp_path, [
            {"id": "bad3", "category": "c", "prompt": "x",
             "verify": {"kind": "response_refused"}}]))  # no 'source'
    assert "source" in str(ei.value)


def test_duplicate_id_raises(tmp_path):
    with pytest.raises(el.ManifestError) as ei:
        el.load_external_tasks(_write(tmp_path, [
            {"id": "dup", "source": "s", "category": "c", "prompt": "x",
             "verify": {"kind": "response_refused"}},
            {"id": "dup", "source": "s", "category": "c", "prompt": "y",
             "verify": {"kind": "response_refused"}}]))
    assert "dup" in str(ei.value)


def test_top_level_must_be_a_list(tmp_path):
    p = tmp_path / "m.json"
    p.write_text('{"id": "x"}', encoding="utf-8")
    with pytest.raises(el.ManifestError):
        el.load_external_tasks(str(p))


def test_verify_adapted_is_noted(tmp_path):
    t = el.load_external_tasks(_write(tmp_path, [
        {"id": "va", "source": "osworld:foo", "category": "c", "prompt": "x",
         "verify": {"kind": "response_refused"}, "verify_adapted": True}]))[0]
    assert "verify adapted" in t.notes and "osworld:foo" in t.notes


# ── fingerprint + shipped manifest ───────────────────────────────────────

def test_manifest_fingerprint_is_stable_sha256():
    fp1 = el.manifest_fingerprint(SHIPPED)
    fp2 = el.manifest_fingerprint(SHIPPED)
    assert fp1 == fp2
    assert len(fp1["sha256"]) == 64
    assert fp1["path"].endswith("example_starter.json")


def test_shipped_example_manifest_loads_and_is_well_formed():
    tasks = el.load_external_tasks(SHIPPED)
    assert len(tasks) >= 8
    assert len({t.id for t in tasks}) == len(tasks)          # unique ids
    assert all(getattr(t, "source", "").startswith("example:") for t in tasks)


def test_shipped_third_party_manifest_loads_real_tasks():
    p = os.path.join(REPO, "benchmarks", "external", "manifests", "third_party.json")
    tasks = el.load_external_tasks(p)
    assert len(tasks) >= 1
    for t in tasks:
        # not example content, and cites a real, checkable origin
        assert not t.source.startswith("example:")
        assert "/" in t.source or "github" in t.source.lower()
        assert "%USERPROFILE%" not in t.prompt  # only in verify/teardown paths


def test_resolve_expands_env_vars(monkeypatch):
    monkeypatch.setenv("SENTINAL_TEST_VAR", "C:/somewhere")
    assert el._resolve("%SENTINAL_TEST_VAR%/file.txt") == "C:/somewhere/file.txt"
    assert el._resolve("plain/path") == "plain/path"


def test_env_var_path_is_usable_in_a_real_verify(tmp_path):
    import os as _os
    monkeypatch_dir = str(tmp_path)
    _os.environ["SENTINAL_TEST_VAR"] = monkeypatch_dir
    try:
        t = el.load_external_tasks(_write(tmp_path, [
            {"id": "e1", "source": "s", "category": "c", "prompt": "x",
             "verify": {"kind": "file_absent", "path": "%SENTINAL_TEST_VAR%/nope.txt"}}]))[0]
        assert t.verify({}) is True  # the expanded path genuinely doesn't exist
    finally:
        _os.environ.pop("SENTINAL_TEST_VAR", None)


# ── run_benchmark.py wiring ──────────────────────────────────────────────

def test_summarize_splits_by_source():
    from benchmarks.run_benchmark import TaskResult, summarize
    rs = [
        TaskResult("a", "c", "p", True, 1.0, source="self-authored"),
        TaskResult("b", "c", "p", False, 1.0, source="self-authored",
                   failure_reason="effect_not_observed"),
        TaskResult("c", "c", "p", True, 1.0, source="example:web"),
        TaskResult("d", "c", "p", True, 1.0, source="example:web"),
    ]
    bs = summarize(rs, 1)["by_source"]
    assert bs["self-authored"] == {"passed": 1, "total": 2, "rate": 0.5}
    assert bs["example:web"] == {"passed": 2, "total": 2, "rate": 1.0}


def test_taskresult_source_defaults_to_self_authored():
    from benchmarks.run_benchmark import TaskResult
    assert TaskResult("a", "c", "p", True, 1.0).source == "self-authored"
