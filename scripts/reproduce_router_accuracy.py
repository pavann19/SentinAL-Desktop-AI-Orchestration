"""Run exhaustive artifact-free router evaluation with cloud credentials unset.

First use downloads the pinned embedding model. Cached weights permit offline
execution. Generated reports are ignored; locally trained classifiers change mode.
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

    print("No cloud API keys required; embedding weights must be cached for offline use. Running:")
    print("  " + " ".join(cmd))
    print()

    # unset the usual cloud keys for the child process too, so a report from
    # this script can never be quietly explained by "it had a key after all"
    env = {k: v for k, v in os.environ.items()
           if k not in ("GROQ_API_KEY", "DEEPGRAM_API_KEY", "TAVILY_API_KEY", "OPENAI_API_KEY")}

    return subprocess.run(cmd, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
