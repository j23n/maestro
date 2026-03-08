# 2A. CI/CD Pipeline

**Phase 2 | Effort: S | Dependencies: Deploy (Phase 1B)**

## Current State

- No `.github/workflows/` directory
- No automation for testing, linting, or deployment
- Tests exist: ~60 unit tests (~2s), ~74 integration tests (mongomock)
- Ruff linter in dev dependencies

## What to Build

### GitHub Actions workflow

Two jobs on push/PR:

1. **Test**: `uv run pytest -m unit tests/unit/ -v && uv run pytest -m integration tests/integration/ -v`
2. **Lint**: `uv run ruff check`

No secrets needed — unit and integration tests mock all external services (mongomock for DB, mocked Anthropic client).

### Auto-deploy

- Railway auto-deploys on push to main (configure branch trigger in Railway dashboard)
- CI must pass before merge (branch protection rule on GitHub)

### Eval tests

- Stay opt-in (require `ANTHROPIC_API_KEY`)
- Run manually or as nightly cron, not blocking CI

## Key Files

- `.github/workflows/ci.yml` (new)
- GitHub repo settings (branch protection)

## Verification

- Push to PR triggers test + lint
- Merge to main triggers Railway deploy
- Failed tests block merge
