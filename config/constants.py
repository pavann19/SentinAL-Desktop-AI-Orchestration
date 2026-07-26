# policy_registry.py
# Unified OS Governance and Policies for SentinAL

# ── Allowlist: Only these Enterprise NLP Intents are permitted ──────────────
ALLOWLIST_INTENTS = {
    "ApplicationLaunchIntent",
    "WebNavigationIntent",
    "InformationRetrievalIntent",
    "GeneralizedOSIntent",
    "MediaStreamingIntent",
    "FileDeletionIntent",
    "ConversationalIntent",      # General chat — no OS permissions required
    "ContinuationIntent",        # Memory / Context expansion
    "ProcessManagementIntent",   # Phase 3: tasklist + safe taskkill
    "ProjectScaffoldIntent",     # Phase 3: npx / create-react-app style flows
    "DependencyInstallIntent",   # Phase 3: npm install / pip install
    "CodeActIntent",             # Advanced CodeAct LLM scripts for complex tasks
    "AcademicResearchIntent",    # Academic PDF analysis
    "DataModelingIntent",        # Pandas/SciKit EDA
    "SysUtilityIntent",          # Dark mode, bin, display, mic
    "SchedulerIntent",           # Tasks, planning, holidays, defense
    "MediaControlIntent",        # Pycaw volume, play/pause
    "WindowManagementIntent",    # Snap windows, virtual desktops, screenshot
    "DictationIntent",           # Hands-free universal typing
    "UnknownIntent"
}

# ── Blocked Keys: Dangerous OS-level keystrokes ────────────────────────────────
# Relaxed (Fix 1.7): Removed 'win' and 'alt' to allow desktop navigation shortcuts
BLOCKED_KEYS = {'f4', 'del', 'esc', 'ctrl'}

# ── Sensitive keywords: Any command target containing these strings is blocked ─
SENSITIVE_TARGETS = [
    "hosts",
    "boot",
    "bios",
    "format ",
    "shutdown",
    "rmdir",
    "reg delete",
    "net stop",
    "vssadmin",
    # NOTE: 'taskkill' removed from SENSITIVE_TARGETS — Phase 3 ProcessManagementIntent
    # handles it safely via process_manager.py with its own protected-process guard.
    "icacls",
    "diskpart",
    "bcdedit",
    "wevtutil",
]


# ── Soft Sensitive keywords: These trigger a WARNING but are ALLOWED (unless deleting) ──
# (Fix 1.7): Moved system-level browsing keywords here to allow exploration
SOFT_SENSITIVE_TARGETS = [
    "system32",
    "\\windows\\",
    "\\windows",
    "registry",
    "regedit",
    "eventvwr",
    "gpedit",
    "secpol",
]

# ── Regex-validated dangerous commands (checked with \b word boundaries) ──────
# These are checked separately in validator.py with re.search(rf'\b{cmd}\b')
# rather than simple 'in' matching, preventing 'del  file' (double-space) bypass
SENSITIVE_CMD_WORDS = [
    "del",
    "rd",
    "rm",
]
