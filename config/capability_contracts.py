# config/capability_contracts.py
# P2-4 — declarative capability contracts (MCP tool-contract layer).
#
# One CapabilityContract per allowlisted intent: the parameter schema the
# executor branch actually reads, the result shape, the containment tier
# (resolved from config.capability_tiers — NOT hand-copied), a coarse cost
# hint, reversibility, side effects, and worked examples.
#
# This is metadata only. It does NOT change dispatch — agentic_core/executor.py
# keeps its own if/elif chain untouched. agentic_core/capability_manifest.py
# reads this file to expose an MCP-style tool manifest and a parallel
# contract-dispatch path (wired for exactly one capability as the P2-4
# deliverable; full pipeline cutover is deferred, see that module).

from __future__ import annotations

from dataclasses import dataclass, field

from config.capability_tiers import INTENT_TIERS, T0, T1, T2, T3

# cost buckets
CHEAP = "cheap"      # local, sub-second, no network / no subprocess
NETWORK = "network"  # an LLM or web call
HEAVY = "heavy"      # spawns a subprocess / installs / runs arbitrary code


def _reversible_for_tier(tier: str) -> str:
    """Reversibility follows the tier by definition (capability_tiers.py §6)."""
    return {T0: "yes", T1: "yes", T2: "snapshot", T3: "no"}[tier]


@dataclass(frozen=True)
class CapabilityContract:
    intent: str
    summary: str
    params: dict = field(default_factory=dict)
    returns: dict = field(default_factory=dict)
    cost: str = CHEAP
    side_effects: list = field(default_factory=list)
    examples: list = field(default_factory=list)
    handler: str | None = None  # "module.path:func" — set only for migrated capabilities

    @property
    def tier(self) -> str:
        """Single source of truth — the broker's map, never a local copy."""
        return INTENT_TIERS[self.intent]

    @property
    def reversible(self) -> str:
        return _reversible_for_tier(self.tier)

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "summary": self.summary,
            "tier": self.tier,
            "reversible": self.reversible,
            "cost": self.cost,
            "side_effects": list(self.side_effects),
            "params": self.params,
            "returns": self.returns,
            "examples": self.examples,
            "handler": self.handler,
        }


def _p(type_, required=True, description="", **extra):
    d = {"type": type_, "required": required, "description": description}
    d.update(extra)
    return d


_STR_RESULT = {"type": "str", "description": "Human-readable result / speech line."}
_TP = {  # the near-universal (target, prompt) handler shape
    "target": _p("str", True, "The extracted object of the request."),
    "prompt": _p("str", False, "Original phrasing, used as an extraction fallback."),
}

CONTRACTS: list[CapabilityContract] = [
    CapabilityContract(
        intent="ApplicationLaunchIntent",
        summary="Start a local application or open a file with its default program.",
        params={"target": _p("str", True, "Executable name, path, or %ENV% path.")},
        returns=_STR_RESULT, cost=CHEAP, side_effects=["starts a process"],
        examples=[{"prompt": "open notepad", "params": {"target": "notepad"}}],
    ),
    CapabilityContract(
        intent="WebNavigationIntent",
        summary="Open a URL (or a known mnemonic like 'github') in the default browser.",
        params={"target": _p("str", True, "URL or mnemonic.")},
        returns=_STR_RESULT, cost=CHEAP, side_effects=["opens a browser tab"],
        examples=[{"prompt": "go to github", "params": {"target": "github"}}],
    ),
    CapabilityContract(
        intent="InformationRetrievalIntent",
        summary="Live web research, synthesised into a short spoken briefing.",
        params={"target": _p("str", True, "The research query.")},
        returns={"type": "str", "description": "A concise briefing from live results."},
        cost=NETWORK, side_effects=["performs a web search", "calls an LLM"],
        examples=[{"prompt": "what's new with the mars rover",
                   "params": {"target": "latest Mars rover news"}}],
    ),
    CapabilityContract(
        intent="GeneralizedOSIntent",
        summary="Run an ordered list of shell and/or GUI actions.",
        params={"actions": _p("list", True,
                              "Ordered [{type: 'shell'|'gui', payload: str, value?: str}].")},
        returns=_STR_RESULT, cost=HEAVY,
        side_effects=["runs arbitrary shell commands", "drives the GUI"],
        examples=[{"prompt": "make a folder called reports on my desktop",
                   "params": {"actions": [{"type": "shell",
                                           "payload": "mkdir %USERPROFILE%/Desktop/reports"}]}}],
    ),
    CapabilityContract(
        intent="MediaStreamingIntent",
        summary="Open a media search / playback page for a title on a platform.",
        params={"target": _p("str", True, "Title or search text."),
                "platform": _p("str", False, "youtube (default), spotify, ...")},
        returns=_STR_RESULT, cost=CHEAP, side_effects=["opens a browser tab"],
        examples=[{"prompt": "play lofi beats on youtube",
                   "params": {"target": "lofi beats", "platform": "youtube"}}],
    ),
    CapabilityContract(
        intent="FileDeletionIntent",
        summary="Delete a file or directory (sandbox-guarded against system paths).",
        params={"target": _p("str", True, "Path to delete, absolute or cwd-relative.")},
        returns=_STR_RESULT, cost=CHEAP, side_effects=["deletes a file or directory"],
        examples=[{"prompt": "delete old_notes.txt", "params": {"target": "old_notes.txt"}}],
    ),
    CapabilityContract(
        intent="ConversationalIntent",
        summary="Plain conversational reply — no OS action.",
        params={"target": _p("str", False, "The user's message.")},
        returns=_STR_RESULT, cost=CHEAP, side_effects=[],
        examples=[{"prompt": "how are you", "params": {"target": "how are you"}}],
    ),
    CapabilityContract(
        intent="ContinuationIntent",
        summary="Expand on / continue the previous interaction from memory.",
        params={"target": _p("str", False, "Follow-up phrasing, e.g. 'elaborate'.")},
        returns=_STR_RESULT, cost=NETWORK, side_effects=["calls an LLM"],
        examples=[{"prompt": "tell me more", "params": {"target": "tell me more"}}],
    ),
    CapabilityContract(
        intent="ProcessManagementIntent",
        summary="List processes, or terminate one by name/PID (protected-process guarded).",
        params={"action": _p("str", False, "list (default) or kill.", enum=["list", "kill"]),
                "target": _p("str", False, "Name or PID; required for kill.")},
        returns=_STR_RESULT, cost=CHEAP,
        side_effects=["may terminate a process (kill)"],
        examples=[{"prompt": "what's running", "params": {"action": "list", "target": ""}},
                  {"prompt": "kill chrome", "params": {"action": "kill", "target": "chrome"}}],
    ),
    CapabilityContract(
        intent="ProjectScaffoldIntent",
        summary="Create a project directory and run its scaffolder (npx / CRA style).",
        params={"framework": _p("str", True, "e.g. 'react', 'next', 'vite'."),
                "project_name": _p("str", False, "Default 'my-project'."),
                "location": _p("str", False, "Parent directory; default cwd.")},
        returns=_STR_RESULT, cost=HEAVY,
        side_effects=["creates a directory tree", "runs a scaffolder subprocess", "network"],
        examples=[{"prompt": "scaffold a react app called dashboard",
                   "params": {"framework": "react", "project_name": "dashboard"}}],
    ),
    CapabilityContract(
        intent="DependencyInstallIntent",
        summary="Install packages with pip or npm.",
        params={"manager": _p("str", False, "pip (default) or npm.", enum=["pip", "npm"]),
                "packages": _p("str", True, "Space-separated package list."),
                "dev": _p("bool", False, "npm --save-dev."),
                "cwd": _p("str", False, "Directory to install in.")},
        returns=_STR_RESULT, cost=HEAVY,
        side_effects=["installs packages", "runs install scripts", "network"],
        examples=[{"prompt": "pip install requests",
                   "params": {"manager": "pip", "packages": "requests"}}],
    ),
    CapabilityContract(
        intent="CodeActIntent",
        summary="Generate a PowerShell script for a complex task and run it (sandboxed if available).",
        params={"prompt": _p("str", True, "The full task description.")},
        returns=_STR_RESULT, cost=HEAVY,
        side_effects=["runs LLM-generated code on the host"],
        examples=[{"prompt": "batch-rename every .jpeg in Downloads to .jpg",
                   "params": {"prompt": "batch-rename every .jpeg in Downloads to .jpg"}}],
    ),
    CapabilityContract(
        intent="AcademicResearchIntent",
        summary="Read a local PDF and write a plain-text analysis to DATA_DIR.",
        params=dict(_TP),
        returns=_STR_RESULT, cost=NETWORK,
        side_effects=["reads a PDF", "writes DATA_DIR/*.txt", "calls an LLM"],
        examples=[{"prompt": "summarise the attention paper pdf",
                   "params": {"target": "attention_is_all_you_need.pdf", "prompt": "summarise it"}}],
    ),
    CapabilityContract(
        intent="DataModelingIntent",
        summary="Run pandas/scikit EDA on a CSV and write a chart PNG to DATA_DIR.",
        params=dict(_TP),
        returns=_STR_RESULT, cost=NETWORK,
        side_effects=["reads a CSV", "writes DATA_DIR/*.png"],
        examples=[{"prompt": "plot the sales csv",
                   "params": {"target": "sales.csv", "prompt": "plot it"}}],
    ),
    CapabilityContract(
        intent="SysUtilityIntent",
        summary="Toggle system settings: dark mode, recycle bin, display, microphone.",
        params=dict(_TP),
        returns=_STR_RESULT, cost=CHEAP,
        side_effects=["changes a system / registry setting"],
        examples=[{"prompt": "switch to light mode",
                   "params": {"target": "light mode", "prompt": "switch to light mode"}}],
    ),
    CapabilityContract(
        intent="SchedulerIntent",
        summary="Add, list, or cancel a reminder / scheduled task (SQLite-backed).",
        params={
            "prompt": _p("str", True, "Full phrasing — routes add vs list vs cancel."),
            "target": _p("str", False, "Reminder text; required only for 'add'."),
        },
        returns={"type": "str", "description": "Confirmation, task list, or cancellation result."},
        cost=CHEAP, side_effects=["writes / updates a scheduled_tasks row"],
        examples=[
            {"prompt": "remind me to call mom at 6pm",
             "params": {"target": "call mom", "prompt": "remind me to call mom at 6pm"}},
            {"prompt": "what are my reminders",
             "params": {"target": "", "prompt": "what are my reminders"}},
        ],
        handler="capabilities.system.scheduler:handle_scheduler",
    ),
    CapabilityContract(
        intent="MediaControlIntent",
        summary="System volume and playback control (mute, up/down, play/pause).",
        params=dict(_TP),
        returns=_STR_RESULT, cost=CHEAP, side_effects=["changes system volume / playback"],
        examples=[{"prompt": "turn the volume down",
                   "params": {"target": "down", "prompt": "turn the volume down"}}],
    ),
    CapabilityContract(
        intent="WindowManagementIntent",
        summary="Snap / minimise windows, switch virtual desktops, take a screenshot.",
        params=dict(_TP),
        returns=_STR_RESULT, cost=CHEAP,
        side_effects=["moves windows / switches desktop / writes a screenshot file"],
        examples=[{"prompt": "take a screenshot",
                   "params": {"target": "screenshot", "prompt": "take a screenshot"}}],
    ),
    CapabilityContract(
        intent="DictationIntent",
        summary="Type text into whatever window currently has focus.",
        params=dict(_TP),
        returns=_STR_RESULT, cost=CHEAP,
        side_effects=["types into the focused window"],
        examples=[{"prompt": "type hello world",
                   "params": {"target": "hello world", "prompt": "type hello world"}}],
    ),
]
