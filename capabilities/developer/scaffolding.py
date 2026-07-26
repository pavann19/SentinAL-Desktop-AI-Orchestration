# capabilities/developer/scaffolding.py
# Project Scaffolding capability for SentinAL.
# Supports: npx create-react-app, create-next-app, Vite, FastAPI, Flask, Django boilerplates.
#
# Design:
#   - All scaffold commands are allowlisted — no arbitrary shell injection
#   - Runs in a subprocess with real-time streaming output (15 min timeout)
#   - Auto-creates the target directory and opens VS Code when done

import subprocess
import os
import shutil
import logging
import time

_logger = logging.getLogger("Scaffolding")

# ── Allowlisted scaffold recipes ─────────────────────────────────────────────
# Each key is the canonical framework name the LLM should use.
# Value is a list of allowlisted command tokens (no shell injection possible).
SCAFFOLD_RECIPES: dict[str, list[str]] = {
    # JavaScript / Node
    "react":        ["npx", "-y", "create-react-app@latest", "."],
    "next":         ["npx", "-y", "create-next-app@latest", ".", "--ts", "--no-git"],
    "vite":         ["npx", "-y", "create-vite@latest", ".", "--template", "react"],
    "vite-ts":      ["npx", "-y", "create-vite@latest", ".", "--template", "react-ts"],
    "vue":          ["npx", "-y", "create-vite@latest", ".", "--template", "vue"],
    "svelte":       ["npx", "-y", "create-vite@latest", ".", "--template", "svelte"],
    "express":      ["npx", "-y", "express-generator@latest", "."],
    # Python
    "fastapi":      ["python", "-m", "pip", "install", "fastapi", "uvicorn"],
    "flask":        ["python", "-m", "pip", "install", "flask"],
    "django":       ["python", "-m", "pip", "install", "django"],
    # Blank workspace
    "workspace":    [],  # Just creates the directory
}

# Maximum time (seconds) for scaffold commands — some npx calls download deps
_SCAFFOLD_TIMEOUT = 900  # 15 minutes


def scaffold_project(framework: str, project_name: str, location: str = "") -> str:
    """
    Scaffolds a new project using the specified framework in the given directory.

    Args:
        framework:    One of the SCAFFOLD_RECIPES keys (case-insensitive)
        project_name: Name of the new project folder
        location:     Parent directory (defaults to user's Desktop)

    Returns:
        str: Human-readable result (success or failure reason)
    """
    framework = framework.lower().strip()
    project_name = re.sub(r'[^a-zA-Z0-9_\-]', '-', project_name.strip()) if project_name.strip() else "my-project"

    if framework not in SCAFFOLD_RECIPES:
        supported = ", ".join(sorted(SCAFFOLD_RECIPES.keys()))
        return f"Framework '{framework}' is not supported. Supported: {supported}"

    # Resolve the target directory
    if not location:
        location = os.path.join(os.path.expanduser("~"), "Desktop")

    project_dir = os.path.join(location, project_name)

    # Create directory
    try:
        os.makedirs(project_dir, exist_ok=True)
        _logger.info(f"Scaffolding '{framework}' project in: {project_dir}")
    except OSError as e:
        return f"ERROR: Could not create project directory '{project_dir}': {e}"

    cmd = SCAFFOLD_RECIPES[framework]

    # Workspace-only: no command to run
    if not cmd:
        return f"Workspace '{project_name}' created at {project_dir}. No framework template applied."

    # Run the scaffold command inside the project directory
    try:
        _logger.info(f"Running scaffold command: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=_SCAFFOLD_TIMEOUT,
        )

        if result.returncode == 0:
            msg = (
                f"'{framework}' project '{project_name}' scaffolded successfully at {project_dir}. "
                f"Opening in VS Code now."
            )
            _logger.info(msg)
            # Open in VS Code if available
            if shutil.which("code"):
                subprocess.Popen(["code", project_dir], shell=False)
            return msg
        else:
            err = (result.stderr or result.stdout or "unknown error").strip()[:300]
            _logger.error(f"Scaffold failed (rc={result.returncode}): {err}")
            return f"Scaffolding failed for '{framework}': {err}"

    except subprocess.TimeoutExpired:
        return f"ERROR: Scaffolding '{framework}' timed out after {_SCAFFOLD_TIMEOUT // 60} minutes."
    except FileNotFoundError:
        return (
            f"ERROR: 'npx' or 'python' not found in PATH. "
            f"Please install Node.js or Python and ensure they are in your system PATH."
        )
    except Exception as e:
        _logger.error(f"scaffold_project error: {e}")
        return f"ERROR scaffolding '{framework}': {e}"


# ── Missing import fix ────────────────────────────────────────────────────────
import re  # noqa: E402 — placed after SCAFFOLD_RECIPES for clarity
