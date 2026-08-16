"""
tests/test_academic_research.py
Real tests for capabilities/developer/academic_research.py.

Writes actual valid PDFs (hand-built minimal PDF syntax with a real text
content stream — no reportlab/fpdf available in this environment) and reads
them for real via pypdf, so extraction is genuinely exercised, not mocked.
Only the LLM call itself is mocked (no network calls in a unit test).
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from capabilities.developer.academic_research import (
    _extract_pdf_filename,
    _extract_text,
    _resolve_pdf_path,
    handle_academic_research,
)


def _make_minimal_pdf(path: str, text: str) -> None:
    """Hand-built single-page PDF with a real, pypdf-extractable text stream."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> /MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF".encode()
    with open(path, "wb") as f:
        f.write(bytes(out))


def _make_empty_page_pdf(path: str) -> None:
    """A structurally valid PDF with a page but NO text content stream at
    all — simulates a scanned/image-only page with no extractable text."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << >> /MediaBox [0 0 612 792] >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF".encode()
    with open(path, "wb") as f:
        f.write(bytes(out))


def _mock_llm(content):
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content=content)
    return llm


class TestExtractPdfFilename:
    def test_extracts_from_target(self):
        assert _extract_pdf_filename("paper.pdf", "") == "paper.pdf"

    def test_extracts_from_prompt(self):
        assert _extract_pdf_filename("", "summarize my paper.pdf for me") == "paper.pdf"

    def test_no_pdf_mentioned_returns_none(self):
        assert _extract_pdf_filename("", "summarize this research") is None


class TestResolvePdfPath:
    def test_absolute_existing_path_resolves(self, tmp_path):
        f = tmp_path / "paper.pdf"
        f.write_bytes(b"%PDF-1.4\n%%EOF")
        assert _resolve_pdf_path(str(f)) == os.path.abspath(str(f))

    def test_missing_file_returns_none(self, tmp_path):
        with patch("capabilities.developer.academic_research._SEARCH_DIRS", [str(tmp_path)]):
            assert _resolve_pdf_path("does_not_exist.pdf") is None

    def test_found_in_search_directory(self, tmp_path):
        f = tmp_path / "found.pdf"
        f.write_bytes(b"%PDF-1.4\n%%EOF")
        with patch("capabilities.developer.academic_research._SEARCH_DIRS", [str(tmp_path)]):
            assert _resolve_pdf_path("found.pdf") == os.path.abspath(str(f))


class TestExtractText:
    def test_extracts_real_text_from_real_pdf(self, tmp_path):
        pdf = tmp_path / "real.pdf"
        _make_minimal_pdf(str(pdf), "This paper studies gradient descent convergence.")
        text = _extract_text(str(pdf))
        assert "gradient descent convergence" in text

    def test_returns_empty_for_textless_pdf(self, tmp_path):
        pdf = tmp_path / "scanned.pdf"
        _make_empty_page_pdf(str(pdf))
        assert _extract_text(str(pdf)) == ""


class TestHandleAcademicResearch:
    def test_no_filename_mentioned_returns_honest_error(self):
        result = handle_academic_research("", "please summarize this")
        assert result.startswith("ERROR")

    def test_unresolvable_file_returns_honest_error(self, tmp_path):
        with patch("capabilities.developer.academic_research._SEARCH_DIRS", [str(tmp_path)]):
            result = handle_academic_research("missing.pdf", "")
        assert result.startswith("ERROR")
        assert "couldn't locate" in result

    def test_corrupt_pdf_returns_honest_error(self, tmp_path):
        bad = tmp_path / "corrupt.pdf"
        bad.write_bytes(b"%PDF-1.4\nthis is not a real pdf structure at all")
        result = handle_academic_research(str(bad), "")
        assert result.startswith("ERROR")

    def test_textless_pdf_returns_honest_error_not_fabricated_summary(self, tmp_path):
        pdf = tmp_path / "scanned.pdf"
        _make_empty_page_pdf(str(pdf))
        result = handle_academic_research(str(pdf), "")
        assert result.startswith("ERROR")
        assert "no extractable text" in result

    def test_real_pdf_gets_real_summary_saved(self, tmp_path, monkeypatch):
        pdf = tmp_path / "paper.pdf"
        _make_minimal_pdf(str(pdf), "This paper proposes a new attention mechanism for transformers.")

        data_dir = tmp_path / "output"
        fake_llm = _mock_llm("The paper proposes a new attention mechanism for transformer models.")

        with patch("config.settings.BrainConfig.get_cloud_llm", return_value=fake_llm), \
             patch("config.paths.DATA_DIR", str(data_dir)):
            result = handle_academic_research(str(pdf), "")

        assert not result.startswith("ERROR")
        assert "attention mechanism" in result
        saved = list(data_dir.glob("SentinAL_Summary_*.txt"))
        assert len(saved) == 1
        assert "attention mechanism" in saved[0].read_text(encoding="utf-8")

    def test_no_llm_configured_returns_honest_error(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        _make_minimal_pdf(str(pdf), "Some real extractable text content here.")

        with patch("config.settings.BrainConfig.get_cloud_llm", return_value=None), \
             patch("config.settings.BrainConfig.get_local_llm", return_value=None):
            result = handle_academic_research(str(pdf), "")

        assert result.startswith("ERROR")
        assert "no llm" in result.lower()

    def test_llm_failure_returns_honest_error_not_fabricated_summary(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        _make_minimal_pdf(str(pdf), "Some real extractable text content here.")

        broken_llm = MagicMock()
        broken_llm.invoke.side_effect = RuntimeError("connection refused")

        with patch("config.settings.BrainConfig.get_cloud_llm", return_value=broken_llm):
            result = handle_academic_research(str(pdf), "")

        assert result.startswith("ERROR")
        assert "summarization failed" in result.lower()

    def test_save_failure_still_returns_the_real_summary(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        _make_minimal_pdf(str(pdf), "Some real extractable text content here.")
        fake_llm = _mock_llm("A genuinely produced summary of the paper.")

        with patch("config.settings.BrainConfig.get_cloud_llm", return_value=fake_llm), \
             patch("os.makedirs", side_effect=OSError("disk full")):
            result = handle_academic_research(str(pdf), "")

        assert "genuinely produced summary" in result
        assert "could not save" in result.lower()
