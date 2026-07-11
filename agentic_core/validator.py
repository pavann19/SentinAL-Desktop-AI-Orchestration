import os
import re
import logging

from config.paths import LOGS_DIR  # Resolves to AppData\SentinAL\logs in prod

# ── Logging Setup ────────────────────────────────────────────────────────────
security_logger = logging.getLogger("SecurityAudit")
security_logger.setLevel(logging.WARNING)
if not security_logger.handlers:
    _handler = logging.FileHandler(os.path.join(LOGS_DIR, "security_audit.log"))
    _handler.setFormatter(logging.Formatter('%(asctime)s - [AUDIT] - %(message)s'))
    security_logger.addHandler(_handler)

# ── Import Centralized OS Policies ────────────────────────────────────────────
from config.constants import ALLOWLIST_INTENTS, BLOCKED_KEYS, SENSITIVE_TARGETS, SENSITIVE_CMD_WORDS, SOFT_SENSITIVE_TARGETS


def validate_sandbox(target_path: str) -> bool:
    """
    Ensures that critical Windows system directories and executables are protected.
    Uses os.path.realpath to resolve symlinks and prevent traversal attacks.
    Also checks against the SENSITIVE_TARGETS and SOFT_SENSITIVE_TARGETS policy lists.
    """
    if not target_path:
        return True

    try:
        # 1. Expand env vars, normalize, resolve symlinks
        expanded_path = os.path.expandvars(target_path)
        full_path     = os.path.realpath(os.path.normpath(expanded_path))
        full_path_lower = full_path.lower()
        expanded_lower  = expanded_path.lower()

        # 2a. Fix [bare-drive-root]: block any path that resolves to an entire
        # drive root (e.g. "C:\", "D:\", "C:/"). Discovered 2026-07-11 via the
        # expanded eval task suite: "format the C drive" was only failing to
        # cause damage because the LLM extracted the literal string "c drive"
        # (a benign nonexistent relative path), NOT because this function
        # would have blocked a real drive-root path. Neither SENSITIVE_TARGETS
        # nor SOFT_SENSITIVE_TARGETS contains a bare-drive pattern, so if the
        # LLM ever extracts an actual root path verbatim, FileDeletionIntent's
        # shutil.rmtree(full_path) would have nothing standing in its way.
        # os.path.splitdrive returns ('C:', '') or ('C:', '\\') for a bare
        # root — no third path component — which is the deterministic signal
        # we check for, independent of what drive letter or slash style was used.
        drive, remainder = os.path.splitdrive(full_path)
        if drive and remainder in ("", "\\", "/"):
            security_logger.warning(
                f"SANDBOX BLOCK (DRIVE-ROOT): Denied operation on bare drive root: {full_path}"
            )
            return False

        # 2b. Block Windows system directories via path check
        for system_dir in ["windows\\", "system32"]:
            if system_dir in full_path_lower:
                security_logger.warning(
                    f"SYSTEM ACCESS DENIED: AI attempted sensitive path: {full_path}"
                )
                return False

        # 3. Block known dangerous executables/commands from SENSITIVE_TARGETS policy
        for pattern in SENSITIVE_TARGETS:
            if pattern.strip().lower() in expanded_lower:
                security_logger.warning(
                    f"SANDBOX BLOCK: Sensitive target pattern '{pattern}' matched in: {expanded_path}"
                )
                return False

        # FIX 4: Also block SOFT_SENSITIVE_TARGETS — these are dangerous executables
        # (regedit.exe, eventvwr, gpedit, etc.) that must never execute via sandbox
        for pattern in SOFT_SENSITIVE_TARGETS:
            if pattern.strip().lower() in expanded_lower:
                security_logger.warning(
                    f"SANDBOX BLOCK (SOFT-GUARD): Soft-sensitive target '{pattern}' matched in: {expanded_path}"
                )
                return False

        return True
    except Exception as e:
        security_logger.error(f"VALIDATION ERROR: Internal sandbox check error: {e}")
        return False



def validate_steps(steps: list) -> tuple[bool, str, bool]:
    """
    Validates an entire array of JSON execution steps.
    Returns: (is_approved, reason, requires_confirmation)

    V2.0 Fixes:
    - Fix 1.6: Env-var paths (%USERPROFILE%\\path) now caught even without quotes
    - Fix 3.1: SENSITIVE_CMD_WORDS checked with \\b word boundaries (no double-space bypass)
    - Fix 3.2: BLOCKED_KEYS now enforced on GUI press/hotkey actions
    - Removed dead MODE = 'development' variable
    """
    if not steps or not isinstance(steps, list):
        return False, "[Security Error] Empty or invalid step array received.", False

    total_requires_confirmation = False

    for i, step in enumerate(steps):
        intent = step.get("intent", "").strip()
        target = step.get("target", "").lower().strip()

        # ── Fix 1.7: INTENT ALIASING (Synonym Mapping) ──
        # Maps LLM variations or older naming conventions to the canonical allowlist.
        INTENT_ALIASES = {
            "open_application": "ApplicationLaunchIntent",
            "launch_app": "ApplicationLaunchIntent",
            "open_app": "ApplicationLaunchIntent",
            "search_web": "InformationRetrievalIntent",
            "web_search": "InformationRetrievalIntent",
            "get_info": "InformationRetrievalIntent",
            "navigate_to": "WebNavigationIntent",
            "open_url": "WebNavigationIntent",
            "stream_media": "MediaStreamingIntent",
            "play_media": "MediaStreamingIntent"
        }
        if intent in INTENT_ALIASES:
            old_intent = intent
            intent = INTENT_ALIASES[intent]
            step["intent"] = intent  # Update in-place for later pipeline steps
            security_logger.info(f"Aliased synonym intent '{old_intent}' -> '{intent}'")

        # 1. Intent Allowlist Check
        if intent not in ALLOWLIST_INTENTS:
            return False, f"[Security Error] Denied Step {i+1}: Intent '{intent}' is forbidden.", False

        # 2. Target Required for certain critical intents
        # We allow MediaStreaming and InformationRetrieval to pass WITHOUT a target here,
        # because the Processor will fallback to using the prompt if extraction failed.
        TARGET_REQUIRED = {"ApplicationLaunchIntent", "WebNavigationIntent", "FileDeletionIntent"}
        if intent in TARGET_REQUIRED and not target:
            return (False,
                    f"[Security Error] Denied Step {i+1}: Intent '{intent}' requires a target for safety.",
                    False)

        # 3. Informational/Media intents: warn but allow if target missing (Processor will handle fallback)
        SOFT_TARGET_REQUIRED = {"MediaStreamingIntent", "InformationRetrievalIntent"}
        if intent in SOFT_TARGET_REQUIRED and not target:
            security_logger.info(f"Target missing for soft-intent '{intent}'. Proceeding with prompt fallback.")

        # 3. FileDeletion signals confirmation needed
        if intent == "FileDeletionIntent":
            total_requires_confirmation = True

        # 4. Sensitive keyword check on target (Hard Block)
        for keyword in SENSITIVE_TARGETS:
            if keyword in target:
                security_logger.warning(f"BLOCKLIST MATCH (HARD): '{keyword}' in target '{target}'")
                return False, f"[Security Error] Denied Step {i+1}: Strict policy prevents accessing '{keyword}'.", False

        # 5. Soft Sensitive keyword check
        # Fix 1.7 (updated): Block for destructive/execution intents, warn-only for informational ones.
        # ApplicationLaunchIntent must be blocked (can't launch exe from system32)
        # FileDeletionIntent must be blocked (can't delete system files)
        # InformationRetrievalIntent / WebNavigationIntent — warn only (safe to mention)
        SOFT_BLOCK_INTENTS = {"ApplicationLaunchIntent", "FileDeletionIntent", "GeneralizedOSIntent"}
        for keyword in SOFT_SENSITIVE_TARGETS:
            if keyword in target:
                if intent in SOFT_BLOCK_INTENTS:
                    security_logger.warning(f"BLOCKLIST MATCH (SOFT-GUARD EXEC): Blocked '{intent}' for '{keyword}'")
                    return False, f"[Security Error] Denied Step {i+1}: Execution involving '{keyword}' is unsafe.", False
                else:
                    security_logger.info(f"Policy Warning: Read-only reference to soft-sensitive keyword '{keyword}' in target '{target}'.")

        # 5. Fix 3.1: Regex word-boundary check for dangerous delete/remove commands
        for cmd_word in SENSITIVE_CMD_WORDS:
            if re.search(rf'\b{re.escape(cmd_word)}\b', target):
                security_logger.warning(f"CMD WORD MATCH: '\\b{cmd_word}\\b' in target '{target}'")
                return False, f"[Security Error] Denied Step {i+1}: Dangerous command '{cmd_word}' detected.", False

        # 6. Sandbox + shell command checks for OS intents
        if intent == "GeneralizedOSIntent":
            actions = step.get("actions", [])
            for action_idx, action in enumerate(actions):
                action_type = action.get("type", "").lower()
                payload     = action.get("payload", "")
                payload_lower = payload.lower()

                if action_type == "shell":
                    # 6a. Keyword scan inside shell commands
                    for keyword in SENSITIVE_TARGETS:
                        if keyword in payload_lower:
                            security_logger.warning(
                                f"BLOCKLIST: '{keyword}' in shell cmd '{payload_lower[:80]}'"
                            )
                            return (False,
                                    f"[Security Error] Step {i+1}.{action_idx+1}: Keyword '{keyword}'.",
                                    False)

                    # 6b. Fix 3.1: Word-boundary dangerous command check
                    for cmd_word in SENSITIVE_CMD_WORDS:
                        if re.search(rf'\b{re.escape(cmd_word)}\b', payload_lower):
                            security_logger.warning(
                                f"CMD WORD: '\\b{cmd_word}\\b' in '{payload_lower[:80]}'"
                            )
                            return (False,
                                    f"[Security Error] Step {i+1}.{action_idx+1}: Command '{cmd_word}'.",
                                    False)

                    # 6c. Fix 1.6: Expanded path extraction — catches bare %VAR%\path patterns
                    # Matches: "C:\path", '%VAR%\path', '/unix/path', quoted variants
                    path_pattern = (
                        r'["\']?(%[^%]+%(?:\\[^"\'&|;]*)?'   # %VAR%\path  (unquoted)
                        r'|[a-zA-Z]:\\[^"\'&|;]*'            # C:\path
                        r'|/[^"\'&|;]+)["\']?'               # /unix/path
                    )
                    path_match = re.search(path_pattern, payload, re.IGNORECASE)
                    if path_match:
                        raw_path = path_match.group(1).strip().strip('"').strip("'")
                        expanded  = os.path.expandvars(raw_path)
                        if not validate_sandbox(expanded):
                            return (False,
                                    f"[Security Error] Step {i+1}.{action_idx+1}: Sandbox violation: {expanded}",
                                    False)

                # 6d. Fix 3.2: Apply BLOCKED_KEYS for GUI press/hotkey actions
                elif action_type in ("press", "hotkey"):
                    value = action.get("value", "") or action.get("payload", "")
                    keys_pressed = [k.strip().lower() for k in str(value).split("+")]
                    blocked = BLOCKED_KEYS.intersection(set(keys_pressed))
                    if blocked:
                        security_logger.warning(
                            f"BLOCKED_KEYS: {blocked} attempted via GUI {action_type}"
                        )
                        return (False,
                                f"[Security Error] Step {i+1}.{action_idx+1}: Blocked key(s) {blocked}.",
                                False)

        # 7. FileDeletion sandbox check on target path
        if intent == "FileDeletionIntent":
            if not validate_sandbox(target):
                return (False,
                        f"[Security Error] Denied Step {i+1}: Sandbox violation on deletion.",
                        False)

    return True, "Approved", total_requires_confirmation
