# 1B. Deployment Infrastructure

**Phase 1 | Effort: M | Dependencies: None (parallel with Auth)**

## Current State

- Dockerfile uses `uv fastapi dev` (dev mode with auto-reload)
- docker-compose only runs local MongoDB
- No TLS/HTTPS
- No health checks
- No production ASGI server
- htmx loaded from unpkg CDN
- `directConnection=true` in MongoDB connection string (won't work with Atlas)
- spaCy model downloaded at runtime, not build time

## What to Build

### Fix Dockerfile

- Pin Python 3.13 (matches `requires-python` in pyproject.toml; 3.14 is pre-release)
- Replace `uv fastapi dev` with `uvicorn maestro.main:app --host 0.0.0.0 --port 8000 --workers 2`
- Download spaCy model at build time: `RUN python -m spacy download it_core_news_md`
- Add `HEALTHCHECK` directive

### Hosting: Railway

- Push-to-deploy from main branch
- Built-in TLS termination (HTTPS automatic)
- Secrets management via dashboard (no .env files in production)
- Simplest option for solo dev

### Database: MongoDB Atlas

- Free tier (512MB shared cluster) to start
- Remove `directConnection=true` from connection string in `db.py`
- Set connection via `MONGODB_URI` environment variable (Atlas provides full URI)

### Environment config

- Add `ENVIRONMENT` setting (dev/staging/production) to `settings.py`
- Toggle: cookie secure flag, debug logging level, allowed origins

### Data seeding

- Startup check or CLI command to run ingest scripts if curriculum collections are empty
- Ingest scripts are already idempotent (upsert by slug/code)

### Static assets

- Self-host htmx.js in `/static/` instead of unpkg CDN (security + reliability)
- Static files served by FastAPI directly (fine for low traffic; add Cloudflare CDN later if needed)

## Key Files

- `Dockerfile`
- `docker-compose.yaml`
- `src/maestro/settings.py`
- `src/maestro/db.py` (connection string)
- `src/maestro/main.py` (lifespan, static mount)
- `templates/base.html` (htmx script tag)

## Verification

- App accessible via HTTPS on Railway
- `GET /health` returns 200
- Lessons generate successfully against Atlas DB
- Ingest data present after first deploy
