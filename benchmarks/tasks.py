"""
benchmarks/tasks.py — the SentinAL task benchmark suite.

Every task here is a REAL user-phrased request executed against the real
pipeline on a real machine. Nothing is synthetic: there are no generated
prompts, no mocked capabilities, and no fabricated outcomes. A task passes only
if an independent check of actual system state says it did.

── Why the checks are independent of the pipeline ───────────────────────────
A benchmark that scored a task by asking the pipeline whether it succeeded
would measure the pipeline's self-report, not its behaviour — exactly the
failure this suite exists to catch (three capabilities were recently found
returning fabricated success strings). So every `verify` below queries the OS
directly: the process table, the filesystem, the window list. The pipeline's
own response string is recorded for the report but never decides pass/fail.

── Task design rules ────────────────────────────────────────────────────────
1. Non-destructive: nothing touches user data. File tasks operate inside a
   per-run temp directory that `setup` creates and `teardown` removes.
2. Self-cleaning: `teardown` runs even when the task fails, so a failed run
   never contaminates the next one.
3. Phrased as a user would speak them, including the sloppy ones — the router
   is part of what's under test, so over-clean prompts would inflate the score.
4. `expected_to_pass=False` marks a task the system is KNOWN not to handle
   (an unimplemented capability). These are scored separately: they measure
   honest refusal, not capability, and must not be silently counted as failures
   that look like regressions.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field

# Category constants — reported per-category so a low overall score can be
# traced to which capability class is actually weak.
CAT_APP = "app_launch"
CAT_WEB = "web_navigation"
CAT_FILE = "file_ops"
CAT_PROC = "process_mgmt"
CAT_CONV = "conversational"
CAT_SYS = "system_utility"
CAT_UNIMPL = "unimplemented"


@dataclass
class Task:
    id: str
    category: str
    prompt: str
    verify: Callable[[dict], bool]
    setup: Callable[[], None] | None = None
    teardown: Callable[[], None] | None = None
    expected_to_pass: bool = True
    notes: str = ""
    # Some effects (a browser rendering, a process starting) are not instant.
    # The harness waits up to this long, re-checking, before calling it failed —
    # same rationale as the observer's settle window.
    settle_seconds: float = 8.0
    tags: list[str] = field(default_factory=list)


# ── Verification helpers (query the OS, never the pipeline) ──────────────────

def _process_running(name: str) -> bool:
    try:
        import psutil
        needle = name.lower()
        return any(needle in (p.info["name"] or "").lower()
                   for p in psutil.process_iter(["name"]))
    except Exception:
        return False


def _kill_process(name: str) -> None:
    # check=False: the process may already be gone (the task under test may have
    # closed it, which is the passing case for proc_kill_notepad). A non-zero
    # taskkill exit is expected there, not an error worth surfacing.
    with contextlib.suppress(Exception):
        subprocess.run(["taskkill", "/F", "/IM", name],
                       capture_output=True, timeout=10, check=False)


def _window_matching(fragment: str) -> bool:
    try:
        import pygetwindow as gw
        return bool(gw.getWindowsWithTitle(fragment))
    except Exception:
        return False


def _response_is_substantive(result: dict, min_words: int = 3) -> bool:
    """For conversational tasks there is no system state to check, so the only
    honest check is that a real answer came back and the pipeline did not report
    an error. This is deliberately weak, and conversational tasks are reported
    as their own category so this weakness never silently props up the headline
    number."""
    if result.get("execution") not in ("Success",):
        return False
    text = str(result.get("response", "")).strip()
    return len(text.split()) >= min_words and not text.upper().startswith("ERROR")


# ── Per-run scratch directory ────────────────────────────────────────────────
_SCRATCH: dict[str, str] = {}


def _scratch_dir() -> str:
    if "path" not in _SCRATCH:
        _SCRATCH["path"] = tempfile.mkdtemp(prefix="sentinal_bench_")
    return _SCRATCH["path"]


def _cleanup_scratch() -> None:
    path = _SCRATCH.pop("path", None)
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _make_file(name: str) -> str:
    path = os.path.join(_scratch_dir(), name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("benchmark fixture\n")
    return path


# ── The suite ────────────────────────────────────────────────────────────────

def build_tasks() -> list[Task]:
    """Constructed per run so scratch paths are fresh each time."""
    tasks: list[Task] = []

    # ── Application launch ───────────────────────────────────────────────────
    for tid, prompt in [
        ("app_notepad_plain",    "open notepad"),
        ("app_notepad_casual",   "can you launch notepad for me"),
        ("app_calc_plain",       "open calculator"),
        ("app_calc_indirect",    "i need to do some math, open the calculator"),
        ("app_paint",            "open paint"),
    ]:
        exe = ("notepad.exe" if "notepad" in prompt else
               "calc" if "calc" in prompt.lower() or "math" in prompt else
               "mspaint.exe")
        probe = ("notepad" if "notepad" in prompt else
                 "calc" if "calc" in prompt.lower() or "math" in prompt else
                 "mspaint")
        tasks.append(Task(
            id=tid, category=CAT_APP, prompt=prompt,
            verify=lambda r, p=probe: _process_running(p)
                   or _window_matching("Calculator" if p == "calc" else p),
            teardown=lambda e=exe: _kill_process(e),
            notes="Windows Calculator runs as CalculatorApp.exe, so the window title is also checked.",
            tags=["gui"],
        ))

    # ── Web navigation ───────────────────────────────────────────────────────
    for tid, prompt, label in [
        ("web_github",   "open github",                       "github"),
        ("web_youtube",  "go to youtube",                     "youtube"),
        ("web_wikipedia", "open wikipedia in my browser",     "wikipedia"),
    ]:
        tasks.append(Task(
            id=tid, category=CAT_WEB, prompt=prompt,
            verify=lambda r, l=label: _window_matching(l),
            settle_seconds=12.0,
            notes="Known limitation: a pre-existing tab for the site also satisfies this.",
            tags=["network", "gui"],
        ))

    # ── File operations ──────────────────────────────────────────────────────
    del_path: dict[str, str] = {}

    def _setup_delete():
        del_path["p"] = _make_file("benchmark_delete_me.txt")

    tasks.append(Task(
        id="file_delete_absolute", category=CAT_FILE,
        prompt="",  # filled in by setup below via prompt_factory
        verify=lambda r: not os.path.exists(del_path.get("p", "")),
        setup=_setup_delete,
        notes="Prompt carries an absolute path inside the run's temp dir.",
        tags=["filesystem", "destructive-safe"],
    ))

    # ── Process management ───────────────────────────────────────────────────
    tasks.append(Task(
        id="proc_list", category=CAT_PROC,
        prompt="what processes are running",
        verify=lambda r: _response_is_substantive(r, min_words=2),
        notes="Read-only; scored on a substantive response since there is no state change.",
    ))

    tasks.append(Task(
        id="proc_kill_notepad", category=CAT_PROC,
        prompt="close notepad",
        verify=lambda r: not _process_running("notepad"),
        setup=lambda: subprocess.Popen(["notepad.exe"]) and time.sleep(2),
        teardown=lambda: _kill_process("notepad.exe"),
        tags=["gui"],
    ))

    # ── Conversational ───────────────────────────────────────────────────────
    for tid, prompt in [
        ("conv_greeting",  "hello, who are you"),
        ("conv_capability", "what can you do"),
        ("conv_followup",  "tell me more about that"),
    ]:
        tasks.append(Task(
            id=tid, category=CAT_CONV, prompt=prompt,
            verify=_response_is_substantive,
            notes="No system state to verify; weak check, reported separately.",
        ))

    # ── Known-unimplemented: must refuse honestly, not fabricate ─────────────
    for tid, prompt in [
        ("unimpl_reminder",  "remind me to submit my thesis tomorrow at 9am"),
        ("unimpl_research",  "analyze the attention is all you need paper"),
        ("unimpl_dataset",   "run an EDA on my sales.csv dataset"),
    ]:
        tasks.append(Task(
            id=tid, category=CAT_UNIMPL, prompt=prompt,
            # Passing here means the system correctly REFUSED. A fabricated
            # success is the failure condition — the inverse of every other task.
            verify=lambda r: str(r.get("response", "")).upper().startswith("ERROR")
                             or r.get("execution") == "Failed",
            expected_to_pass=True,
            notes="Scored on honest refusal. Regression guard for the fabricated-success defect.",
            tags=["honesty"],
        ))

    return tasks


def prompt_for(task: Task) -> str:
    """Late-bound prompts for tasks whose text depends on setup-created paths."""
    if task.id == "file_delete_absolute":
        return f"delete the file {_scratch_dir()}\\benchmark_delete_me.txt"
    return task.prompt


__all__ = ["Task", "_cleanup_scratch", "build_tasks", "prompt_for"]
