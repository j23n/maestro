FROM python:3.14-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create app directory
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock /app/

# Install dependencies using uv
RUN uv pip install --system -r pyproject.toml
 
# Copy application code
COPY . /app/

# Copy entrypoint script
COPY docker-entrypoint.sh /app/

EXPOSE 8000

CMD ["uv", \
     "fastapi", \
     "dev", \
     "main.py"]
