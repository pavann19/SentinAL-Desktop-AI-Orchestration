import logging

_logger = logging.getLogger(__name__)


def handle_data_modeling(target: str, prompt: str) -> str:
    """
    CSV parsing, pandas EDA, and basic scikit-learn modelling.

    NOT IMPLEMENTED — see the note in academic_research.py; this had the same
    defect and the same fix.

    It previously returned a hardcoded string claiming it had handled missing
    values, run a correlation matrix, "found a strong positive correlation
    between the primary features", and saved visualisations to the workspace.
    No dataset is read, no analysis runs, and no file is written — so the
    correlation it reported was an invented finding about data it never opened.

    A user acting on that output would be making decisions from a fabricated
    statistical result, which is a materially worse outcome than being told the
    feature does not exist. It also passed as execution="Success" downstream,
    since the returned string did not start with "ERROR".

    When real EDA lands, the postcondition is a filesystem check on the
    visualisation/output path it actually writes (the tier already exists).
    """
    _logger.warning(
        f"DataModelingIntent invoked for '{target}' but the capability is not implemented; "
        "returning an explicit failure rather than fabricated analysis results."
    )
    return (
        "ERROR: I can't analyse datasets yet — that capability isn't "
        "implemented. No data was read and no visualisations were saved."
    )
