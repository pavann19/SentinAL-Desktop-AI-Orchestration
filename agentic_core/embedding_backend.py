# agentic_core/embedding_backend.py
# Router memory swap: the router's embedding model is the single largest
# resident-memory cost in the idle process (torch + sentence-transformers +
# BertModel weights). This module lets that cost be swapped for an ONNX
# Runtime backend that returns numerically equivalent vectors, without
# touching anything that consumes `.encode()` — router.py,
# semantic_memory.py, procedural_memory.py, skill_matcher.py all call
# `model.encode(list[str]) -> ndarray of shape (N, 384)` and neither know nor
# care which backend produced it.
#
# Measured on this machine (venv, cold process, RSS via psutil):
#   torch backend (sentence-transformers, current default)
#     import + load + first encode: ~458 MB resident
#   onnx backend (fastembed's ONNX export of the SAME checkpoint,
#   sentence-transformers/all-MiniLM-L6-v2)
#     import + load + first encode: ~202 MB resident  (~56% smaller)
#
# Numerical equivalence measured across 14 router-style phrases: cosine
# similarity between the two backends' output vectors was 0.999999+ on every
# phrase (min 0.9999999, mean 1.0000000 — float32 noise, not a real
# difference), and nearest-neighbour ranking agreed 14/14. The trained
# classifier (classifier_v2_realdata.joblib) was fit on sentence-transformers
# MiniLM vectors; this level of equivalence means its decision boundaries
# transfer to the ONNX backend's output without retraining.
#
# Still defaults to the proven "torch" backend — same discipline as every
# other flag this session: ship it, validate it, then flip the default.
# SENTINAL_EMBEDDING_BACKEND=onnx opts in.

from __future__ import annotations

import logging
import os

import numpy as np

_logger = logging.getLogger("EmbeddingBackend")

BACKEND = os.getenv("SENTINAL_EMBEDDING_BACKEND", "torch").strip().lower()
if BACKEND not in ("torch", "onnx"):
    _logger.warning(f"Unknown SENTINAL_EMBEDDING_BACKEND={BACKEND!r}, falling back to 'torch'")
    BACKEND = "torch"

_ONNX_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class _TorchBackend:
    """The original path: sentence-transformers + torch."""

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

    def encode(self, texts: list[str]) -> np.ndarray:
        return self._model.encode(texts)


class _OnnxBackend:
    """fastembed's ONNX Runtime export of the identical checkpoint. No torch
    import at all — this is where the memory saving comes from."""

    def __init__(self):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=_ONNX_MODEL_NAME)

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(list(self._model.embed(list(texts))), dtype=np.float32)


def build_embedder(backend: str | None = None):
    """Constructs the selected backend. Raises on failure — the caller
    (router.py's own try/except around model init) already has a keyword-
    fallback path for exactly this case, so this does not need its own."""
    choice = (backend or BACKEND).strip().lower()
    if choice == "onnx":
        _logger.info(f"Loading ONNX embedding backend ({_ONNX_MODEL_NAME}, fastembed)")
        return _OnnxBackend()
    _logger.info("Loading torch embedding backend (sentence-transformers, all-MiniLM-L6-v2)")
    return _TorchBackend()
