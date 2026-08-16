"""
tests/test_data_modeler.py
Real tests for capabilities/developer/data_modeler.py's EDA implementation.
Writes actual temp CSVs and reads them for real (pandas), no mocked
DataFrames — only isolates the filesystem search paths so tests don't
accidentally hit a real Desktop/Downloads/Documents.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from capabilities.developer.data_modeler import (
    _extract_csv_filename,
    _resolve_csv_path,
    handle_data_modeling,
)


class TestExtractCsvFilename:
    def test_extracts_from_target(self):
        assert _extract_csv_filename("sales.csv", "") == "sales.csv"

    def test_extracts_from_prompt_when_target_empty(self):
        assert _extract_csv_filename("", "run an EDA on my sales.csv dataset") == "sales.csv"

    def test_no_csv_mentioned_returns_none(self):
        assert _extract_csv_filename("", "analyse my data please") is None

    def test_quoted_filename_with_spaces(self):
        assert _extract_csv_filename('', 'analyse "monthly sales.csv" for me') == "monthly sales.csv"

    def test_unquoted_absolute_path_with_spaces_in_a_directory_name(self):
        # Real Windows usernames routinely contain spaces ("Jane Doe" is the
        # OS's own suggested default) - regression guard for the bug this
        # surfaced as: the bare (no-space) branch alone truncated a real
        # scratch-directory path to whatever followed the space, silently
        # resolving against the wrong location.
        prompt = r"run an eda on C:\Users\Jane Doe\Documents\sales.csv"
        assert _extract_csv_filename("", prompt) == r"C:\Users\Jane Doe\Documents\sales.csv"

    def test_unquoted_relative_filename_with_spaces_and_no_anchor_grabs_trailing_fragment(self):
        # A relative filename with embedded spaces and no quotes and no
        # drive-letter anchor has no way to be disambiguated from the
        # surrounding sentence - the bare pattern's best-effort fallback is
        # the trailing space-free segment, not the intended full name. A
        # known, accepted limitation (not a bug): unquoted names with spaces
        # need quotes or an absolute path to resolve correctly.
        assert _extract_csv_filename("", "run an eda on my sales data.csv please") == "data.csv"


class TestResolveCsvPath:
    def test_absolute_existing_path_resolves(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        assert _resolve_csv_path(str(f)) == os.path.abspath(str(f))

    def test_missing_file_returns_none(self, tmp_path):
        with patch("capabilities.developer.data_modeler._SEARCH_DIRS", [str(tmp_path)]):
            assert _resolve_csv_path("does_not_exist.csv") is None

    def test_found_in_search_directory(self, tmp_path):
        f = tmp_path / "found.csv"
        f.write_text("a,b\n1,2\n")
        with patch("capabilities.developer.data_modeler._SEARCH_DIRS", [str(tmp_path)]):
            assert _resolve_csv_path("found.csv") == os.path.abspath(str(f))


class TestHandleDataModeling:
    def test_no_filename_mentioned_returns_honest_error(self):
        result = handle_data_modeling("", "please analyse this for me")
        assert result.startswith("ERROR")
        assert "csv" in result.lower()

    def test_unresolvable_file_returns_honest_error(self, tmp_path):
        with patch("capabilities.developer.data_modeler._SEARCH_DIRS", [str(tmp_path)]):
            result = handle_data_modeling("nonexistent.csv", "")
        assert result.startswith("ERROR")
        assert "couldn't locate" in result

    def test_malformed_csv_returns_honest_error(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_bytes(b"\x00\x01\x02\xff\xfe not,really,,,,csv\n\"unterminated")
        result = handle_data_modeling(str(bad), "")
        # Either a real read error, or pandas tolerates it and reports emptiness -
        # either way it must never claim a fabricated analysis result.
        assert "strong positive correlation" not in result

    def test_empty_csv_returns_honest_error(self, tmp_path):
        f = tmp_path / "empty.csv"
        f.write_text("col_a,col_b\n")  # header only, zero data rows
        result = handle_data_modeling(str(f), "")
        assert result.startswith("ERROR")
        assert "no rows" in result.lower()

    def test_real_csv_with_correlated_columns_computes_real_correlation(self, tmp_path, monkeypatch):
        f = tmp_path / "correlated.csv"
        f.write_text(
            "x,y,label\n"
            "1,2,a\n2,4,b\n3,6,c\n4,8,d\n5,10,e\n6,12,f\n7,14,g\n8,16,h\n"
        )
        data_dir = tmp_path / "eda_output"
        monkeypatch.setattr("capabilities.developer.data_modeler._data_dir", lambda: str(data_dir))

        result = handle_data_modeling(str(f), "")

        assert not result.startswith("ERROR")
        assert "8 rows x 3 columns" in result
        # y = 2x exactly -> perfect correlation, must be reported near 1.0, not fabricated
        assert "r=1.000" in result or "r=0.999" in result
        assert "heatmap saved to" in result.lower()
        saved_files = list(data_dir.glob("SentinAL_EDA_*.png"))
        assert len(saved_files) == 1
        assert saved_files[0].stat().st_size > 0  # a real image was written, not an empty file

    def test_single_numeric_column_skips_heatmap_honestly(self, tmp_path):
        f = tmp_path / "single_numeric.csv"
        f.write_text("id,name\n1,alice\n2,bob\n3,carol\n")
        result = handle_data_modeling(str(f), "")
        assert not result.startswith("ERROR")
        assert "fewer than 2 numeric columns" in result.lower()
        assert "heatmap" not in result.lower() or "no correlation heatmap" in result.lower()

    def test_missing_values_are_counted_for_real(self, tmp_path, monkeypatch):
        f = tmp_path / "gappy.csv"
        f.write_text("a,b\n1,\n2,4\n,6\n")
        # 2 numeric columns triggers a real heatmap write - must not land in
        # the real data/ directory during a test run.
        monkeypatch.setattr("capabilities.developer.data_modeler._data_dir", lambda: str(tmp_path / "out"))
        result = handle_data_modeling(str(f), "")
        assert not result.startswith("ERROR")
        assert "Missing values: 2 total" in result
