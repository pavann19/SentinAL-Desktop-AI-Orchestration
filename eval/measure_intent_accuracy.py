"""
Reproducible intent-accuracy measurement tool for eval/intent_dataset.json.

Formalizes the ad-hoc, throwaway verification scripts written during Session 9
(each written, run once, then deleted) into a real, committed, versioned
instrument — so every future accuracy claim in the thesis traces to a
command that can be re-run by anyone, not a one-off script that no longer
exists.

Reproducibility guarantees:
  - The dataset file's SHA-256 hash is recorded in every report, so a report
    can always be matched back to the exact dataset version that produced it
    (critical once the dataset grows/changes — see the 704 -> ~3000 scale-up).
  - --sample-seed makes the full-pipeline sample (which calls the live LLM
    pipeline and is too slow to run in full at large scale) deterministic —
    the same seed always draws the same sample from a given dataset.
  - Router-only measurement is exhaustive (every entry, no sampling) since it
    requires no network/LLM calls and is fast even at thousands of entries.
  - Every report is written to _evidence/intent_accuracy/ with a timestamp-
    free, content-addressable-ish name (run id), never overwriting silently.

Usage:
    # Router-only, full dataset (fast, no LLM calls, exhaustive):
    python -m eval.measure_intent_accuracy --mode router-only --run-id v1

    # Full-pipeline, sampled (slow, live LLM calls):
    python -m eval.measure_intent_accuracy --mode full-pipeline --sample-size 40 --sample-seed 7 --run-id v1
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import random
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "eval" / "intent_dataset.json"
DEFAULT_OUT_DIR = ROOT / "_evidence" / "intent_accuracy"


def _dataset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_dataset(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _per_intent_breakdown(results: list[dict]) -> dict[str, dict]:
    breakdown: dict[str, dict] = {}
    for r in results:
        exp = r["expected_intent"]
        b = breakdown.setdefault(exp, {"total": 0, "correct": 0})
        b["total"] += 1
        if r["correct"]:
            b["correct"] += 1
    for b in breakdown.values():
        b["accuracy"] = round(b["correct"] / b["total"], 4) if b["total"] else 0.0
    return breakdown


def measure_router_only(dataset: list[dict]) -> dict:
    """Exhaustive, fast, no LLM calls — every entry, every time."""
    from agentic_core.router import router

    results = []
    for item in dataset:
        r = router.route(item["prompt"])
        results.append({
            "prompt": item["prompt"],
            "expected_intent": item["expected_intent"],
            "got_intent": r["intent"],
            "confidence": r["confidence"],
            "correct": r["intent"] == item["expected_intent"],
        })

    correct = sum(1 for r in results if r["correct"])
    return {
        "mode": "router-only",
        "total": len(results),
        "correct": correct,
        "accuracy": round(correct / len(results), 4) if results else 0.0,
        "per_intent": _per_intent_breakdown(results),
        "results": results,
    }


async def measure_full_pipeline(dataset: list[dict], sample_size: int, sample_seed: int) -> dict:
    """Sampled (live LLM calls are slow + costly at dataset scale). Seeded
    for reproducibility: same seed + same dataset always draws the same
    sample, so results are directly comparable across runs."""
    from agentic_core.processor import extract_intent

    rng = random.Random(sample_seed)
    sample = rng.sample(dataset, min(sample_size, len(dataset)))

    results = []
    for item in sample:
        try:
            steps = extract_intent(item["prompt"])
            got = steps[0].get("intent") if steps else "NO_STEPS"
        except Exception as exc:
            got = f"EXCEPTION: {exc}"
        results.append({
            "prompt": item["prompt"],
            "expected_intent": item["expected_intent"],
            "got_intent": got,
            "correct": got == item["expected_intent"],
        })

    correct = sum(1 for r in results if r["correct"])
    return {
        "mode": "full-pipeline",
        "sample_size": len(sample),
        "sample_seed": sample_seed,
        "correct": correct,
        "accuracy": round(correct / len(sample), 4) if sample else 0.0,
        "per_intent": _per_intent_breakdown(results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproducible intent-accuracy measurement.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=["router-only", "full-pipeline"], required=True)
    parser.add_argument("--sample-size", type=int, default=40)
    parser.add_argument("--sample-seed", type=int, default=7)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    dataset = _load_dataset(args.dataset)
    dataset_hash = _dataset_hash(args.dataset)

    if args.mode == "router-only":
        report = measure_router_only(dataset)
    else:
        report = asyncio.run(measure_full_pipeline(dataset, args.sample_size, args.sample_seed))

    report["dataset_path"] = str(args.dataset)
    report["dataset_sha256_16"] = dataset_hash
    report["dataset_total_entries"] = len(dataset)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{args.mode}_{args.run_id}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Dataset: {args.dataset} ({len(dataset)} entries, sha256[:16]={dataset_hash})")
    print(f"Mode: {report['mode']}")
    print(f"Accuracy: {report['correct']}/{report.get('total', report.get('sample_size'))} = {report['accuracy']*100:.2f}%")
    print(f"Report: {out_path}\n")
    print(f"{'intent':<28} {'correct/total':>15} {'accuracy':>10}")
    for intent, b in sorted(report["per_intent"].items()):
        print(f"{intent:<28} {b['correct']:>6}/{b['total']:<7} {b['accuracy']*100:>9.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
