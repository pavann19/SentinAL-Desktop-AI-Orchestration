"""Reject incomplete, skipped, cancelled, or failed required CI jobs."""
from __future__ import annotations

import json
import os
import sys


def unsuccessful_jobs(results: object) -> list[str]:
    if not isinstance(results, dict) or not results:
        raise ValueError("Required job results must be a non-empty object.")
    return [
        name for name, details in results.items()
        if not isinstance(details, dict) or details.get("result") != "success"
    ]


def main() -> int:
    try:
        failed = unsuccessful_jobs(json.loads(os.environ.get("CI_RESULTS", "")))
    except (ValueError, TypeError) as exc:
        print(f"Invalid CI result input: {exc}", file=sys.stderr)
        return 1
    if failed:
        print("Required jobs did not succeed: " + ", ".join(failed), file=sys.stderr)
        return 1
    print("Every required job succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
