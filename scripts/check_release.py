"""Check the source release contract without importing the desktop runtime."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check() -> list[str]:
    errors = []
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
                    if line.strip() and not line.startswith("#")]
    if requirements != project["project"]["dependencies"]:
        errors.append("requirements.txt must mirror project.dependencies")
    reference = json.loads((ROOT / "eval/reference_environment.json").read_text())
    for name, expected in reference["input_sha256"].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            errors.append(f"Reference input hash changed: {name}")
    constants = {node.targets[0].id: ast.literal_eval(node.value)
                 for node in ast.parse((ROOT / "config/constants.py").read_text()).body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in {"EMBEDDING_MODEL_ID", "EMBEDDING_MODEL_REVISION"}}
    if (reference["model"]["id"] != constants["EMBEDDING_MODEL_ID"]
            or reference["model"]["revision"] != constants["EMBEDDING_MODEL_REVISION"]):
        errors.append("Reference model and configured model differ")
    package = json.loads((ROOT / "sentinal-ui/package.json").read_text())
    for resource in package["build"]["extraResources"]:
        if resource["from"] in {"../.env", "../data", "../memory", "../logs", "../.sentinal_token"}:
            errors.append("Private runtime material in Electron resources")
    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                                    cwd=ROOT, text=True).splitlines()
    paths = sorted({p for p in paths if (ROOT / p).is_file()})
    forbidden = {"_evidence", "thesis", "data", "memory", "logs", "telemetry", "node_modules", "venv", ".venv",
                 "_backups", "_context_packs", "__pycache__", "dev-history", "planning", "reports"}
    key_pattern = re.compile(rb"(?:gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|tvly-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
    for name in paths:
        path = ROOT / name
        if path.parts and any(part in forbidden for part in Path(name).parts):
            errors.append(f"Runtime/generated material in release: {name}")
        if path.name in {".env", ".sentinal_token"} or path.suffix in {".db", ".joblib", ".npy", ".log"}:
            errors.append(f"Private/generated file in release: {name}")
        if key_pattern.search(path.read_bytes()):
            errors.append(f"Credential pattern found: {name}")
    for name in paths:
        path = ROOT / name
        if path.suffix != ".md":
            continue
        if re.search(r"_context_packs|VERIFICATION_PROTOCOL|PROCESS NOTE|(?:generated|authored|maintained) by (?:an? )?(?:AI|ChatGPT|Codex|Claude)",
                     path.read_text(encoding="utf-8"), re.IGNORECASE):
            errors.append(f"Internal authoring/process material in documentation: {name}")
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("https://", "http://", "mailto:", "#")):
                continue
            target = target.split("#", 1)[0]
            if target and not (path.parent / target).exists():
                errors.append(f"Broken local link: {name}: {target}")
    return errors


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    errors = check()
    for error in errors:
        print(error)
    print(f"Release source checks: {'FAILED' if errors else 'passed'}")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
