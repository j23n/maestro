# 3. LLM Cost Management

**Phase 3 | Effort: M | Dependencies: Monitoring (Phase 2B, need token tracking)**

## Current State

- ~7-8 API calls per A1 lesson, mostly Sonnet
- No cost visibility — unknown per-lesson cost
- No per-user rate limiting
- No circuit breaker on API errors
- Scoring uses Sonnet (`SCORING_MODEL`) but many tasks are structured rubric checks that may work with Haiku

## What to Build

### Measure actual costs

- Use token tracking from Phase 2B to compute real per-lesson costs
- Aggregate by model (Sonnet vs Haiku) and call type (generation, scoring, feedback, analysis)
- Target: know the exact dollar cost of a typical 20-minute A1 lesson

### Model tier optimization

- Test Haiku for scoring (fill_blank, reading comprehension, error_correction)
- Run eval tests (`tests/eval/`) comparing Haiku vs Sonnet scoring quality
- Switch scoring to Haiku where quality is maintained
- Keep Sonnet for lesson generation (needs creativity + long output)

### Per-user lesson limit

- Free tier: unlimited A0 lessons, 10 A1 lessons lifetime
- Pro tier: unlimited lessons at all CEFR levels
- Check at lesson creation time (`POST /lezione/`)
- Count against `Lesson` documents with `cefr_at_start == "A1"` and `status in (active, completed)`

### Circuit breaker

- Graceful degradation when Anthropic API errors or rate-limits
- Surface clear errors to user instead of retrying indefinitely
- Current retry logic: `max_retries=3` in llm.py — add timeout and user-facing error

## Key Files

- `src/maestro/learning/scorer.py` (model selection)
- `src/maestro/llm.py` (client wrapper, cost aggregation)
- `src/maestro/lezione/planner.py` (generation model)
- `src/maestro/settings.py` (model configs)
- `tests/eval/` (scoring quality comparison)

## Verification

- Per-lesson cost visible in DB (dollar amount derived from token counts)
- Lifetime A1 lesson cap enforced for free tier (10 lessons), A0 unrestricted
- Haiku scoring validated by eval tests (if switching)
- API errors show user-friendly message, not 500
