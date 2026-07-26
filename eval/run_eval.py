"""CLI entry point for the SentinAL task-success benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from eval.harness import run_suite

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TASKS_PATH = ROOT / "eval" / "tasks.yaml"
DEFAULT_REPORT_DIR = ROOT / "_evidence" / "P1-5"


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value


def _load_yaml_fallback(path: Path) -> list[dict]:
    tasks: list[dict] = []
    current: dict[str, Any] | None = None

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("- "):
            if current is not None:
                tasks.append(current)
            current = {}
            line = line[2:].strip()
            if not line:
                continue

        if current is None or ":" not in line:
            raise ValueError(f"Unsupported YAML shape at {path}:{line_number}")

        key, value = line.split(":", 1)
        current[key.strip()] = _parse_scalar(value)

    if current is not None:
        tasks.append(current)

    return tasks


def load_tasks(path: Path) -> list[dict]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return _load_yaml_fallback(path)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected a YAML list in {path}")
    return data


def _select_tasks(tasks: list[dict], task_ids: list[str], include_skip_in_ci: bool) -> list[dict]:
    selected = tasks
    if task_ids:
        wanted = set(task_ids)
        selected = [task for task in selected if task.get("id") in wanted]
    if not include_skip_in_ci:
        selected = [task for task in selected if not task.get("skip_in_ci")]
    return selected


def _format_table(results: list[dict]) -> str:
    lines = ["id | pass/fail | latency_ms | reason-if-failed"]
    lines.append("--- | --- | ---: | ---")
    for result in results:
        status = "PASS" if result["passed"] else "FAIL"
        reason = "; ".join(result["reasons"])
        lines.append(f"{result['id']} | {status} | {result['latency_ms']:.2f} | {reason}")
    return "\n".join(lines)


async def _main_async(args: argparse.Namespace) -> int:
    tasks = load_tasks(args.tasks)
    selected_tasks = _select_tasks(tasks, args.task_id, args.include_skip_in_ci)
    report = await run_suite(selected_tasks)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report_dir / f"report_{args.run_id}.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(_format_table(report["results"]))
    print(f"\nReport: {report_path}")
    print(f"Success rate: {report['success_rate']:.3f}")

    return 0 if report["success_rate"] == 1.0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SentinAL task-success evaluation.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    parser.add_argument("--run-id", default="demo")
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument(
        "--task-id",
        action="append",
        default=[],
        help="Run only the given task id. Can be passed more than once.",
    )
    parser.add_argument(
        "--include-skip-in-ci",
        action="store_true",
        help="Include tasks marked skip_in_ci, such as app-launch tasks.",
    )
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
