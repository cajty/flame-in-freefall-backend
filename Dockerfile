FROM node:22-bookworm-slim AS data
WORKDIR /build
COPY package.json ./
COPY scripts ./scripts
COPY data/processed ./data/processed
RUN node scripts/build-data.mjs

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir --editable .
COPY --from=data /build/generated.json ./generated.json
COPY data/processed ./data/processed
COPY data/reference ./data/reference
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
