"""Audit every installed dependency; the local application is not a PyPI release."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from importlib.metadata import distributions
from pathlib import Path


def main() -> int:
    # Include transitive and development packages, not just declared direct dependencies.
    # Exclude only this local application, whose source is checked separately.
    requirements = sorted({f"{dist.metadata['Name']}=={dist.version}"
                           for dist in distributions()
                           if dist.metadata['Name'].lower().replace('_', '-') != 'sentinal'})
    with tempfile.TemporaryDirectory(prefix="sentinal-dependency-audit-") as directory:
        path = Path(directory) / "installed.txt"
        path.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        # The manifest already enumerates all installed versions; no resolution/install is needed.
        return subprocess.run([sys.executable, "-m", "pip_audit", "--strict", "--disable-pip",
                               "--no-deps", "-r", str(path), *sys.argv[1:]], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
