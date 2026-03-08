# Production Dockerfile

**Area:** `Dockerfile`, `docker-compose.yaml`
**Roadmap:** [02-deploy](../roadmap/02-deploy.md)
**Depends on:** #26 (environment config)

## Goal

Make the Dockerfile production-ready: proper ASGI server, build-time model download, health check.

## Work

### Pin Python version

- Use `python:3.13-slim` as the base image (matches `requires-python` in pyproject.toml; 3.14 is pre-release)

### Replace dev server with uvicorn

- Remove `uv fastapi dev` command
- Use `uvicorn maestro.main:app --host 0.0.0.0 --port 8000 --workers 2`

### Download spaCy model at build time

- Add `RUN python -m spacy download it_core_news_md` so the model is baked into the image instead of downloaded at runtime

### Add HEALTHCHECK

- `HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1`
- Requires the `/health` endpoint (add a simple `GET /health` route returning 200 if not already present)

### Update docker-compose.yaml

- Set `ENVIRONMENT=development` for local dev
- Ensure local MongoDB setup still works

## Tests

- Build image locally and verify it starts with uvicorn
- `GET /health` returns 200
- spaCy model is available without runtime download

## Notes

- The `/health` endpoint should be unauthenticated and lightweight (no DB query needed for now; just return 200).
