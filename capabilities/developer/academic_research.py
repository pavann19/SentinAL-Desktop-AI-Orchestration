import logging

_logger = logging.getLogger(__name__)


def handle_academic_research(target: str, prompt: str) -> str:
    """
    Academic paper retrieval and analysis (arXiv / local PDFs).

    NOT IMPLEMENTED — and this function is deliberately explicit about that.

    It previously returned a hardcoded string claiming it had analysed the
    paper, found "a 15% improvement over baseline models", and "saved a
    detailed summary to your desktop". None of that happened: there is no PDF
    retrieval, no parsing, and no file is ever written. Every invocation
    reported a confident success for work that was never performed, including
    an invented quantitative finding.

    That is worse than failing. A silent failure loses a task; a fabricated
    success actively misleads the user into believing a file exists and a
    result was obtained — and, because the returned string does not start with
    "ERROR", api_wrapper.process_command() classified the whole pipeline run as
    execution="Success", so nothing downstream could catch it either.

    The honest failure below is also why this intent needs no postcondition: it
    makes no claim about system state, so there is nothing to verify. When real
    retrieval/parsing lands, the postcondition is a filesystem check on the
    summary path it actually writes (the tier already exists).
    """
    _logger.warning(
        f"AcademicResearchIntent invoked for '{target}' but the capability is not implemented; "
        "returning an explicit failure rather than a fabricated summary."
    )
    return (
        "ERROR: I can't analyse research papers yet — that capability isn't "
        "implemented. No paper was retrieved and no summary was saved."
    )
