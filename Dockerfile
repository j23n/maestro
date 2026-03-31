## Stage 1: Resolve Git LFS pointers into real files
FROM alpine:3.21 AS lfs
RUN apk add --no-cache curl
ARG GITHUB_TOKEN
ARG RAILWAY_GIT_COMMIT_SHA=main
WORKDIR /repo
COPY data/ data/
# Download real content for any LFS pointer files via GitHub's media endpoint
RUN find /repo -type f -size -1k | while IFS= read -r f; do \
      if head -1 "$f" 2>/dev/null | grep -q "version https://git-lfs"; then \
        rel="${f#/repo/}"; \
        echo "Resolving LFS: ${rel}"; \
        curl -sfL -H "Authorization: token ${GITHUB_TOKEN}" \
          "https://media.githubusercontent.com/media/j23n/maestro/${RAILWAY_GIT_COMMIT_SHA}/${rel}" \
          -o "$f" || { echo "ERROR: failed to download ${rel}"; exit 1; }; \
        if head -1 "$f" 2>/dev/null | grep -q "version https://git-lfs"; then \
          echo "ERROR: ${rel} is still an LFS pointer after download"; exit 1; \
        fi; \
      fi; \
    done

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

# Copy application code (least-frequently-changed dirs first for layer caching)
COPY data/ /app/data/
COPY templates/ /app/templates/
COPY prompts/ /app/prompts/
COPY src/ /app/src/

# Overwrite LFS pointer files with real files from stage 1
COPY --from=lfs /repo/data/ /app/data/

ENV PYTHONPATH=/app/src

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1

CMD exec uvicorn maestro.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
