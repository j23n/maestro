FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files and install
COPY pyproject.toml uv.lock /app/
RUN uv pip install --system -r pyproject.toml

# Copy application code
COPY src/ /app/src/
COPY templates/ /app/templates/
COPY data/ /app/data/

WORKDIR /app/src

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "maestro.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
