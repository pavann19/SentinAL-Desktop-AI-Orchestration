"""Check published documentation, package metadata and release resource boundaries."""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = (
    "README.md", "CONTRIBUTING.md", "SECURITY.md", "docs/README.md",
    "docs/EVALUATION.md", "docs/DECISIONS.md", "CONTAINMENT_ARCHITECTURE.md",
    "sentinal-ui/README.md", "thesis/Thesis.md", "historical-record/README.md",
)


def check() -> list[str]:
    errors: list[str] = []
    for name in DOCS:
        document = ROOT / name
        if not document.is_file():
            errors.append(f"Missing document: {name}")
            continue
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            target = target.strip().split(' "', 1)[0].strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            resolved = (document.parent / unquote(parsed.path)).resolve()
            if not resolved.is_relative_to(ROOT) or not resolved.exists():
                errors.append(f"Broken local link in {name}: {target}")
    thesis = ROOT / "thesis/Thesis.md"
    if not thesis.is_file() or thesis.stat().st_size == 0:
        errors.append("Stable thesis entry point is missing or empty")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if "dependencies" not in project["project"].get("dynamic", []):
        errors.append("Runtime dependencies must come from the canonical requirements file")
    setuptools = project["tool"]["setuptools"]
    if setuptools.get("dynamic", {}).get("dependencies", {}).get("file") != ["requirements.txt"]:
        errors.append("Package dependencies diverge from requirements.txt")
    for module in setuptools.get("py-modules", []):
        if not (ROOT / f"{module}.py").is_file():
            errors.append(f"Missing packaged module: {module}")
    for package in setuptools.get("packages", []):
        if not (ROOT / package.replace(".", "/")).is_dir():
            errors.append(f"Missing packaged directory: {package}")
    ui = json.loads((ROOT / "sentinal-ui/package.json").read_text())
    lock = json.loads((ROOT / "sentinal-ui/package-lock.json").read_text())
    if ui["name"] != lock["name"] or ui["name"] != lock["packages"][""]["name"]:
        errors.append("Frontend manifest and lockfile names disagree")
    for resource in ui["build"]["extraResources"]:
        source = resource if isinstance(resource, str) else resource["from"]
        path = Path(source)
        if any(part in {".env", "data", ".sentinal_token", "venv", "_evidence"} for part in path.parts):
            errors.append(f"Private/runtime resource in desktop package: {source}")
        if not (ROOT / "sentinal-ui" / source).exists():
            errors.append(f"Missing desktop resource: {source}")
    for line in (ROOT / "Dockerfile").read_text().splitlines():
        if line.startswith("COPY "):
            for source in line.split()[1:-1]:
                if source.startswith("--"):
                    continue
                if not (ROOT / source).exists():
                    errors.append(f"Missing image build source: {source}")
    return errors


if __name__ == "__main__":
    findings = check()
    for finding in findings:
        print(f"ERROR: {finding}", file=sys.stderr)
    if findings:
        raise SystemExit(1)
    print("Repository documentation, package metadata and resource checks passed")
