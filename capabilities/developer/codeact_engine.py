# capabilities/developer/codeact_engine.py
# ═══════════════════════════════════════════════════════════════════
# CODEACT ENGINE — SentinAL's Dynamic Script Generation & Execution
#
# Architecture:
#   1. LLM generates a PowerShell script for the WHOLE multi-step task
#   2. Script is validated against a security blocklist (no rm -rf, no registry edits etc.)
#   3. Script is saved into a per-run directory
#   4a. If Windows Sandbox is available: the script runs inside a fresh,
#       disposable Windows Sandbox VM (S4 containment — T3 throwaway
#       environment). Only the per-run directory is mapped in; nothing the
#       script does can touch the host outside it, and the whole VM is
#       destroyed when its window closes.
#   4b. Otherwise: the script runs in a VISIBLE PowerShell window ON THE HOST
#       with the user's full privileges (the pre-containment behaviour), and
#       the response says so plainly.
#
# This bypasses the rigid JSON Intent system for developer workflow tasks.
# ═══════════════════════════════════════════════════════════════════

import logging
import os
import re
import subprocess
import tempfile
import time

_logger = logging.getLogger("CodeActEngine")

# ── S4 containment: Windows Sandbox ─────────────────────────────────────────
# CodeAct's whole point is running arbitrary LLM-generated PowerShell — a
# blocklist over free-form code is inherently incomplete, so this is the
# system's widest attack surface (T3). Windows Sandbox gives it an ephemeral,
# disposable Windows VM: the generated script runs there, only a single per-run
# directory is shared in, and the VM (and anything the script did to it) is
# gone when the window closes.
#
# Requires the Windows Sandbox optional feature (Pro/Enterprise/Education/
# Workstations editions) enabled + a reboot. Checked fresh per call, with a
# RAM floor — a Sandbox instance needs ~1.5-2 GB and this project's dev
# machine has crashed under memory pressure before. When it isn't available
# CodeAct falls back to the pre-containment host path, saying so explicitly
# rather than silently pretending it's contained.
_SANDBOX_EXE = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsSandbox.exe")
_SANDBOX_MIN_FREE_GB = float(os.getenv("SENTINAL_CODEACT_SANDBOX_MIN_FREE_GB", "3.0"))
_SANDBOX_MEMORY_MB = int(os.getenv("SENTINAL_CODEACT_SANDBOX_MEMORY_MB", "2048"))
# Fixed mount point inside the Sandbox — the per-run host dir maps to here.
_SANDBOX_SHARE = r"C:\shared"


def _sandbox_available() -> bool:
    """True if Windows Sandbox can be launched right now: the feature is
    installed AND there is enough free RAM to not risk thrashing the host."""
    if not os.path.exists(_SANDBOX_EXE):
        return False
    try:
        import psutil
        free_gb = psutil.virtual_memory().available / 1e9
        if free_gb < _SANDBOX_MIN_FREE_GB:
            _logger.warning(
                f"[CodeAct] Windows Sandbox installed but only {free_gb:.1f} GB free "
                f"(< {_SANDBOX_MIN_FREE_GB} GB floor) — falling back to host execution."
            )
            return False
    except Exception:
        # psutil missing / unreadable: don't block on the RAM check, but the
        # exe existing is still required above.
        pass
    return True


def _build_wsb(host_run_dir: str, script_filename: str, sentinel_filename: str) -> str:
    """
    Builds a .wsb (Windows Sandbox config) that:
      - maps ONLY host_run_dir in, at C:\\shared (read-write) — the sole host
        path the sandboxed script can reach
      - runs the generated script on logon
      - is deliberately minimal: 2 GB, no vGPU, no clipboard/audio/video
        redirection, ProtectedClient on. Networking stays ON because CodeAct
        scripts routinely install/download.
    The generated script writes its completion sentinel into C:\\shared, which
    is host_run_dir on the other side — so the host's process supervisor sees
    it exactly as it would for a non-sandboxed run.
    """
    script_in_box = f"{_SANDBOX_SHARE}\\{script_filename}"
    return (
        "<Configuration>\n"
        "  <MappedFolders>\n"
        "    <MappedFolder>\n"
        f"      <HostFolder>{host_run_dir}</HostFolder>\n"
        f"      <SandboxFolder>{_SANDBOX_SHARE}</SandboxFolder>\n"
        "      <ReadOnly>false</ReadOnly>\n"
        "    </MappedFolder>\n"
        "  </MappedFolders>\n"
        "  <LogonCommand>\n"
        f"    <Command>powershell.exe -ExecutionPolicy Bypass -NoProfile -NoExit -File \"{script_in_box}\"</Command>\n"
        "  </LogonCommand>\n"
        f"  <MemoryInMB>{_SANDBOX_MEMORY_MB}</MemoryInMB>\n"
        "  <Networking>Enable</Networking>\n"
        "  <vGPU>Disable</vGPU>\n"
        "  <ProtectedClient>Enable</ProtectedClient>\n"
        "  <ClipboardRedirection>Disable</ClipboardRedirection>\n"
        "  <AudioInput>Disable</AudioInput>\n"
        "  <VideoInput>Disable</VideoInput>\n"
        "</Configuration>\n"
    )

# ── Security Blocklist ────────────────────────────────────────────────────────
# These patterns are forbidden in generated scripts.
# The list is conservative — we block destructive ops, registry edits, and
# anything that could exfiltrate data or escalate privileges.
_BLOCKED_PATTERNS = [
    r'\bRemove-Item\b.*-Recurse.*-Force',  # rm -rf equivalent
    r'\bFormat-Volume\b',                  # disk format
    r'\bSet-MpPreference\b',               # disable Windows Defender
    r'\bNew-ItemProperty\b.*HKLM',         # HKEY_LOCAL_MACHINE registry writes
    r'\bInvoke-Expression\b.*http',        # download + execute
    r'\biex\b.*http',                      # iex shorthand
    r'\bStart-Process\b.*-Credential',     # credential impersonation
    r'curl.*\|\s*sh',                      # curl pipe to shell
    r'wget.*\|\s*sh',
    r'\bNet\s+user\b.*\/add',              # add Windows user
    r'\bnet\s+localgroup\b.*administrators',  # add to admin group
]

_DEVELOPER_KEYWORDS = [
    'install', 'npm', 'node', 'react', 'vue', 'angular', 'svelte', 'next',
    'vite', 'create-react-app', 'scaffold', 'init', 'pip install', 'conda',
    'git clone', 'docker', 'python', 'flask', 'fastapi', 'django',
    'package', 'dependency', 'framework', 'project', 'setup', 'configure',
    'build', 'compile', 'deploy', 'run dev', 'start server',
]

_CODEACT_SYSTEM_PROMPT = """You are SentinAL's PowerShell code generation engine running on Windows 11.
The user has given you a multi-step developer task. Generate a SINGLE complete PowerShell script that:
1. Executes ALL steps in sequence
2. Shows clear progress messages with Write-Host (use different colors: Green=success, Yellow=progress, Red=error)
3. Uses proper error handling with try/catch blocks
4. Uses real Windows paths with $env:USERPROFILE, $env:APPDATA, $env:LOCALAPPDATA
5. For Node.js installation: use winget (winget install OpenJS.NodeJS --accept-source-agreements --accept-package-agreements)
6. For npx commands: always use `npx --yes` to auto-accept prompts
7. After every major step, write a clear status line with Write-Host
8. At the end, print a summary of what was done

CRITICAL RULES:
- Output ONLY the raw PowerShell script. No markdown, no backticks, no explanation.
- Never use placeholder paths like "your-project" or "directory_name" - use real specific names from the user's request
- If the user says "on desktop", use "$env:USERPROFILE\\Desktop"
- Always handle the case where a tool is not installed (check first, install if missing)
- Keep it focused and practical - no unnecessary decorations

START the script with:
Write-Host "=== SentinAL CodeAct: Starting mission ===" -ForegroundColor Cyan
END the script with:
Write-Host "=== SentinAL CodeAct: Mission Complete ===" -ForegroundColor Green
Read-Host "Press Enter to close this window"
"""


def is_developer_task(prompt: str) -> bool:
    """
    Heuristic check: does this prompt describe a developer workflow task
    that would benefit from CodeAct instead of rigid JSON intents?
    Returns True if 2+ developer keywords are found.
    """
    prompt_lower = prompt.lower()
    matches = sum(1 for kw in _DEVELOPER_KEYWORDS if kw in prompt_lower)
    return matches >= 2


def _validate_script(script: str) -> tuple[bool, str]:
    """
    Security validation: check the generated script against the blocklist.
    Returns (is_safe, reason).
    """
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, script, re.IGNORECASE):
            return False, f"Blocked pattern detected: {pattern}"
    return True, "ok"


def generate_and_run(prompt: str, llm) -> str:
    """
    Main entry point for the CodeAct engine.

    1. Calls the LLM to generate a PowerShell script for the full task.
    2. Validates it against the security blocklist.
    3. Saves it to a temp .ps1 file.
    4. Launches it in a visible PowerShell window.
    5. Returns a status string for the TTS/UI.

    Args:
        prompt: The original user request
        llm:    A pre-initialized LLM instance from BrainConfig

    Returns:
        str: Human-readable result for speech response
    """
    _logger.info(f"[CodeAct] Generating script for: {prompt}")
    print(f"[CodeAct] LLM generating PowerShell script for: '{prompt}'")

    # ── Step 1: Generate the script ───────────────────────────────────────────
    try:
        full_prompt = (
            f"{_CODEACT_SYSTEM_PROMPT}\n\n"
            f"User task: {prompt}\n\n"
            f"Generate the PowerShell script now:"
        )
        resp = llm.invoke([("system", full_prompt)])
        script = resp.content.strip()

        # Strip markdown if LLM wrapped it anyway
        script = re.sub(r'^```(?:powershell|ps1|ps)?\s*', '', script, flags=re.IGNORECASE)
        script = re.sub(r'\s*```$', '', script, flags=re.IGNORECASE)
        script = script.strip()

        if not script:
            return "CodeAct: LLM returned an empty script. Cannot execute."

        print(f"[CodeAct] Script generated ({len(script)} chars)")
        _logger.debug(f"[CodeAct] Script:\n{script}")

    except Exception as e:
        _logger.error(f"[CodeAct] Script generation failed: {e}")
        return f"CodeAct: Script generation failed — {e}"

    # ── Step 2: Security validation ───────────────────────────────────────────
    is_safe, reason = _validate_script(script)
    if not is_safe:
        _logger.warning(f"[CodeAct] SECURITY BLOCK: {reason}")
        return "CodeAct: Security block — generated script contains a forbidden operation. Aborting."

    # ── Step 3: Save to a per-run directory ──────────────────────────────────
    # A per-run dir (not a shared flat one) so the WHOLE thing can be mapped
    # into a sandbox as the single shared folder, and so the completion
    # sentinel lands somewhere both the host and (when sandboxed) the VM can
    # see via that one mapping.
    stamp = int(time.time() * 1000)
    try:
        base = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "SentinAL_CodeAct")
        run_dir = os.path.join(base, f"run_{stamp}")
        os.makedirs(run_dir, exist_ok=True)

        script_filename = f"codeact_{stamp}.ps1"
        script_path = os.path.join(run_dir, script_filename)
        sentinel_filename = f"sentinel_{stamp}.json"
        host_sentinel_path = os.path.join(run_dir, sentinel_filename)

        use_sandbox = _sandbox_available()

        # Completion sentinel: the script is launched with -NoExit, so process
        # death is NOT a completion signal — a footer that writes a marker file
        # when the body ends is. When sandboxed, the script writes it to the
        # sandbox-side view of the mapping (C:\shared\...); the host watches the
        # host-side path (run_dir\...) — the same file.
        try:
            from agentic_core.process_supervisor import (
                build_sentinel_footer,
                build_sentinel_header,
            )
            sentinel_in_script = (
                f"{_SANDBOX_SHARE}\\{sentinel_filename}" if use_sandbox else host_sentinel_path
            )
            script = build_sentinel_header() + script + build_sentinel_footer(sentinel_in_script)
        except Exception as e:
            _logger.warning(f"[CodeAct] Could not attach completion sentinel (non-fatal): {e}")
            host_sentinel_path = None

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)
        print(f"[CodeAct] Script saved to: {script_path} (sandboxed={use_sandbox})")

    except Exception as e:
        _logger.error(f"[CodeAct] Failed to save script: {e}")
        return f"CodeAct: Could not save script to disk — {e}"

    # ── Step 4a: Run inside a disposable Windows Sandbox ─────────────────────
    if use_sandbox:
        try:
            wsb_path = os.path.join(run_dir, f"codeact_{stamp}.wsb")
            with open(wsb_path, "w", encoding="utf-8") as f:
                f.write(_build_wsb(run_dir, script_filename, sentinel_filename))

            proc = subprocess.Popen(
                [_SANDBOX_EXE, wsb_path],
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                start_new_session=True,
            )
            watch_id = None
            try:
                from agentic_core.process_supervisor import register_watch
                watch_id = register_watch(
                    label="codeact",
                    sentinel_path=host_sentinel_path,
                    pid=proc.pid,
                    expected_state={"script_path": script_path, "sandboxed": True},
                )
            except Exception as e:
                _logger.warning(f"[CodeAct] Could not register process watch (non-fatal): {e}")

            time.sleep(1.5)
            print("[CodeAct] Windows Sandbox launched.")
            winget_note = (
                " Note: a fresh Sandbox has no winget, so any install steps that rely on it "
                "will fail inside it — that's a containment limit, not a bug."
                if "winget" in script.lower() else ""
            )
            task_note = f" Task id: {watch_id}." if watch_id else ""
            return (
                "I've started your request inside an isolated Windows Sandbox. It has its own "
                f"throwaway copy of Windows; nothing it does can touch your machine except the "
                f"one shared folder ({run_dir}). Close the Sandbox window when it's done — "
                f"everything else in it is discarded.{winget_note}{task_note}"
            )
        except Exception as e:
            _logger.error(f"[CodeAct] Sandbox launch failed ({e}); falling back to host execution.")
            # fall through to 4b

    # ── Step 4b: Run in a visible host PowerShell window (UNCONTAINED) ────────
    try:
        launch_cmd = [
            "powershell", "-ExecutionPolicy", "Bypass", "-NoProfile", "-NoExit",
            "-File", script_path,
        ]
        proc = subprocess.Popen(
            launch_cmd,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            start_new_session=True,
        )
        watch_id = None
        try:
            from agentic_core.process_supervisor import register_watch
            watch_id = register_watch(
                label="codeact",
                sentinel_path=host_sentinel_path,
                pid=proc.pid,
                expected_state={"script_path": script_path, "sandboxed": False},
            )
        except Exception as e:
            _logger.warning(f"[CodeAct] Could not register process watch (non-fatal): {e}")

        time.sleep(1.5)
        print("[CodeAct] Visible host terminal launched (UNSANDBOXED).")
        task_note = f" Task id: {watch_id}." if watch_id else ""
        return (
            "I've opened a terminal window and started executing your request. "
            "Windows Sandbox isn't available right now, so this is running directly on "
            f"your machine with full access to your files — watch the PowerShell window.{task_note}"
        )
    except Exception as e:
        _logger.error(f"[CodeAct] Launch failed: {e}")
        return f"CodeAct: Failed to launch PowerShell window — {e}"
