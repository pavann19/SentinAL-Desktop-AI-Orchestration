# Policy and evaluation constants.
EMBEDDING_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
# Unified OS Governance and Policies for SentinAL

# ── Allowlist: Supported intent allowlist ──────────────
ALLOWLIST_INTENTS = {
    "ApplicationLaunchIntent",
    "WebNavigationIntent",
    "InformationRetrievalIntent",
    "GeneralizedOSIntent",
    "MediaStreamingIntent",
    "FileDeletionIntent",
    "ConversationalIntent",      # General chat — no OS permissions required
    "ContinuationIntent",        # Memory / Context expansion
    "ProcessManagementIntent",
    "ProjectScaffoldIntent",
    "DependencyInstallIntent",
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
    "icacls",
    "diskpart",
    "bcdedit",
    "wevtutil",
]


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
