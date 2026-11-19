FROM node:22-bookworm-slim AS data
WORKDIR /build
COPY package.json ./
COPY scripts ./scripts
COPY data/processed ./data/processed
RUN node scripts/build-data.mjs

FROM python:3.12-slim
WORKDIR /app
# Langfuse export is off unless LANGFUSE_* env is supplied at runtime.
# compose.yaml overrides this for the local Langfuse stack.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANGFUSE_ENABLED=0
COPY pyproject.toml ./
COPY src ./src
# The reranker stays disabled unless FLAME_RERANKER_ENABLED is set; the
# onnxruntime and tokenizers wheels are installed so enabling it needs only a
# model directory, not a rebuild.
RUN pip install --no-cache-dir --editable ".[rerank]"
COPY --from=data /build/generated.json ./generated.json
COPY data/processed ./data/processed
COPY data/reference ./data/reference
COPY models ./models
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
