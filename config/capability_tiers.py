
T0 = "T0"
T1 = "T1"
T2 = "T2"
T3 = "T3"

VALID_TIERS = (T0, T1, T2, T3)

# ── Default tier per intent ──────────────────────────────────────────────────
INTENT_TIERS: dict[str, str] = {
    # T0 — read-only / conversational, no OS-state change
    "ConversationalIntent": T0,       # pure chat
    "ContinuationIntent": T0,         # memory/context expansion, no side effect
    "InformationRetrievalIntent": T0, # web search, read-only

    # T1 — low-harm, trivially reversible
    "ApplicationLaunchIntent": T1,    # fixed application names; other launches are T3
    "WebNavigationIntent": T1,        # opens a browser tab; undo = close it
    "MediaStreamingIntent": T1,       # opens a media page; undo = close it
    "MediaControlIntent": T1,         # volume/playback virtual keys; transient
    "WindowManagementIntent": T1,     # snap/minimize/screenshot; reversible or additive
    "SchedulerIntent": T1,            # writes a SQLite reminder row; undo = cancel it
    "DataModelingIntent": T1,         # reads a CSV, writes a PNG to DATA_DIR; additive, contained
    "AcademicResearchIntent": T1,     # reads a PDF, writes a .txt to DATA_DIR; additive, contained

    # T2 — writes without complete rollback
    "DictationIntent": T2,            # types text into whatever has focus — could land in a real document
    "SysUtilityIntent": T2,           # changes registry / display / mic settings — real system writes
    "ProjectScaffoldIntent": T2,      # creates a project dir + runs npx/create-react-app — filesystem + network
    "DependencyInstallIntent": T2,    # installs packages, runs install scripts — modifies the environment

    # T3 — irreversible
    "FileDeletionIntent": T3,         # delete — the canonical irreversible action
    "CodeActIntent": T3,             # generated PowerShell; requires Windows Sandbox
    "GeneralizedOSIntent": T3,        # can run arbitrary shell + GUI actions per its own docstring
    "ProcessManagementIntent": T3,    # default (kill) — terminating a process can lose unsaved work

    # Never reaches the broker in practice (validator/pipeline rejects it first),
    # assigned defensively.
    "UnknownIntent": T3,
}

# ── Sub-action overrides ─────────────────────────────────────────────────────
# Some intents span a range: a read-only variant and a mutating one. Where the
# variant is a plain, reliable signal on the step dict (not an LLM decision made
# later inside the handler), it earns a distinct tier.
#
# Shape: {intent: {normalised_action_value: tier}}. The resolver lower-cases and
# strips step["action"] before lookup; anything not listed falls back to
# INTENT_TIERS[intent].
ACTION_TIER_OVERRIDES: dict[str, dict[str, str]] = {
    # "list" is read-only; "kill" is the T3 default.
    "ProcessManagementIntent": {
        "list": T0,
    },
    # "list" is read-only; add/cancel keep the T1 default.
    "SchedulerIntent": {
        "list": T0,
    },
}


def tier_for(step: dict) -> str:
    """
    Resolves the containment tier for a single validated step dict.

    Reads step["intent"] and, when present, an override on step["action"]
    (case-insensitive). Unknown intents get T3 — the safe default, matching how
    the rest of the system treats anything it does not have an explicit rule for.
    """
    if not isinstance(step, dict):
        return T3

    intent = str(step.get("intent", "") or "").strip()
    base = INTENT_TIERS.get(intent, T3)
    if intent == "SysUtilityIntent":
        from capabilities.system.sys_utility import resolve_system_action
        action = resolve_system_action(step.get("target", ""), step.get("prompt", ""))
        return T3 if action in {"recycle_bin", "unknown"} else T2
    if intent == "ApplicationLaunchIntent":
        target = str(step.get("target", "") or "").strip().lower()
        # Arbitrary executables, scripts and explicit paths are code execution.
        # Only fixed application names retain the low-risk launch classification.
        if target and target not in {"notepad", "notepad.exe", "calc", "calc.exe",
                                     "calculator", "mspaint", "mspaint.exe"}:
            return T3

    overrides = ACTION_TIER_OVERRIDES.get(intent)
    if overrides:
        action = str(step.get("action", "") or "").strip().lower()
        if action in overrides:
            return overrides[action]

    return base
