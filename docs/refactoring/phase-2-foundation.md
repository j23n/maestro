# Phase 2: Foundation

**Goal**: Establish shared infrastructure (client factory, profile helper, model registry, unified settings) that removes duplication and enables cleaner testing. These are small, independent refactors that set the stage for Phase 3.

**Effort**: 1-2 sessions. Tasks are independent and can be done in any order.

**Validation**: `uv run pytest -m unit tests/unit/ -v && uv run pytest -m integration tests/integration/ -v` must pass after each task.

---

## Task 2.1: Extract Shared Anthropic Client Factory

### Problem

7+ call sites independently construct Anthropic clients, mixing sync and async:

| File | Line | Type | Code |
|------|------|------|------|
| `routes/lezione.py` | 90 | sync | `anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)` |
| `learning/analyzer.py` | 49-50 | sync | `_client()` returns `anthropic.Anthropic(...)` |
| `vocab/generate_definitions.py` | 56 | sync | `anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)` |
| `grammar/generate_explanations.py` | 143 | sync | `anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)` |
| `lezione/planner.py` | 227 | async | `anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)` |
| `lezione/planner.py` | 531 | async | `anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)` |
| `learning/lesson_analyzer.py` | 251 | async | `anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)` |

This means:
- Tests must patch each call site individually
- No consistent client configuration (timeouts, retries, etc.)
- Some modules also import `anthropic` at module level, adding the dependency everywhere

### Solution

Create `src/maestro/llm.py` with factory functions that return configured clients.

### New file: `src/maestro/llm.py`

```python
"""
Anthropic client factories.

All LLM calls should obtain their client from here rather than constructing
one directly. This provides a single point of configuration and a single
target for test mocking.
"""
import anthropic
from maestro.config import settings


def get_client() -> anthropic.Anthropic:
    """Return a synchronous Anthropic client."""
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)


def get_async_client() -> anthropic.AsyncAnthropic:
    """Return an asynchronous Anthropic client."""
    return anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
```

### Migration plan — file by file

**`src/maestro/learning/analyzer.py`**

The existing `_client()` at line 49 is already a factory — replace its body:

```python
# BEFORE (lines 49-50)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

# AFTER
from maestro.llm import get_client

def _client() -> anthropic.Anthropic:
    return get_client()
```

Alternatively, remove `_client()` entirely and replace all 6 call sites (`analyzer.py:108`, `198`, `239`, `321`, `370`, `430`, `477`) that do `_client().messages.create(...)` with `get_client().messages.create(...)`. But keeping the `_client()` wrapper is fine for now since tests already patch it — the key change is that its *implementation* delegates to the factory.

Remove the `from maestro.config import settings` import if it's no longer needed after this change (it is — `settings.LESSON_MODEL` is used throughout). Remove `import anthropic` at the top if `_client()` now delegates.

```python
# Remove (line 16)
import anthropic

# Add
from maestro.llm import get_client
```

Wait — `analyzer.py` still references `anthropic` nowhere else except through `_client()`, so the direct import of `anthropic` can be removed. Check: no, `TYPE_CHECKING` block at line 18 imports `Message`, not anthropic. Good.

**`src/maestro/routes/lezione.py`**

After Phase 1 Task 1.1 converts `_generate_lesson_feedback` to async:

```python
# BEFORE (line 90, after Phase 1 fix)
client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

# AFTER
from maestro.llm import get_async_client
# ...
client = get_async_client()
```

Remove `import anthropic` from the file (line 8). Verify no other uses of `anthropic` remain.

**`src/maestro/lezione/planner.py`**

Two call sites:

```python
# Line 227 (inside generate_topic)
_client = client or anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

# Line 531 (inside generate_lesson_background)
client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
```

Replace:

```python
# Line 227
from maestro.llm import get_async_client
# ...
_client = client or get_async_client()

# Line 531
client = get_async_client()
```

Remove `import anthropic` (line 20). But check: `generate_topic` signature uses `anthropic.AsyncAnthropic` as a type hint (line 182). Change to:

```python
from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    import anthropic

async def generate_topic(
    ...
    client: Optional["anthropic.AsyncAnthropic"] = None,
) -> LessonTopic:
```

Similarly `_generate_lesson_content` (line 316) takes `client: anthropic.AsyncAnthropic`. Move the type hint behind `TYPE_CHECKING`.

**`src/maestro/learning/lesson_analyzer.py`**

```python
# Line 251
client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
```

Replace:

```python
from maestro.llm import get_async_client
# ...
client = get_async_client()
```

Remove `import anthropic` (line 18). But check: `_analyze_gps` and `_analyze_cfs_staged` take `client: anthropic.AsyncAnthropic` parameters. Use `TYPE_CHECKING` guard:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import anthropic
```

**`src/maestro/vocab/generate_definitions.py`**

```python
# Line 56
client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
```

Replace:

```python
from maestro.llm import get_client
# ...
client = get_client()
```

Remove `import anthropic` (line 21). Remove `from maestro.settings import Settings` and `settings = Settings()` (lines 23, 28) — use `from maestro.config import settings` instead (this also relates to Task 2.4).

**`src/maestro/grammar/generate_explanations.py`**

```python
# Line 143
client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
```

Replace:

```python
from maestro.llm import get_client
# ...
client = get_client()
```

Remove `import anthropic` (line 20). Remove standalone `settings = Settings()` (line 31) — use config singleton.

### Test impact

The integration test fixture `mock_analyzer_client` in `tests/integration/conftest.py:46-49` patches `maestro.learning.analyzer._client`. This still works since `_client()` still exists — it just delegates to `get_client()` now.

For new tests that need to mock the LLM more broadly, they can now patch `maestro.llm.get_client` or `maestro.llm.get_async_client` once:

```python
@pytest.fixture
def mock_llm(mocker):
    mock = mocker.MagicMock()
    mocker.patch("maestro.llm.get_client", return_value=mock)
    return mock

@pytest.fixture
def mock_async_llm(mocker):
    mock = mocker.AsyncMock()
    mocker.patch("maestro.llm.get_async_client", return_value=mock)
    return mock
```

### Verification

- `uv run pytest -v` — all existing tests pass
- `rg 'anthropic\.(Anthropic|AsyncAnthropic)\(' src/maestro/` — should return only `llm.py`
- `rg 'import anthropic' src/maestro/` — should return only `llm.py` (plus `TYPE_CHECKING` guards)

---

## Task 2.2: Extract `get_profile()` Helper

### Problem

`LearningProfile.find_one()` appears in 16+ places, almost always followed by `profile.cefr_estimate if profile else "A1"`. The pattern is:

```python
profile = await LearningProfile.find_one()
cefr = profile.cefr_estimate if profile else "A1"
```

This is repeated in:
- `routes/lezione.py`: lines 133, 156, 271, 407, 471
- `routes/grammar.py`: line 15
- `routes/vocab.py`: lines 23, 65
- `routes/profilo.py`: lines 42, 64
- `vocab/discover.py`: line 47
- `learning/analyzer.py`: line 40
- `learning/profile.py`: line 24
- `learning/lesson_analyzer.py`: line 249
- `learning/ingest.py`: line 122
- `lezione/planner.py`: line 525

### Solution

Add helpers to a new `src/maestro/profile.py` module (or could go in `utils.py`, but a dedicated module is cleaner since it touches the DB).

### New file: `src/maestro/profile.py`

```python
"""
Singleton learning profile access.

The app currently assumes a single student. All profile lookups go through
here so the assumption is easy to find and change later.
"""
from maestro.models import LearningProfile


async def get_profile() -> LearningProfile | None:
    """Return the singleton LearningProfile, or None if not yet created."""
    return await LearningProfile.find_one()


async def get_or_create_profile() -> LearningProfile:
    """Return the singleton LearningProfile, creating an empty one if needed."""
    profile = await LearningProfile.find_one()
    if profile is None:
        profile = LearningProfile()
        await profile.insert()
    return profile


async def get_cefr_level() -> str:
    """Return the student's current CEFR estimate, defaulting to 'A1'."""
    profile = await get_profile()
    return profile.cefr_estimate if profile else "A1"
```

### Migration plan — by call site

The migration is mechanical. For each call site, determine which helper to use:

**Pattern A** — Only needs CEFR level (use `get_cefr_level()`):
- `vocab/discover.py:47-48` (`_get_student_level`)
- `routes/grammar.py:15-16`

```python
# BEFORE
profile = await LearningProfile.find_one()
level = profile.cefr_estimate if profile else "A1"

# AFTER
from maestro.profile import get_cefr_level
level = await get_cefr_level()
```

**Pattern B** — Needs the profile object + CEFR (use `get_profile()` + inline fallback or `get_cefr_level()`):
- `routes/lezione.py:133-134` (lezione_new)
- `routes/lezione.py:156` (lezione_create)
- `routes/lezione.py:271` (lezione_activity — vocab_review)
- `routes/lezione.py:407` (lezione_vocab_reveal)
- `routes/lezione.py:471` (lezione_writing_submit)
- `routes/vocab.py:23-26` (_get_word_def)
- `routes/vocab.py:65-66` (vocab_entry)
- `routes/profilo.py:42` (profilo_page)
- `routes/profilo.py:64` (save_profilo_interests)
- `lezione/planner.py:525`
- `learning/lesson_analyzer.py:249`

```python
# BEFORE
profile = await LearningProfile.find_one()

# AFTER
from maestro.profile import get_profile
profile = await get_profile()
```

**Pattern C** — Creates profile if missing (use `get_or_create_profile()`):
- `learning/profile.py:24-27` (update_profile)
- `learning/ingest.py:122-126`

```python
# BEFORE
profile = await LearningProfile.find_one()
if profile is None:
    profile = LearningProfile()
    await profile.insert()

# AFTER
from maestro.profile import get_or_create_profile
profile = await get_or_create_profile()
```

**Pattern D** — Analyzer cache loading (use `get_profile()`):
- `learning/analyzer.py:40-42`

```python
# BEFORE
profile = await LearningProfile.find_one()
if profile:
    _student_level = profile.cefr_estimate

# AFTER
from maestro.profile import get_profile
profile = await get_profile()
if profile:
    _student_level = profile.cefr_estimate
```

### What NOT to change

- `routes/profilo.py:64` (save_profilo_interests) — this function *saves* the profile, so it needs the actual object. `get_or_create_profile()` works here.
- `learning/profile.py:24` (update_profile) — same, it modifies and saves. Use `get_or_create_profile()`.

### Cleanup

After migration, remove `from maestro.models import ... LearningProfile` from files that no longer directly query it. However, many files still reference `LearningProfile` for type hints or other queries — check each file individually.

### Verification

- `uv run pytest -v` — all pass
- `rg 'LearningProfile\.find_one' src/maestro/` — should return only `profile.py`

---

## Task 2.3: Single Source of Truth for Document Model List

### Problem

The list of all Beanie document models is maintained in three places:

1. **`src/maestro/db.py:25-39`** — 13 models in `init_beanie(document_models=[...])`
2. **`tests/integration/conftest.py:21-35`** — `ALL_MODELS` list (13 models)
3. **`tests/integration/test_routes.py:16-19`** — `ALL_MODELS` list (13 models)

Adding a new document model requires updating all three. Forgetting one causes subtle test failures.

### Solution

Define `ALL_DOCUMENT_MODELS` once in `src/maestro/models.py` and import it everywhere.

### Changes

**File: `src/maestro/models.py`**

Add at the bottom of the file (after the `Lesson` class definition):

```python
# Registry of all Beanie Document subclasses for init_beanie()
ALL_DOCUMENT_MODELS = [
    ItalianChunk,
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
    GrammarPoint,
    GrammarPointExplanation,
    CommunicativeFunction,
    LearningEvent,
    LearningProfile,
    DrillTemplate,
    GeneratedDrill,
    DrillAttempt,
    Lesson,
]
```

**File: `src/maestro/db.py`**

```python
# BEFORE (lines 4-18, 25-39)
from maestro.models import (
    ItalianChunk,
    VocabularyWord,
    # ... 11 more imports ...
)

async def init_db():
    client = AsyncMongoClient(settings.database_url)
    await init_beanie(
        database=client[settings.MONGODB_DB],
        document_models=[
            ItalianChunk,
            VocabularyWord,
            # ... 11 more ...
        ],
    )

# AFTER
from maestro.models import ALL_DOCUMENT_MODELS

async def init_db():
    client = AsyncMongoClient(settings.database_url)
    await init_beanie(
        database=client[settings.MONGODB_DB],
        document_models=ALL_DOCUMENT_MODELS,
    )
```

Note: `db.py` also uses individual model imports for `init_indices` — but `init_indices` only uses raw collection names, not model classes. The individual imports in `db.py` lines 4-18 can be fully removed if `init_indices` uses string collection names only. Check: yes, `init_indices` at line 43 uses `client[settings.MONGODB_DB]["italian_chunks"]` — a string, not a model. So the individual imports can go.

**File: `tests/integration/conftest.py`**

```python
# BEFORE (lines 5-35)
from maestro.models import (
    ItalianChunk, VocabularyWord, ...
)
ALL_MODELS = [ItalianChunk, VocabularyWord, ...]

@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(database=client["test_maestro"], document_models=ALL_MODELS)

# AFTER
from maestro.models import ALL_DOCUMENT_MODELS

@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(database=client["test_maestro"], document_models=ALL_DOCUMENT_MODELS)
```

**File: `tests/integration/test_routes.py`**

```python
# BEFORE (lines 9-19)
from maestro.models import (
    ItalianChunk, VocabularyWord, ...
)
ALL_MODELS = [ItalianChunk, VocabularyWord, ...]

# AFTER
from maestro.models import ALL_DOCUMENT_MODELS

# Then at line 27:
await init_beanie(database=mongo_client["test_maestro"], document_models=ALL_DOCUMENT_MODELS)
```

Keep individual model imports in `test_routes.py` only if specific tests reference them directly. In the current code, `test_routes.py` doesn't reference any individual models — the imports are only for the `ALL_MODELS` list. So they can all be removed.

### Verification

- `uv run pytest -v` — all pass
- `rg 'ALL_MODELS|ALL_DOCUMENT_MODELS' src/ tests/` — only `models.py` defines it; others import it

---

## Task 2.4: Unify Settings Access Pattern

### Problem

Most of the app uses `from maestro.config import settings` (a module-level singleton). But three files create their own `Settings()` instances:

| File | Line | Code |
|------|------|------|
| `vocab/generate_definitions.py` | 23, 28 | `from maestro.settings import Settings` + `settings = Settings()` |
| `grammar/generate_explanations.py` | 26, 31 | `from maestro.settings import Settings` + `settings = Settings()` |
| `rag/ingest.py` | 12, 274 | `from maestro.settings import Settings` + `settings = Settings()` |

Additionally, `rag/retrieve.py:2` imports `from maestro.settings import Settings` but never uses it.

Each standalone `Settings()` construction re-reads the `.env` file and creates a new settings object. While functionally equivalent, it's inconsistent and means test environment variable overrides might not propagate uniformly.

### Solution

All files should use `from maestro.config import settings`.

### Changes

**File: `src/maestro/vocab/generate_definitions.py`**

```python
# BEFORE (lines 23, 28)
from maestro.settings import Settings
# ...
settings = Settings()

# AFTER
from maestro.config import settings
# (delete the `settings = Settings()` line)
```

**File: `src/maestro/grammar/generate_explanations.py`**

```python
# BEFORE (lines 26, 31)
from maestro.settings import Settings
# ...
settings = Settings()

# AFTER
from maestro.config import settings
# (delete the `settings = Settings()` line)
```

**File: `src/maestro/rag/ingest.py`**

```python
# BEFORE (line 12)
from maestro.settings import Settings

# Line 274 (inside __main__ block)
settings = Settings()

# AFTER (line 12)
from maestro.config import settings

# Line 274: remove `settings = Settings()` — the module-level import covers it
```

**File: `src/maestro/rag/retrieve.py`**

```python
# BEFORE (line 2)
from maestro.settings import Settings

# AFTER: delete this line entirely (Settings is never used in this file)
```

### Verification

- `uv run pytest -v`
- `rg 'from maestro\.settings import Settings' src/maestro/` — should return only `config.py`
- `rg 'Settings\(\)' src/maestro/` — should return only `config.py:3`

---

## Commit Strategy

Four separate commits:

1. `refactor: extract Anthropic client factory to llm.py`
2. `refactor: extract get_profile/get_cefr_level helpers`
3. `refactor: define ALL_DOCUMENT_MODELS in models.py`
4. `refactor: unify settings access through maestro.config`

Tasks 2.3 and 2.4 are the smallest and safest — good warm-up commits. Task 2.1 is the most impactful for future testability. Task 2.2 is the most mechanical (16 call sites to update).
