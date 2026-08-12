# TKOS Ontology Runtime — container image (volcengine-deployment-design §9.2/§13)
#
# Notes:
#   * Editable install on purpose: server.py resolves the repo root as
#     Path(__file__).resolve().parents[3] — a plain `pip install .` would
#     put the package in site-packages and break the path. `-e .` keeps
#     __file__ in the copied source tree.
#   * Stage A artifact distribution (design §4): schema/shapes/dataset/
#     instances are baked into the image. Tag the image as
#     tkos-runtime:<code-sha>-<dataset-rev12> — code and data travel together.
#   * gunicorn CMD per design §6.1: no --preload (each worker loads its own
#     in-memory graph), --graceful-timeout must exceed p99 LLM latency.
FROM python:3.11-slim

# China-network pip mirror (default PyPI is flaky/incomplete from CN networks —
# causes spurious ResolutionImpossible). Override for CI/production:
#   docker build --build-arg PIP_INDEX_URL=https://pypi.org/simple ...
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install runtime deps (cached layer — rebuild only when pyproject changes)
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --index-url "$PIP_INDEX_URL" -e '.[api]'

# Ontology + instance artifacts (Stage A: baked into image)
COPY ontology/schema/ ./ontology/schema/
COPY ontology/shapes/ ./ontology/shapes/
COPY ontology/datasets/ ./ontology/datasets/
COPY data/instances/ ./data/instances/

# Run as non-root
RUN adduser --disabled-password --gecos "" --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Shell-form CMD so GUNICORN_* env vars take effect (design §6.1 default
# reflected here): LLM polish can take ~120s, so --timeout defaults to 180
# and must stay above LLM_TIMEOUT + margin. Override per deployment:
#   GUNICORN_WORKERS=1 (2 GiB hosts) / GUNICORN_TIMEOUT=300 (slow models)
CMD ["sh", "-c", "gunicorn tkos_runtime.api.server:app \
     -k uvicorn.workers.UvicornWorker \
     -w ${GUNICORN_WORKERS:-2} \
     -b 0.0.0.0:8000 \
     --timeout ${GUNICORN_TIMEOUT:-180} \
     --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-35} \
     --keep-alive 5 \
     --access-logfile - \
     --error-logfile -"]
