# 2B. Monitoring & Observability

**Phase 2 | Effort: S | Dependencies: Deploy (Phase 1B)**

## Current State

- `logging.basicConfig(level=logging.WARNING)` with DEBUG for maestro namespace
- No error tracking (no Sentry)
- No health check endpoint
- No metrics or token usage tracking
- No structured logging

## What to Build

### Sentry

- Add `sentry-sdk[fastapi]` to dependencies
- Initialize in `main.py` lifespan with `SENTRY_DSN` from settings
- Captures unhandled exceptions, LLM API errors, slow transactions
- Free tier: 5K errors/month

### Health check

- `GET /health` — checks MongoDB connectivity, returns 200/503
- Used by Railway for health monitoring

### LLM token tracking

This is critical for understanding costs before setting prices.

- Wrap `get_async_client()` in `llm.py` to log input/output tokens per API call
- Anthropic client returns `usage` metadata (input_tokens, output_tokens) on every response
- Store per-lesson totals on `Lesson` document (new field: `token_usage: dict`)
- All LLM call sites go through either `_client()` in scorer.py or `get_async_client()` in llm.py

Current call sites per A1 lesson (~7-8 calls):
- 1 Sonnet call for lesson generation (planner.py, up to 16K output tokens — most expensive)
- 2-3 Sonnet calls for scoring (scorer.py)
- 1 Haiku call for end-of-lesson feedback (service.py)
- 2-3 Haiku calls for CF analysis (lesson_analyzer.py)

### Structured logging

- Replace `logging.basicConfig` with JSON-formatted logs
- Railway aggregates logs automatically; structured format makes them searchable

## Key Files

- `src/maestro/main.py` (Sentry init, health endpoint)
- `src/maestro/llm.py` (token tracking wrapper)
- `src/maestro/settings.py` (SENTRY_DSN)
- `src/maestro/models.py` (token_usage field on Lesson)

## Verification

- Sentry dashboard shows test error
- `GET /health` returns 200 when DB is up, 503 when down
- Token usage logged per lesson in DB
