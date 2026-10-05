# capabilities/developer/dependency_installer.py
# Dependency Installation capability for SentinAL.
# Supports contained npm installs; host pip execution is disabled.
#
# npm requires Docker and never falls back to host execution.
# pip host installation is disabled until a contained target-environment design exists.

import logging
import os
import re
import subprocess
import tempfile
import time

_logger = logging.getLogger("DependencyInstaller")

# ── Package Name Safety Pattern ───────────────────────────────────────────────
# Allows: letters, digits, hyphens, underscores, dots, [] (pip extras), @versions
# Blocks: shell metacharacters (&, |, ;, >, <, ` etc.)
_SAFE_PKG_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.\[\]@>=<!, ]+$')

# Maximum time for dependency install (large packages can take a while)
_INSTALL_TIMEOUT = 300  # 5 minutes

# Disposable npm container: the selected workspace remains a writable mount.
_DOCKER_NODE_IMAGE = "node:22-slim"
_DOCKER_CHECK_TIMEOUT = 5


def _docker_available() -> bool:
    """True if the Docker daemon is reachable right now. Checked fresh per
    call, not cached — Docker Desktop on a memory-constrained machine can be
    started and stopped between requests, and a stale "available" answer
    would launch a script that immediately fails to connect."""
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=_DOCKER_CHECK_TIMEOUT, check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sandboxed_npm_script_body(pkg_list: list[str], dev: bool, work_dir: str) -> str:
    """Quote arguments literally; fail on Docker errors or incompatible native output."""
    args = ["docker", "run", "--rm", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "-v", f"{work_dir}:/workspace", "-w", "/workspace", _DOCKER_NODE_IMAGE,
            "npm", "install", *pkg_list]
    if dev:
        args.append("--save-dev")
    command = "& " + " ".join(_ps_quote(arg) for arg in args)
    return (
        f"Set-Location -LiteralPath {_ps_quote(work_dir)}\n"
        f"{command}\n"
        "if ($LASTEXITCODE -ne 0) { throw 'Contained npm install failed.' }\n"
        "$native = Get-ChildItem -LiteralPath node_modules -Recurse -Filter '*.node' -ErrorAction SilentlyContinue\n"
        "if ($native) { throw 'Linux native modules cannot be used on Windows; host fallback is disabled.' }\n"
    )


def _validate_packages(packages: str) -> tuple[bool, str]:
    if not packages or not packages.strip():
        return False, "No package name specified."
    if not _SAFE_PKG_PATTERN.fullmatch(packages.strip()):
        return False, f"Unsafe characters detected in package specification: '{packages[:80]}'"
    return True, ""


def pip_install(packages: str, upgrade: bool = False) -> str:
    """
    Installs one or more Python packages using pip.

    Args:
        packages: Space or comma-separated package names (e.g. 'requests flask')
        upgrade:  If True, adds --upgrade flag

    Returns:
        str: Human-readable result
    """
    valid, reason = _validate_packages(packages)
    if not valid:
        return f"ERROR: {reason}"

    return "ERROR: Host pip installation is disabled. Install dependencies manually in a reviewed virtual environment."



def npm_install(packages: str = "", dev: bool = False, cwd: str = "") -> str:
    """
    Installs npm packages in the specified directory.
    If no packages specified, runs `npm install` (installs from package.json).

    Args:
        packages: Space-separated package names (empty = install from package.json)
        dev:      If True, adds --save-dev flag
        cwd:      Working directory (defaults to os.getcwd())

    Returns:
        str: Human-readable result
    """
    work_dir = cwd.strip() if cwd.strip() else os.getcwd()

    if not os.path.isdir(work_dir):
        return f"ERROR: Directory '{work_dir}' does not exist."

    pkg_list: list[str] = []
    if packages.strip():
        valid, reason = _validate_packages(packages)
        if not valid:
            return f"ERROR: {reason}"
        pkg_list = [p.strip() for p in re.split(r'[, ]+', packages.strip()) if p.strip()]
        cmd = ["npm", "install"] + pkg_list
        if dev:
            cmd.append("--save-dev")
    else:
        # npm install with no args = restore from package.json
        cmd = ["npm", "install"]

    label = f"npm install {packages}"
    if _docker_available():
        _logger.info(f"npm install in '{work_dir}' (sandboxed via Docker): {' '.join(cmd)}")
        return _run_install(
            cmd, label=label, cwd=work_dir,
            script_body=_sandboxed_npm_script_body(pkg_list, dev, work_dir),
        )

    return "ERROR: Docker is unavailable; host npm fallback is disabled."


def _run_install(cmd: list[str], label: str, cwd: str | None = None, script_body: str | None = None) -> str:
    """Launch a contained script with its actual PID and completion sentinel."""
    if script_body is None:
        return "ERROR: Uncontained dependency installation is disabled."
    work_dir = cwd or os.getcwd()

    script_dir = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "SentinAL_DependencyInstall")
    sentinel_path = None
    try:
        os.makedirs(script_dir, exist_ok=True)
        script_path = os.path.join(script_dir, f"install_{int(time.time() * 1000)}.ps1")

        from agentic_core.process_supervisor import (
            build_sentinel_footer,
            build_sentinel_header,
            new_sentinel_path,
        )
        sentinel_path = new_sentinel_path("dependency_install")

        body = script_body
        script = (
            build_sentinel_header()
            + body
            + build_sentinel_footer(sentinel_path)
        )
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
    except Exception as e:
        return f"ERROR: Could not prepare contained install: {e}"

    _logger.info(f"Launching contained install: {label} in {work_dir}")
    try:
        launch_cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-File", script_path]

        proc = subprocess.Popen(
            launch_cmd,
            creationflags=subprocess.CREATE_NO_WINDOW,
            start_new_session=True
        )

        watch_id = None
        try:
            from agentic_core.process_supervisor import register_watch
            watch_id = register_watch(
                label="dependency_install",
                sentinel_path=sentinel_path,
                pid=proc.pid,
                expected_state={"command": label},
            )
        except Exception as e:
            _logger.warning(f"Could not register process watch (non-fatal): {e}")

        # Report only launch acknowledgement; completion is observed by the supervisor.
        task_note = f"\nTask id: {watch_id} — poll it with process_supervisor.get_task_status()." if watch_id else ""
        return (
            f"✓ Launched contained install for: {label}\n"
            f"This is a launch acknowledgement, not a completion result.{task_note}"
        )
    except FileNotFoundError:
        return "ERROR: PowerShell is unavailable; host command fallback is disabled."
    except Exception as e:
        _logger.error(f"_run_install launch error: {e}")
        return f"ERROR launching '{label}': {e}"

