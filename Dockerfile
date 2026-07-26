# ─────────────────────────────────────────────────────────────────────────────
# SentinAL — Evaluation Reproduction Image
#
# SCOPE, STATED HONESTLY: this image does NOT run the SentinAL desktop agent.
# The agent is a Windows application — it drives the GUI (pyautogui, win32gui),
# launches native apps, captures a microphone for wake-word/STT, and calls
# Windows-only tooling (tasklist, taskkill). None of that runs in a Linux
# container, and pretending it does would be dishonest.
#
# What this image DOES do — and the reason it exists — is let anyone reproduce
# the paper's headline intent-accuracy numbers from scratch on a clean machine,
# with no Windows box required:
#   - trained-classifier vs. zero-shot accuracy (99.33% / 92.00% test/OOD)
#   - router-only accuracy over the full dataset
# These depend only on sentence-transformers + scikit-learn.
#
# Build:  docker build -t sentinal-eval .
# Run:    docker run --rm sentinal-eval            # reproduces classifier accuracy
#         docker run --rm sentinal-eval python -m eval.measure_intent_accuracy \
#                        --mode router-only --run-id docker
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TRANSFORMERS_NO_ADVISORY_WARNINGS=1

WORKDIR /app

# Only the evaluation surface's dependencies — deliberately NOT the full
# requirements.txt, which pulls in GUI/voice/Windows packages that neither
# install cleanly nor serve any purpose in a headless Linux container.
RUN pip install --no-cache-dir \
    "sentence-transformers>=3.0.0,<4.0.0" \
    "scikit-learn>=1.5.0,<2.0.0" \
    "numpy>=1.26.0,<2.0.0" \
    "joblib>=1.3.0"

# Copy only what the evaluation actually reads: the harness, the datasets, the
# committed model + split, and the router's phrase banks (imported by the
# zero-shot baseline path). The agent runtime is intentionally excluded.
# agentic_core has no __init__.py — it is an implicit namespace package, which
# resolves correctly as long as the directory containing router.py is on the
# path (WORKDIR is, when running `python -m ...`). Only router.py is needed:
# the zero-shot baseline path imports the router singleton, nothing else.
COPY eval/ ./eval/
COPY agentic_core/router.py ./agentic_core/router.py
COPY _evidence/finetuning/ ./_evidence/finetuning/
COPY _evidence/intent_accuracy/ ./_evidence/intent_accuracy/

# Default: retrain the classifier and print the accuracy comparison. Fully
# reproducible — the split is seeded and its indices are committed, so the
# numbers come out identical to those reported in the thesis.
CMD ["python", "-m", "eval.finetune_classifier", "--run-id", "docker"]
