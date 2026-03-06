# Phase D — Nice to Have

Lower-priority improvements. Address when time allows or when working in nearby code.

---

## D.1: Atomic Lesson State Transitions

### Problem

`lezione/service.py:advance_lesson()` reads a `Lesson` document, modifies it in Python, then saves it back. If two concurrent requests hit the same lesson (e.g., user double-clicks "next"), the read-modify-save cycle can lose state changes. One request's save overwrites the other's.

The same pattern exists in `routes/lezione.py:lezione_generating` and several other handlers that modify lesson state.

### Fix

Use MongoDB atomic update operators instead of full document replacement:

```python
async def advance_lesson(lesson: Lesson, current_idx: int, skip: bool = False) -> str:
    status = "skipped" if skip else "completed"
    next_idx = current_idx + 1
    # ... find next pending activity ...

    await Lesson.find_one({"_id": lesson.id}).update({
        "$set": {
            f"activities.{current_idx}.status": status,
            f"activities.{next_idx}.status": "active",
            "current_index": next_idx,
        }
    })
```

For lesson completion:
```python
await Lesson.find_one({"_id": lesson.id}).update({
    "$set": {"status": "completed", "completed_at": utcnow()}
})
```

### Complexity

Medium — requires rethinking how lesson state is managed. Currently the pattern is "load full doc, modify in Python, save" which is convenient for complex logic. Atomic updates are safer but harder to compose.

### Recommendation

Implement selectively for the highest-risk transitions (advance, complete) rather than rewriting all state management at once.

---

## D.2: User-Visible Error State for Failed Background Generation

### Problem

When `generate_lesson_background` fails, the error handler sets `generating=False` and the lesson is left with whatever activities were created before the failure (possibly zero). The user sees either:
- An empty lesson with no activities
- A lesson stuck on the generating spinner (if the flag wasn't cleared)

There's no feedback about what went wrong or how to recover.

### Fix

1. Add a `generation_error: Optional[str] = None` field to `Lesson`
2. On background failure, set it:
   ```python
   lesson.generating = False
   lesson.generation_error = "Content generation failed. Please try again."
   await lesson.save()
   ```
3. In the generating/activity templates, check for the error and show a retry button:
   ```html
   {% if lesson.generation_error %}
     <p class="error">{{ lesson.generation_error }}</p>
     <form method="POST" action="/lezione/{{ lesson.id }}/retry">
       <button type="submit">Riprova</button>
     </form>
   {% endif %}
   ```
4. Add a `POST /lezione/{id}/retry` route that re-triggers background generation.

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/models.py` | Add `generation_error` to `Lesson` |
| `src/maestro/lezione/planner.py` | Set error message on failure |
| `src/maestro/routes/lezione.py` | Add retry route, show error in template |
| `templates/lezione-generating.html` | Error display + retry button |

---

## D.3: Awaitable Background Tasks for Test Determinism

### Problem

`create_background_task()` fires tasks with no way to await them. Integration tests that trigger background tasks (lesson generation, lesson analysis, vocab definition generation) can't verify the task completed. Tests either:
- Ignore the background work entirely
- Use `asyncio.sleep()` hacks
- Mock out the background task creation

### Fix

Add an optional "test mode" to `utils.py` that collects tasks for manual awaiting:

```python
_test_mode: bool = False
_pending_tasks: list[asyncio.Task] = []

def enable_test_mode():
    global _test_mode
    _test_mode = True

async def drain_background_tasks():
    """Await all pending background tasks. Only works in test mode."""
    while _pending_tasks:
        task = _pending_tasks.pop(0)
        try:
            await task
        except Exception:
            pass

def create_background_task(coro, *, name=None):
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    if _test_mode:
        _pending_tasks.append(task)
    # ... existing done callback ...
    return task
```

Tests can then:
```python
@pytest.fixture(autouse=True)
def bg_test_mode():
    from maestro.utils import enable_test_mode
    enable_test_mode()

async def test_lesson_generates_activities(lesson):
    # trigger lesson creation
    await drain_background_tasks()
    # now verify activities exist
```

### Alternative

Simply `await` the coroutine directly in tests instead of going through `create_background_task`. This is simpler but doesn't test the actual background task path.

---

## D.4: Context-Based Cache Isolation for Tests

### Problem

`taxonomy.py` and `vocab/cache.py` use module-level mutable globals (`_grammar_points`, `_word_index`, `_loaded`). Tests must call `invalidate()` / `seed()` manually and an autouse fixture ensures cleanup. This is fragile — if a test forgets the fixture dependency or if invalidation order matters, tests leak state.

### Fix

Replace module globals with a `contextvars.ContextVar` per cache:

```python
import contextvars

_taxonomy_cache: contextvars.ContextVar[TaxonomyData | None] = contextvars.ContextVar(
    "_taxonomy_cache", default=None
)
```

Each test automatically gets its own context (pytest-asyncio creates a new event loop context per test). No explicit invalidation needed.

### Complexity

High — requires rethinking the cache API. The current `ensure_loaded()` + `grammar_points()` pattern would need to return from the context var. All call sites are the same, but the internal implementation changes significantly.

### Recommendation

Only pursue if test pollution becomes a recurring debugging problem. The current `seed()` / `invalidate()` pattern works and is well-understood.

---

## D.5: Error-Path Integration Tests

### Problem

No tests verify behavior when things go wrong:
- LLM returns malformed JSON (not valid JSON, wrong shape)
- A drill referenced by a `LessonActivity` doesn't exist in DB
- Background generation fails mid-way (some activities created, some not)
- Profile update fails during lesson completion

### Fix

Add targeted tests in `tests/integration/`:

```python
# test_error_paths.py

@pytest.mark.integration
async def test_malformed_llm_json_returns_fallback(mock_scorer_client, db, ...):
    """When LLM returns non-JSON, scorer falls back to all-incorrect."""
    mock_scorer_client.messages.create.return_value.content = [
        MagicMock(text="This is not JSON at all")
    ]
    results = await score_multi_item_drill(...)
    assert all(not r["objective_correct"] for r in results)

@pytest.mark.integration
async def test_missing_drill_returns_400(test_app, db, student):
    """Activity referencing a deleted drill returns 400."""
    lesson = Lesson(
        student_id=student.id,
        activities=[LessonActivity(type="drill", ..., drill_id=PydanticObjectId())],
        ...
    )
    await lesson.insert()
    response = test_app.get(f"/lezione/{lesson.id}/activity/0")
    assert response.status_code == 404

@pytest.mark.integration
async def test_background_generation_failure_clears_flag(db, student):
    """If LLM call raises, lesson.generating is set to False."""
    ...
```

### Estimated Effort

Small per test, but there are many error paths. Prioritize:
1. Malformed LLM JSON in scorer (most common failure mode)
2. Missing drill/card references
3. Background generation failure cleanup

---

## Checklist

- [ ] D.1 — Atomic updates for `advance_lesson` and `complete`
- [ ] D.2 — `generation_error` field + retry route + template error display
- [ ] D.3 — Awaitable background tasks for tests
- [ ] D.4 — Context-based cache isolation (only if needed)
- [ ] D.5 — Error-path integration tests (at least 3-5 tests)
