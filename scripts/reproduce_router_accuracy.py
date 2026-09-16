"""
scripts/reproduce_router_accuracy.py — one command, no API keys, no network.

Reproduces the intent-router accuracy number: every request runs through the
REAL classifier + embedding model (agentic_core/router.py) against the full,
committed eval/intent_dataset.json, exhaustively (no sampling). Nothing here
calls an LLM, so there is nothing to configure — no Groq key, no Ollama, no
Deepgram, no Tavily, no network of any kind.

This is a thin, discoverable wrapper — the real, already-built, already-
documented instrument is eval/measure_intent_accuracy.py (every accuracy
number in this repo's docs traces back to a run of it). This just gives it
one obvious command and a timestamped run id so repeat runs don't overwrite
each other's report.

Usage:
    python scripts/reproduce_router_accuracy.py
    python scripts/reproduce_router_accuracy.py --run-id my-label

Exit code matches eval.measure_intent_accuracy's own.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", default=None,
                    help="report label (default: a UTC timestamp)")
    ap.add_argument("--dataset", default=None,
                    help="override eval/intent_dataset.json")
    args = ap.parse_args()

    run_id = args.run_id or datetime.now(UTC).strftime("repro_%Y%m%dT%H%M%SZ")

    cmd = [
        sys.executable, "-m", "eval.measure_intent_accuracy",
        "--mode", "router-only", "--run-id", run_id,
    ]
    if args.dataset:
        cmd += ["--dataset", args.dataset]

    print("No API keys / network required. Running:")
    print("  " + " ".join(cmd))
    print()

    # unset the usual cloud keys for the child process too, so a report from
    # this script can never be quietly explained by "it had a key after all"
    env = {k: v for k, v in os.environ.items()
           if k not in ("GROQ_API_KEY", "DEEPGRAM_API_KEY", "TAVILY_API_KEY", "OPENAI_API_KEY")}

    return subprocess.run(cmd, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
