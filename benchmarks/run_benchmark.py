"""
benchmarks/run_benchmark.py — SentinAL end-to-end task benchmark harness.

Measures the metric that actually matters and that unit tests cannot reach:
given a real user request, does the system accomplish the real-world effect?

    python benchmarks/run_benchmark.py                    # full suite
    python benchmarks/run_benchmark.py --category app_launch
    python benchmarks/run_benchmark.py --repeat 3         # flakiness measurement
    python benchmarks/run_benchmark.py --dry-run          # list tasks, execute nothing

── Reproducibility contract ─────────────────────────────────────────────────
Every run writes a JSON report containing the exact conditions that produced
it: git commit, dirty-tree flag, OS build, Python version, resolved model names,
and the config env vars that change behaviour. A number from this harness is
only quotable alongside that block — reported without it, it is not reproducible
and therefore not defensible.

Two properties make the score honest:

  1. Verification is independent of the pipeline. Pass/fail comes from querying
     the OS (process table, filesystem, window list), never from the pipeline's
     own success report. This exists because three capabilities were recently
     found returning fabricated success strings — a harness that trusted
     self-reports would have scored all three as passing.

  2. Nothing is retried or excluded to improve the number. Failures are recorded
     with their reason. --repeat measures flakiness; it does NOT take the best
     run. A task that passes 1 of 3 times is reported as 33%, not as a pass.

Real desktop effects need a real desktop, so this cannot run on a headless CI
runner. That is a property of what is being measured, not a gap in the harness.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from benchmarks.tasks import Task, _cleanup_scratch, build_tasks, prompt_for

REPORT_DIR = os.path.join(os.path.dirname(__file__), "results")


# ══════════════════════════════════════════════════════════════════════════════
# Provenance — what makes a number reproducible
# ══════════════════════════════════════════════════════════════════════════════
def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=os.path.join(os.path.dirname(__file__), ".."),
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return "unknown"


def capture_environment() -> dict:
    """Everything needed to reproduce a run. If any of this differs, the numbers
    are not comparable — which is exactly why it is recorded rather than assumed."""
    dirty = _git("status", "--porcelain")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        # A dirty tree means the commit hash does NOT identify the code that ran.
        # Surfaced loudly rather than buried, since it invalidates comparability.
        "working_tree_dirty": bool(dirty),
        "uncommitted_files": len(dirty.splitlines()) if dirty else 0,
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "python": sys.version.split()[0],
        "hostname": platform.node(),
        "config": {
            k: os.getenv(k)
            for k in (
                "LLM_PROVIDER", "OLLAMA_MODEL", "OLLAMA_VISION_MODEL",
                "EXECUTOR_STEP_DELAY", "EXECUTOR_MAX_REPLANS",
                "GUI_FOCUS_WAIT", "OBSERVER_BROWSER_SETTLE_MS",
            )
            if os.getenv(k) is not None
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# Results
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class TaskResult:
    task_id: str
    category: str
    prompt: str
    passed: bool
    duration_s: float
    pipeline_execution: str = ""
    pipeline_response: str = ""
    pipeline_intents: list[str] = field(default_factory=list)
    replanned: bool = False
    failure_reason: str = ""
    error: str = ""


def _verify_with_settle(task: Task, result: dict) -> bool:
    """Re-checks until the effect appears or the settle window expires. Same
    reasoning as the observer's settle poll: a browser or process start is not
    instantaneous, and calling it failed too early measures our impatience
    rather than the system."""
    deadline = time.time() + task.settle_seconds
    while True:
        # A raising verify() means "cannot confirm yet" (e.g. the window list is
        # momentarily unavailable), not "failed" — so it is suppressed and
        # retried until the deadline, at which point the task fails normally.
        with contextlib.suppress(Exception):
            if task.verify(result):
                return True
        if time.time() >= deadline:
            return False
        time.sleep(0.5)


async def run_task(task: Task) -> TaskResult:
    from capabilities.system.api_wrapper import process_command

    started = time.time()

    # setup() BEFORE prompt_for(): the world a prompt refers to must exist
    # before the prompt is formed. Prompts are resolved at build time now, so
    # this no longer matters for correctness — but the previous ordering is
    # exactly what let the file_ops prompts reference a path that setup had not
    # created yet, so the safe order is made explicit rather than left to luck.
    if task.setup:
        try:
            task.setup()
        except Exception as e:
            return TaskResult(
                task_id=task.id, category=task.category, prompt=prompt_for(task),
                passed=False, duration_s=0.0,
                error=f"setup failed: {e}", failure_reason="setup_error",
            )

    prompt = prompt_for(task)

    pipeline: dict = {}
    error = ""
    try:
        pipeline = await process_command(prompt)
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    passed = False if error else _verify_with_settle(task, pipeline)

    # teardown always runs, including after a failure, so one bad task cannot
    # contaminate the next one's starting state. A failing teardown must not
    # mask the task's own result, so it is suppressed rather than raised.
    if task.teardown:
        with contextlib.suppress(Exception):
            task.teardown()

    reason = ""
    if not passed:
        if error:
            reason = "pipeline_exception"
        elif pipeline.get("validation") == "Denied":
            reason = "blocked_by_validator"
        elif str(pipeline.get("response", "")).upper().startswith("ERROR"):
            reason = "pipeline_reported_error"
        elif pipeline.get("execution") == "Success":
            # The pipeline said it worked; the OS says otherwise. This is the
            # silent-failure class the postcondition work exists to eliminate,
            # and the single most valuable signal this harness produces.
            reason = "false_success"
        else:
            reason = "effect_not_observed"

    return TaskResult(
        task_id=task.id, category=task.category, prompt=prompt, passed=passed,
        duration_s=round(time.time() - started, 2),
        pipeline_execution=str(pipeline.get("execution", "")),
        pipeline_response=str(pipeline.get("response", ""))[:300],
        pipeline_intents=[s.get("intent", "") for s in pipeline.get("steps", []) if isinstance(s, dict)],
        replanned=bool(pipeline.get("replanned", False)),
        failure_reason=reason, error=error,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Scoring
# ══════════════════════════════════════════════════════════════════════════════
def wilson_interval(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a binomial proportion.

    Reported because a bare percentage from a few dozen trials is not a
    defensible figure: 16/17 and 160/170 are both "94%" but support very
    different claims. Wilson rather than the normal approximation because the
    latter misbehaves badly near 0 and 1 — exactly where a good agent's scores
    sit — and can produce bounds outside [0, 1].
    """
    if total == 0:
        return (0.0, 0.0)
    p = passed / total
    denom = 1 + z**2 / total
    centre = (p + z**2 / (2 * total)) / denom
    margin = z * ((p * (1 - p) / total + z**2 / (4 * total**2)) ** 0.5) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def summarize(results: list[TaskResult], repeat: int) -> dict:
    by_task: dict[str, list[TaskResult]] = {}
    for r in results:
        by_task.setdefault(r.task_id, []).append(r)

    # With --repeat, a task's score is its PASS RATE, not its best run. Taking
    # the best would report a flaky task as solid, which is the most common way
    # a benchmark quietly overstates a system.
    task_rates = {tid: sum(r.passed for r in rs) / len(rs) for tid, rs in by_task.items()}

    categories: dict[str, dict] = {}
    for r in results:
        c = categories.setdefault(r.category, {"passed": 0, "total": 0})
        c["total"] += 1
        c["passed"] += int(r.passed)
    for c in categories.values():
        c["rate"] = round(c["passed"] / c["total"], 4) if c["total"] else 0.0

    flaky = {t: round(rate, 4) for t, rate in task_rates.items() if 0 < rate < 1}
    false_successes = [r.task_id for r in results if r.failure_reason == "false_success"]

    total = len(results)
    passed = sum(r.passed for r in results)
    lo, hi = wilson_interval(passed, total)

    return {
        "overall_rate": round(passed / total, 4) if total else 0.0,
        "ci95_low": round(lo, 4),
        "ci95_high": round(hi, 4),
        "passed": passed,
        "total": total,
        "unique_tasks": len(by_task),
        "repeat": repeat,
        # Tasks that passed EVERY repeat. The honest headline for "what can this
        # system be relied on to do", since a task that works 2 times in 3 is not
        # something a user would call working.
        "fully_reliable_tasks": sum(1 for rate in task_rates.values() if rate == 1.0),
        "by_category": categories,
        "flaky_tasks": flaky,
        # Called out separately because it is the defect class this whole effort
        # targets: the pipeline reported success while the OS disagreed.
        "false_success_tasks": sorted(set(false_successes)),
        "failure_reasons": {
            reason: sum(1 for r in results if r.failure_reason == reason)
            for reason in sorted({r.failure_reason for r in results if r.failure_reason})
        },
    }


def print_report(summary: dict, results: list[TaskResult], env: dict) -> None:
    w = 74
    print("\n" + "=" * w)
    print("SentinAL Task Benchmark".center(w))
    print("=" * w)
    print(f"commit   {env['commit'][:12]} ({env['branch']})"
          + ("  ** WORKING TREE DIRTY **" if env["working_tree_dirty"] else ""))
    print(f"os       {env['os']}")
    print(f"python   {env['python']}")
    print("-" * w)

    for r in sorted(results, key=lambda x: (x.category, x.task_id)):
        mark = "PASS" if r.passed else "FAIL"
        extra = f"  [{r.failure_reason}]" if r.failure_reason else ""
        print(f"  {mark}  {r.task_id:<26} {r.duration_s:>6.1f}s{extra}")

    print("-" * w)
    print(f"  OVERALL   {summary['passed']}/{summary['total']} "
          f"= {summary['overall_rate'] * 100:.1f}%"
          f"   (95% CI {summary['ci95_low'] * 100:.1f}–{summary['ci95_high'] * 100:.1f}%)")
    if summary["repeat"] > 1:
        print(f"  RELIABLE  {summary['fully_reliable_tasks']}/{summary['unique_tasks']} "
              f"tasks passed all {summary['repeat']} runs")
    print("\n  By category:")
    for cat, c in sorted(summary["by_category"].items()):
        print(f"    {cat:<20} {c['passed']:>3}/{c['total']:<3} = {c['rate'] * 100:5.1f}%")

    if summary["false_success_tasks"]:
        print("\n  ** FALSE SUCCESSES — pipeline claimed success, OS disagreed:")
        for t in summary["false_success_tasks"]:
            print(f"      {t}")

    if summary["flaky_tasks"]:
        print("\n  Flaky (scored as pass rate, not best run):")
        for t, rate in sorted(summary["flaky_tasks"].items()):
            print(f"      {t:<26} {rate * 100:.0f}%")

    if summary["failure_reasons"]:
        print("\n  Failure breakdown:")
        for reason, n in sorted(summary["failure_reasons"].items(), key=lambda kv: -kv[1]):
            print(f"      {reason:<26} {n}")
    print("=" * w + "\n")


# ══════════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="SentinAL end-to-end task benchmark")
    ap.add_argument("--category", help="run only one category")
    ap.add_argument("--task", help="run a single task by id")
    ap.add_argument("--repeat", type=int, default=1, help="runs per task (measures flakiness)")
    ap.add_argument("--dry-run", action="store_true", help="list tasks without executing")
    ap.add_argument("--output", help="report path (default: benchmarks/results/<timestamp>.json)")
    args = ap.parse_args()

    tasks = build_tasks()
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]
    if args.task:
        tasks = [t for t in tasks if t.id == args.task]

    if not tasks:
        print("No tasks matched.", file=sys.stderr)
        return 2

    if args.dry_run:
        print(f"\n{len(tasks)} task(s):\n")
        for t in tasks:
            print(f"  [{t.category}] {t.id}\n      {prompt_for(t)!r}")
        print()
        return 0

    env = capture_environment()
    if env["working_tree_dirty"]:
        print(f"\nWARNING: {env['uncommitted_files']} uncommitted file(s). "
              "The commit hash does not identify the code being measured, so "
              "this run is not reproducible and must not be quoted.\n", file=sys.stderr)

    print(f"\nRunning {len(tasks)} task(s) x{args.repeat} against the real system...")
    print("This drives real applications — avoid using the machine while it runs.\n")

    results: list[TaskResult] = []
    try:
        for rep in range(args.repeat):
            for i, task in enumerate(tasks, 1):
                label = f"[{rep + 1}/{args.repeat}] {i}/{len(tasks)} {task.id}"
                print(f"  {label} ... ", end="", flush=True)
                r = asyncio.run(run_task(task))
                results.append(r)
                print(f"{'PASS' if r.passed else 'FAIL'} ({r.duration_s:.1f}s)")
    except KeyboardInterrupt:
        print("\nInterrupted — reporting partial results.\n", file=sys.stderr)
    finally:
        _cleanup_scratch()

    summary = summarize(results, args.repeat)
    print_report(summary, results, env)

    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = args.output or os.path.join(REPORT_DIR, f"benchmark_{stamp}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "schema": 1,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "environment": env,
            "summary": summary,
            "results": [asdict(r) for r in results],
        }, fh, indent=2)
    print(f"Report written to {path}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
