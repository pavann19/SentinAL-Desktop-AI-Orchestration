# capabilities/developer/dependency_installer.py
# Dependency Installation capability for SentinAL.
# Supports: pip install, npm install, npm install --save-dev, pip uninstall (with confirmation).
#
# Design:
#   - Package names are validated against an injection-safe regex before execution
#   - pip: always uses `python -m pip` (not bare `pip`) for correct venv targeting
#   - npm: runs in a user-specified cwd (defaults to CWD)
#   - npm: sandboxed in a throwaway Docker container when Docker is available
#     (S4 containment — see _sandboxed_npm_script_body's docstring), falling
#     back to a direct host install when Docker isn't running or produces a
#     native module the host can't use. pip stays unsandboxed — see the same
#     docstring for why.
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

# ── Sandboxed npm install (S4 containment) ──────────────────────────────────
# npm install's real threat is the same one pip's setup.py has always had:
# an npm postinstall script (or a compromised/malicious package) runs
# arbitrary code at install time, directly on the host, with the user's full
# privileges — a well-known real supply-chain attack vector, not a
# hypothetical one. Containing that code inside a throwaway Linux container
# is a genuine, narrow win: node_modules still lands on the host (mounted as
# a volume — the whole point of the install), but whatever the postinstall
# script does beyond that mounted directory cannot touch the rest of the
# machine.
#
# NOT extended to pip_install(): pip has no existing "install location"
# concept to redirect into a mount (it always targets whatever interpreter
# environment is currently active) — sandboxing it cleanly needs a
# --target/venv design decision this function doesn't have yet, so it stays
# out of scope here rather than bolted on as a behavior change.
#
# Docker Desktop on this class of Windows Home machine only runs LINUX
# containers (Windows containers need Hyper-V, which Home editions don't
# support — same reason Windows Sandbox is unavailable). That means a
# package with a native/compiled component (node-sass, sharp, bcrypt, any
# node-gyp build) comes out of the sandboxed install as a Linux binary,
# unusable by the host's Windows Node. Detected after the fact (see the
# generated script's own post-install check below) rather than guessed at
# up front — if it happens, the script falls back to a direct, unsandboxed
# install in the same visible window so the packages actually work,
# consistent with sandbox-by-default rather than sandbox-only.
_DOCKER_NODE_IMAGE = "node:20-slim"
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


def _sandboxed_npm_script_body(pkg_list: list[str], dev: bool, work_dir: str) -> str:
    """Builds the PowerShell body for a Docker-sandboxed npm install, with a
    post-install native-module check that falls back to a direct host
    install in the same window if the sandboxed result isn't usable."""
    npm_args = " ".join(pkg_list) if pkg_list else ""
    dev_flag = " --save-dev" if dev else ""
    # Windows drive-letter paths pass through Docker Desktop's CLI path
    # translation unchanged (e.g. "C:\Users\..." -> the Linux mount it needs) —
    # no manual /c/... conversion needed from a native docker.exe invocation.
    docker_cmd = (
        f'docker run --rm -v "{work_dir}:/workspace" -w /workspace '
        f'{_DOCKER_NODE_IMAGE} npm install {npm_args}{dev_flag}'.strip()
    )
    direct_cmd = f'npm install {npm_args}{dev_flag}'.strip()
    return (
        f"cd '{work_dir}'\n"
        f"Write-Host '[SentinAL] Sandboxed install (Docker): {docker_cmd}' -ForegroundColor Cyan\n"
        f"{docker_cmd}\n"
        "$__native = Get-ChildItem -Path node_modules -Recurse -Filter '*.node' -ErrorAction SilentlyContinue\n"
        "if ($__native) {\n"
        "    Write-Host 'WARNING: sandboxed install produced native module(s) built for Linux, "
        "not usable on Windows:' -ForegroundColor Yellow\n"
        "    $__native | ForEach-Object { Write-Host \"  - $($_.FullName)\" -ForegroundColor Yellow }\n"
        "    Write-Host '[SentinAL] Falling back to a direct (unsandboxed) install so these "
        "packages actually work...' -ForegroundColor Yellow\n"
        f"    {direct_cmd}\n"
        "}\n"
    )


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

    _logger.info(f"npm install in '{work_dir}' (Docker unavailable, direct): {' '.join(cmd)}")
    return _run_install(cmd, label=label, cwd=work_dir)


def _run_install(cmd: list[str], label: str, cwd: str | None = None, script_body: str | None = None) -> str:
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

    script_body: pre-built PowerShell body (e.g. a Docker-sandboxed install
    with its own fallback logic) to use verbatim instead of deriving one from
    `cmd`. `cmd` is still used for the fallback (`FileNotFoundError`) path
    below, since that path has no sandboxing concept to preserve.
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

        body = script_body if script_body is not None else (
            f"cd '{work_dir}'\n"
            f"{inner_cmd}\n"
            "Write-Host '---[SentinAL] Install complete---' -ForegroundColor Green\n"
        )
        script = (
            build_sentinel_header()
            + body
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
            ps_command = (
                f"cd '{work_dir}'; {inner_cmd}; "
                "Write-Host '---[SentinAL] Install complete---' -ForegroundColor Green"
            )
            launch_cmd = ["powershell", "-NoExit", "-Command", ps_command]

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

