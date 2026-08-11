import logging

_logger = logging.getLogger(__name__)


def handle_scheduler(target: str, prompt: str) -> str:
    """
    Local reminders, task lists, and planning.

    NOT IMPLEMENTED — same defect and same fix as
    capabilities/developer/academic_research.py and data_modeler.py.

    It previously branched on keywords in the prompt and returned a different
    fabricated confirmation for each: "I have planned a detailed holiday
    itinerary for you and saved the schedule", "synced the threat vectors to
    your calendar", "I have added '<target>' to your personal schedule", and —
    the most damaging — "Got it. I will remind you about '<target>' at the
    requested time."

    No schedule store exists, nothing is written to a calendar, and no timer or
    reminder is ever registered. The keyword branching made this especially
    convincing: the reply was tailored to what the user asked for, so it read
    like the system had understood and acted.

    The reminder branch is the reason this is worse than an ordinary silent
    failure. A user told "I will remind you" reasonably stops tracking the thing
    themselves. The failure then surfaces only when the reminder does not
    arrive — at the moment it was needed, when it is too late to recover.

    Note this is unrelated to agentic_core/scheduler.py, which is the pipeline's
    internal task queue and is genuinely implemented.

    When real scheduling lands, the postcondition is a filesystem/store check on
    the persisted entry it actually writes (the tier already exists).
    """
    _logger.warning(
        f"SchedulerIntent invoked for '{target}' but the capability is not implemented; "
        "returning an explicit failure rather than a fabricated confirmation."
    )
    return (
        "ERROR: I can't set reminders or manage a schedule yet — that capability "
        "isn't implemented. Nothing was saved and no reminder will fire, so "
        "please track this yourself."
    )
