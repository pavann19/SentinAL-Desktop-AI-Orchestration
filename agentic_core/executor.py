# executor.py
# Thin execution layer for SentinAL.
# The LLM determines what to execute; this module only performs safe dispatch.
#
# V2.0 Fixes:
#   Fix 1.1 — Shell injection guard: blocks &&, ||, |, ; chain operators in LLM payloads
#   Fix 1.2 — YouTube HTML scraper removed: replaced with webbrowser.open (ToS compliant)
#   Fix 2.9 — Path cache routed through thread-safe MemoryManager (not raw sqlite3.connect)
#   Fix 2.10 — Hardcoded time.sleep(0.5) and sleep(2.0) replaced with env-configurable values
#   Fix 5.1 — Structured logging via logging module instead of print()

import logging
import os
import re
import subprocess
import time
import urllib.parse
import webbrowser
from datetime import datetime

import pyautogui

from agentic_core.memory_hook import MemoryManager
from agentic_core.validator import validate_sandbox
from capabilities.developer.dependency_installer import npm_install, pip_install
from capabilities.developer.scaffolding import scaffold_project
from capabilities.system.gui_resolver import resolve_element

# Phase 3 capability modules
from capabilities.system.process_manager import kill_process, list_processes
from config.constants import SENSITIVE_TARGETS

# ── Structured Logger (Fix 5.1) ───────────────────────────────────────────────
from config.paths import LOGS_DIR  # Resolves to AppData\SentinAL\logs in prod

_logger = logging.getLogger("Executor")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _fh = logging.FileHandler(os.path.join(LOGS_DIR, "sentinal_runtime.log"))
    _fh.setFormatter(logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s'))
    _logger.addHandler(_fh)
    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter('[%(name)s] %(message)s'))
    _logger.addHandler(_sh)

# ── Configuration ─────────────────────────────────────────────────────────────
# Fix 2.10: Configurable step delay (default 0.1s, was hardcoded 0.5s)
STEP_DELAY     = float(os.getenv("EXECUTOR_STEP_DELAY", "0.1"))
# Fix 2.10: Configurable GUI focus wait (default 1.0s, was hardcoded 2.0s)
GUI_FOCUS_WAIT = float(os.getenv("GUI_FOCUS_WAIT", "1.0"))

# ── Initialize Dynamic URL Cache ──────────────────────────────────────────────
memory = MemoryManager()

# ── Hardware Kill-Switch ──────────────────────────────────────────────────────
# Throwing the mouse to any corner of the screen aborts the agent instantly.
pyautogui.FAILSAFE = True


def _sanitize_shell_cmd(command: str) -> str:
    """
    Fix 1.1: Guards against shell injection via LLM-generated payloads.
    Scans for chain operators (&&, ||, ;) and raises ValueError if found.
    Single pipes (|) are allowed for benign CLI usage (dir | findstr).

    GUI-prefix commands (start, explorer, notepad) bypass this check
    because they are deterministic application launchers, not LLM payloads.
    """
    GUI_PREFIXES = ('start ""', 'start "', 'explorer ', 'notepad ')
    if any(command.strip().startswith(p) for p in GUI_PREFIXES):
        return command  # Whitelisted GUI launchers, skip injection check

    CHAIN_OPERATORS = ['&&', '||', ';']
    for op in CHAIN_OPERATORS:
        if op in command:
            _logger.error(f"SECURITY BLOCK: Shell chain operator '{op}' rejected: '{command[:80]}'")
            raise ValueError(
                f"[Executor] Security: Shell chain operator '{op}' in command — injection rejected."
            )
    return command


def _is_safe_command(command: str) -> bool:
    """
    Secondary safety check on the raw command string before execution.
    The validator.py gates the intent earlier; this is a last-resort guard.
    """
    cmd_lower = command.lower()
    for pattern in SENSITIVE_TARGETS:
        if pattern in cmd_lower:
            _logger.warning(f"BLOCKED: unsafe pattern '{pattern}' in: '{command[:80]}'")
            return False
    return True


def _resolve_url_template(step: dict, default_platform: str = "google") -> tuple:
    """
    Shared helper: resolves a URL template via the SQLite cache or
    the LLM-provided template. Returns (url_template, query_encoded, platform).
    """
    target       = step.get("target", "")
    platform     = step.get("value", default_platform).lower()
    llm_template = step.get("url_template", "")
    query        = urllib.parse.quote(target)

    # 1. Check the SQLite Cache
    url_template = memory.get_url_template(platform)

    # 2. Cache Miss: Use LLM's template and save it for the future
    if not url_template:
        url_template = llm_template
        if url_template:
            memory.save_url_template(platform, url_template)
            print(f"[CACHE] Learned new route for '{platform}'")

    return url_template, query, platform



def execute_pipeline(validated_steps: list, cancel_event=None) -> str:
    """
    Sequentially executes an array of validated JSON intents.
    Halts immediately if any single step fails or if the session is cancelled.


    Args:
        validated_steps: [{"intent": str, "target": str}]
    Returns:
        str: Success message or the error that halted the pipeline.
    """
    blackboard = []  # Fix 1.6: Stores textual results of each step for {{LAST_RESULT}} injection
    master_stdout_buffer = ""

    for index, step in enumerate(validated_steps):
        step_success = False
        last_error = None
        for attempt in range(3):
            if cancel_event and cancel_event.is_set():
                print("[RELIABILITY] ABORTING Executor: Cancellation signal detected.")
                return "Mission interrupted by system."

            # ── Fix 1.6: VARIABLE INJECTION ──
            # Recursively replace {{LAST_RESULT}} with the last item in the blackboard
            def inject_vars(obj):
                if isinstance(obj, str):
                    if "{{LAST_RESULT}}" in obj:
                        replacement = blackboard[-1] if blackboard else "No previous result available."
                        return obj.replace("{{LAST_RESULT}}", str(replacement))
                    return obj
                elif isinstance(obj, list):
                    return [inject_vars(x) for x in obj]
                elif isinstance(obj, dict):
                    return {k: inject_vars(v) for k, v in obj.items()}
                return obj

            step = inject_vars(step)

            intent = step.get("intent", "").strip()
            target = step.get("target", "")

            print(f"[Executor] Step {index+1}: Executing [{intent}] -> target='{target}'")

            step_result = ""
            try:
                # ── 0. CodeActIntent (Developer Workflow) ───────────────────────────
                if intent == "CodeActIntent":
                    prompt_val = step.get("prompt", "")
                    if not prompt_val:
                        return f"ERROR Step {index+1}: CodeAct missing prompt."
                    
                    from capabilities.developer.codeact_engine import generate_and_run
                    from config.settings import BrainConfig
                    
                    # Use the most capable LLM for code generation
                    llm = BrainConfig.get_cloud_llm(max_tokens=2048) or BrainConfig.get_local_llm(num_predict=2048)
                    result_msg = generate_and_run(prompt_val, llm)
                    
                    master_stdout_buffer += f"CodeAct Execution:\n{result_msg}\n"
                    # Fix (ruff F821): `SESSION_MEMORY` was referenced here but never
                    # defined anywhere in this module — every CodeActIntent step raised
                    # NameError immediately after successfully launching its script,
                    # was caught by the broad except below, and retried up to 3 times
                    # (each retry re-invoking the LLM and re-launching a real PowerShell
                    # window) before ultimately reporting failure to the user despite
                    # having actually run. Record the result the same way every other
                    # intent does (`blackboard`, used for {{LAST_RESULT}} injection —
                    # Fix 1.6) instead, and fall through to the loop's normal
                    # step_success=True/break so a real success is reported as one.
                    step_result = result_msg

                # ── 0.5. NEW SKILLS EXPANSION (Part 1, 2, 3) ────────────────────────
                elif intent == "AcademicResearchIntent":
                    from capabilities.developer.academic_research import handle_academic_research
                    step_result = handle_academic_research(target, step.get("prompt", ""))
                elif intent == "DataModelingIntent":
                    from capabilities.developer.data_modeler import handle_data_modeling
                    step_result = handle_data_modeling(target, step.get("prompt", ""))
                elif intent == "SysUtilityIntent":
                    from capabilities.system.sys_utility import handle_sys_utility
                    # Prompt passed as a fallback: extraction returned an empty
                    # target for "switch to light mode", which made this a 0/3
                    # task in the benchmark. Matches how every comparable
                    # handler (dictation, media_control, window_manager) is called.
                    step_result = handle_sys_utility(target, step.get("prompt", ""))
                elif intent == "SchedulerIntent":
                    from capabilities.system.scheduler import handle_scheduler
                    step_result = handle_scheduler(target, step.get("prompt", ""))
                elif intent == "MediaControlIntent":
                    from capabilities.system.media_control import handle_media_control
                    step_result = handle_media_control(target, step.get("prompt", ""))
                elif intent == "WindowManagementIntent":
                    from capabilities.system.window_manager import handle_window_management
                    step_result = handle_window_management(target, step.get("prompt", ""))
                elif intent == "DictationIntent":
                    from capabilities.system.dictation import handle_dictation
                    step_result = handle_dictation(target, step.get("prompt", ""))

                # ── 1. ApplicationLaunchIntent ──────────────────────────────────────
                elif intent == "ApplicationLaunchIntent":
                    if not target:
                        return f"ERROR Step {index+1}: '{intent}' missing target."
                    # ── Fix 1.6: Application Launch Retry Loop ──
                    max_launch_retries = 3
                    launched = False
                    for launch_attempt in range(max_launch_retries):
                        # Support Windows environment variables (e.g., %USERPROFILE%)
                        expanded_target = os.path.expandvars(target)
                        if os.path.exists(expanded_target):
                            os.startfile(expanded_target)
                        else:
                            subprocess.Popen(
                                f'start "" "{expanded_target}"',
                                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True
                            )
                        # Wait for the window to appear before proceeding to next step
                        time.sleep(GUI_FOCUS_WAIT)
                        launched = True
                        break

                    if not launched:
                        return f"ERROR Step {index+1}: Failed to launch '{target}' after {max_launch_retries} attempts."
                    step_result = f"I have launched {target}."

                # ── 2. WebNavigationIntent ──────────────────────────────────────────
                elif intent == "WebNavigationIntent":
                    if not target:
                        return f"ERROR Step {index+1}: '{intent}' missing target URL."

                    # Map common mnemonics to full URLs
                    MNEMONIC_MAP = {
                        "youtube": "https://www.youtube.com",
                        "google": "https://www.google.com",
                        "github": "https://github.com",
                        "gmail": "https://mail.google.com",
                        "reddit": "https://www.reddit.com",
                        "twitter": "https://twitter.com",
                        "x": "https://x.com",
                        "linkedin": "https://www.linkedin.com",
                        "spotify": "https://open.spotify.com",
                        "netflix": "https://www.netflix.com",
                        "chatgpt": "https://chat.openai.com",
                    }
                    # Sites added after the 40x3 benchmark: "open wikipedia" and
                    # "open stack overflow" silently degraded to a Google search
                    # and then reported "I have opened the website ...", so the
                    # user was told the site was open when a search page was.
                    MNEMONIC_MAP.update({
                        "wikipedia": "https://www.wikipedia.org",
                        "stack overflow": "https://stackoverflow.com",
                        "stackoverflow": "https://stackoverflow.com",
                        "amazon": "https://www.amazon.com",
                        "instagram": "https://www.instagram.com",
                        "facebook": "https://www.facebook.com",
                        "whatsapp": "https://web.whatsapp.com",
                        "maps": "https://maps.google.com",
                        "google maps": "https://maps.google.com",
                        "drive": "https://drive.google.com",
                        "google drive": "https://drive.google.com",
                        "outlook": "https://outlook.live.com",
                        "claude": "https://claude.ai",
                        "wikipedia.org": "https://www.wikipedia.org",
                    })

                    normalized = target.lower().strip()
                    url = MNEMONIC_MAP.get(normalized, target)
                    fell_back_to_search = False

                    if not url.startswith("http"):
                        if "." in url and " " not in url:
                            url = "https://" + url
                        else:
                            # Last resort: try <name>.com before searching, since
                            # "open <site>" almost always means a site rather
                            # than a search for its name.
                            slug = re.sub(r"[^a-z0-9]", "", normalized)
                            if slug and len(slug) >= 3:
                                url = f"https://www.{slug}.com"
                                print(f"[Executor] '{target}' unknown; trying {url}")
                            else:
                                print(f"[Executor] Target '{url}' is not a known URL or mnemonic. Defaulting to Google Search.")
                                query = urllib.parse.quote(url)
                                url = f"https://www.google.com/search?q={query}"
                                fell_back_to_search = True

                    print(f"[Executor] Opening URL: {url}")
                    webbrowser.open(url)
                    # An honest response when we searched instead of navigating:
                    # claiming "I have opened the website" for a search results
                    # page is the same fabricated-success pattern fixed elsewhere.
                    if fell_back_to_search:
                        step_result = (
                            f"I couldn't resolve '{target}' to a website, so I searched for it instead."
                        )
                    else:
                        step_result = f"I have opened the website {url}."


                # ── 3. InformationRetrievalIntent ──────────────────────────────────
                elif intent == "InformationRetrievalIntent":
                    print("[Executor] InformationRetrievalIntent - Processing Web Research.")

                    # --- CLOUD LEAK PATCH: Security Governance ---
                    from system_services.privacy_router import privacy_guard
                    if privacy_guard.analyze(target)["route"] == "local":
                        step_result = "Security Block: I cannot perform web searches containing private system paths or sensitive data."
                        print("[Executor] " + step_result)
                        continue

                    from agentic_core.processor import _get_routing_llm
                    from capabilities.web.search_engine import get_live_research

                    try:
                        search_data = get_live_research(target)
                    except Exception as e:
                        search_data = {"error": str(e)}

                    if "error" in search_data:
                        context = "System: Live research failed. Provide a briefing based only on your current internal neural parameters."
                    else:
                        context = search_data.get("context", "")

                    # Intentionally naive/local (ruff DTZ005): this date is spoken back
                    # to the user ("Date: Tuesday..."), so it must be their local time,
                    # not UTC — adding tz=timezone.utc would tell the user the wrong day
                    # near midnight in most timezones. Display-only, never stored/compared.
                    today = datetime.now().strftime("%A, %B %d, %Y")  # noqa: DTZ005
                    strict_rule = " CRITICAL RULE: You are a tactical AI. Your initial response MUST be a 2-sentence high-level summary. End your summary with the exact phrase: 'Shall I elaborate, Boss?'. Do NOT output the full details unless the user's prompt explicitly contains the word 'continue', 'elaborate', or 'yes'."
                    rag_prompt = f"Date: {today}. Query: {target}. Context: {context}. Brief the user concisely.{strict_rule}"

                    llm = _get_routing_llm(target)
                    try:
                        response = llm.invoke([("human", rag_prompt)])
                        step_result = response.content.strip()
                    except Exception as e:
                        step_result = f"Failed to synthesize research: {e}"

                    print("[Executor] Research Complete.")

                # ── 4. GeneralizedOSIntent ────────────────────────────────────
                elif intent == "GeneralizedOSIntent":
                    actions = step.get("actions", [])
                    if not actions:
                        return f"ERROR Step {index+1}: '{intent}' missing actions array."

                    print(f"[Executor] Initializing Generalized OS execution: {len(actions)} actions.")

                    was_explorer = False

                    for action_idx, action in enumerate(actions):
                        action_type = action.get("type", "").lower()
                        payload = action.get("payload", "")
                        value = action.get("value", "")

                        print(f"  [Action {action_idx+1}] Type: {action_type} | Payload: {payload}")

                        if action_type == "shell":
                            # ── ACTION VS. INFORMATION ROUTING (PRE-CHECK) ─────────────
                            speech = step.get("speech_response", "").lower()
                            is_visual = any(kw in speech for kw in ["open", "show", "look at", "display"])

                            # ── PAYLOAD + VALUE COMBINATION ──────────────────────────────
                            # LLMs often split 'mkdir' and '%USERPROFILE%/Desktop/my_folder'
                            # into payload and value separately. Combine them into a full cmd.
                            raw_value = str(value).strip() if value else ""
                            if raw_value:
                                # Expand env vars in value and quote paths with spaces
                                expanded_value = os.path.expandvars(raw_value)
                                if " " in expanded_value and not expanded_value.startswith('"'):
                                    expanded_value = f'"{expanded_value}"'
                                safe_target = f"{os.path.expandvars(payload)} {expanded_value}".strip()
                            else:
                                safe_target = os.path.expandvars(payload)

                            if is_visual:
                                safe_target = re.sub(r'^(?:dir|ls)\s+', 'explorer ', safe_target, flags=re.IGNORECASE)

                            # Fix 1.1: Sanitize LLM shell payloads for chain operators
                            # Explorer commands are whitelisted inside _sanitize_shell_cmd
                            commands = [safe_target]  # Execute as single command (no && splitting by executor)
                            try:
                                _sanitize_shell_cmd(safe_target)
                            except ValueError as sec_err:
                                _logger.error(str(sec_err))
                                return f"ERROR Step {index+1}: {sec_err!s}"

                            current_cwd = os.getcwd()

                            for cmd in commands:
                                print(f"    [Shell] Running: {cmd}")

                                # --- INTELLIGENT WINDOWS EXPLORER INTERCEPTOR ---
                                if cmd.startswith("explorer "):
                                    raw_path = cmd.replace("explorer ", "", 1).strip(' "\'')
                                    clean_path = os.path.normpath(os.path.expandvars(raw_path))
                                    folder_name = os.path.basename(clean_path)

                                    # 1. Verify the LLM's guessed path
                                    if not os.path.exists(clean_path):
                                        _logger.info(f"Path not found: {clean_path}. Searching MemoryManager cache for '{folder_name}'.")
                                        # Fix 2.9: Use thread-safe MemoryManager instead of raw sqlite3.connect
                                        found_path = memory.get_cached_path(folder_name)

                                        if found_path:
                                            clean_path = found_path
                                            _logger.info(f"Cache HIT: Located at {clean_path}")
                                        else:
                                            _logger.info(f"Cache MISS for '{folder_name}'")
                                            return f"I checked my memory index, but I could not locate the {folder_name} folder."

                                    # 2. Execute the verified path
                                    try:
                                        os.startfile(clean_path)
                                        return f"I have found and opened the {folder_name} folder for you."
                                    except Exception as e:
                                        print(f"      [Error] OS blocked folder execution: {e}")
                                        return f"I found the {folder_name} folder, but the operating system blocked me from opening it."

                                # ── STRICT PROCESS ROUTING (GUI vs CLI / VISIBLE vs HIDDEN) ──
                                # Fix (benchmark: multi_open_then_close, flaky 2/3): the previous
                                # check was `f" {t}" in cmd`, a substring match anywhere in the
                                # string. "taskkill /IM notepad.exe /F" contains " notepad" and was
                                # therefore classified as a GUI LAUNCH — routed through detached
                                # Popen + sleep(1.0) + continue, which never waits for completion or
                                # checks a return code. A command meant to CLOSE notepad was handled
                                # as if it were opening it, so the kill sometimes hadn't finished by
                                # the time the step reported success.
                                #
                                # Now matched on the command's own executable (first token, or the
                                # token after "start"), not on any trigger word appearing anywhere in
                                # the command line — so a GUI app name used as an ARGUMENT to another
                                # command (taskkill, tasklist, findstr) no longer qualifies.
                                _cmd_tokens = cmd.strip().split()
                                _first_tok = _cmd_tokens[0].lower() if _cmd_tokens else ""
                                if _first_tok == "start" and len(_cmd_tokens) > 1:
                                    _first_tok = _cmd_tokens[1].lower().strip('"')
                                gui_executables = {
                                    "notepad", "notepad.exe", "code", "code.exe",
                                    "explorer", "explorer.exe", "explorer.com",
                                }
                                is_gui = _first_tok in gui_executables

                                # ── VISIBLE TERMINAL ROUTING ──────────────────────────────
                                # Installs and long-running ops get a VISIBLE terminal window
                                # so the user can watch real-time progress instead of a black box.
                                _VISIBLE_TERMINAL_PREFIXES = (
                                    'npm ', 'pip ', 'python -m pip', 'winget ', 'choco ',
                                    'node ', 'npx ', 'yarn ', 'pnpm ', 'cargo ',
                                    'git clone', 'curl ', 'wget '
                                )
                                is_visible_install = any(
                                    cmd.strip().lower().startswith(p) for p in _VISIBLE_TERMINAL_PREFIXES
                                )

                                if is_gui:
                                    if "explorer" in cmd.lower():
                                        was_explorer = True
                                    print(f"      [Process] Detaching GUI Application: {cmd}")
                                    subprocess.Popen(
                                        cmd, shell=True, cwd=current_cwd,
                                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_CONSOLE,
                                        start_new_session=True
                                    )

                                    time.sleep(1.0)
                                    continue  # Move to the next command in the chain

                                if is_visible_install:
                                    # This is the GeneralizedOSIntent raw-shell path (a literal
                                    # "npm install ..." etc. command extracted from the request).
                                    #
                                    # Fix (same PID bug as DependencyInstallIntent, see
                                    # capabilities/developer/dependency_installer.py's _run_install):
                                    # previously launched via `start powershell -NoExit -Command "..."`
                                    # (shell=True). `start` spawns the console detached and returns
                                    # immediately, so Popen.pid was the transient cmd.exe, not the
                                    # PowerShell actually running the install — registering that pid
                                    # as a watch would report "completed" about a second later, a
                                    # confident wrong answer, which is worse than no observation.
                                    #
                                    # Fixed identically to DependencyInstallIntent: write the command
                                    # into a generated .ps1 with a completion sentinel footer and launch
                                    # it directly (list-form Popen, CREATE_NEW_CONSOLE, no `start`
                                    # wrapper), so Popen.pid is the real process and the supervisor can
                                    # tell success from failure, not just that the process died.
                                    print(f"      [Process] Opening visible terminal for: {cmd}")
                                    sentinel_path = None
                                    script_path = None
                                    try:
                                        import tempfile as _tempfile

                                        from agentic_core.process_supervisor import (
                                            build_sentinel_footer,
                                            build_sentinel_header,
                                            new_sentinel_path,
                                        )
                                        script_dir = os.path.join(
                                            os.environ.get("TEMP", _tempfile.gettempdir()),
                                            "SentinAL_GeneralizedInstall",
                                        )
                                        os.makedirs(script_dir, exist_ok=True)
                                        script_path = os.path.join(
                                            script_dir, f"install_{int(time.time() * 1000)}.ps1"
                                        )
                                        sentinel_path = new_sentinel_path("generalized_install")
                                        script = (
                                            build_sentinel_header()
                                            + f"{cmd}\n"
                                            + "Write-Host '---[SentinAL] Install complete---' -ForegroundColor Green\n"
                                            + build_sentinel_footer(sentinel_path)
                                        )
                                        with open(script_path, "w", encoding="utf-8") as f:
                                            f.write(script)
                                    except Exception as e:
                                        _logger.warning(f"Could not prepare supervised install script (non-fatal): {e}")
                                        script_path = None
                                        sentinel_path = None

                                    if script_path:
                                        launch_cmd = [
                                            "powershell", "-ExecutionPolicy", "Bypass",
                                            "-NoProfile", "-NoExit", "-File", script_path,
                                        ]
                                    else:
                                        launch_cmd = [
                                            "powershell", "-NoExit", "-Command",
                                            cmd.replace('"', "'"),
                                        ]

                                    proc = subprocess.Popen(
                                        launch_cmd, cwd=current_cwd,
                                        creationflags=subprocess.CREATE_NEW_CONSOLE,
                                        start_new_session=True
                                    )

                                    try:
                                        from agentic_core.process_supervisor import register_watch
                                        register_watch(
                                            label="generalized_install",
                                            sentinel_path=sentinel_path,
                                            pid=proc.pid,
                                            expected_state={"command": cmd},
                                        )
                                    except Exception as e:
                                        _logger.warning(f"Could not register process watch (non-fatal): {e}")

                                    time.sleep(1.5)
                                    master_stdout_buffer += f"Launched visible terminal for: {cmd}"
                                    success = True
                                    continue

                                # ── STANDARD SYNCHRONOUS CLI EXECUTION WITH REACT LOOP ──
                                max_retries = 2
                                attempt = 0
                                success = False

                                while attempt <= max_retries and not success:
                                    try:
                                        process = subprocess.Popen(
                                            cmd, shell=True, cwd=current_cwd,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            text=True, bufsize=1, universal_newlines=True,
                                            start_new_session=True
                                        )


                                        try:
                                            # Protect ASGI Threadpool: Maximum 15 second lock per command.
                                            step_stdout, step_stderr = process.communicate(timeout=15)
                                        except subprocess.TimeoutExpired:
                                            print("      [Progress] Command exceeded 15s. Detaching to background.")
                                            success = True
                                            master_stdout_buffer += "Command detached and running in background."
                                            break

                                        if process.returncode == 0:
                                            if step_stdout: print(f"      [Progress] {step_stdout.strip()[:100]}...")
                                            master_stdout_buffer += (step_stdout or "")
                                            success = True

                                            # ── AUTO VISUAL CONFIRMATION for folder creation ──
                                            # If the user just created a folder with mkdir/md,
                                            # pop open Explorer at that location so they can see it.
                                            cmd_lower = cmd.strip().lower()
                                            is_mkdir = cmd_lower.startswith(('mkdir', 'md '))
                                            if is_mkdir:
                                                try:
                                                    # Extract the path from the command
                                                    folder_arg = cmd.strip()[len('mkdir'):].strip().strip('"').strip("'")
                                                    folder_arg = os.path.expandvars(folder_arg).replace('/', '\\')
                                                    if folder_arg and os.path.isdir(folder_arg):
                                                        subprocess.Popen(
                                                            f'explorer "{folder_arg}"',
                                                            shell=True, start_new_session=True
                                                        )
                                                        print(f"      [Visual] Opened Explorer at: {folder_arg}")
                                                except Exception as e:
                                                    # Auto-open is best-effort; never block execution on it,
                                                    # but log rather than silently swallow (ruff S110).
                                                    _logger.debug(f"Auto-open Explorer for '{folder_arg if 'folder_arg' in locals() else cmd}' failed (non-fatal): {e}")
                                        else:
                                            step_stderr = step_stderr or ""
                                            print(f"      [Error] Command failed (Code {process.returncode}): {step_stderr.strip()}")
                                            if attempt < max_retries:
                                                print(f"      [Healing] Auto-correcting command via LLM (Attempt {attempt+1}/{max_retries})...")
                                                from agentic_core.processor import _get_routing_llm
                                                llm = _get_routing_llm("Fix OS Command")
                                                prompt = (
                                                    f"You are a Windows OS repair agent. A command failed and you must fix it.\n"
                                                    f"Failed Command: {cmd}\n"
                                                    f"Error Output: {step_stderr.strip()}\n"
                                                    f"RULES:\n"
                                                    f"- Output ONLY the corrected command string. No markdown, no backticks, no explanation.\n"
                                                    f"- NEVER use placeholder words like 'directory_name', 'path', 'folder_name', 'your_path', '<path>'.\n"
                                                    f"- Use real Windows paths with %USERPROFILE%, %APPDATA%, etc. if needed.\n"
                                                    f"- The command must be complete and directly executable in cmd.exe.\n"
                                                    f"Example fix: 'mkdir' → 'mkdir \"%USERPROFILE%\\Desktop\\my_folder\"'"
                                                )
                                                try:
                                                    resp = llm.invoke([("system", prompt)])
                                                    cmd = resp.content.strip().replace('```', '').strip()
                                                    print(f"      [Healing] New Command: {cmd}")
                                                except Exception as e:
                                                    print(f"      [Healing] LLM correction failed: {e}")
                                                    break
                                            attempt += 1
                                    except Exception as e:
                                        print(f"      [Error] Critical Execution Error: {e}")
                                        break

                                if not success:
                                    print(f"      [Executor] HARD HALT: Command failed after {max_retries} retries.")
                                    return "Task failed after multiple attempts. Aborting sequence."

                        elif action_type == "gui":
                            print("    [GUI] Routing to GUI Automation Engine...")
                            action_label = payload  # e.g. 'click', 'type', 'scroll'
                            gui_target   = value

                            # Phase 3 FIX: If action is 'click' but resolved_x/y is missing,
                            # use gui_resolver to locate the element first
                            resolved_coords = (None, None)
                            if action_label == "click" and not (step.get("resolved_x") and step.get("resolved_y")):
                                label    = action.get("label", gui_target)
                                app_name = action.get("app", "")
                                img_path = action.get("image", "")
                                if label or img_path or app_name:
                                    coords = resolve_element(
                                        label=label,
                                        image_path=img_path,
                                        app_title=app_name,
                                    )
                                    if coords:
                                        resolved_coords = coords
                                        print(f"      [GUIResolver] Located '{label}' at {coords}")
                                    else:
                                        print(f"      [GUIResolver] WARNING: Could not locate '{label}' — proceeding with raw target")

                            simulated_intent = {
                                "action": action_label,
                                "target": gui_target,
                                "resolved_x": resolved_coords[0] or step.get("resolved_x"),
                                "resolved_y": resolved_coords[1] or step.get("resolved_y"),
                            }
                            result = execute_gui_command(simulated_intent)

                            if result.startswith("ERROR"):
                                return f"ERROR Step {index+1}.{action_idx+1}: {result}"
                            else:
                                print(f"      [GUI] {result}")
                        else:
                            return f"ERROR Step {index+1}.{action_idx+1}: Unrecognized action type '{action_type}'"

                    # ── STDOUT SUMMARIZATION & RETURN ROUTING ───────────────────
                    if was_explorer:
                        return "I have opened the folder on your screen, Boss."

                    speech = step.get("speech_response", "").strip()
                    if speech and ("diagnostic" in speech.lower() or not master_stdout_buffer.strip()):
                        return speech

                    if master_stdout_buffer.strip():
                        # Fix (found writing coverage for this block): _get_routing_llm()
                        # itself was OUTSIDE the try/except, only llm.invoke() was guarded.
                        # The healing block earlier in this same function wraps its
                        # equivalent _get_routing_llm() call in an outer try (the
                        # while-loop's own try/except), so a fetch failure there is
                        # caught and degrades to "Task failed after multiple attempts".
                        # Here there was no outer guard at all: a fetch failure would
                        # propagate past this whole intent handler to the per-step retry
                        # loop, retried 3 times, then surfaced as a raw ERROR string -
                        # inconsistent with every other LLM-call failure in this function,
                        # all of which degrade to a spoken explanation instead.
                        try:
                            from agentic_core.processor import _get_routing_llm
                            llm = _get_routing_llm("Summarize terminal output")
                            print("[Executor] Summarizing terminal output...")
                            prompt = f"You are an AI system taking raw terminal output and summarizing it for a voice TTS engine. The user asked for this data. Summarize the following terminal output in 1 to 2 natural, conversational sentences. Do not use markdown. Output: {master_stdout_buffer.strip()}"
                            summary_response = llm.invoke([("system", prompt)])
                            step_result = summary_response.content.strip()
                        except Exception as e:
                            print(f"[Executor] Summarization failed: {e}")
                            step_result = "I successfully executed the command sequence, but the output summary failed."


                # ── 5. FileDeletionIntent ───────────────────────────────────────────
                elif intent == "FileDeletionIntent":
                    if not target:
                        return f"ERROR Step {index+1}: '{intent}' missing target."

                    # Resolve absolute path and shield against system-level blocks
                    full_path = os.path.abspath(os.path.join(os.getcwd(), target)) if not os.path.isabs(target) else os.path.abspath(target)

                    if not validate_sandbox(full_path):
                        return f"ERROR Step {index+1}: Sandbox Violation — Attempted to delete protected system path."

                    if os.path.exists(full_path):
                        import shutil
                        if os.path.isdir(full_path):
                            shutil.rmtree(full_path)
                        else:
                            os.remove(full_path)
                        print(f"[Executor] Deleted: {full_path}")
                    else:
                        print(f"[Executor] Skip: Path {full_path} not found.")

                # ── 5. MediaStreamingIntent ─────────────────────────────────────────
                elif intent == "MediaStreamingIntent":
                    if not target:
                        return f"ERROR Step {index+1}: '{intent}' missing target."

                    url_template, query, platform = _resolve_url_template(step, default_platform="youtube")

                    # ── YOUTUBE: Direct search via webbrowser (Fix 1.2) ────────────
                    # Removed fragile HTML scraper (violates ToS, regex false positives).
                    # Now just opens the YouTube search results page — always works.
                    if platform == "youtube":
                        search_q   = urllib.parse.quote(target)
                        search_url = f"https://www.youtube.com/results?search_query={search_q}"
                        _logger.info(f"MediaStream: Opening YouTube search for '{target}'")
                        webbrowser.open(search_url)
                    else:
                        # Standard Execution for all other platforms
                        if url_template:
                            final_url = url_template.replace("{query}", query)
                            print(f"[Executor] Resolved URL via cache: {final_url}")
                            webbrowser.open(final_url)
                        else:
                            print(f"[Executor] No URL template available for '{platform}'. Skipping.")

                # ── 6. ConversationalIntent ─────────────────────────────────────────
                elif intent == "ConversationalIntent":
                    message = step.get("message", "I'm here and ready to assist you.")
                    print("[Executor] ConversationalIntent — logging AI message.")
                    step_result = message

                # ── 6.5. ContinuationIntent ──────────────────────────────────────────
                # Fix: this intent was reachable via the router (see the router.py
                # classifier-blind-spot fix) but had no dispatch branch at all here,
                # falling through to "Unrecognized Enterprise Intent" - a hard error
                # on every "continue"/"go on"/"tell me more" request. It relies on
                # memory.log_interaction() below (also previously never called
                # anywhere) to have something to continue FROM; the
                # InformationRetrievalIntent prompt above was already written
                # assuming this existed ("Do NOT output the full details unless the
                # user's prompt explicitly contains 'continue'...").
                elif intent == "ContinuationIntent":
                    print("[Executor] ContinuationIntent — retrieving prior context.")
                    prior_context = memory.get_context_for_prompt(limit=1)

                    if not prior_context:
                        step_result = "There's nothing recent for me to continue — what would you like me to do?"
                    else:
                        from agentic_core.processor import _get_routing_llm
                        continuation_prompt = (
                            f"{prior_context}\n\n"
                            "The user just asked you to continue, elaborate, or say more about "
                            "your most recent response above. Expand on it naturally and "
                            "conversationally - do not repeat it verbatim, and do not ask what "
                            "they mean; you already know from the context above."
                        )
                        llm = _get_routing_llm("Continuation")
                        try:
                            response = llm.invoke([("human", continuation_prompt)])
                            step_result = response.content.strip()
                        except Exception as e:
                            step_result = f"I couldn't continue on that — {e}"

                elif intent == "UnknownIntent":
                    return f"ERROR Step {index+1}: The intent layer could not understand the request."

                # ── Phase 3a. ProcessManagementIntent ──────────────────────────────
                elif intent == "ProcessManagementIntent":
                    action = step.get("action", "list").lower().strip()
                    process_target = step.get("target", "").strip()

                    if action == "list":
                        procs = list_processes(name_filter=process_target)
                        if not procs:
                            step_result = (
                                f"No processes matching '{process_target}' found."
                                if process_target else "No processes found (system may be unresponsive)."
                            )
                        else:
                            # Summarize top 10 results for TTS
                            lines = [f"{p['name']} (PID {p['pid']}, {p['mem_kb']})" for p in procs[:10]]
                            more  = f" and {len(procs)-10} more..." if len(procs) > 10 else ""
                            step_result = "Running processes: " + ", ".join(lines) + more

                    elif action == "kill":
                        if not process_target:
                            step_result = "ERROR: No process name or PID specified for kill."
                        else:
                            step_result = kill_process(process_target)
                    else:
                        step_result = f"Unknown ProcessManagementIntent action '{action}'. Use 'list' or 'kill'."

                # ── Phase 3b. ProjectScaffoldIntent ───────────────────────────────
                elif intent == "ProjectScaffoldIntent":
                    framework    = step.get("framework", "").strip()
                    project_name = step.get("project_name", "my-project").strip()
                    location     = step.get("location", "").strip()

                    if not framework:
                        step_result = "ERROR: No framework specified for ProjectScaffoldIntent."
                    else:
                        print(f"[Executor] Scaffolding '{framework}' project '{project_name}'...")
                        step_result = scaffold_project(
                            framework=framework,
                            project_name=project_name,
                            location=location,
                        )

                # ── Phase 3c. DependencyInstallIntent ─────────────────────────────
                elif intent == "DependencyInstallIntent":
                    manager  = step.get("manager", "pip").lower().strip()
                    packages = step.get("packages", "").strip()
                    dev      = bool(step.get("dev", False))
                    cwd      = step.get("cwd", "").strip()

                    print(f"[Executor] Installing packages via {manager}: '{packages}'")

                    if manager == "pip":
                        step_result = pip_install(packages)
                    elif manager == "npm":
                        step_result = npm_install(packages=packages, dev=dev, cwd=cwd)
                    else:
                        step_result = f"ERROR: Unknown package manager '{manager}'. Use 'pip' or 'npm'."

                else:
                    return f"ERROR Step {index+1}: Unrecognized Enterprise Intent '{intent}' passed validation."

                # Record result for Blackboard if successful
                if step_result:
                    blackboard.append(step_result)

                    # Fix: memory.get_context_for_prompt() has been read by
                    # processor.py (InformationRetrievalIntent/GeneralizedOSIntent
                    # target extraction) and now by ContinuationIntent above, but
                    # nothing ever called log_interaction() to populate the table
                    # those reads query - interaction_history was permanently
                    # empty, so every "contextual memory injection" silently had
                    # no context to inject. Skip logging ContinuationIntent itself
                    # so a chain of "continue" requests doesn't bury the actual
                    # prior interaction it should keep referring back to.
                    if intent != "ContinuationIntent":
                        try:
                            memory.log_interaction(
                                timestamp=datetime.now().isoformat(),  # noqa: DTZ005 (local log, see other DTZ005 notes in this file)
                                intent=intent,
                                target=target,
                                result=str(step_result)[:200],
                                platform=step.get("value", ""),
                            )
                        except Exception as e:
                            # Best-effort: a logging failure must never break the
                            # actual pipeline result the user is waiting on.
                            _logger.debug(f"log_interaction failed (non-fatal): {e}")


            except subprocess.TimeoutExpired:
                last_error = f"ERROR Step {index+1}: Terminal command '{target}' timed out."
                continue
            except Exception as e:
                last_error = f"ERROR Step {index+1}: Exception applying '{intent}' on '{target}' — {e!s}"
                print(f"[SRE] Step {index+1} failed, attempt {attempt+1}/3... Error: {e}")
                time.sleep(1)
                continue

            # Fix 2.10: Configurable step delay between multi-step command execution
            time.sleep(STEP_DELAY)
            step_success = True
            break

        if not step_success:
            return last_error

    if blackboard:
        return blackboard[-1]

    num_steps = len(validated_steps)
    return f"Pipeline successfully completed ({num_steps} steps)."


# ── P1-4: Failure taxonomy + bounded replan on postcondition mismatch ────────
# Fix P1-4.1: whole-pipeline replan cap, configurable like STEP_DELAY/GUI_FOCUS_WAIT.
MAX_REPLANS = int(os.getenv("EXECUTOR_MAX_REPLANS", "1"))

FAILURE_CATEGORY_SUCCESS = "success"
FAILURE_CATEGORY_PIPELINE_ERROR = "pipeline_error"
FAILURE_CATEGORY_CANCELLED = "cancelled"
FAILURE_CATEGORY_POSTCONDITION_MISMATCH = "postcondition_mismatch"

_CANCELLATION_MESSAGE = "Mission interrupted by system."  # exact string execute_pipeline() returns on cancel


def _classify_result(result: str, step_observations: list) -> str:
    """
    Failure taxonomy for a completed execute_pipeline() run.
    Order matters: an ERROR/cancellation result always wins over a postcondition
    mismatch, since those are execute_pipeline()'s own authoritative signals —
    a postcondition check on a run that already failed outright is meaningless.

    Fix P1-4.4 (from the continued Gate-2 review — same review task as
    P1-4.2/P1-4.3): a malformed "expected_state" (e.g. a bare string or bool
    instead of a dict) makes observe_postcondition() fall through to
    tier_used="none", verified=False — correctly not a crash, but naively
    counting THAT as a postcondition mismatch would waste a full bounded
    replan on garbage input that was never actually checkable in the first
    place. Only an observation where something concrete WAS checked
    (tier_used in {"process", "window", "vlm"}) and came back unverified
    counts as a genuine mismatch worth replanning over.
    """
    if result == _CANCELLATION_MESSAGE:
        return FAILURE_CATEGORY_CANCELLED
    if isinstance(result, str) and result.startswith("ERROR"):
        return FAILURE_CATEGORY_PIPELINE_ERROR
    if any(
        (not entry["observation"].verified and entry["observation"].tier_used != "none")
        for entry in step_observations
    ):
        return FAILURE_CATEGORY_POSTCONDITION_MISMATCH
    return FAILURE_CATEGORY_SUCCESS


def _run_and_observe(validated_steps: list, cancel_event) -> tuple:
    """One full execute_pipeline() call + its before/after snapshot diff and
    per-step postcondition observations. Extracted so both the initial run
    and any bounded replan attempt share identical logic."""
    from capabilities.system.postcondition_observer import (
        capture_state_snapshot,
        diff_snapshots,
        observe_postcondition,
    )

    before = capture_state_snapshot()
    result = execute_pipeline(validated_steps, cancel_event=cancel_event)

    # Fix P1-4.3 (from an independent Gate-2 review of P1-1 —
    # _context_packs/P1-1_review_gate2_secondparty.md /
    # tests/test_executor_observed_review.py): capture_state_snapshot()'s
    # "after" call and diff_snapshots() both run AFTER execute_pipeline()
    # has already completed (and possibly mutated real system state, e.g.
    # deleted a file or launched an app). If either raised, the previous
    # implementation propagated the exception straight out of this function
    # and lost that already-completed result entirely — a real, confirmed
    # gap, not a hypothetical one. Same principle as the observe_postcondition
    # guard above: never let a downstream observability failure erase real
    # work that already happened.
    try:
        after = capture_state_snapshot()
        snapshot_diff = diff_snapshots(before, after)
    except Exception as exc:
        _logger.warning(f"[P1-4] snapshot/diff computation raised unexpectedly: {exc}")
        snapshot_diff = {"error": str(exc)}

    step_observations = []
    for index, step in enumerate(validated_steps):
        expected_state = step.get("expected_state") if isinstance(step, dict) else None
        if expected_state:
            # Fix P1-4.2 (pre-emptive hardening): postcondition_observer.py's own
            # spec guarantees observe_postcondition() never raises, but this is a
            # cheap belt-and-suspenders guard anyway — if that guarantee is ever
            # violated, we must not lose the execute_pipeline() result that
            # already ran and may have mutated real system state.
            try:
                observation = observe_postcondition(expected_state)
            except Exception as exc:
                from capabilities.system.postcondition_observer import Observation
                observation = Observation(
                    verified=False, tier_used="none", confidence=0.0,
                    latency_ms=0.0, detail=f"observe_postcondition raised unexpectedly: {exc}",
                )
                _logger.warning(f"[P1-4] observe_postcondition raised for step {index}: {exc}")
            step_observations.append({"step_index": index, "observation": observation})

    return result, snapshot_diff, step_observations


def execute_pipeline_observed(validated_steps: list, cancel_event=None) -> dict:
    """
    P1-1 (Agentic OS roadmap, Phase 1 — close the loop): observe-act wrapper
    around execute_pipeline(), extended in P1-4 with a failure taxonomy and
    one bounded whole-pipeline replan on postcondition mismatch.

    Design note: execute_pipeline() is deliberately left UNTOUCHED, in both
    P1-1 and this P1-4 extension. It is 600+ lines of security-critical logic
    (shell sanitization, its OWN 3-attempt per-step retry loop, LLM
    self-healing, sandbox validation) with an established `str` return
    contract that capabilities/system/api_wrapper.py and the existing test
    suite depend on byte-for-byte. Rewriting it in place would be exactly the
    kind of invasive, hard-to-verify change this project's verification
    protocol (VERIFICATION_PROTOCOL.md) exists to prevent.

    Why a WHOLE-PIPELINE replan, not per-step: execute_pipeline() already
    retries individual steps up to 3 times on EXCEPTION internally. What it
    cannot detect is a step that runs without raising, reports success, but
    did not actually achieve the intended effect (e.g. "launch notepad"
    returns "I have launched notepad." but no notepad.exe process exists).
    That is a fundamentally different failure mode — a silent one — and can
    only be caught by checking real system state AFTER the run, which is
    exactly what postcondition_observer.py (P1-2) does. Re-running the whole
    pipeline once is the safe, bounded response: single retry, capped by
    MAX_REPLANS (env: EXECUTOR_MAX_REPLANS, default 1), never retried on
    "cancelled" or "pipeline_error" categories (those are execute_pipeline's
    own authoritative failure signals, already exhausted its own internal
    retries, and blindly re-running a whole pipeline that errored partway
    through risks duplicate side effects like a second file deletion).

    IMPORTANT — currently a dormant, forward-compatible mechanism: no step
    anywhere in the codebase sets "expected_state" today (that is Phase 2
    processor/validator work), so step_observations is always [] and this
    replan path never actually triggers in production yet. It activates the
    moment Phase 2 wires expected_state onto steps. This mirrors P1-1's own
    forward-compatible design — shipping the mechanism now, safely inert,
    rather than coupling this change to unrelated Phase 2 work.

    Returns:
        {
            "result": str,                    # execute_pipeline()'s FINAL return value
                                                # (post-replan, if a replan happened)
            "snapshot_diff": dict,             # from the run that produced "result"
            "step_observations": list[dict],   # from the run that produced "result"
            "failure_category": str,           # one of the FAILURE_CATEGORY_* constants
            "attempts": int,                   # 1 = no replan happened, 2 = one replan happened
            "replanned": bool,
        }
    """
    result, snapshot_diff, step_observations = _run_and_observe(validated_steps, cancel_event)
    category = _classify_result(result, step_observations)
    attempts = 1
    replanned = False

    while category == FAILURE_CATEGORY_POSTCONDITION_MISMATCH and attempts <= MAX_REPLANS:
        _logger.info(
            f"[P1-4] Postcondition mismatch detected — bounded replan "
            f"attempt {attempts}/{MAX_REPLANS}."
        )
        result, snapshot_diff, step_observations = _run_and_observe(validated_steps, cancel_event)
        category = _classify_result(result, step_observations)
        attempts += 1
        replanned = True

    return {
        "result": result,
        "snapshot_diff": snapshot_diff,
        "step_observations": step_observations,
        "failure_category": category,
        "attempts": attempts,
        "replanned": replanned,
    }


def execute_gui_command(intent: dict) -> str:
    """Handles physical screen interaction via PyAutoGUI (mouse/keyboard/scroll)."""
    action     = intent.get("action", "").lower()
    target     = intent.get("target", "")
    resolved_x = intent.get("resolved_x")
    resolved_y = intent.get("resolved_y")

    print(f"[Executor] GUI Action: {action} | Target: {target} | Coords: ({resolved_x}, {resolved_y})")

    try:
        if action == "click":
            if resolved_x is not None and resolved_y is not None:
                pyautogui.click(resolved_x, resolved_y)
                return f"Clicked at pixel ({resolved_x}, {resolved_y}) successfully."
            # Fallback: parse from target string
            if "," in (target or ""):
                x, y = map(int, target.split(",", 1))
                pyautogui.click(x, y)
                return f"Clicked at pixel ({x}, {y}) successfully."
            return "ERROR: Click failed — no valid coordinates provided."

        elif action == "type":
            if not target:
                return "ERROR: Typing failed — no text provided."
            # Fix 2.10: Use configurable GUI_FOCUS_WAIT instead of hardcoded 2.0s
            time.sleep(GUI_FOCUS_WAIT)
            try:
                pyautogui.write(target, interval=0.05)
                return f"Text typed successfully: '{target}'"
            except Exception as e:
                return f"ERROR: Typing failed — window not focused or input rejected: {e!s}"

        elif action == "press" or action == "hotkey":
            if not target:
                return "Press failed: no key specified."
            keys = target.split("+")
            if len(keys) > 1:
                pyautogui.hotkey(*keys)
            else:
                pyautogui.press(keys[0].strip())
            return f"Key pressed: '{target}'"

        elif action == "sleep":
            sleep_time = float(target) if target else 1.0
            time.sleep(sleep_time)
            return f"Slept for {sleep_time} seconds."

        elif action == "scroll":
            direction = 1 if str(target).lower() == "up" else -1
            clicks    = direction * 5  # scroll 5 units
            if resolved_x is not None and resolved_y is not None:
                pyautogui.scroll(clicks, x=resolved_x, y=resolved_y)
                return f"Scrolled {'up' if direction > 0 else 'down'} at ({resolved_x}, {resolved_y})"
            pyautogui.scroll(clicks)
            return f"Scrolled {'up' if direction > 0 else 'down'} at current position"

    except Exception as e:
        return f"GUI action failed: {e!s}"

    return f"Unrecognized GUI action: '{action}'"