# Phase C — Code Quality

Enums, retry logic, query optimization, and typed LLM responses.

**Prerequisite**: Phase B completed (especially B.4 — planner split makes C.4 much cleaner).

---

## C.1: Introduce Enums for Magic Strings

### Problem

Strings like `"drill"`, `"active"`, `"fill_blank"` are used as types/statuses in models, planner, routes, and templates. A typo silently creates a broken state. No IDE autocomplete, no exhaustiveness checking.

Occurrences (estimated):
- Activity type strings: ~40 comparisons across routes, planner, service, tests
- Status strings: ~25 comparisons
- Exercise type strings: ~20 comparisons

### Fix

Add `str, Enum` classes to `models.py`. Using `str` as a base ensures:
- MongoDB stores plain strings (backward compatible, no migration needed)
- Jinja2 templates can compare with `==` (`{% if activity.type == "drill" %}` still works)
- Pydantic serializes/deserializes transparently

```python
from enum import Enum

class ActivityType(str, Enum):
    DRILL = "drill"
    VOCAB_REVIEW = "vocab_review"
    READING = "reading"
    WRITING = "writing"
    GRAMMAR = "grammar"
    SPEAKING = "speaking"
    ONBOARDING = "onboarding"

class ActivityStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    SKIPPED = "skipped"

class LessonStatus(str, Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"

class ExerciseType(str, Enum):
    FILL_BLANK = "fill_blank"
    ERROR_CORRECTION = "error_correction"
    FREE_FORM = "free_form"
```

Then update `LessonActivity`, `Lesson`, `DrillTemplate`, `GeneratedDrill` to use the enum types:
```python
class LessonActivity(BaseModel):
    type: ActivityType
    status: ActivityStatus = ActivityStatus.PENDING
    ...

class Lesson(Document):
    status: LessonStatus = LessonStatus.PLANNING
    ...
```

### Rollout Strategy

1. Add the enum classes to `models.py`
2. Update model field types
3. Grep for every string literal and replace with enum member (mechanical)
4. Templates don't need changes — `str, Enum` comparison with string literals works
5. Run tests to catch any missed spots

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/models.py` | Add 4 enum classes, update field types |
| `src/maestro/lezione/planner.py` | Use enum members |
| `src/maestro/lezione/service.py` | Use enum members |
| `src/maestro/lezione/selection.py` | Use `ExerciseType` |
| `src/maestro/routes/lezione.py` | Use enum members |
| `src/maestro/drills/scoring.py` | Use `ExerciseType` |
| `src/maestro/learning/lesson_analyzer.py` | Use `ActivityType`, `ActivityStatus` |
| Tests (various) | Use enum members in fixtures |

### Verification

All existing tests pass. No migration needed — `str, Enum` values are identical strings.

---

## C.2: Add LLM Call Retry Logic

### Problem

Every LLM call is a single attempt. A transient API 500, rate limit, or timeout during `generate_lesson_background` means the lesson gets zero content activities. During scoring, the student's work is marked "all incorrect" via the fallback dict.

### Fix

The Anthropic Python SDK supports a `max_retries` parameter on client construction. Use it:

```python
@lru_cache(maxsize=1)
def get_async_client() -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(
        api_key=settings.ANTHROPIC_API_KEY,
        max_retries=3,
    )
```

The SDK handles exponential backoff and retries on 429 (rate limit) and 5xx errors automatically. This is the simplest path — no wrapper function needed.

If finer control is needed later, add a `call_llm()` wrapper in `llm.py` that catches specific exceptions and logs retry attempts.

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/llm.py` | Add `max_retries=3` to both client constructors |

### Verification

Existing tests pass (mocked clients unaffected). Manual verification: temporarily set an invalid API key and confirm the retry behavior in logs.

---

## C.3: Optimize Profile Computation Queries

### Problem

`learning/profile.py:_compute_cefr()` and `_generate_description()` are called on every profile update and perform expensive DB queries:

- `_compute_cefr()` loads ALL `GrammarPoint` and ALL `CommunicativeFunction` documents from DB
- `_generate_description()` loads ALL `VocabularyWord` documents, ALL `UserVocabularyCard` documents, then calls `fetch_all_links()` in a loop (N+1 queries)
- `_generate_description()` also loads ALL `CommunicativeFunction` documents again

As data grows (currently 246 GPs, 460 CFs, ~1000+ vocab words), these become increasingly expensive.

### Fix

#### `_compute_cefr` — use taxonomy cache

The taxonomy module already caches GPs and CFs at startup. Use it:

```python
async def _compute_cefr(profile: LearningProfile) -> str:
    await taxonomy.ensure_loaded()
    grammar_points = taxonomy.grammar_points()
    comm_functions = taxonomy.comm_functions()
    # ... rest of logic unchanged, but no DB queries ...
```

#### `_generate_description` — use aggregation for vocab coverage

Replace the "load all words + all cards + N+1 fetch_all_links" with:

1. Use taxonomy cache for GP labels and CF data
2. Use an aggregation pipeline for vocab coverage:
   ```python
   pipeline = [
       {"$match": {"student_id": profile.student_id}},
       {"$lookup": {
           "from": "vocabulary_words",
           "localField": "word",
           "foreignField": "_id",
           "as": "word_doc",
       }},
       {"$unwind": "$word_doc"},
       {"$group": {
           "_id": "$word_doc.cefr_level",
           "count": {"$sum": 1},
       }},
   ]
   results = await UserVocabularyCard.aggregate(pipeline).to_list()
   discovered_by_level = {r["_id"]: r["count"] for r in results if r["_id"]}
   ```
3. Get total vocab counts from a similar aggregation on `VocabularyWord` (or cache at startup since vocab rarely changes).

#### `fill_vocab_cards` (in `selection.py`) — batch fetch

Replace the loop of `fetch_all_links()` with a single lookup:
```python
# Fetch all word docs in one query
word_ids = [c.word.ref.id for c in due_all]
words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
word_map = {w.id: w for w in words}
```

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/learning/profile.py` | Use taxonomy cache in `_compute_cefr`, aggregation in `_generate_description` |
| `src/maestro/lezione/selection.py` | Batch word fetch in `fill_vocab_cards` |

### Risks

- Aggregation pipeline syntax differs between mongomock (used in tests) and real MongoDB. Verify the `$lookup` stage works in both. If mongomock doesn't support it, keep the Python-side approach for tests and use the pipeline in production behind a flag, or accept the test/prod divergence.
- Taxonomy cache assumes GPs/CFs don't change during a session — this is already the case.

### Verification

- Integration tests for profile update still pass
- Manual benchmark: measure profile update time before/after with ~500 vocab cards

---

## C.4: Typed Pydantic Models for LLM Responses

### Problem

All LLM responses are parsed via `parse_llm_json()` into untyped `dict | list`. Downstream code uses `.get()` with no validation. If the LLM changes its output format (missing key, wrong type), errors propagate silently until they hit a template or DB write.

Examples of fragile patterns:
- `content.get("readings", [])` — no check that readings is a list of dicts with `text`, `questions`, `answers`
- `drill_data.get("items") or []` — no check that items have `prompt` and `correct_answer`
- `data.get("objective_correct", False)` — no check that it's actually a bool

### Fix

Define Pydantic response models in a new file `src/maestro/lezione/schemas.py` (or alongside the prompt builder if Phase B.4 was done):

```python
from pydantic import BaseModel
from typing import Optional

class GrammarMotivation(BaseModel):
    code: str
    text: str

class DrillItemResponse(BaseModel):
    prompt: str
    correct_answer: Optional[str] = None

class DrillResponse(BaseModel):
    grammar_point_code: str
    items: list[DrillItemResponse] = []
    prompt: Optional[str] = None

class ReadingResponse(BaseModel):
    text: str
    questions: list[str] = []
    answers: list[str] = []

class WritingResponse(BaseModel):
    prompt: str

class SpeakingResponse(BaseModel):
    prompt: str

class LessonContentResponse(BaseModel):
    topic_title: str = ""
    topic_description: str = ""
    overview: str = ""
    grammar_motivations: list[GrammarMotivation] = []
    drills: list[DrillResponse] = []
    readings: list[ReadingResponse] = []
    writing: Optional[WritingResponse] = None
    speakings: list[SpeakingResponse] = []
```

Similarly for scorer responses:

```python
class ScoringResult(BaseModel):
    objective_correct: bool = False
    objective_note: str = ""
    grammar_errors: list[str] = []
    tips: list[str] = []
```

Usage in planner (after Phase B.4 split):
```python
raw = parse_llm_json(response_text)
try:
    content = LessonContentResponse.model_validate(raw)
except ValidationError as e:
    logger.error(f"LLM response validation failed: {e}")
    content = LessonContentResponse()  # safe empty default
```

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/lezione/schemas.py` | New — response models for lesson content |
| `src/maestro/learning/schemas.py` | New — response models for scoring |
| `src/maestro/lezione/planner.py` (or `materialize.py`) | Validate LLM response |
| `src/maestro/learning/scorer.py` | Validate scoring responses |
| `src/maestro/drills/scoring.py` | Use typed results |

### Benefits

- Early, clear errors when LLM output changes shape
- IDE autocomplete for response fields
- Self-documenting expected schemas
- Default values prevent `None` propagation

### Risks

- LLMs sometimes return slightly malformed data — models need permissive defaults (`= []`, `= ""`)
- Don't make fields too strict initially — start with liberal validation, tighten later

---

## Checklist

- [ ] C.1 — Add 4 enum classes, update all string comparisons (~40 files touches)
- [ ] C.2 — Add `max_retries=3` to client constructors
- [ ] C.3 — Taxonomy cache in `_compute_cefr`, aggregation in `_generate_description`, batch fetch in `fill_vocab_cards`
- [ ] C.4 — Response models for lesson content and scoring
- [ ] All tests pass
