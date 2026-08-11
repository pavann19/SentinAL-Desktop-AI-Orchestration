"""
tests/test_settings.py
Tests for unified BrainConfig LLM Factory.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
from config.settings import BrainConfig

class TestBrainConfig:
    @patch('langchain_ollama.ChatOllama')
    @patch.dict(os.environ, {"OLLAMA_MODEL": "test-model"})
    def test_get_local_llm(self, MockChatOllama):
        llm = BrainConfig.get_local_llm(num_predict=123)
        MockChatOllama.assert_called_once_with(model="test-model", temperature=0, num_predict=123)
        assert llm == MockChatOllama.return_value

    # clear=True on both: @patch.dict MERGES into os.environ by default rather
    # than replacing it, so without clear=True these leaked the real
    # GROQ_API_KEY_2 from the actual .env (loaded once at process start via
    # load_dotenv()) straight into the test — BrainConfig then legitimately saw
    # 2 configured keys and returned a _RotatingGroqLLM / a real ChatGroq
    # instead of the None/single-key result the test expected. Not a flaw in
    # the rotation feature; a pre-existing test-isolation gap the new env var
    # was the first thing to actually expose.
    @patch('langchain_groq.ChatGroq')
    @patch.dict(os.environ, {"GROQ_API_KEY": "fake-key", "GROQ_MODEL": "fake-model"}, clear=True)
    def test_get_cloud_llm_with_key(self, MockChatGroq):
        llm = BrainConfig.get_cloud_llm(max_tokens=456)
        MockChatGroq.assert_called_once_with(model_name="fake-model", groq_api_key="fake-key", temperature=0, max_tokens=456)
        assert llm == MockChatGroq.return_value

    @patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=True)
    def test_get_cloud_llm_without_key_returns_none(self):
        llm = BrainConfig.get_cloud_llm()
        assert llm is None

    @patch('config.settings.BrainConfig.get_local_llm')
    def test_get_correction_llm(self, mock_get_local_llm):
        llm = BrainConfig.get_correction_llm()
        mock_get_local_llm.assert_called_once_with(num_predict=100)
        assert llm == mock_get_local_llm.return_value

    @patch('system_services.privacy_router.privacy_guard.analyze')
    @patch('config.settings.BrainConfig.get_local_llm')
    def test_get_routed_llm_local_route(self, mock_local, mock_analyze):
        mock_analyze.return_value = {"route": "local", "reason": "PII detected"}
        mock_local.return_value = "local_llm"
        llm = BrainConfig.get_routed_llm("my password is sec")
        mock_analyze.assert_called_once_with("my password is sec")
        assert llm == "local_llm"

    @patch('system_services.privacy_router.privacy_guard.analyze')
    @patch('config.settings.BrainConfig.get_cloud_llm')
    @patch('config.settings.BrainConfig.get_local_llm')
    @patch('concurrent.futures.ThreadPoolExecutor')
    def test_get_routed_llm_cloud_route_success(self, mock_pool, mock_local, mock_cloud, mock_analyze):
        mock_analyze.return_value = {"route": "cloud", "reason": "Safe"}
        mock_cloud_instance = MagicMock()
        mock_cloud.return_value = mock_cloud_instance
        
        # Setup mock future for successful ping
        mock_future = MagicMock()
        mock_future.result.return_value = "pong"
        mock_executor = MagicMock()
        mock_executor.__enter__.return_value = mock_executor
        mock_executor.submit.return_value = mock_future
        mock_pool.return_value = mock_executor

        llm = BrainConfig.get_routed_llm("what is the weather")
        
        assert llm == mock_cloud_instance
        mock_executor.submit.assert_called_once()
        mock_local.assert_not_called()

    @patch('system_services.privacy_router.privacy_guard.analyze')
    @patch('config.settings.BrainConfig.get_cloud_llm')
    @patch('config.settings.BrainConfig.get_local_llm')
    @patch('concurrent.futures.ThreadPoolExecutor')
    def test_get_routed_llm_cloud_fallback_timeout(self, mock_pool, mock_local, mock_cloud, mock_analyze):
        import concurrent.futures
        mock_analyze.return_value = {"route": "cloud", "reason": "Safe"}
        mock_cloud.return_value = MagicMock()
        mock_local.return_value = "local_fallback"
        
        mock_future = MagicMock()
        mock_future.result.side_effect = concurrent.futures.TimeoutError("Timeout")
        mock_executor = MagicMock()
        mock_executor.__enter__.return_value = mock_executor
        mock_executor.submit.return_value = mock_future
        mock_pool.return_value = mock_executor

        llm = BrainConfig.get_routed_llm("weather")
        assert llm == "local_fallback"
        mock_local.assert_called_once()

    @patch('system_services.privacy_router.privacy_guard.analyze')
    @patch('config.settings.BrainConfig.get_cloud_llm')
    @patch('config.settings.BrainConfig.get_local_llm')
    @patch('concurrent.futures.ThreadPoolExecutor')
    def test_get_routed_llm_cloud_fallback_exception(self, mock_pool, mock_local, mock_cloud, mock_analyze):
        mock_analyze.return_value = {"route": "cloud", "reason": "Safe"}
        mock_cloud.return_value = MagicMock()
        mock_local.return_value = "local_fallback"
        
        mock_future = MagicMock()
        mock_future.result.side_effect = Exception("API down")
        mock_executor = MagicMock()
        mock_executor.__enter__.return_value = mock_executor
        mock_executor.submit.return_value = mock_future
        mock_pool.return_value = mock_executor

        llm = BrainConfig.get_routed_llm("weather")
        assert llm == "local_fallback"
        mock_local.assert_called_once()
