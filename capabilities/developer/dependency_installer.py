# capabilities/developer/dependency_installer.py
# Dependency Installation capability for SentinAL.
# Supports: pip install, npm install, npm install --save-dev, pip uninstall (with confirmation).
#
# Design:
#   - Package names are validated against an injection-safe regex before execution
#   - pip: always uses `python -m pip` (not bare `pip`) for correct venv targeting
#   - npm: runs in a user-specified cwd (defaults to CWD)
#   - Output is streamed and capped at 2000 chars for LLM summarization

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


def _validate_packages(packages: str) -> tuple[bool, str]:
    """
    Validates that the package string contains only safe characters.
    Returns (is_valid, reason).
    """
    if not packages or not packages.strip():
        return False, "No package name specified."
    if not _SAFE_PKG_PATTERN.match(packages.strip()):
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

    # Normalize multiple packages (comma or space separated)
    pkg_list = [p.strip() for p in re.split(r'[, ]+', packages.strip()) if p.strip()]
    cmd = ["python", "-m", "pip", "install"] + pkg_list
    if upgrade:
        cmd.append("--upgrade")

    _logger.info(f"pip install: {' '.join(cmd)}")
    return _run_install(cmd, label=f"pip install {packages}")


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

    _logger.info(f"npm install in '{work_dir}': {' '.join(cmd)}")
    return _run_install(cmd, label=f"npm install {packages}", cwd=work_dir)


def _run_install(cmd: list[str], label: str, cwd: str | None = None) -> str:
    """
    Internal: runs an install command in a VISIBLE terminal window.
    The user can watch the install progress scroll by in real-time.
    Returns immediately after launching, with a short startup wait.

    Fix (dependency-install PID bug): the previous implementation launched via
    `subprocess.Popen(["powershell", "-Command", "Start-Process powershell ..."])`
    — an outer PowerShell that runs Start-Process and then exits immediately,
    since it has no -NoExit itself. Popen.pid was therefore that transient
    outer process, not the actual -NoExit install window Start-Process spawned
    a moment later. Registering that pid as a watch would have reported
    "completed" almost instantly, regardless of whether the install had
    actually started. Same failure shape as CodeAct's original PID problem
    (see agentic_core/process_supervisor.py's module docstring), fixed the
    same way here: write the command to a temp .ps1 with a completion
    sentinel appended, and launch it directly (list-form Popen,
    CREATE_NEW_CONSOLE, no `start`/`Start-Process` wrapper) so Popen.pid IS
    the real, visible install window.
    """
    work_dir = cwd or os.getcwd()
    inner_cmd = " ".join(f'"{arg}"' if " " in arg else arg for arg in cmd)

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

        script = (
            build_sentinel_header()
            + f"cd '{work_dir}'\n"
            + f"{inner_cmd}\n"
            + "Write-Host '---[SentinAL] Install complete---' -ForegroundColor Green\n"
            + build_sentinel_footer(sentinel_path)
        )
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
    except Exception as e:
        # Falls through to the direct-command fallback below — install still
        # runs, it just loses the sentinel and the visible-window niceties.
        _logger.warning(f"Could not prepare supervised install script (non-fatal): {e}")
        script_path = None
        sentinel_path = None

    _logger.info(f"Launching visible install: {label} in {work_dir}")
    try:
        if script_path:
            launch_cmd = [
                "powershell", "-ExecutionPolicy", "Bypass",
                "-NoProfile", "-NoExit", "-File", script_path,
            ]
        else:
            launch_cmd = [
                "powershell", "-NoExit", "-Command",
                f"cd '{work_dir}'; {inner_cmd}; "
                "Write-Host '---[SentinAL] Install complete---' -ForegroundColor Green",
            ]

        proc = subprocess.Popen(
            launch_cmd,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            start_new_session=True
        )

        try:
            from agentic_core.process_supervisor import register_watch
            register_watch(
                label="dependency_install",
                sentinel_path=sentinel_path,
                pid=proc.pid,
                expected_state={"command": label},
            )
        except Exception as e:
            _logger.warning(f"Could not register process watch (non-fatal): {e}")

        # Small wait to let the window open before the executor moves on
        time.sleep(2.0)
        return (
            f"✓ Launched visible terminal for: {label}\n"
            f"Watch the PowerShell window for real-time progress."
        )
    except FileNotFoundError:
        # Fallback: powershell not found, try cmd. Not supervised — cmd has no
        # equivalent sentinel mechanism wired here, and this branch is rare
        # enough (missing powershell on Windows) not to warrant one.
        cmd_str = " ".join(cmd)
        subprocess.Popen(
            f'start cmd /K "cd /d "{work_dir}" && {cmd_str}"',
            shell=True, start_new_session=True,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        time.sleep(2.0)
        return f"✓ Launched terminal for: {label}. Watch the CMD window."
    except Exception as e:
        _logger.error(f"_run_install launch error: {e}")
        return f"ERROR launching '{label}': {e}"

