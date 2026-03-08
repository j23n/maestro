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

# Fetch LFS files (BSON seed data) via deploy key
RUN apt-get update && apt-get install -y --no-install-recommends git git-lfs openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY data/ /app/data/

ARG DEPLOY_KEY
RUN mkdir -p /root/.ssh \
    && echo "${DEPLOY_KEY}" > /root/.ssh/id_rsa \
    && chmod 600 /root/.ssh/id_rsa \
    && ssh-keyscan github.com >> /root/.ssh/known_hosts \
    && git init /app \
    && git -C /app remote add origin git@github.com:johannesio/maestro.git \
    && git -C /app lfs install \
    && for f in /app/data/seed/current/*.bson; do \
         git -C /app lfs smudge < "$f" > "$f.real" && mv "$f.real" "$f"; \
       done \
    && rm -rf /app/.git /root/.ssh

ENV PYTHONPATH=/app/src

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1

CMD exec uvicorn maestro.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
