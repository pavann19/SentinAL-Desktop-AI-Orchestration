"""
capabilities/developer/data_modeler.py
CSV loading and pandas-based exploratory data analysis (EDA) for DataModelingIntent.

Replaces the fabricated-success stub (see git history / MERGE_LOG.md): the
previous version returned a hardcoded "found a strong positive correlation"
claim without ever opening a file. This version does the real work — reads
the actual CSV, computes real summary statistics from it, and saves a real
correlation heatmap — or returns an honest ERROR if any of that fails.
"""
import glob
import logging
import os
import re
import time

_logger = logging.getLogger(__name__)

# Lazily-created, module-level shared instance — not one MemoryManager() per
# resolution call. Each instance opens its own sqlite3 connection that only
# ever closes when the process exits; instantiating fresh per call (as an
# earlier version of this file did) leaked one connection per unresolved
# file lookup. Mirrors agentic_core/executor.py's own `memory = MemoryManager()`
# module-level singleton.
_memory_singleton = None


def _memory():
    global _memory_singleton
    if _memory_singleton is None:
        from agentic_core.memory_hook import MemoryManager
        _memory_singleton = MemoryManager()
    return _memory_singleton

# Matches "sales.csv", "data/sales.csv", "'my file.csv'" etc. embedded in a
# free-text prompt. Two alternatives, not one greedy class: an UNQUOTED name
# must not contain spaces (otherwise "run an EDA on my sales.csv dataset"
# greedily captures "run an EDA on my sales.csv", not just "sales.csv" -
# there's no word-boundary signal telling the regex where the filename
# actually starts). A QUOTED name may contain spaces, since the quotes
# themselves mark the boundary. Includes ':' so Windows drive letters
# (C:\...) survive extraction - dropping it silently turned an absolute
# path into a drive-relative one that resolved against the wrong drive.
_CSV_NAME_PATTERN = re.compile(
    r"""['"](?P<quoted>[\w .:\\/-]+\.csv)['"]|(?P<bare>[\w.:\\/-]+\.csv)""",
    re.IGNORECASE,
)

# Where user documents are conventionally found on Windows — searched in
# order when the target isn't an already-resolvable path. Mirrors the same
# "search common locations" idea already used for folder resolution in
# agentic_core/executor.py's Explorer interceptor.
_SEARCH_DIRS = [
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Downloads"),
    os.path.join(os.path.expanduser("~"), "Documents"),
    os.getcwd(),
]


def _extract_csv_filename(target: str, prompt: str) -> str | None:
    """Pulls a .csv filename out of target first, then the raw prompt."""
    for text in (target, prompt):
        if not text:
            continue
        match = _CSV_NAME_PATTERN.search(text)
        if match:
            return (match.group("quoted") or match.group("bare")).strip()
    return None


def _resolve_csv_path(filename: str) -> str | None:
    """Finds a real, existing CSV file for `filename`, or None if it can't be located.

    Checks the path as given (absolute or cwd-relative) first, then the
    common user directories, then the memory path cache — the same fallback
    order already established for folder resolution elsewhere in the
    codebase, so this doesn't invent a new resolution convention.
    """
    if os.path.isabs(filename) and os.path.isfile(filename):
        return os.path.abspath(filename)

    cwd_candidate = os.path.join(os.getcwd(), filename)
    if os.path.isfile(cwd_candidate):
        return os.path.abspath(cwd_candidate)

    basename = os.path.basename(filename)
    for directory in _SEARCH_DIRS:
        candidate = os.path.join(directory, basename)
        if os.path.isfile(candidate):
            return os.path.abspath(candidate)

    try:
        cached = _memory().get_cached_path(basename)
        if cached and os.path.isfile(cached):
            return os.path.abspath(cached)
    except Exception as e:
        _logger.warning(f"Path cache lookup failed (non-fatal): {e}")

    return None


def handle_data_modeling(target: str, prompt: str) -> str:
    """
    Runs real pandas EDA against a real CSV: shape, dtypes, missing-value
    counts, descriptive statistics, and — for datasets with 2+ numeric
    columns — a correlation heatmap saved to config.paths.DATA_DIR.

    Returns an honest ERROR (no fabricated numbers) if the file can't be
    located, can't be parsed, or contains no usable data.
    """
    # If target itself already looks like a .csv reference — the common case,
    # since this is normally exactly what the extraction pipeline hands us —
    # trust it directly rather than re-parsing it with a regex tuned for
    # pulling a filename out of free-text prompt. The regex's unquoted
    # branch can't contain spaces (no other way to bound where the filename
    # starts in a sentence), which would wrongly truncate a real path like
    # "C:\Users\Jane Doe\data.csv" if it were forced through that path.
    stripped_target = (target or "").strip().strip('"').strip("'")
    filename = stripped_target if stripped_target.lower().endswith(".csv") else _extract_csv_filename(target, prompt)
    if not filename:
        return (
            "ERROR: I couldn't tell which CSV file to analyse — no .csv "
            "filename was mentioned in the request."
        )

    csv_path = _resolve_csv_path(filename)
    if not csv_path:
        return f"ERROR: I couldn't locate '{filename}' in Desktop, Downloads, Documents, or the current directory."

    try:
        import pandas as pd
    except ImportError:
        return "ERROR: pandas is not installed — CSV analysis is unavailable in this environment."

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return f"ERROR: '{os.path.basename(csv_path)}' could not be read as a CSV — {e}"

    if df.empty:
        return f"ERROR: '{os.path.basename(csv_path)}' has no rows — nothing to analyse."

    n_rows, n_cols = df.shape
    missing = df.isna().sum()
    missing_total = int(missing.sum())
    numeric_df = df.select_dtypes(include="number")

    summary_lines = [
        f"Loaded '{os.path.basename(csv_path)}': {n_rows} rows x {n_cols} columns.",
        f"Missing values: {missing_total} total across {int((missing > 0).sum())} columns.",
    ]

    viz_path = None
    if numeric_df.shape[1] >= 2:
        corr = numeric_df.corr(numeric_only=True)
        # Report the strongest real off-diagonal correlation, not an invented one.
        abs_corr = corr.abs().where(~corr.isna())
        import numpy as np
        np.fill_diagonal(abs_corr.values, 0.0)
        if abs_corr.to_numpy().max() > 0:
            i, j = divmod(int(abs_corr.to_numpy().argmax()), abs_corr.shape[1])
            col_a, col_b = corr.columns[i], corr.columns[j]
            actual_r = corr.iloc[i, j]
            summary_lines.append(
                f"Strongest correlation: {col_a} vs {col_b}, r={actual_r:.3f}."
            )

        try:
            import matplotlib
            matplotlib.use("Agg")  # headless — this runs with no display attached
            import matplotlib.pyplot as plt

            os.makedirs(_data_dir(), exist_ok=True)
            viz_path = os.path.join(
                _data_dir(), f"SentinAL_EDA_{_safe_stem(csv_path)}_{int(time.time())}.png"
            )
            fig, ax = plt.subplots(figsize=(6, 5))
            im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
            ax.set_xticks(range(len(corr.columns)))
            ax.set_yticks(range(len(corr.columns)))
            ax.set_xticklabels(corr.columns, rotation=45, ha="right")
            ax.set_yticklabels(corr.columns)
            fig.colorbar(im, ax=ax, label="correlation")
            ax.set_title(f"Correlation heatmap — {os.path.basename(csv_path)}")
            fig.tight_layout()
            fig.savefig(viz_path, dpi=120)
            plt.close(fig)
            summary_lines.append(f"Correlation heatmap saved to {viz_path}.")
        except Exception as e:
            _logger.warning(f"Heatmap generation failed (non-fatal, EDA numbers still real): {e}")
    else:
        summary_lines.append("Fewer than 2 numeric columns — no correlation heatmap generated.")

    return " ".join(summary_lines)


def _data_dir() -> str:
    from config.paths import DATA_DIR
    return DATA_DIR


def _safe_stem(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[^\w-]", "_", stem)[:40] or "dataset"
