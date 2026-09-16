# tests/test_embedding_backend.py
# Router memory swap: build_embedder() selection + interface-compatibility
# tests. The real memory/equivalence measurements live in the commit message
# and embedding_backend.py's own docstring (they need a live model load,
# not something to re-measure on every test run).

from __future__ import annotations

import importlib
import os

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _reset_module(monkeypatch):
    """Each test picks its own backend via the env var; reload so the
    module-level BACKEND constant reflects it."""
    yield
    monkeypatch.delenv("SENTINAL_EMBEDDING_BACKEND", raising=False)
    import agentic_core.embedding_backend as eb
    importlib.reload(eb)


def test_default_backend_is_torch(monkeypatch):
    monkeypatch.delenv("SENTINAL_EMBEDDING_BACKEND", raising=False)
    import agentic_core.embedding_backend as eb
    eb = importlib.reload(eb)
    assert eb.BACKEND == "torch"


def test_onnx_backend_selected_via_env(monkeypatch):
    monkeypatch.setenv("SENTINAL_EMBEDDING_BACKEND", "onnx")
    import agentic_core.embedding_backend as eb
    eb = importlib.reload(eb)
    assert eb.BACKEND == "onnx"


def test_unknown_backend_falls_back_to_torch(monkeypatch):
    monkeypatch.setenv("SENTINAL_EMBEDDING_BACKEND", "quantum")
    import agentic_core.embedding_backend as eb
    eb = importlib.reload(eb)
    assert eb.BACKEND == "torch"


def test_build_embedder_explicit_choice_overrides_env(monkeypatch):
    monkeypatch.setenv("SENTINAL_EMBEDDING_BACKEND", "torch")
    import agentic_core.embedding_backend as eb
    eb = importlib.reload(eb)

    class _Fake:
        def encode(self, texts):
            return np.zeros((len(texts), 384), dtype=np.float32)

    monkeypatch.setattr(eb, "_OnnxBackend", _Fake)
    embedder = eb.build_embedder(backend="onnx")
    assert isinstance(embedder, _Fake)


def test_torch_backend_interface_shape(monkeypatch):
    """Doesn't load the real model — verifies the wrapper's contract:
    encode(list[str]) -> ndarray shaped (N, dim)."""
    import agentic_core.embedding_backend as eb

    class _FakeSentenceTransformer:
        def __init__(self, *a, **k):
            pass

        def encode(self, texts):
            return np.ones((len(texts), 384), dtype=np.float32)

    backend = eb._TorchBackend.__new__(eb._TorchBackend)
    backend._model = _FakeSentenceTransformer()
    out = backend.encode(["a", "b", "c"])
    assert out.shape == (3, 384)


def test_onnx_backend_interface_shape():
    """Doesn't load the real model — verifies embed()'s generator output is
    normalised to the same (N, dim) ndarray contract as the torch backend."""
    import agentic_core.embedding_backend as eb

    class _FakeFastEmbed:
        def __init__(self, *a, **k):
            pass

        def embed(self, texts):
            for _ in texts:
                yield np.ones(384, dtype=np.float32)

    backend = eb._OnnxBackend.__new__(eb._OnnxBackend)
    backend._model = _FakeFastEmbed()
    out = backend.encode(["a", "b"])
    assert out.shape == (2, 384)
    assert isinstance(out, np.ndarray)


@pytest.mark.skipif(
    not os.getenv("SENTINAL_RUN_SLOW_TESTS"),
    reason="loads two real embedding models (~20s+) — set SENTINAL_RUN_SLOW_TESTS=1 to run",
)
def test_onnx_and_torch_backends_agree_on_real_embeddings():
    """The real equivalence check — both backends load the actual models and
    must produce near-identical vectors for the same text. Opt-in only, so
    the default test run stays fast; this is the test that was actually run
    (manually) to produce the cosine-similarity numbers in the commit
    message and this module's docstring."""
    from agentic_core.embedding_backend import build_embedder

    torch_backend = build_embedder("torch")
    onnx_backend = build_embedder("onnx")

    phrases = ["open notepad", "delete the file report.txt", "remind me to call mom at 6pm"]
    t_vecs = torch_backend.encode(phrases)
    o_vecs = onnx_backend.encode(phrases)

    for i in range(len(phrases)):
        cos = float(np.dot(t_vecs[i], o_vecs[i]) /
                    (np.linalg.norm(t_vecs[i]) * np.linalg.norm(o_vecs[i])))
        assert cos > 0.999, f"backends diverged on {phrases[i]!r}: cos={cos}"
