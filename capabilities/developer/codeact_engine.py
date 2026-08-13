# capabilities/developer/codeact_engine.py
# ═══════════════════════════════════════════════════════════════════
# CODEACT ENGINE — SentinAL's Dynamic Script Generation & Execution
#
# Architecture:
#   1. LLM generates a PowerShell script for the WHOLE multi-step task
#   2. Script is validated against a security blocklist (no rm -rf, no registry edits etc.)
#   3. Script is saved to a temp file
#   4. Script runs in a VISIBLE PowerShell window the user can watch
#
# This completely bypasses the rigid JSON Intent system for developer
# workflow tasks, giving the agent unlimited flexibility.
# ═══════════════════════════════════════════════════════════════════

import logging
import os
import re
import subprocess
import tempfile
import time

_logger = logging.getLogger("CodeActEngine")

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

    # ── Step 3: Save to temp file ──────────────────────────────────────────────
    try:
        # Use a named temp file in the user's temp dir so it's traceable
        script_dir = os.path.join(os.environ.get("TEMP", tempfile.gettempdir()), "SentinAL_CodeAct")
        os.makedirs(script_dir, exist_ok=True)

        script_name = f"codeact_{int(time.time())}.ps1"
        script_path = os.path.join(script_dir, script_name)

        # Completion sentinel: this script is launched detached with -NoExit, so
        # the console stays open indefinitely after the body finishes and process
        # death is NOT a completion signal. A footer that writes a marker file
        # when the body ends is the only accurate signal available, and it is
        # only possible because SentinAL generated this script itself.
        # Registration is best-effort — if it fails, the script still runs
        # exactly as before, just unobserved.
        sentinel_path = None
        try:
            from agentic_core.process_supervisor import (
                build_sentinel_footer,
                build_sentinel_header,
                new_sentinel_path,
            )
            sentinel_path = new_sentinel_path("codeact")
            script = build_sentinel_header() + script + build_sentinel_footer(sentinel_path)
        except Exception as e:
            _logger.warning(f"[CodeAct] Could not attach completion sentinel (non-fatal): {e}")
            sentinel_path = None

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        print(f"[CodeAct] Script saved to: {script_path}")

    except Exception as e:
        _logger.error(f"[CodeAct] Failed to save script: {e}")
        return f"CodeAct: Could not save script to disk — {e}"

    # ── Step 4: Launch in a visible PowerShell window ─────────────────────────
    try:
        # ExecutionPolicy Bypass allows running unsigned scripts
        # -NoProfile speeds up startup
        # -NoExit keeps window open after script completes so user can read results
        launch_cmd = [
            "powershell",
            "-ExecutionPolicy", "Bypass",
            "-NoProfile",
            "-NoExit",
            "-File", script_path
        ]

        proc = subprocess.Popen(
            launch_cmd,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            start_new_session=True
        )

        # Hand the process to the supervisor so its completion is reconciled in
        # the background. The request below returns immediately either way -
        # this adds observation, it does not add waiting.
        try:
            from agentic_core.process_supervisor import register_watch
            register_watch(
                label="codeact",
                sentinel_path=sentinel_path,
                pid=proc.pid,
                expected_state={"script_path": script_path},
            )
        except Exception as e:
            _logger.warning(f"[CodeAct] Could not register process watch (non-fatal): {e}")

        time.sleep(1.5)  # Let the window open before Jarvis speaks
        print("[CodeAct] Visible terminal launched successfully.")

        return (
            "I've opened a terminal window and started executing your request. "
            "You can watch every step happen in real time in the PowerShell window."
        )

    except Exception as e:
        _logger.error(f"[CodeAct] Launch failed: {e}")
        return f"CodeAct: Failed to launch PowerShell window — {e}"
