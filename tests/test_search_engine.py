"""
tests/test_search_engine.py
Tests for capabilities/web/search_engine.py.
All network calls mocked — no real Tavily API needed.
Covers: validation, singleton, retry logic, error handling.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock


class TestSearchEngineInputValidation:

    def test_empty_query_returns_error(self):
        from capabilities.web.search_engine import get_live_research
        result = get_live_research("")
        assert "error" in result
        assert result.get("code") == 400

    def test_whitespace_only_query_returns_error(self):
        from capabilities.web.search_engine import get_live_research
        result = get_live_research("   ")
        assert "error" in result
        assert result.get("code") == 400

    def test_single_char_query_returns_error(self):
        from capabilities.web.search_engine import get_live_research
        result = get_live_research("x")
        assert "error" in result
        assert result.get("code") == 400

    def test_symbol_heavy_query_returns_error(self):
        from capabilities.web.search_engine import get_live_research
        result = get_live_research("!@#$%^&*()")
        assert "error" in result

    def test_none_query_returns_error(self):
        from capabilities.web.search_engine import get_live_research
        result = get_live_research(None)
        assert "error" in result


class TestSearchEngineMissingConfig:

    def test_no_api_key_returns_error(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": ""}):
            import importlib
            import capabilities.web.search_engine as se_module
            importlib.reload(se_module)
            result = se_module.get_live_research("what is python")
            assert "error" in result

    def test_tavily_not_installed_returns_error(self):
        with patch.dict(sys.modules, {"tavily": None}):
            import importlib
            import capabilities.web.search_engine as se_module
            importlib.reload(se_module)
            if not se_module.TAVILY_AVAILABLE:
                result = se_module.get_live_research("test query for space")
                assert "error" in result


class TestSearchEngineSuccessPath:

    def test_successful_search_returns_context(self):
        """Mock a successful Tavily response."""
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {"content": "Python is a programming language."},
                {"content": "It was created by Guido van Rossum."}
            ]
        }

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test_key"}):
            with patch("tavily.TavilyClient", return_value=mock_client):
                import importlib
                import capabilities.web.search_engine as se_module
                importlib.reload(se_module)
                se_module._tavily_client = mock_client
                se_module.TAVILY_AVAILABLE = True
                se_module._TAVILY_API_KEY = "test_key"

                result = se_module.get_live_research("what is python")
                assert "context" in result
                assert "Python" in result["context"]

    def test_no_results_returns_error(self):
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test_key"}):
            with patch("tavily.TavilyClient", return_value=mock_client):
                import importlib
                import capabilities.web.search_engine as se_module
                importlib.reload(se_module)
                se_module._tavily_client = mock_client
                se_module.TAVILY_AVAILABLE = True
                se_module._TAVILY_API_KEY = "test_key"

                result = se_module.get_live_research("valid query here again")
                assert "error" in result
                assert result.get("code") == 404


class TestSearchEngineRetryLogic:

    def test_retries_on_429_error(self):
        """On a 429-like error, the function must retry up to 2 times."""
        call_count = [0]

        def flaky_search(**kwargs):
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("Http status 429: rate limited")
            return {"results": [{"content": "Success after retry."}]}

        mock_client = MagicMock()
        mock_client.search = flaky_search

        import importlib
        import capabilities.web.search_engine as se_module
        importlib.reload(se_module)
        se_module._tavily_client = mock_client
        se_module.TAVILY_AVAILABLE = True
        se_module._TAVILY_API_KEY = "test_key"

        with patch("time.sleep"):  # Don't actually sleep in tests
            result = se_module.get_live_research("retry test input query")

        assert call_count[0] == 2  # Must have retried exactly once
        assert "context" in result

    def test_singleton_client_not_recreated(self):
        """_tavily_client singleton must not be re-created on each call."""
        import importlib
        import capabilities.web.search_engine as se_module
        importlib.reload(se_module)

        original_client = MagicMock()
        original_client.search.return_value = {"results": [{"content": "Test"}]}
        se_module._tavily_client = original_client
        se_module.TAVILY_AVAILABLE = True
        se_module._TAVILY_API_KEY = "test_key"

        se_module.get_live_research("query number one today")
        se_module.get_live_research("query number two today")

        # The same client object should be reused
        assert se_module._tavily_client is original_client
