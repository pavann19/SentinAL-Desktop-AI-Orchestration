"""
tests/test_brain_config_key_rotation.py

Regression tests for Groq API key rotation on rate-limit errors.

Context: a 40x3 end-to-end benchmark run tonight burned through Groq's 100k
token/day quota partway through. Target extraction started failing with a bare
"[SRE] Target extraction failed: Error code: 429 ..." and no fallback, silently
producing empty targets for every cloud-routed intent for the rest of the run.
BrainConfig.get_routed_llm() already pinged Groq once before returning it, but
that only catches a key that is ALREADY exhausted at request time - not one
that runs out mid-session, which is what actually happened.

These tests never touch real key values or make real network calls - the Groq
client is replaced with a fake that raises a synthetic 429 on demand.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from config.settings import BrainConfig, _is_rate_limit_error


# ══════════════════════════════════════════════════════════════════════════════
# Rate-limit detection
# ══════════════════════════════════════════════════════════════════════════════
class TestRateLimitDetection:
    def test_detects_groq_429_message(self):
        exc = Exception(
            "Error code: 429 - {'error': {'message': 'Rate limit reached ...', "
            "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
        )
        assert _is_rate_limit_error(exc) is True

    def test_does_not_misclassify_a_network_error(self):
        """A network failure or bad key must NOT trigger rotation - those need
        get_routed_llm()'s existing fallback to Ollama, not a key swap that
        would fail identically."""
        assert _is_rate_limit_error(Exception("Connection refused")) is False

    def test_does_not_misclassify_an_auth_error(self):
        assert _is_rate_limit_error(Exception("Error code: 401 - invalid api key")) is False

    def test_does_not_misclassify_a_generic_500(self):
        assert _is_rate_limit_error(Exception("Error code: 500 - internal server error")) is False


# ══════════════════════════════════════════════════════════════════════════════
# Key collection
# ══════════════════════════════════════════════════════════════════════════════
class TestGroqApiKeyCollection:
    def test_single_key_from_primary_var(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "key-one")
        monkeypatch.delenv("GROQ_API_KEY_2", raising=False)
        assert BrainConfig._groq_api_keys() == ["key-one"]

    def test_collects_primary_and_fallback(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "key-one")
        monkeypatch.setenv("GROQ_API_KEY_2", "key-two")
        assert BrainConfig._groq_api_keys() == ["key-one", "key-two"]

    def test_no_keys_configured_returns_empty(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY_2", raising=False)
        assert BrainConfig._groq_api_keys() == []

    def test_duplicate_key_is_not_added_twice(self, monkeypatch):
        """A copy-paste mistake in .env (same key in both slots) must not
        produce a rotation that swaps a key onto itself."""
        monkeypatch.setenv("GROQ_API_KEY", "same-key")
        monkeypatch.setenv("GROQ_API_KEY_2", "same-key")
        assert BrainConfig._groq_api_keys() == ["same-key"]

    def test_strips_quotes_and_whitespace(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "  'key-one'  ")
        monkeypatch.delenv("GROQ_API_KEY_2", raising=False)
        assert BrainConfig._groq_api_keys() == ["key-one"]


# ══════════════════════════════════════════════════════════════════════════════
# get_cloud_llm() dispatch
# ══════════════════════════════════════════════════════════════════════════════
class TestGetCloudLlmDispatch:
    def test_no_keys_returns_none(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("GROQ_API_KEY_2", raising=False)
        assert BrainConfig.get_cloud_llm() is None

    def test_single_key_returns_plain_chatgroq_not_the_wrapper(self, monkeypatch):
        """Backward compatibility: with one key configured, the return type
        must be unchanged from before this feature existed."""
        monkeypatch.setenv("GROQ_API_KEY", "solo-key")
        monkeypatch.delenv("GROQ_API_KEY_2", raising=False)
        with patch("langchain_groq.ChatGroq") as mock_cls:
            mock_cls.return_value = MagicMock()
            result = BrainConfig.get_cloud_llm()
        mock_cls.assert_called_once()
        assert mock_cls.return_value is result

    def test_multiple_keys_returns_rotating_wrapper(self, monkeypatch):
        from config.settings import _RotatingGroqLLM
        monkeypatch.setenv("GROQ_API_KEY", "key-one")
        monkeypatch.setenv("GROQ_API_KEY_2", "key-two")
        with patch("langchain_groq.ChatGroq", return_value=MagicMock()):
            result = BrainConfig.get_cloud_llm()
        assert isinstance(result, _RotatingGroqLLM)


# ══════════════════════════════════════════════════════════════════════════════
# _RotatingGroqLLM.invoke() — the actual failover behaviour
# ══════════════════════════════════════════════════════════════════════════════
class TestRotatingGroqLLMInvoke:
    def _wrapper_with_fake_clients(self, *clients):
        """Builds a _RotatingGroqLLM with _build_client patched to hand out the
        given fakes in order, so no real ChatGroq/network call ever happens."""
        from config.settings import _RotatingGroqLLM
        wrapper = _RotatingGroqLLM.__new__(_RotatingGroqLLM)
        wrapper._api_keys = [f"key-{i}" for i in range(len(clients))]
        wrapper._model_name = "fake-model"
        wrapper._temperature = 0
        wrapper._max_tokens = 1024
        wrapper._index = 0
        wrapper._client = clients[0]
        wrapper._clients = list(clients)
        wrapper._build_client = lambda i, c=clients: c[i]
        return wrapper

    def test_succeeds_on_first_key_without_rotating(self):
        good = MagicMock()
        good.invoke.return_value = "ok"
        wrapper = self._wrapper_with_fake_clients(good)
        assert wrapper.invoke("prompt") == "ok"
        assert wrapper._index == 0

    def test_rotates_to_second_key_on_429_and_succeeds(self):
        exhausted = MagicMock()
        exhausted.invoke.side_effect = Exception(
            "Error code: 429 - rate_limit_exceeded"
        )
        fresh = MagicMock()
        fresh.invoke.return_value = "recovered"

        wrapper = self._wrapper_with_fake_clients(exhausted, fresh)
        result = wrapper.invoke("prompt")

        assert result == "recovered"
        assert wrapper._index == 1
        exhausted.invoke.assert_called_once()
        fresh.invoke.assert_called_once()

    def test_the_same_call_arguments_reach_the_fallback_client(self):
        """Rotation must retry the SAME call, not silently drop the request —
        callers throughout the pipeline rely on .invoke(messages) working
        exactly as it would against a single ChatGroq."""
        exhausted = MagicMock()
        exhausted.invoke.side_effect = Exception("429 rate_limit_exceeded")
        fresh = MagicMock()
        fresh.invoke.return_value = "ok"

        wrapper = self._wrapper_with_fake_clients(exhausted, fresh)
        wrapper.invoke([("system", "extract the target")], some_kwarg=True)

        fresh.invoke.assert_called_once_with([("system", "extract the target")], some_kwarg=True)

    def test_raises_when_every_key_is_rate_limited(self):
        a = MagicMock()
        a.invoke.side_effect = Exception("429 rate_limit_exceeded")
        b = MagicMock()
        b.invoke.side_effect = Exception("429 rate_limit_exceeded")

        wrapper = self._wrapper_with_fake_clients(a, b)
        with pytest.raises(Exception, match="429"):
            wrapper.invoke("prompt")

        a.invoke.assert_called_once()
        b.invoke.assert_called_once()

    def test_non_rate_limit_error_raises_immediately_without_rotating(self):
        """A genuine failure (bad key, network down) must surface immediately
        rather than silently trying every key, which would just multiply
        identical failures and delay the real error."""
        broken = MagicMock()
        broken.invoke.side_effect = Exception("Connection refused")
        untouched = MagicMock()

        wrapper = self._wrapper_with_fake_clients(broken, untouched)
        with pytest.raises(Exception, match="Connection refused"):
            wrapper.invoke("prompt")

        untouched.invoke.assert_not_called()
