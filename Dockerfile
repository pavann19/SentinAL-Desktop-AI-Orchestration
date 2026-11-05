# Headless router evaluation only. This image does not operate a desktop.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    TRANSFORMERS_NO_ADVISORY_WARNINGS=1 \
    HOME=/home/sentinal

WORKDIR /app
COPY requirements-eval.txt ./
RUN python -m pip install --no-cache-dir -r requirements-eval.txt \
    && useradd --create-home --uid 10001 sentinal

COPY eval/ ./eval/
COPY agentic_core/router.py agentic_core/embedding_backend.py ./agentic_core/
RUN mkdir -p _evidence/finetuning _evidence/intent_accuracy \
    && chown -R sentinal:sentinal /app

USER sentinal
# Encoder weights may download on the first run. No classifier is bundled.
CMD ["python", "-m", "eval.measure_intent_accuracy", "--mode", "router-only", "--run-id", "container"]
