"""CPU embedding adapters: Torch by default, optional ONNX backend.

Backend equivalence and model compatibility require evaluation for the selected
versions. Backend selection does not establish a performance guarantee.
"""
from __future__ import annotations

import logging
import os

import numpy as np

from config.constants import EMBEDDING_MODEL_ID, EMBEDDING_MODEL_REVISION

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
        self._model = SentenceTransformer(EMBEDDING_MODEL_ID, revision=EMBEDDING_MODEL_REVISION, device="cpu")

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
