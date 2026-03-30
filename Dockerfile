## Stage 1: Resolve Git LFS pointers into real files
FROM alpine:3.21 AS lfs
RUN apk add --no-cache git git-lfs
WORKDIR /repo
COPY .git .git
COPY .gitattributes .
RUN git lfs install && git lfs pull

## Stage 2: Application
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files and install
COPY pyproject.toml uv.lock /app/
RUN uv pip install --system --group deploy

# Copy application code
COPY src/ /app/src/
COPY templates/ /app/templates/
COPY prompts/ /app/prompts/

# Overwrite LFS pointer files with real files from stage 1
COPY --from=lfs /repo/src/ /app/src/

ENV PYTHONPATH=/app/src

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1

CMD exec uvicorn maestro.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
