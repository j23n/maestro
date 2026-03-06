# Phase A — Critical Fixes

Two bugs that affect production reliability. Fix before anything else.

---

## A.1: Fix Sync-in-Async Blocking in Scorer and Analyzer

### Problem

`scorer.py` and `analyzer.py` declare `async def` functions but call the **synchronous** Anthropic client (`_client().messages.create()`). This blocks the asyncio event loop for 1-5 seconds per call. Under concurrent requests, all scoring and analysis serializes — one user's drill submission blocks every other request.

Affected functions in `scorer.py` (6 functions, all blocking):
- `feedback_fill_blank` (line 55)
- `evaluate_error_correction` (line 96)
- `score_multi_item_drill` (line 171)
- `generate_writing_feedback` (line 217)
- `score_free_form_drill` (line 270)
- `score_reading_answers` (line 317)

Affected function in `analyzer.py` (1 function):
- `analyze_message` (line 96)

### Fix

1. **`learning/scorer.py`**: Change `_client()` to return async client:
   ```python
   def _client():
       return get_async_client()  # was: get_client()
   ```
   Then change every `_client().messages.create(...)` to `await _client().messages.create(...)` (6 call sites).

2. **`learning/analyzer.py`**: Same change — switch `_client()` to `get_async_client()`, add `await` to the `.messages.create()` call at line 96.

3. **Update test fixtures** in `tests/integration/conftest.py`:
   - `mock_scorer_client`: the mock's `messages.create` must be an `AsyncMock`
   - `mock_analyzer_client`: same

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/learning/scorer.py` | `get_client` → `get_async_client`, add `await` ×6 |
| `src/maestro/learning/analyzer.py` | `get_client` → `get_async_client`, add `await` ×1 |
| `tests/integration/conftest.py` | Update mock fixtures for async |

### Verification

```
uv run pytest -m integration tests/integration/test_scoring.py -v
uv run pytest -m integration tests/integration/test_analyzer.py -v
```

Also verify with `PYTHONASYNCIODEBUG=1` — no "Executing <Handle ...> took X.XXX seconds" warnings should appear during scoring.

---

## A.2: Anthropic Client Lifecycle

### Problem

`llm.py` creates a **new** `anthropic.Anthropic()` / `anthropic.AsyncAnthropic()` on every call to `get_client()` / `get_async_client()`. This wastes TCP connection setup and prevents HTTP connection pooling. A single lesson generation triggers 3-5 client instantiations.

### Fix

Cache client instances with `@lru_cache`, matching the existing pattern used for spaCy (`vocab/nlp.py`) and SentenceTransformer (`rag/retrieve.py`):

```python
from functools import lru_cache
import anthropic
from maestro.config import settings


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


@lru_cache(maxsize=1)
def get_async_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
```

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/llm.py` | Add `@lru_cache(maxsize=1)` to both functions |

### Verification

All existing tests pass. No behavioral change — purely a performance improvement.

---

## Checklist

- [ ] A.1 — scorer.py: async client + await ×6
- [ ] A.1 — analyzer.py: async client + await ×1
- [ ] A.1 — test fixtures: AsyncMock for messages.create
- [ ] A.2 — llm.py: lru_cache on both client factories
- [ ] Full test suite passes
