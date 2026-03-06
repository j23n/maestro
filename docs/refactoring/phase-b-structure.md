# Phase B — Structure

Structural improvements to the two largest files (`planner.py` at 735 lines, `routes/lezione.py` at 596 lines) and consolidation of duplicated patterns.

**Prerequisite**: Phase A completed.

---

## B.1: Store `grammar_point_code` on Grammar LessonActivities

### Problem

`routes/lezione.py:221` resolves the grammar point for a grammar activity by parsing the title string:
```python
gp_label = activity.title.replace("Grammatica: ", "")
gp = await GrammarPoint.find_one({"label": gp_label})
```
If the title format changes, the lookup silently breaks and falls back to `GrammarPoint.find_one({})` — a random GP.

### Fix

1. **Add field** to `LessonActivity` in `models.py`:
   ```python
   grammar_point_code: Optional[str] = None
   ```

2. **Set it in `planner.py`** when creating grammar activities (~line 613):
   ```python
   grammar_activities.append(LessonActivity(
       type="grammar",
       ...
       grammar_point_code=gp.code,
   ))
   ```
   Also set it in `_generate_a0_lesson_background` for A0 grammar activities (use `gp_code` from the YAML data).

3. **Use it in `routes/lezione.py`** instead of title parsing:
   ```python
   if activity.grammar_point_code:
       gp = await GrammarPoint.find_one({"code": activity.grammar_point_code})
   ```
   Keep the title-parsing fallback for old lessons that lack the field.

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/models.py` | Add `grammar_point_code` to `LessonActivity` |
| `src/maestro/lezione/planner.py` | Set `grammar_point_code` on grammar activities |
| `src/maestro/routes/lezione.py` | Use `grammar_point_code` for GP lookup |

---

## B.2: Consolidate Word-Definition Lookup

### Problem

The pattern "look up `VocabularyWordDefinition` at student level, fall back to A1 if level is A0" is duplicated in three places:

1. `routes/lezione.py:188-194` (vocab_review in `lezione_activity`)
2. `routes/lezione.py:409-415` (`lezione_vocab_reveal`)
3. `routes/vocab.py:25-38` (`_get_word_def`)

These will drift apart when fallback logic changes.

### Fix

1. **Move `_get_word_def` from `routes/vocab.py` to `vocab/query.py`** as a public function:
   ```python
   async def get_word_definition(
       word: VocabularyWord, student_level: str
   ) -> VocabularyWordDefinition | None:
       wdef = await VocabularyWordDefinition.find_one(
           {"word.$id": word.id, "student_level": student_level}
       )
       if wdef is None and student_level == "A0":
           wdef = await VocabularyWordDefinition.find_one(
               {"word.$id": word.id, "student_level": "A1"}
           )
       return wdef
   ```

2. **Replace all 3 call sites** to use `from maestro.vocab.query import get_word_definition`.

3. **In `routes/vocab.py`**, change `_get_word_def` to call the shared function (or remove it and import directly).

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/vocab/query.py` | Add `get_word_definition()` |
| `src/maestro/routes/lezione.py` | Import and use `get_word_definition` (2 sites) |
| `src/maestro/routes/vocab.py` | Replace `_get_word_def` with import |

### New Tests

Add to `tests/unit/test_vocab_lookup.py`:
- `test_get_word_definition_at_level` — returns matching definition
- `test_get_word_definition_a0_fallback` — A0 falls back to A1
- `test_get_word_definition_none` — returns None when no definition exists

---

## B.3: Extract Business Logic from Route Handlers

### Problem

`routes/lezione.py` contains business logic that belongs in service functions:

- **Reading answer scoring** (lines 527-564): scoring, enrichment, aggregation of `correct_count` / `overall_correct`
- **Lesson completion** (lines 568-596): background analysis trigger, feedback generation, annotated feedback rendering
- **Onboarding field dispatch** (lines 286-310): `if profile_field == "name" ... elif "persona_tags" ... elif "interests"` — a dispatcher that should live in profile logic

### Fix

1. **`lezione/service.py`** — add `score_reading_activity()`:
   ```python
   async def score_reading_activity(
       questions: list[str],
       correct_answers: list[str],
       student_answers: list[str],
   ) -> tuple[bool, dict]:
       """Score reading answers. Returns (overall_correct, feedback_dict)."""
       raw_results = await score_reading_answers(questions, correct_answers, student_answers)
       # ... enrichment logic currently in route handler ...
       return overall_correct, feedback
   ```

2. **`lezione/service.py`** — add `prepare_completion_context()`:
   ```python
   async def prepare_completion_context(
       lesson: Lesson, student_id: PydanticObjectId
   ) -> dict:
       """Gather all data needed for the completion page."""
       # Trigger background analysis, generate feedback, annotate
       # Returns dict ready for template context
   ```

3. **`profile.py`** — add `save_onboarding_field()`:
   ```python
   async def save_onboarding_field(
       student: Student, profile_field: str, answer: str
   ) -> None:
       """Dispatch onboarding answer to the correct profile/student field."""
   ```

4. **Slim down route handlers** to: parse request → call service → render template.

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/lezione/service.py` | Add `score_reading_activity`, `prepare_completion_context` |
| `src/maestro/profile.py` | Add `save_onboarding_field` |
| `src/maestro/routes/lezione.py` | Replace inline logic with service calls |

### New Tests

- `tests/unit/test_service.py`: test `score_reading_activity` with mock scorer results
- `tests/integration/test_lesson_flow.py`: test `prepare_completion_context` end-to-end

---

## B.4: Split planner.py into Focused Modules

### Problem

`planner.py` is 735 lines handling five distinct responsibilities:
1. Slot allocation by duration (pure function)
2. LLM prompt construction for content generation (~170 lines)
3. LLM API call orchestration
4. Activity materialization from LLM response (~150 lines)
5. A0 static lesson loading (~120 lines)

This makes it hard to test prompt logic without mocking the LLM, and hard to modify materialization without understanding prompt construction.

### Fix

Split into focused files within `lezione/`:

| New File | Responsibility | Lines (approx) |
|----------|---------------|----------------|
| `lezione/slots.py` | `allocate_slots(duration)` — pure function | ~30 |
| `lezione/prompts.py` | `build_lesson_content_prompt(...)` — returns prompt string | ~170 |
| `lezione/materialize.py` | `materialize_activities(content, ...)` — LLM dict → activities | ~200 |
| `lezione/a0.py` | `generate_a0_lesson_background(...)` — static YAML loading | ~120 |
| `lezione/planner.py` | Orchestrator: `prepare_lesson_immediate`, `generate_lesson_background` | ~150 |

### Implementation Steps

1. **Extract `_allocate_slots` → `lezione/slots.py`**
   - Pure function, no dependencies. Move `_READING_WORD_COUNT` and `_READING_QUESTION_COUNT` too.
   - Existing unit test `tests/unit/test_planner_slots.py` updates its import.

2. **Extract prompt construction → `lezione/prompts.py`**
   - Move lines 95-265 of `_generate_lesson_content` (everything before the API call) into `build_lesson_content_prompt()`.
   - The function returns a `str` (the assembled prompt) and a `dict` (the JSON schema).
   - The LLM call stays in `planner.py`.

3. **Extract activity creation → `lezione/materialize.py`**
   - Move lines 596-714 (grammar, reading, drill, speaking, writing activity creation loops).
   - Function signature: `async def materialize_activities(content: dict, grammar_gps, drill_specs, ...) -> list[LessonActivity]`
   - The drill `GeneratedDrill` insertions happen here.

4. **Extract A0 logic → `lezione/a0.py`**
   - Move `_generate_a0_lesson_background` (lines 342-462).
   - Also move `_pick_a0_scenario` from `selection.py` if desired (it's only called from A0 flow).

5. **Slim down `planner.py`** to ~150 lines:
   - `prepare_lesson_immediate` (unchanged)
   - `generate_lesson_background` / `_generate_lesson_background` (orchestrator calling the sub-modules)

### Public API Stays the Same

Only two functions are imported externally:
- `from maestro.lezione.planner import prepare_lesson_immediate, generate_lesson_background`

These stay in `planner.py`. Internal restructuring is invisible to callers.

### Files Changed

| File | Change |
|------|--------|
| `src/maestro/lezione/slots.py` | New — slot allocation |
| `src/maestro/lezione/prompts.py` | New — prompt construction |
| `src/maestro/lezione/materialize.py` | New — activity materialization |
| `src/maestro/lezione/a0.py` | New — A0 static lesson logic |
| `src/maestro/lezione/planner.py` | Slim orchestrator |
| `tests/unit/test_planner_slots.py` | Update import path |

### New Tests

- `tests/unit/test_lesson_prompts.py`: verify prompt contains expected sections given various inputs (no LLM mock needed)
- `tests/unit/test_materialize.py`: verify activity creation from a sample LLM response dict
- `tests/integration/test_a0.py`: existing tests should keep passing with import-path-only changes

---

## Checklist

- [ ] B.1 — Add `grammar_point_code` to `LessonActivity`, set in planner, use in route
- [ ] B.2 — Consolidate word-definition lookup into `vocab/query.py`
- [ ] B.3 — Extract reading scoring, completion context, onboarding dispatch from routes
- [ ] B.4 — Split planner.py into slots, prompts, materialize, a0, orchestrator
- [ ] All tests pass
- [ ] No file > 400 lines after split
