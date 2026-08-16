"""
capabilities/system/scheduler.py
Real local task/reminder persistence for SchedulerIntent.

Replaces the fabricated-success stub (see git history / MERGE_LOG.md): the
previous version returned "Got it. I will remind you..." without ever
registering anything anywhere. This version genuinely persists tasks to
SQLite (agentic_core/memory_hook.py's scheduled_tasks table) and can list
and cancel them for real.

SCOPE, STATED HONESTLY: this makes tasks/reminders real, queryable, and
persistent across restarts. It does NOT add active notification delivery —
there is no background timer that pops a toast or speaks a reminder when
due_at arrives. That is a genuinely separate feature (a resident scheduler
loop, wired into main.py's lifecycle, plus a delivery mechanism) and belongs
with the "proactive triggers" work already scoped in
SENTINAL_V2_RECONCILED_ARCHITECTURE.md (§5) rather than bolted on here.
Every response that saves a timed reminder says so explicitly, so nobody
reasonably concludes they'll be notified when nothing will notify them —
the same fabricated-confidence failure this rewrite exists to fix.

Note this is unrelated to agentic_core/scheduler.py, which is the
pipeline's internal task queue.
"""
import logging
import re
import time
import uuid

_logger = logging.getLogger(__name__)

_LIST_TRIGGERS = (
    "what's on", "what is on", "what do i have", "show my", "list my",
    "my schedule", "my tasks", "my reminders", "my to-do", "my todo",
    "what have i got planned", "what's planned",
)

_CANCEL_TRIGGERS = ("cancel", "remove", "delete", "mark done", "mark as done", "complete", "finished with")

# Stripped from the front of a description before storing it, so "remind me
# to call mom" is saved as "call mom" — the trigger words carry no
# information once the item is in the store.
_LEADIN_PATTERN = re.compile(
    r"^(please\s+)?(remind me to|set a reminder to|remember to|add|schedule|plan)\s+",
    re.IGNORECASE,
)


# Lazily-created, module-level shared instance — not one MemoryManager() per
# call. Same leak, same fix as capabilities/developer/data_modeler.py and
# academic_research.py: each instance opens its own sqlite3 connection that
# only closes at process exit, so instantiating fresh per call leaked one
# connection per add/list/cancel. Tests monkeypatch this function directly
# (see tests/test_scheduler.py's isolated_memory fixture), which still works
# fine against a singleton-returning function.
_memory_singleton = None


def _memory():
    global _memory_singleton
    if _memory_singleton is None:
        from agentic_core.memory_hook import MemoryManager
        _memory_singleton = MemoryManager()
    return _memory_singleton


_TIME_HINT_PATTERN = re.compile(
    r"(\b(?:today|tomorrow|tonight)\b(?:\s+at\s+[\d:]+\s*(?:am|pm)?)?"
    r"|\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month)\b"
    r"|\b(?:in|for)\s+\d+\s+(?:minute|hour|day|week)s?\b"
    r"|\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b"
    r"|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b)",
    re.IGNORECASE,
)


def _parse_due_at(text: str) -> float | None:
    """Best-effort natural-language time extraction ('tomorrow at 9am', 'in
    2 hours'). Returns None for plain to-do items with no time reference —
    that's a normal, expected outcome, not a parse failure.

    Deliberately does NOT hand the whole free-text prompt to dateparser:
    dateparser.parse() requires the ENTIRE string to be a date expression
    (a sentence like "call mom tomorrow at 9am" returns None, not the
    embedded date), and its dateparser.search.search_dates() alternative
    is too permissive for this — it misreads ordinary words like "me" and
    "to" as date references on real test input. Extracting a bounded
    time-phrase substring first, with a narrow pattern, and parsing only
    that avoids both failure modes.
    """
    if not text:
        return None
    match = _TIME_HINT_PATTERN.search(text)
    if not match:
        return None
    phrase = match.group(0)
    # dateparser understands bare "today"/"tomorrow" but not bare "tonight"
    # (returns None for it, unlike the other two) - map it to a concrete
    # time it does understand rather than silently losing the reminder's
    # time and degrading it to an undated task.
    if re.fullmatch(r"tonight", phrase, re.IGNORECASE):
        phrase = "today 8pm"
    # dateparser understands "in N minutes" as a relative duration but not
    # "for N minutes" (same duration, timer-style phrasing - "set a timer
    # FOR 20 minutes") - translate the preposition rather than lose the
    # duration and silently degrade a timer request to an undated task.
    phrase = re.sub(r"^for\b", "in", phrase, flags=re.IGNORECASE)
    try:
        import dateparser
    except ImportError:
        return None
    parsed = dateparser.parse(
        phrase, settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False}
    )
    return parsed.timestamp() if parsed else None


def _clean_description(target: str, prompt: str) -> str:
    raw = (target or "").strip() or (prompt or "").strip()
    cleaned = _LEADIN_PATTERN.sub("", raw).strip()
    return cleaned or raw


def _format_due(due_at: float | None) -> str:
    if due_at is None:
        return ""
    return " (due " + time.strftime("%Y-%m-%d %H:%M", time.localtime(due_at)) + ")"


def _add_task(target: str, prompt: str) -> str:
    description = _clean_description(target, prompt)
    if not description:
        return "ERROR: I couldn't tell what to add — the request had no task description."

    due_at = _parse_due_at(prompt)
    task_id = uuid.uuid4().hex
    try:
        _memory().register_scheduled_task(task_id, description, due_at, time.time())
    except Exception as e:
        return f"ERROR: couldn't save '{description}' — {e}"

    if due_at is not None:
        return (
            f"Saved: \"{description}\"{_format_due(due_at)}. This is stored and you can ask "
            "me to list it later, but I don't yet send active notifications — I won't "
            "alert you when it's due, so keep your own reminder for anything time-critical."
        )
    return f"Saved to your task list: \"{description}\"."


def _list_tasks() -> str:
    try:
        tasks = _memory().get_pending_scheduled_tasks()
    except Exception as e:
        return f"ERROR: couldn't read your task list — {e}"

    if not tasks:
        return "Your task list is empty — nothing pending."

    lines = [f"- {t['description']}{_format_due(t['due_at'])}" for t in tasks]
    return f"You have {len(tasks)} pending item(s):\n" + "\n".join(lines)


def _cancel_task(target: str, prompt: str) -> str:
    keyword = _clean_description(target, prompt)
    for trigger in _CANCEL_TRIGGERS:
        keyword = re.sub(re.escape(trigger), "", keyword, flags=re.IGNORECASE).strip()
    # Words like "my" and "reminder" left over from "cancel my dentist reminder"
    # carry no matching value and would only narrow the LIKE search unhelpfully.
    keyword = re.sub(r"\b(my|the|reminder|task)\b", "", keyword, flags=re.IGNORECASE).strip()

    if not keyword:
        return "ERROR: I couldn't tell which task to cancel — no description was given."

    try:
        matches = _memory().find_pending_tasks_by_keyword(keyword)
    except Exception as e:
        return f"ERROR: couldn't search your task list — {e}"

    if not matches:
        return f"ERROR: I couldn't find a pending task matching '{keyword}' to cancel."

    if len(matches) > 1:
        lines = [f"- {t['description']}{_format_due(t['due_at'])}" for t in matches]
        return (
            f"'{keyword}' matches {len(matches)} pending items — I won't guess which one. "
            "Be more specific:\n" + "\n".join(lines)
        )

    task = matches[0]
    try:
        _memory().complete_scheduled_task(task["task_id"], time.time())
    except Exception as e:
        return f"ERROR: found '{task['description']}' but couldn't mark it done — {e}"
    return f"Cancelled: \"{task['description']}\"."


def handle_scheduler(target: str, prompt: str) -> str:
    """Routes to add/list/cancel based on the request's own wording — see
    module docstring for the one thing this deliberately does NOT do
    (active notification delivery)."""
    lower_prompt = (prompt or "").lower()

    if any(trigger in lower_prompt for trigger in _LIST_TRIGGERS):
        return _list_tasks()

    if any(trigger in lower_prompt for trigger in _CANCEL_TRIGGERS):
        return _cancel_task(target, prompt)

    return _add_task(target, prompt)
