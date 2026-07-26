"""
Ablation study runner for the thesis Evaluation chapter (§7.1 routing / §7.5 privacy).

Runs the task-success harness (eval/harness.py) under several configurations by
temporarily disabling one subsystem at a time, so the thesis can report the
DELTA each subsystem contributes rather than just an absolute number:

  - baseline        : the system exactly as shipped
  - no_fast_path    : deterministic_fast_path() forced to return None, so every
                      prompt goes through the embedding router / LLM path
                      (evidence for RQ1 — the latency/accuracy value of the
                      deterministic fast-path)
  - privacy_all_local : privacy router forced to route every prompt local
                      (evidence for RQ2 — task-success delta when nothing is
                      allowed to use the cloud)

Each ablation is applied via monkeypatching at runtime and UNDONE immediately
after that configuration's run — the real code on disk is never modified, and
configurations do not leak into each other.

IMPORTANT: this runs the REAL pipeline, which makes live LLM/API calls for any
task that isn't handled by a fast-path or hardcoded bypass. It therefore needs
valid API keys / a reachable local model, and is slower than the offline
latency_report. Use --task-id to run a subset while iterating.

Usage:
    python -m eval.ablation --run-id demo --task-id conv-hello --task-id info-capital
    python -m eval.ablation --run-id full        # whole non-skip suite, all configs
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from eval.harness import run_suite
from eval.run_eval import load_tasks, _select_tasks, DEFAULT_TASKS_PATH

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = ROOT / "_evidence" / "ablation"


def _summarize(report: dict) -> dict:
    """Strip the heavy per-task 'raw' payloads; keep the comparison-relevant bits."""
    lat = [r["latency_ms"] for r in report["results"]]
    return {
        "total": report["total"],
        "passed": report["passed"],
        "failed": report["failed"],
        "success_rate": report["success_rate"],
        "mean_latency_ms": round(sum(lat) / len(lat), 3) if lat else 0.0,
        "per_task": [
            {"id": r["id"], "passed": r["passed"], "latency_ms": round(r["latency_ms"], 3),
             "reasons": r["reasons"]}
            for r in report["results"]
        ],
    }


async def _run_config(tasks: list[dict]) -> dict:
    return _summarize(await run_suite(tasks))


async def run_all(tasks: list[dict]) -> dict:
    import agentic_core.processor as processor
    import system_services.privacy_router as pr

    configs: dict[str, dict] = {}

    # ── baseline ──────────────────────────────────────────────────────────────
    configs["baseline"] = await _run_config(tasks)

    # ── no_fast_path ──────────────────────────────────────────────────────────
    original_fast_path = processor.deterministic_fast_path
    try:
        processor.deterministic_fast_path = lambda prompt: None
        configs["no_fast_path"] = await _run_config(tasks)
    finally:
        processor.deterministic_fast_path = original_fast_path

    # ── privacy_all_local ─────────────────────────────────────────────────────
    # Force the privacy guard to classify everything as "local". We patch the
    # instance method used by the pipeline (privacy_guard.analyze) rather than
    # the class, and restore it afterward.
    original_analyze = pr.privacy_guard.analyze
    try:
        def _all_local(query, *a, **k):
            return {"route": "local", "reason": "ABLATION: forced local", "sensitive": True}
        pr.privacy_guard.analyze = _all_local
        configs["privacy_all_local"] = await _run_config(tasks)
    finally:
        pr.privacy_guard.analyze = original_analyze

    # ── deltas vs baseline ────────────────────────────────────────────────────
    base = configs["baseline"]
    deltas = {}
    for name, cfg in configs.items():
        if name == "baseline":
            continue
        deltas[name] = {
            "success_rate_delta": round(cfg["success_rate"] - base["success_rate"], 4),
            "mean_latency_ms_delta": round(cfg["mean_latency_ms"] - base["mean_latency_ms"], 3),
        }

    return {"configs": configs, "deltas_vs_baseline": deltas}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SentinAL ablation study.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    parser.add_argument("--run-id", default="demo")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--include-skip-in-ci", action="store_true")
    args = parser.parse_args()

    all_tasks = load_tasks(args.tasks)
    tasks = _select_tasks(all_tasks, args.task_id, args.include_skip_in_ci)

    report = asyncio.run(run_all(tasks))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"ablation_{args.run_id}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Ablation report written: {out}\n")
    print(f"{'config':<20} {'passed':>8} {'success':>9} {'mean_lat_ms':>13}")
    for name, cfg in report["configs"].items():
        print(f"{name:<20} {str(cfg['passed'])+'/'+str(cfg['total']):>8} "
              f"{cfg['success_rate']:>9.3f} {cfg['mean_latency_ms']:>13.1f}")
    print("\nDeltas vs baseline:")
    for name, d in report["deltas_vs_baseline"].items():
        print(f"  {name:<18} success {d['success_rate_delta']:+.3f}   "
              f"mean_latency {d['mean_latency_ms_delta']:+.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
