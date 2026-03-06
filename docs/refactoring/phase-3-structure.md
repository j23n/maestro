# Phase 3: Structure

**Goal**: Replace global mutable state with a proper cache, handle background task errors, split oversized files, and fix the eager model load in RAG ingest. These are medium-effort changes that benefit from Phase 2's foundation.

**Effort**: 2-3 sessions. Tasks 3.2 and 3.4 are small; Tasks 3.1 and 3.3 are medium.

**Prerequisites**: Phase 2 complete (especially Task 2.1 — client factory).

**Validation**: `uv run pytest -m unit tests/unit/ -v && uv run pytest -m integration tests/integration/ -v` after each task.

---

## Task 3.1: Replace Global Mutable Caches with a Taxonomy Cache

### Problem

Two modules maintain their own copies of the same data using module-level globals:

**`learning/analyzer.py:29-31`**:
```python
_grammar_points_cache: list[GrammarPoint] = []
_comm_functions_cache: list[CommunicativeFunction] = []
_student_level: str = "B2"
```

**`learning/lesson_analyzer.py:37-38`**:
```python
_grammar_points_cache: list[GrammarPoint] = []
_comm_functions_cache: list[CommunicativeFunction] = []
```

Each has its own `_ensure_codes()` function that populates these via `global` statements:

```python
async def _ensure_codes() -> None:
    global _grammar_points_cache, _comm_functions_cache, _student_level
    if _grammar_points_cache:
        return
    _grammar_points_cache = await GrammarPoint.find_all().to_list()
    _comm_functions_cache = await CommunicativeFunction.find_all().to_list()
    ...
```

Problems:
1. **Duplicated logic** — two identical `_ensure_codes()` functions
2. **Stale caches** — after `learning/ingest.py` replaces GrammarPoints, the caches still hold old data until process restart
3. **Test fragility** — tests must manually seed `analyzer_module._grammar_points_cache` and reset it in fixtures
4. **`global` keyword** — makes data flow opaque and error-prone

### Solution

Create a `TaxonomyCache` class in a new `src/maestro/taxonomy.py` module. Both `analyzer.py` and `lesson_analyzer.py` import from it. Tests can call `invalidate()` or inject mock data.

### New file: `src/maestro/taxonomy.py`

```python
"""
Shared cache for grammar points and communicative functions.

Used by analyzer.py and lesson_analyzer.py to avoid repeated DB queries.
Call invalidate() after bulk writes (e.g. ingest scripts) to force a refresh.
"""
from __future__ import annotations

import logging
from maestro.models import GrammarPoint, CommunicativeFunction

logger = logging.getLogger(__name__)

_grammar_points: list[GrammarPoint] = []
_comm_functions: list[CommunicativeFunction] = []
_loaded: bool = False


async def ensure_loaded() -> None:
    """Load taxonomy data from DB if not already cached."""
    global _grammar_points, _comm_functions, _loaded
    if _loaded:
        return
    _grammar_points = await GrammarPoint.find_all().to_list()
    _comm_functions = await CommunicativeFunction.find_all().to_list()
    _loaded = True
    logger.info(
        f"[taxonomy] loaded {len(_grammar_points)} grammar points, "
        f"{len(_comm_functions)} comm functions"
    )


def grammar_points() -> list[GrammarPoint]:
    """Return cached grammar points. Must call ensure_loaded() first."""
    return _grammar_points


def comm_functions() -> list[CommunicativeFunction]:
    """Return cached communicative functions. Must call ensure_loaded() first."""
    return _comm_functions


def invalidate() -> None:
    """Clear the cache, forcing a reload on next ensure_loaded() call."""
    global _grammar_points, _comm_functions, _loaded
    _grammar_points = []
    _comm_functions = []
    _loaded = False


def seed(
    gps: list[GrammarPoint] | None = None,
    cfs: list[CommunicativeFunction] | None = None,
) -> None:
    """Directly populate cache for testing. Marks cache as loaded."""
    global _grammar_points, _comm_functions, _loaded
    if gps is not None:
        _grammar_points = gps
    if cfs is not None:
        _comm_functions = cfs
    _loaded = True
```

### Migration: `learning/analyzer.py`

**Remove** the module-level caches and `_ensure_codes`:

```python
# DELETE (lines 29-31)
_grammar_points_cache: list[GrammarPoint] = []
_comm_functions_cache: list[CommunicativeFunction] = []
_student_level: str = "B2"

# DELETE (lines 34-46)
async def _ensure_codes() -> None:
    global _grammar_points_cache, _comm_functions_cache, _student_level
    ...
```

**Add** import and local student_level handling:

```python
from maestro import taxonomy

# Keep _student_level as a module-level var since it's specific to analyzer
_student_level: str = "B2"
_student_level_loaded: bool = False


async def _ensure_loaded() -> None:
    """Ensure taxonomy cache is populated and student level is set."""
    global _student_level, _student_level_loaded
    await taxonomy.ensure_loaded()
    if not _student_level_loaded:
        from maestro.profile import get_profile
        profile = await get_profile()
        if profile:
            _student_level = profile.cefr_estimate
        _student_level_loaded = True
```

**Replace** all references:
- `_grammar_points_cache` → `taxonomy.grammar_points()`
- `_comm_functions_cache` → `taxonomy.comm_functions()`
- `await _ensure_codes()` → `await _ensure_loaded()`

Specific locations in `analyzer.py`:

| Line | Before | After |
|------|--------|-------|
| 58 | `gp_relevant = [g for g in _grammar_points_cache if ...]` | `gp_relevant = [g for g in taxonomy.grammar_points() if ...]` |
| 59 | `cf_relevant = [f for f in _comm_functions_cache if ...]` | `cf_relevant = [f for f in taxonomy.comm_functions() if ...]` |
| 104 | `await _ensure_codes()` | `await _ensure_loaded()` |
| 121 | `valid_grammar = {g.code for g in _grammar_points_cache}` | `valid_grammar = {g.code for g in taxonomy.grammar_points()}` |
| 122 | `valid_functions = {f.code for f in _comm_functions_cache}` | `valid_functions = {f.code for f in taxonomy.comm_functions()}` |
| 290 | `await _ensure_codes()` | `await _ensure_loaded()` |
| 291 | `gp_label = next((g.label for g in _grammar_points_cache if ...` | `gp_label = next((g.label for g in taxonomy.grammar_points() if ...` |
| 292 | `grammar_code_list = "\n".join(... for g in _grammar_points_cache)` | `grammar_code_list = "\n".join(... for g in taxonomy.grammar_points())` |

### Migration: `learning/lesson_analyzer.py`

**Remove** the module-level caches and `_ensure_codes`:

```python
# DELETE (lines 37-38)
_grammar_points_cache: list[GrammarPoint] = []
_comm_functions_cache: list[CommunicativeFunction] = []

# DELETE (lines 53-58)
async def _ensure_codes() -> None:
    global _grammar_points_cache, _comm_functions_cache
    ...
```

**Add** import:

```python
from maestro import taxonomy
```

**Replace** all references:
- `_grammar_points_cache` → `taxonomy.grammar_points()`
- `_comm_functions_cache` → `taxonomy.comm_functions()`
- `await _ensure_codes()` → `await taxonomy.ensure_loaded()`

Specific locations in `lesson_analyzer.py`:

| Line | Before | After |
|------|--------|-------|
| 129 | `for gp in _grammar_points_cache` | `for gp in taxonomy.grammar_points()` |
| 134 | `gp = next((g for g in _grammar_points_cache if ...` | `gp = next((g for g in taxonomy.grammar_points() if ...` |
| 209 | `for cf in _comm_functions_cache` | `for cf in taxonomy.comm_functions()` |
| 248 | `await _ensure_codes()` | `await taxonomy.ensure_loaded()` |

### Migration: `drills/scoring.py`

This file imports `_ensure_codes` and `_grammar_points_cache` directly:

```python
# BEFORE (line 28)
from maestro.learning.analyzer import score_free_form_drill, score_multi_item_drill, _ensure_codes, _grammar_points_cache

# AFTER
from maestro.learning.analyzer import score_free_form_drill, score_multi_item_drill
from maestro import taxonomy
```

Replace in the function body (lines 71-73):

```python
# BEFORE
await _ensure_codes()
valid_codes = {g.code for g in _grammar_points_cache}
gp_labels = {g.code: g.label for g in _grammar_points_cache}

# AFTER
await taxonomy.ensure_loaded()
valid_codes = {g.code for g in taxonomy.grammar_points()}
gp_labels = {g.code: g.label for g in taxonomy.grammar_points()}
```

### Migration: Tests

**`tests/integration/conftest.py`** — update the fixture:

```python
# BEFORE (lines 45-49)
@pytest.fixture
def mock_analyzer_client(mocker):
    """Patches _client() in analyzer.py to return a MagicMock."""
    mock = mocker.MagicMock()
    mocker.patch("maestro.learning.analyzer._client", return_value=mock)
    return mock

# AFTER — keep as-is (analyzer._client still exists), but add:
@pytest.fixture(autouse=True)
def reset_taxonomy():
    """Reset taxonomy cache between tests."""
    from maestro import taxonomy
    taxonomy.invalidate()
    yield
    taxonomy.invalidate()
```

**`tests/integration/test_analyzer.py`** — replace cache seeding:

```python
# BEFORE (lines 19-28)
def _seed_cache(gp_codes=("GP_001", "GP_002"), cf_codes=("CF_001",)):
    analyzer_module._grammar_points_cache = [...]
    analyzer_module._comm_functions_cache = [...]
    analyzer_module._student_level = "A1"

# AFTER
from maestro import taxonomy

def _seed_cache(gp_codes=("GP_001", "GP_002"), cf_codes=("CF_001",)):
    from unittest.mock import MagicMock
    import maestro.learning.analyzer as analyzer_module
    taxonomy.seed(
        gps=[MagicMock(code=c, cefr_level="A1", label=c, description=c) for c in gp_codes],
        cfs=[MagicMock(code=c, cefr_level="A1", label=c, description=c) for c in cf_codes],
    )
    analyzer_module._student_level = "A1"
    analyzer_module._student_level_loaded = True
```

**`tests/integration/test_analyzer.py`** — update the `reset_cache` fixture:

```python
# BEFORE (lines 30-39)
@pytest.fixture(autouse=True)
def reset_cache():
    original_gp = analyzer_module._grammar_points_cache[:]
    original_cf = analyzer_module._comm_functions_cache[:]
    original_level = analyzer_module._student_level
    yield
    analyzer_module._grammar_points_cache = original_gp
    analyzer_module._comm_functions_cache = original_cf
    analyzer_module._student_level = original_level

# AFTER
@pytest.fixture(autouse=True)
def reset_cache():
    yield
    taxonomy.invalidate()
    analyzer_module._student_level_loaded = False
```

**`tests/integration/test_scoring.py`** — update cache seeding (lines 40-42, 76-78, etc.):

```python
# BEFORE
analyzer_module._grammar_points_cache = [
    MagicMock(code="GP_001", label="Passato Prossimo", cefr_level="A1")
]

# AFTER
taxonomy.seed(
    gps=[MagicMock(code="GP_001", label="Passato Prossimo", cefr_level="A1")],
)
```

### Verification

- `uv run pytest -v` — all pass
- `rg 'global _grammar_points_cache|global _comm_functions_cache' src/` — should return nothing
- `rg '_grammar_points_cache|_comm_functions_cache' src/maestro/` — should only be in `taxonomy.py`

---

## Task 3.2: Handle Background Task Errors

### Problem

Two places use `asyncio.create_task()` without handling potential exceptions:

**`routes/lezione.py:159`**:
```python
asyncio.create_task(generate_lesson_background(lesson.id, duration, hint, grammar_codes))
```

**`routes/lezione.py:568`**:
```python
asyncio.create_task(analyze_lesson(lesson))
```

If these tasks raise exceptions, Python logs a "Task exception was never retrieved" warning and the error is effectively swallowed. For `generate_lesson_background`, this means the lesson stays in `generating=True` state forever. For `analyze_lesson`, learning profile updates are silently lost.

### Solution

Add a `done_callback` that logs exceptions. Also store the task reference to prevent garbage collection (Python can GC unreferenced tasks).

### Changes

**File: `src/maestro/utils.py`**

Add a helper:

```python
import asyncio
import logging

_background_tasks: set[asyncio.Task] = set()
_logger = logging.getLogger(__name__)


def create_background_task(coro, *, name: str | None = None) -> asyncio.Task:
    """Create a background task with error logging. Prevents GC of the task."""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            _logger.error(f"Background task {t.get_name()!r} failed: {exc}", exc_info=exc)

    task.add_done_callback(_done)
    return task
```

**File: `src/maestro/routes/lezione.py`**

```python
# ADD import
from maestro.utils import create_background_task

# Line 159 — BEFORE
asyncio.create_task(generate_lesson_background(lesson.id, duration, hint, grammar_codes))

# AFTER
create_background_task(
    generate_lesson_background(lesson.id, duration, hint, grammar_codes),
    name=f"lesson-generate-{lesson.id}",
)

# Line 568 — BEFORE
asyncio.create_task(analyze_lesson(lesson))

# AFTER
create_background_task(
    analyze_lesson(lesson),
    name=f"lesson-analyze-{lesson.id}",
)
```

Remove the `import asyncio` from the top of `routes/lezione.py` if it's no longer used elsewhere in the file. Check: line 1 `import asyncio` — it's used at lines 159, 568 only. After the change, those calls go through `create_background_task`, so `import asyncio` can be removed.

### Additional: Ensure `generate_lesson_background` sets `generating=False` on error

Currently `generate_lesson_background` in `planner.py` has no top-level try/except. If it raises, the lesson stays `generating=True` forever. Add a safety net:

**File: `src/maestro/lezione/planner.py`**

Wrap the body of `generate_lesson_background` (lines 522-765):

```python
async def generate_lesson_background(
    lesson_id,
    duration_minutes: int,
    hint: str,
    grammar_codes: list[str],
) -> None:
    """Generate topic, grammar, reading, drills, speaking, writing and append to lesson."""
    try:
        # ... existing body ...
        pass
    except Exception:
        logger.exception(f"[planner] generate_lesson_background failed for lesson {lesson_id}")
        # Ensure the lesson doesn't stay stuck in generating state
        try:
            lesson = await Lesson.get(lesson_id)
            if lesson and lesson.generating:
                lesson.generating = False
                await lesson.save()
        except Exception:
            logger.exception(f"[planner] failed to clear generating flag for lesson {lesson_id}")
        raise  # re-raise so the background task handler logs it too
```

### Test to add

**File: `tests/unit/test_utils.py`**

```python
import asyncio
from maestro.utils import create_background_task

@pytest.mark.unit
async def test_background_task_runs_to_completion():
    result = []
    async def work():
        result.append(1)
    task = create_background_task(work(), name="test")
    await task
    assert result == [1]


@pytest.mark.unit
async def test_background_task_logs_exception(caplog):
    async def failing():
        raise ValueError("boom")
    task = create_background_task(failing(), name="test-fail")
    await asyncio.sleep(0.05)  # let the callback fire
    assert any("boom" in r.message for r in caplog.records)
```

### Verification

- `uv run pytest -v`
- Manual: start a lesson, kill the LLM call (e.g. invalid API key) — verify the lesson's `generating` flag is cleared and an error is logged

---

## Task 3.3: Split Large Files

### Problem

Three files are too large and mix too many responsibilities:

| File | Lines | Responsibilities |
|------|-------|-----------------|
| `lezione/planner.py` | 765 | Slot allocation, GP selection, CF selection, topic generation, vocab card filling, LLM content generation, lesson creation (immediate + background), activity materialization |
| `routes/lezione.py` | 578 | 14 route handlers + lesson state machine (`_advance_lesson`) + LLM feedback generation + weak GP lookup |
| `learning/analyzer.py` | 495 | Message analysis, fill-blank feedback, error-correction evaluation, multi-item scoring, writing feedback, free-form scoring, reading answer scoring |

### Split plan

#### 3.3a: Split `lezione/planner.py` → `lezione/planner.py` + `lezione/selection.py`

**New file: `src/maestro/lezione/selection.py`** — Grammar point and CF selection logic

Move these functions:
- `_pick_grammar_points()` (lines 89-113) — pure DB query + sorting
- `_pick_comm_functions()` (lines 121-156) — pure DB query + sorting
- `_fill_vocab_cards()` (lines 267-300) — DB query + card creation
- `_get_past_topics()` (lines 164-174) — DB query

```python
# src/maestro/lezione/selection.py
"""
Selection helpers for lesson planning.

Picks grammar points, communicative functions, and vocabulary cards
based on the student's profile and CEFR level.
"""
from __future__ import annotations

import logging
import random
from datetime import date, datetime
from typing import Optional

from maestro.models import (
    CommunicativeFunction,
    GrammarPoint,
    Lesson,
    LessonTopic,
    LearningProfile,
    UserVocabularyCard,
    VocabularyWord,
)
from maestro.utils import CEFR_ORDER, utcnow

logger = logging.getLogger(__name__)

MIN_VOCAB = 5


async def pick_grammar_points(
    profile: Optional[LearningProfile],
    cefr_level: str,
    count: int,
) -> list[GrammarPoint]:
    # ... move from planner.py lines 89-113 ...


async def pick_comm_functions(
    profile: Optional[LearningProfile],
    cefr_level: str,
    count: int,
    preferred_codes: list[str] = [],
) -> list[CommunicativeFunction]:
    # ... move from planner.py lines 121-156 ...


async def get_past_topics(n: int = 10) -> list[LessonTopic]:
    # ... move from planner.py lines 164-174 ...


async def fill_vocab_cards(vocab_count: int, cefr_level: str) -> list[UserVocabularyCard]:
    # ... move from planner.py lines 267-300 ...
```

**Update `planner.py`**: Replace moved functions with imports:

```python
from maestro.lezione.selection import (
    pick_grammar_points,
    pick_comm_functions,
    get_past_topics,
    fill_vocab_cards,
)
```

Remove the leading underscore from function names since they're now part of a module's public API. Update all call sites in `planner.py`.

**Update `routes/lezione.py:132`**: The lazy import of `_pick_grammar_points`:

```python
# BEFORE
from maestro.lezione.planner import _pick_grammar_points

# AFTER
from maestro.lezione.selection import pick_grammar_points
```

**Expected result**: `planner.py` drops from ~765 to ~600 lines. `selection.py` is ~170 lines. Functions in `selection.py` are independently testable.

#### 3.3b: Split `routes/lezione.py` → keep routes + extract `lezione/service.py`

**New file: `src/maestro/lezione/service.py`** — Lesson state management and helpers

Move these functions:
- `_advance_lesson()` (lines 41-63)
- `_generate_lesson_feedback()` (lines 66-98)
- `_get_weak_grammar_points()` (lines 101-117)

```python
# src/maestro/lezione/service.py
"""
Lesson lifecycle helpers.

- advance_lesson: state machine for moving between activities
- generate_lesson_feedback: end-of-lesson AI feedback
- get_weak_grammar_points: identify grammar areas needing work
"""
from __future__ import annotations

import logging
import re

import anthropic

from maestro.models import GeneratedDrill, GrammarPoint, Lesson
from maestro.llm import get_async_client
from maestro.utils import utcnow

logger = logging.getLogger(__name__)


def activity_url(lesson_id, idx: int) -> str:
    return f"/lezione/{lesson_id}/activity/{idx}"


async def advance_lesson(lesson: Lesson, current_idx: int, skip: bool = False) -> str:
    # ... move from routes/lezione.py lines 41-63 ...
    # replace _activity_url with activity_url


async def generate_lesson_feedback(lesson: Lesson, weak_grammar_points: list) -> str:
    # ... move from routes/lezione.py lines 66-98 ...
    # already made async in Phase 1


async def get_weak_grammar_points(lesson: Lesson) -> list[GrammarPoint]:
    # ... move from routes/lezione.py lines 101-117 ...
```

**Update `routes/lezione.py`**: Replace with imports:

```python
from maestro.lezione.service import (
    activity_url,
    advance_lesson,
    generate_lesson_feedback,
    get_weak_grammar_points,
)
```

Update all call sites (search for `_advance_lesson`, `_activity_url`, `_generate_lesson_feedback`, `_get_weak_grammar_points`).

**Expected result**: `routes/lezione.py` drops from ~578 to ~470 lines. `service.py` is ~110 lines. The route file becomes a thinner HTTP layer.

#### 3.3c: Split `learning/analyzer.py` → `learning/analyzer.py` + `learning/scorer.py`

**New file: `src/maestro/learning/scorer.py`** — Drill, writing, and reading scoring

Move these functions:
- `feedback_fill_blank()` (lines 170-209)
- `evaluate_error_correction()` (lines 212-263)
- `score_multi_item_drill()` (lines 269-339)
- `generate_writing_feedback()` (lines 342-389)
- `score_free_form_drill()` (lines 392-445)
- `score_reading_answers()` (lines 448-495)

Keep in `analyzer.py`:
- `analyze_message()` (lines 84-167) — the core analysis function
- `_ensure_loaded()` (the new version from Task 3.1)
- `_build_prompt()` (lines 53-81)
- `_FALLBACK_ITEM` constant

```python
# src/maestro/learning/scorer.py
"""
Scoring and feedback generation for drills, writing, and reading activities.

Each function calls an LLM to evaluate student responses and returns
structured feedback dicts.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from maestro import taxonomy
from maestro.llm import get_client
from maestro.config import settings
from maestro.prompts import analyzer as _prompts
from maestro.utils import parse_llm_json

logger = logging.getLogger(__name__)

_FALLBACK_ITEM = {"objective_correct": False, "objective_note": "", "grammar_errors": [], "tips": []}


async def feedback_fill_blank(...) -> dict | str:
    # ... moved from analyzer.py ...


async def evaluate_error_correction(...) -> tuple[bool, dict | str]:
    # ...


async def score_multi_item_drill(...) -> list[dict]:
    # ...


async def generate_writing_feedback(...) -> dict:
    # ...


async def score_free_form_drill(...) -> dict:
    # ...


async def score_reading_answers(...) -> list[dict]:
    # ...
```

**Update imports** in consumers:

`drills/scoring.py`:
```python
# BEFORE
from maestro.learning.analyzer import score_free_form_drill, score_multi_item_drill, _ensure_codes, _grammar_points_cache

# AFTER
from maestro.learning.scorer import score_free_form_drill, score_multi_item_drill
from maestro import taxonomy
```

`routes/lezione.py`:
```python
# BEFORE
from maestro.learning.analyzer import generate_writing_feedback, score_reading_answers

# AFTER
from maestro.learning.scorer import generate_writing_feedback, score_reading_answers
```

**Expected result**: `analyzer.py` drops from ~495 to ~170 lines. `scorer.py` is ~330 lines. The two files have distinct responsibilities.

### Test migration

Tests in `tests/integration/test_analyzer.py` that test scoring functions now need to import from `maestro.learning.scorer` instead:

```python
# Tests for feedback_fill_blank, evaluate_error_correction, score_multi_item_drill,
# generate_writing_feedback → update import paths
```

The `mock_analyzer_client` fixture still works for tests that mock `_client()` in analyzer.py. For scorer.py, tests should mock `maestro.llm.get_client` (from Phase 2) or create a separate `mock_scorer_client` fixture.

### Verification

- `uv run pytest -v` — all pass
- No file in `src/maestro/` exceeds ~600 lines
- Each new module (`selection.py`, `service.py`, `scorer.py`) is focused on one concern

---

## Task 3.4: Lazy-Load SentenceTransformer in RAG Ingest

### Problem

`src/maestro/rag/ingest.py:19`:
```python
model = SentenceTransformer("intfloat/multilingual-e5-large")
```

This runs at import time, triggering a multi-GB model download/load whenever any code transitively imports `rag.ingest`. The sibling file `rag/retrieve.py` already handles this correctly:

```python
@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("intfloat/multilingual-e5-large")
```

### Solution

Use the same `get_model()` from `rag/retrieve.py` instead of a module-level instantiation.

### Changes

**File: `src/maestro/rag/ingest.py`**

```python
# BEFORE (lines 5-6, 19)
from sentence_transformers import SentenceTransformer
# ...
model = SentenceTransformer("intfloat/multilingual-e5-large")

# AFTER
from maestro.rag.retrieve import get_model
# (delete the module-level `model = ...` line)
```

Then at line 252 where `model` is used:

```python
# BEFORE
embeddings = model.encode(texts, batch_size=64, show_progress_bar=True)

# AFTER
embeddings = get_model().encode(texts, batch_size=64, show_progress_bar=True)
```

Also remove `from sentence_transformers import SentenceTransformer` (line 5) since it's no longer needed at module level.

### Verification

- `uv run pytest -v` — all pass (the ingest script isn't tested, but imports should not break)
- `python -c "from maestro.rag import ingest"` — should complete instantly without loading the model

---

## Commit Strategy

Four commits (or five if 3.3 is split into sub-commits):

1. `refactor: extract taxonomy cache from analyzer/lesson_analyzer globals`
2. `fix: log background task errors and prevent stuck generating state`
3. `refactor: split planner.py, routes/lezione.py, and analyzer.py` (can be 3 sub-commits: 3.3a, 3.3b, 3.3c)
4. `refactor: lazy-load SentenceTransformer in rag/ingest.py`

Do 3.4 first (smallest, no dependencies), then 3.1, then 3.2, then 3.3 (which benefits from all prior changes).
