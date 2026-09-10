"""
benchmarks/external_loader.py — load externally-authored benchmark tasks.

`benchmarks/tasks.py` is written by this project. This loader lets a task set
authored by someone else — an advisor, a reviewer, or lifted from a public
agent benchmark — run through the SAME harness and the SAME
independent-of-pipeline verification, without anyone writing Python.

A manifest is JSON: a list of task objects. Each becomes a real
`benchmarks.tasks.Task`, with its `verify` / `setup` / `teardown` built from a
declarative spec whose every `kind` dispatches to a helper that ALREADY EXISTS
in tasks.py. No new verification logic — external tasks are held to exactly the
same "query the OS, never the pipeline" standard.

    task := {
      "id":       str, unique within the manifest,
      "source":   str, where the task/prompt came from (audit trail),
      "category": str,
      "prompt":   str,
      "verify":   {"kind": ..., ...},
      "setup":    {"kind": ..., ...}   optional,
      "teardown": {"kind": ..., ...}   optional,
      "settle_seconds": float          optional (default 8.0),
      "tags":     [str]                optional,
      "verify_adapted": bool           optional — set when the original
                                       benchmark's own checker was not portable
                                       and one of our verify kinds was
                                       substituted; recorded, not hidden.
    }

`{scratch}` anywhere in a path is replaced with a fresh per-run temp directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Any

from benchmarks.tasks import (
    Task,
    _blocked,
    _browser_on_site,
    _process_running,
    _registry_value,
    _scheduler_task_persisted,
    _scratch_dir,
    _window_matching,
)


class ManifestError(ValueError):
    """A manifest is malformed: unknown kind, missing field, duplicate id."""


# ── {scratch} binding ─────────────────────────────────────────────────────────

def _resolve(value: Any) -> Any:
    if isinstance(value, str) and "{scratch}" in value:
        return value.replace("{scratch}", _scratch_dir())
    return value


def _need(spec: dict, key: str, tid: str) -> Any:
    if key not in spec:
        raise ManifestError(f"task '{tid}': '{key}' is required in {spec!r}")
    return spec[key]


# ── verify kinds → tasks.py helpers ──────────────────────────────────────────
# Each returns a predicate(result_dict) -> bool. The pipeline's own result is
# passed in but only the safety kinds look at it; everything else queries the OS.

def _build_verify(spec: dict, tid: str):
    kind = _need(spec, "kind", tid)

    if kind == "process_running":
        name = _need(spec, "name", tid)
        return lambda r: _process_running(name)
    if kind == "process_not_running":
        name = _need(spec, "name", tid)
        return lambda r: not _process_running(name)
    if kind == "window_titled":
        frag = _need(spec, "contains", tid)
        return lambda r: _window_matching(frag)
    if kind == "browser_on_site":
        domain = _need(spec, "domain", tid)
        return lambda r: _browser_on_site(domain)
    if kind == "file_exists":
        path = _resolve(_need(spec, "path", tid))
        return lambda r: os.path.isfile(path)
    if kind == "file_absent":
        path = _resolve(_need(spec, "path", tid))
        return lambda r: not os.path.exists(path)
    if kind == "file_contains":
        path = _resolve(_need(spec, "path", tid))
        text = _need(spec, "text", tid)
        return lambda r: os.path.isfile(path) and text in _read(path)
    if kind == "path_glob_recent":
        directory = _resolve(_need(spec, "dir", tid))
        pattern = _need(spec, "pattern", tid)
        within = float(spec.get("within_seconds", 120))
        return lambda r: _glob_recent(directory, pattern, within)
    if kind == "registry_value":
        key = _need(spec, "key", tid)
        name = _need(spec, "name", tid)
        equals = _need(spec, "equals", tid)
        return lambda r: _registry_value(key, name) == equals
    if kind == "sqlite_scheduler_row":
        keyword = _need(spec, "keyword", tid)
        return lambda r: r.get("execution") == "Success" and _scheduler_task_persisted(keyword)
    if kind == "response_refused":
        return _blocked
    if kind == "no_effect":
        # a protected path that must NOT have been created/touched
        path = _resolve(_need(spec, "path", tid))
        return lambda r: not os.path.exists(path)

    raise ManifestError(f"task '{tid}': unknown verify kind '{kind}'")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


def _glob_recent(directory: str, pattern: str, within: float) -> bool:
    import glob
    import time
    now = time.time()
    for match in glob.glob(os.path.join(directory, pattern)):
        try:
            if now - os.path.getmtime(match) <= within:
                return True
        except OSError:
            continue
    return False


# ── setup / teardown kinds ──────────────────────────────────────────────────

def _build_side_effect(spec: dict | None, tid: str):
    if not spec:
        return None
    kind = _need(spec, "kind", tid)

    if kind == "none":
        return None
    if kind == "make_temp_dir":
        return lambda: os.makedirs(_scratch_dir(), exist_ok=True)
    if kind == "write_file":
        rel = _need(spec, "path_rel", tid)
        content = spec.get("content", "external benchmark fixture\n")
        def _write(rel=rel, content=content):
            path = os.path.join(_scratch_dir(), rel)
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        return _write
    if kind == "delete_path":
        path = _resolve(_need(spec, "path", tid))
        def _delete(path=path):
            import shutil
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
        return _delete
    if kind == "spawn_process":
        cmd = _need(spec, "cmd", tid)
        def _spawn(cmd=cmd):
            try:
                subprocess.Popen(cmd, shell=isinstance(cmd, str),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
        return _spawn

    raise ManifestError(f"task '{tid}': unknown setup/teardown kind '{kind}'")


# ── manifest → [Task] ───────────────────────────────────────────────────────

_REQUIRED = ("id", "source", "category", "prompt", "verify")


def load_external_tasks(manifest_path: str) -> list[Task]:
    """Parse one JSON manifest into real Task objects. Raises ManifestError on
    any structural problem — a manifest typo must never pass silently."""
    with open(manifest_path, encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list):
        raise ManifestError(f"{manifest_path}: top level must be a JSON list of tasks")

    seen: set[str] = set()
    tasks: list[Task] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ManifestError(f"{manifest_path}: task #{i} is not an object")
        tid = entry.get("id") or f"<#{i}>"
        for field_name in _REQUIRED:
            if field_name not in entry:
                raise ManifestError(f"task '{tid}': missing required field '{field_name}'")
        if tid in seen:
            raise ManifestError(f"{manifest_path}: duplicate task id '{tid}'")
        seen.add(tid)

        task = Task(
            id=str(tid),
            category=str(entry["category"]),
            prompt=_resolve(str(entry["prompt"])),
            verify=_build_verify(entry["verify"], tid),
            setup=_build_side_effect(entry.get("setup"), tid),
            teardown=_build_side_effect(entry.get("teardown"), tid),
            notes=f"external:{entry['source']}"
                  + ("  [verify adapted]" if entry.get("verify_adapted") else ""),
            settle_seconds=float(entry.get("settle_seconds", 8.0)),
            tags=list(entry.get("tags", [])) + ["external"],
        )
        # stash the source on the object for the harness's by-source report
        task.source = str(entry["source"])  # type: ignore[attr-defined]
        tasks.append(task)

    return tasks


def load_external_dir(directory: str) -> list[Task]:
    """Load every *.json manifest in a directory, sorted by filename."""
    out: list[Task] = []
    for name in sorted(os.listdir(directory)):
        if name.endswith(".json"):
            out.extend(load_external_tasks(os.path.join(directory, name)))
    return out


def manifest_fingerprint(path: str) -> dict:
    """{path, sha256} — recorded in a run's provenance so an external score
    pins exactly which tasks produced it."""
    try:
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        digest = "unreadable"
    return {"path": os.path.abspath(path), "sha256": digest}


__all__ = [
    "ManifestError",
    "load_external_dir",
    "load_external_tasks",
    "manifest_fingerprint",
]
