# agentic_core/mock_llm.py
# SENTINAL_OFFLINE=1 support: a zero-network, zero-model stand-in for
# BrainConfig's LLM factories, used only when BOTH the cloud path (Groq) is
# skipped by the offline flag AND no local Ollama server is reachable
# either. Rule-based, not intelligent — enough to keep the pipeline running
# end to end (a demo, a from-scratch clone, a CI box with nothing installed)
# without silently hanging on a network call or crashing on a missing key.
#
# Shape matches what every test file in this repo already mocks by hand:
# `llm.invoke(messages) -> object with .content` — see any
# `MagicMock(content=...)` in tests/. This class is that same shape, made
# real and reusable instead of re-created ad hoc per test.

from __future__ import annotations

import json
import re
import urllib.request

_OLLAMA_HOST = "http://localhost:11434"


def ollama_reachable(timeout: float = 0.75) -> bool:
    """True if a local Ollama server answers. Cheap, local-only, never
    raises — a closed port or missing binary is the expected common case,
    not an error."""
    try:
        with urllib.request.urlopen(f"{_OLLAMA_HOST}/api/tags", timeout=timeout):
            return True
    except Exception:
        return False


class _MockMessage:
    def __init__(self, content: str):
        self.content = content


def _flatten(messages) -> str:
    """Handles the ("role", "text") tuple-list shape every call site in this
    repo uses (`llm.invoke([("system", prompt)])`), plus plain strings."""
    if isinstance(messages, str):
        return messages
    try:
        return "\n".join(
            m[1] if isinstance(m, (tuple, list)) and len(m) > 1 else str(m)
            for m in messages
        )
    except Exception:
        return str(messages)


# Heuristics for the handful of prompt SHAPES the pipeline actually sends —
# not general understanding. Each returns a minimal, syntactically valid
# response of the kind the caller's own parser expects, so extraction/
# planning code paths don't crash on a malformed response; the CONTENT is a
# stub, clearly not a real answer.
_JSON_ARRAY_HINTS = ("json array", "output only", "actions array", "step objects")


class DeterministicMockLLM:
    """Offline-mode fallback. Never used unless SENTINAL_OFFLINE=1 AND no
    local Ollama is reachable — see BrainConfig.get_local_llm()."""

    def invoke(self, messages) -> _MockMessage:
        prompt = _flatten(messages).lower()

        if any(h in prompt for h in _JSON_ARRAY_HINTS):
            content = json.dumps([
                {"type": "shell", "payload": "echo SentinAL offline mode — no LLM reachable"}
            ])
        elif re.search(r"step_id|depends_on|goal", prompt):
            # planner-shaped prompt: one inert step, not a real decomposition
            content = json.dumps([{
                "step_id": "step_1", "intent": "ConversationalIntent",
                "target": "", "prompt": "offline mode",
                "depends_on": [], "speech_response":
                    "I'm running in offline mode with no LLM reachable — nothing to plan.",
            }])
        else:
            content = (
                "SentinAL is running in offline mode (SENTINAL_OFFLINE=1) with no "
                "local Ollama server reachable, so this is a canned response, not "
                "a real answer. Start Ollama for genuine local responses, or unset "
                "SENTINAL_OFFLINE to use a configured cloud key."
            )
        return _MockMessage(content)
