"""
Latency aggregation for the thesis Evaluation chapter (§7.2 End-to-End Latency).

Reads the OpenTelemetry trace files produced by the P1-3 tracing layer
(agentic_core/tracing.py writes one JSON span-tree per process_command call
into logs/traces/) and aggregates per-stage duration distributions:
percentiles (p50/p90/p95/p99), min/max/mean, and the raw sorted samples that
a plotting tool can turn into a CDF.

This is pure data aggregation — it does NOT run the pipeline or call any LLM.
It only reads already-emitted trace files, so it is safe, offline, and
deterministic given a fixed set of trace files.

Usage:
    python -m eval.latency_report                         # reads logs/traces/
    python -m eval.latency_report --traces-dir <dir> \
        --out _evidence/latency/latency_report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACES_DIR = ROOT / "logs" / "traces"
DEFAULT_OUT = ROOT / "_evidence" / "latency" / "latency_report.json"

# The pipeline stage span names produced by P1-3 tracing (agentic_core/tracing.py
# TRACE_ROOT_NAME + the three wrapped call sites in api_wrapper.py).
ROOT_SPAN = "pipeline.process_command"
STAGE_SPANS = ("extract_intent", "validate_steps", "execute_pipeline")


def _percentile(sorted_samples: list[float], pct: float) -> float:
    """Nearest-rank percentile. sorted_samples must be pre-sorted ascending."""
    if not sorted_samples:
        return 0.0
    if pct <= 0:
        return sorted_samples[0]
    if pct >= 100:
        return sorted_samples[-1]
    # nearest-rank: ceil(pct/100 * N) - 1, clamped
    rank = int(-(-pct / 100 * len(sorted_samples) // 1)) - 1  # ceil via //
    rank = max(0, min(rank, len(sorted_samples) - 1))
    return sorted_samples[rank]


def _summarize(samples: list[float]) -> dict[str, Any]:
    if not samples:
        return {"count": 0}
    s = sorted(samples)
    return {
        "count": len(s),
        "min_ms": round(s[0], 3),
        "max_ms": round(s[-1], 3),
        "mean_ms": round(sum(s) / len(s), 3),
        "p50_ms": round(_percentile(s, 50), 3),
        "p90_ms": round(_percentile(s, 90), 3),
        "p95_ms": round(_percentile(s, 95), 3),
        "p99_ms": round(_percentile(s, 99), 3),
        # Raw sorted samples for CDF plotting (rounded to keep the file small).
        "sorted_samples_ms": [round(x, 3) for x in s],
    }


def _walk_spans(node: dict, by_name: dict[str, list[float]]) -> None:
    """Collect duration_ms for every span whose name we care about."""
    name = node.get("name")
    if name == ROOT_SPAN or name in STAGE_SPANS:
        dur = node.get("duration_ms")
        if isinstance(dur, (int, float)):
            by_name.setdefault(name, []).append(float(dur))
    for child in node.get("children", []):
        _walk_spans(child, by_name)


def aggregate(traces_dir: Path) -> dict[str, Any]:
    trace_files = sorted(traces_dir.glob("trace_*.json"))
    by_name: dict[str, list[float]] = {}
    ok_count = 0
    error_count = 0
    parse_failures = 0

    for tf in trace_files:
        try:
            doc = json.loads(tf.read_text(encoding="utf-8"))
        except Exception:
            parse_failures += 1
            continue
        root = doc.get("root")
        if not isinstance(root, dict):
            parse_failures += 1
            continue
        if root.get("status") == "ERROR":
            error_count += 1
        else:
            ok_count += 1
        _walk_spans(root, by_name)

    return {
        "traces_dir": str(traces_dir),
        "trace_files_found": len(trace_files),
        "parse_failures": parse_failures,
        "root_status_counts": {"OK": ok_count, "ERROR": error_count},
        "note": (
            "Durations include BOTH successful and errored runs. For a clean "
            "latency picture, filter by root status in a follow-up pass — an "
            "ERROR root (e.g. LLM extraction failure) is typically much faster "
            "than a successful cloud round-trip and will skew the low end."
        ),
        "stages": {name: _summarize(by_name.get(name, [])) for name in (ROOT_SPAN, *STAGE_SPANS)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate P1-3 trace files into latency distributions.")
    parser.add_argument("--traces-dir", type=Path, default=DEFAULT_TRACES_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.traces_dir.exists():
        print(f"No traces directory at {args.traces_dir} — run the pipeline first to emit traces.")
        return 1

    report = aggregate(args.traces_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Traces read: {report['trace_files_found']} "
          f"(OK={report['root_status_counts']['OK']}, "
          f"ERROR={report['root_status_counts']['ERROR']}, "
          f"parse_failures={report['parse_failures']})")
    print(f"Report written: {args.out}\n")
    print(f"{'stage':<24} {'count':>6} {'p50':>9} {'p90':>9} {'p95':>9} {'p99':>9} {'max':>10}")
    for name in (ROOT_SPAN, *STAGE_SPANS):
        s = report["stages"][name]
        if s.get("count"):
            print(f"{name:<24} {s['count']:>6} {s['p50_ms']:>9} {s['p90_ms']:>9} "
                  f"{s['p95_ms']:>9} {s['p99_ms']:>9} {s['max_ms']:>10}")
        else:
            print(f"{name:<24} {'0':>6}   (no samples)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
