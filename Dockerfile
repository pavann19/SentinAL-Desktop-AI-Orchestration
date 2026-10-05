# Headless evaluation only; this image cannot execute Windows desktop actions.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app
RUN pip install --no-cache-dir "sentence-transformers>=5.6,<7" "torch>=2.13,<3" "transformers>=5.10,<6" "scikit-learn==1.8.0" "numpy>=2.0.2,<3" "joblib>=1.3"
COPY eval/ ./eval/
COPY agentic_core/router.py agentic_core/embedding_backend.py ./agentic_core/
CMD ["python", "-m", "eval.finetune_classifier", "--run-id", "docker"]
