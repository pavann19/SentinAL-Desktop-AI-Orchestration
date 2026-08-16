"""
capabilities/developer/academic_research.py
Local PDF text extraction + LLM summarization for AcademicResearchIntent.

Replaces the fabricated-success stub (see git history / MERGE_LOG.md): the
previous version claimed "a 15% improvement over baseline models" and a
saved summary without ever opening a file. This version extracts real text
from a real PDF and summarizes what was actually extracted — or returns an
honest ERROR if the file can't be found, opened, or has no extractable text.

Deliberately local-PDF only, not arXiv/web retrieval — that would add a
network dependency and a much larger surface (search, download, rate
limits) for a first real implementation. A local file is the bounded,
verifiable case: the postcondition is a filesystem check on the summary
path this module actually writes.
"""
import logging
import os
import re
import time

_logger = logging.getLogger(__name__)

# See the identical comment in data_modeler.py — a shared, lazily-created
# module-level instance, not one MemoryManager() per resolution call.
_memory_singleton = None


def _memory():
    global _memory_singleton
    if _memory_singleton is None:
        from agentic_core.memory_hook import MemoryManager
        _memory_singleton = MemoryManager()
    return _memory_singleton

_PDF_NAME_PATTERN = re.compile(
    r"""['"](?P<quoted>[\w .:\\/-]+\.pdf)['"]|(?P<bare>[\w.:\\/-]+\.pdf)""",
    re.IGNORECASE,
)

_SEARCH_DIRS = [
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Downloads"),
    os.path.join(os.path.expanduser("~"), "Documents"),
    os.getcwd(),
]

# Roughly 12k characters is a safe margin under most chat-model context
# windows once the summarization prompt and response budget are accounted
# for, without needing a per-model token count here.
_MAX_EXTRACTED_CHARS = 12_000


def _extract_pdf_filename(target: str, prompt: str) -> str | None:
    for text in (target, prompt):
        if not text:
            continue
        match = _PDF_NAME_PATTERN.search(text)
        if match:
            return (match.group("quoted") or match.group("bare")).strip()
    return None


def _resolve_pdf_path(filename: str) -> str | None:
    """Same resolution order as data_modeler._resolve_csv_path — kept as a
    parallel implementation rather than a shared helper so each capability
    module stays independently readable, matching this codebase's existing
    per-capability style."""
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


def _extract_text(pdf_path: str) -> str:
    """Raises on a genuinely unreadable file; returns '' for a valid PDF
    with no extractable text (e.g. scanned images with no text layer) so
    the caller can distinguish "broken file" from "nothing to summarize"."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return "\n".join(parts)


def handle_academic_research(target: str, prompt: str) -> str:
    """
    Extracts real text from a local PDF and summarizes it with the same LLM
    used elsewhere in the pipeline (cloud-first, local fallback — the same
    BrainConfig.get_cloud_llm() or BrainConfig.get_local_llm() pattern
    CodeActIntent uses). Saves the real summary to config.paths.DATA_DIR.

    Returns an honest ERROR (no invented findings) if the file can't be
    located, can't be parsed, has no extractable text, or the LLM call
    itself fails.
    """
    stripped_target = (target or "").strip().strip('"').strip("'")
    filename = stripped_target if stripped_target.lower().endswith(".pdf") else _extract_pdf_filename(target, prompt)
    if not filename:
        return "ERROR: I couldn't tell which PDF to analyse — no .pdf filename was mentioned in the request."

    pdf_path = _resolve_pdf_path(filename)
    if not pdf_path:
        return f"ERROR: I couldn't locate '{filename}' in Desktop, Downloads, Documents, or the current directory."

    try:
        import pypdf  # noqa: F401 — import-availability check before use below
    except ImportError:
        return "ERROR: pypdf is not installed — PDF analysis is unavailable in this environment."

    try:
        text = _extract_text(pdf_path)
    except Exception as e:
        return f"ERROR: '{os.path.basename(pdf_path)}' could not be read as a PDF — {e}"

    if not text.strip():
        return (
            f"ERROR: '{os.path.basename(pdf_path)}' has no extractable text "
            "(likely a scanned image with no text layer) — nothing to summarize."
        )

    truncated = text[:_MAX_EXTRACTED_CHARS]
    was_truncated = len(text) > _MAX_EXTRACTED_CHARS

    try:
        from config.settings import BrainConfig
        llm = BrainConfig.get_cloud_llm(max_tokens=1024) or BrainConfig.get_local_llm(num_predict=1024)
        if llm is None:
            return "ERROR: No LLM is configured (no Groq key, no local Ollama model) — can't summarize."
        response = llm.invoke(
            "Summarize the following academic paper excerpt in 4-6 sentences, "
            "covering its stated goal, method, and main finding. Do not invent "
            "numbers or claims that aren't in the text.\n\n" + truncated
        )
        summary = str(getattr(response, "content", response)).strip()
    except Exception as e:
        return f"ERROR: summarization failed — {e}"

    if not summary:
        return "ERROR: the summarizer returned an empty response — nothing was saved."

    try:
        from config.paths import DATA_DIR
        os.makedirs(DATA_DIR, exist_ok=True)
        stem = re.sub(r"[^\w-]", "_", os.path.splitext(os.path.basename(pdf_path))[0])[:40] or "paper"
        summary_path = os.path.join(DATA_DIR, f"SentinAL_Summary_{stem}_{int(time.time())}.txt")
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary)
    except Exception as e:
        # The summary was genuinely produced; only the save failed. Report the
        # content so it isn't lost, and say plainly that nothing was saved.
        return f"Summary of '{os.path.basename(pdf_path)}' (could not save to disk — {e}): {summary}"

    truncation_note = " (only the first portion of the document was summarized)" if was_truncated else ""
    return f"Summarized '{os.path.basename(pdf_path)}'{truncation_note}, saved to {summary_path}: {summary}"
