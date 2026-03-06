# Phase 6: Curriculum Scenarios, Student Persona, and Lesson History

Replace free-form LLM topic generation with a structured curriculum of real-world scenarios derived from CEFR communicative functions and grammar points. Student interests become a persona that flavors content, not a topic selector. Add lesson history and scenario progress tracking to the profile.

## Context

- **CommunicativeFunction** (84 at A1): CEFR-defined language tasks grouped by macro_category (interagire_informazioni, rituali_sociali, emozioni_sentimenti, etc.).
- **GrammarPoint** (48 at A1): CEFR-tagged grammar objectives grouped by category (verbi, preposizioni, articoli, nome, etc.).
- **Current topic generation**: `generate_topic()` in `planner.py` makes an LLM call each lesson, taking flat `student_interests` and a list of past topic titles. This produces repetitive topics (Rome/villas) and has no curriculum structure.
- **Current interests**: `LearningProfile.student_interests: List[str]` — free-text comma-separated strings passed verbatim into the topic prompt.

## Goals

1. **Curriculum backbone**: scenarios are the unit of progression. Each groups CFs + GPs into a real-world situation (ordering at a bar, making a phone call, asking directions). The planner picks which scenario and depth to cover — no LLM call needed for selection.
2. **Persona as flavor**: student context (life situation, hobbies, profession, why learning Italian) personalizes *how* content is generated, not *what* is covered. A lesson on "al bar" plays out differently for a wine enthusiast vs. a university student.
3. **Progress tracking**: the profile tracks which scenarios have been covered at which depth, enabling informed selection and visible curriculum progress.
4. **Reuse**: with scenario slugs on lessons and drills, past content can be re-served for review without regeneration.
5. **Clean break**: the old topic generation system (`generate_topic`, `LessonTopic`, `get_past_topics`, `student_interests`, `hint`) is fully removed, not left as dead code. A migration script handles existing data.

---

## Tasks

### 6.1 — Generate A1 scenario bank

**What**: Cluster A1 CFs and GPs into 15-20 real-world scenarios, each with 3 depth levels.

**How**:
1. Write `scripts/generate_scenario_bank.py` — a one-off script similar to `scripts/generate_gp_chunk_mapping.py`.
2. Feed Claude all 84 A1 CFs (code, label, macro_category, description) and all 48 A1 GPs (code, label, category, description).
3. Prompt it to cluster them into scenarios. Each scenario:
   - Has a slug (url-safe), label, and short English description
   - Maps to 3-6 CF codes and 3-8 GP codes
   - Has 3 depth descriptions (depth 1 = introduction, 2 = developing, 3 = consolidating)
   - CFs/GPs can appear in multiple scenarios (real life overlaps)
   - Every CF and GP should appear in at least one scenario
4. Output to `src/maestro/data/scenarios_a1.yaml`.
5. Manually review and adjust. This is the curriculum — it's worth a human pass.

**Output format**:
```yaml
scenarios:
  - slug: al-bar
    label: "Al bar"
    description: "Ordering drinks and snacks at an Italian cafe"
    cefr_level: A1
    cf_codes:
      - intazio_chiincserv_a1
      - intritsoc_salutare_a1
      - intritsoc_rispsal_a1
      - interag_inform05_a1
    gp_codes:
      - la_differente_funzione_di_tutti_gli_articoli_determinativi_ed_indeterminativi
      - aggettivi_numerali_cardinali_da_1_a_100
      - i_principali_nomi_invariabili_es_caffe_cinema_citta_universita
      - di_quantita_molto_poco_tanto_piu_meno_niente_un_po
    depths:
      1: "Ordering a coffee — basic requests, greetings, numbers for paying"
      2: "Asking what's available, expressing preferences, small talk with the barista"
      3: "Handling a misunderstanding, asking about ingredients, making conversation"
```

**Validation**: after generation, check that every A1 CF and GP appears in at least one scenario. Log any orphans.

**Files**:
- `scripts/generate_scenario_bank.py` (new)
- `src/maestro/data/scenarios_a1.yaml` (new, generated + reviewed)

---

### 6.2 — Data model changes

**What**: Add `CurriculumScenario` document, `StudentPersona` embedded model, scenario progress tracking on `LearningProfile`, and scenario linkage on `Lesson`/`GeneratedDrill`. Remove old topic-related models and fields.

**New models in `models.py`**:

```python
class CurriculumScenario(Document):
    slug: str                     # "al-bar" (unique)
    label: str                    # "Al bar"
    description: str              # English description of the scenario
    cefr_level: str               # "A1"
    cf_codes: List[str]           # CF codes exercised in this scenario
    gp_codes: List[str]           # GP codes exercised in this scenario
    depths: List[str]             # index 0 = depth 1, etc. Always 3 entries.

    class Settings:
        name = "curriculum_scenarios"


class StudentPersona(BaseModel):
    tags: List[str] = []          # ["university student", "wine enthusiast", ...]
    freetext: str = ""            # optional free-form narrative


class ScenarioProgress(BaseModel):
    depth: int = 0                # highest depth completed (0 = unvisited)
    last_visited: Optional[datetime] = None
    lesson_count: int = 0
```

**Changes to `LearningProfile`**:
```python
class LearningProfile(Document):
    ...
    persona: StudentPersona = StudentPersona()
    scenario_progress: dict[str, ScenarioProgress] = {}  # slug -> progress
    # REMOVED: student_interests
```

**Changes to `Lesson`**:
```python
class Lesson(Document):
    ...
    scenario_slug: Optional[str] = None    # links to CurriculumScenario.slug
    scenario_depth: Optional[int] = None   # which depth level this lesson covered
    topic_title: Optional[str] = None      # creative title generated by content LLM
    topic_description: Optional[str] = None
    # REMOVED: topic: Optional[LessonTopic]
```

**Remove `LessonTopic`**: the `LessonTopic` BaseModel is deleted entirely. Its responsibilities are split:
- Curriculum structure (cf_codes, depth) → `CurriculumScenario` + `Lesson.scenario_slug/scenario_depth`
- Display title/description → `Lesson.topic_title` / `Lesson.topic_description` (plain strings, generated by the content LLM)
- `builds_on` → no longer needed; scenario progression replaces it

**Changes to `GeneratedDrill`**:
```python
class GeneratedDrill(Document):
    ...
    scenario_slug: Optional[str] = None   # for reuse queries
    # REMOVED: topic_used
```

**Changes to `db.py`**: register `CurriculumScenario` in `ALL_DOCUMENT_MODELS`.

**Migration script** (`scripts/migrate_phase6.py`):
1. Copy `LearningProfile.student_interests` → `persona.tags`, then `$unset` `student_interests`
2. For each existing `Lesson` with a `topic` field: copy `topic.title` → `topic_title`, `topic.description` → `topic_description`, then `$unset` `topic`
3. For each existing `GeneratedDrill` with `topic_used`: `$unset` `topic_used`

Run once, idempotent.

**Files**:
- `src/maestro/models.py`
- `src/maestro/db.py`
- `scripts/migrate_phase6.py` (new)

---

### 6.3 — Ingest scenarios

**What**: Load `scenarios_a1.yaml` into `CurriculumScenario` documents at ingest time.

**How**: Add a `seed_scenarios()` function to `learning/ingest.py` (or a new `scenarios/ingest.py`) that:
1. Reads `data/scenarios_a1.yaml`
2. Upserts each scenario by slug (idempotent, like GP/CF ingest)

Call it from the existing ingest entry point.

**Files**:
- `src/maestro/learning/ingest.py`

---

### 6.4 — Scenario selection and old topic system removal

**What**: Replace `generate_topic()` LLM call with deterministic scenario selection. Scope GP and CF picks to the scenario's codes. Remove all old topic generation artifacts.

#### 6.4a — Scenario selection

**New function** in `lezione/selection.py`:

```python
async def pick_scenario(
    profile: LearningProfile,
    cefr_level: str,
) -> tuple[CurriculumScenario, int]:
    """Pick the next scenario and depth level to cover.

    Selection criteria (weighted scoring):
    1. Unvisited scenarios strongly preferred over visited ones
    2. Lower-depth scenarios preferred (don't skip ahead)
    3. Scenarios whose GP codes overlap with the student's weakest GPs get a boost
    4. Recently visited scenarios get a cooldown penalty (avoid back-to-back)
    5. Small random jitter for variety

    Returns (scenario, next_depth).
    """
```

**Changes to `pick_grammar_points`**: add `candidate_codes: list[str] | None = None` parameter. When provided (from `scenario.gp_codes`), filter candidates to those codes before ranking by weakness. The current "all GPs at level" behavior is the fallback when `candidate_codes` is None.

**Changes to `pick_comm_functions`**: replace `preferred_codes` parameter with `candidate_codes: list[str] | None = None`. When provided (from `scenario.cf_codes`), filter candidates to those codes. Falls back to all CFs at level when None.

**Remove `get_past_topics()`** — no longer needed; scenario progress replaces past-topic deduplication.

#### 6.4b — Planner rewrite

**Changes to `lezione/planner.py`**:

- **Delete** `generate_topic()` function entirely
- In `_generate_lesson_background()`:
  1. Call `pick_scenario(profile, cefr_level)` to get `(scenario, depth)`
  2. Set `lesson.scenario_slug = scenario.slug` and `lesson.scenario_depth = depth`
  3. GP selection: `pick_grammar_points(profile, cefr_level, count, candidate_codes=scenario.gp_codes)`
  4. CF selection: `pick_comm_functions(profile, cefr_level, count, candidate_codes=scenario.cf_codes)`
  5. Pass scenario label, depth description, and persona to `_generate_lesson_content()`
  6. Set `lesson.topic_title` and `lesson.topic_description` from content LLM output
- **Remove** all `hint` parameters from `prepare_lesson_immediate()`, `generate_lesson_background()`, `_generate_lesson_background()`
- **Remove** all `LessonTopic` references — use `lesson.topic_title` / `lesson.topic_description` directly
- Set `scenario_slug` on each `GeneratedDrill` created during drill materialisation

#### 6.4c — Prompt cleanup

**Changes to `prompts/planner.yaml`**:

- **Delete** `generate_topic` prompt block entirely
- Update `lesson_content_header` / `lesson_content_footer` to include:
  - Scenario label and depth description as the structural frame
  - Student persona (tags + freetext) as the personalization context
  - Instruction to generate `topic_title` and `topic_description` in the JSON output
  - Explicit instruction: "Set all content in a context that matches the student's persona"

**Updated content prompt structure**:
```
You are generating content for an Italian language lesson.

Curriculum scenario: "Al bar" (depth 2)
Depth focus: "Asking what's available, expressing preferences, small talk"

Student persona: university student, wine enthusiast, on Erasmus in Bologna

Student CEFR level: A1
Student profile: [description]

Grammar activity points:
  - Articoli determinativi (GP code) — ...
  - ...

Drills to generate:
  - ...

Return JSON: { "topic_title": "...", "topic_description": "...", "overview": "...", ... }
```

#### 6.4d — Route and template cleanup

**Changes to `routes/lezione.py`**:
- `lezione_create()`: remove `hint` Form parameter; only takes `duration`
- Update `generate_lesson_background()` call (no `hint` arg)

**Changes to `templates/lezione-new.html`**:
- Remove the "Suggerimento (opzionale)" textarea and its form section

**Changes to `templates/lezione.html`**:
- Replace `lesson.topic.title` → `lesson.topic_title`
- Replace `lesson.topic.description` → `lesson.topic_description`

**Changes to `templates/lezione-complete.html`**:
- Update any `lesson.topic.*` references to use `lesson.topic_title` / `lesson.topic_description`

**Changes to `templates/grammar-detail.html`**:
- Remove the broken `focus_hint` link (`/lezione/new?focus_hint=...`). Replace with a plain link to `/lezione/new` or remove entirely.

**Files**:
- `src/maestro/lezione/selection.py`
- `src/maestro/lezione/planner.py`
- `prompts/planner.yaml`
- `src/maestro/routes/lezione.py`
- `templates/lezione-new.html`
- `templates/lezione.html`
- `templates/lezione-complete.html`
- `templates/grammar-detail.html`

---

### 6.5 — Update scenario progress on lesson completion

**What**: When a lesson completes, update `LearningProfile.scenario_progress` for the covered scenario.

**Where**: In `lezione/service.py` `advance_lesson()`, at the point where `lesson.status = "completed"`:

```python
if lesson.scenario_slug:
    progress = profile.scenario_progress.get(lesson.scenario_slug, ScenarioProgress())
    progress.depth = max(progress.depth, lesson.scenario_depth or 1)
    progress.last_visited = utcnow()
    progress.lesson_count += 1
    profile.scenario_progress[lesson.scenario_slug] = progress
    await profile.save()
```

Note: setting `scenario_slug` on `GeneratedDrill` is handled in 6.4b during drill materialisation.

**Files**:
- `src/maestro/lezione/service.py`

---

### 6.6 — Student persona on profile page

**What**: Replace the free-text interests input with a persona section: tag input + optional freetext.

**Template changes** (`templates/profilo.html`):

Replace the "I tuoi interessi" card with:

```html
<div class="card">
  <h2>Chi sei</h2>
  <p>Dicci qualcosa di te — le lezioni saranno ambientate nel tuo mondo.</p>

  <form method="post" action="/profilo/persona">
    <div class="field">
      <label for="tags">Tag (es. studente, vino rosso, storia romana, marketing)</label>
      <input type="text" id="tags" name="tags"
        value="{{ profile.persona.tags | join(', ') }}"
        placeholder="studente universitario, appassionato di vino, Erasmus a Bologna">
    </div>
    <div class="field">
      <label for="freetext">Raccontaci di te (opzionale)</label>
      <textarea id="freetext" name="freetext"
        placeholder="Studio economia a Bologna. Amo il vino rosso e la storia romana...">{{ profile.persona.freetext }}</textarea>
    </div>
    <button class="submit-btn" type="submit">Salva</button>
  </form>
</div>
```

**Route changes** (`routes/profilo.py`):

- Add `POST /profilo/persona` endpoint that parses tags (comma-separated) and freetext, saves to `profile.persona`
- **Delete** `POST /profilo/interests` endpoint and all `student_interests` references

**Files**:
- `templates/profilo.html`
- `src/maestro/routes/profilo.py`

---

### 6.7 — Scenario map on profile page

**What**: Show a visual grid of all scenarios at the student's CEFR level with progress indicators.

**Route changes** (`routes/profilo.py`):

In `profilo_page()`, add:
```python
scenarios = await CurriculumScenario.find({"cefr_level": cefr}).to_list()
progress = profile.scenario_progress if profile else {}
scenario_map = [
    {
        "scenario": s,
        "depth_completed": progress.get(s.slug, ScenarioProgress()).depth,
        "lesson_count": progress.get(s.slug, ScenarioProgress()).lesson_count,
        "last_visited": progress.get(s.slug, ScenarioProgress()).last_visited,
    }
    for s in scenarios
]
```

**Template** (`templates/profilo.html`):

New section between the CEFR tracker and the skills section:

```html
<div class="scenario-map">
  <h2>Percorso</h2>
  <div class="scenario-grid">
    {% for item in scenario_map %}
    <div class="scenario-card">
      <div class="scenario-label">{{ item.scenario.label }}</div>
      <div class="scenario-dots">
        {% for d in range(1, 4) %}
          <span class="dot {% if d <= item.depth_completed %}filled{% endif %}"></span>
        {% endfor %}
      </div>
      <div class="scenario-meta">{{ item.lesson_count }} lezioni</div>
    </div>
    {% endfor %}
  </div>
</div>
```

Each card shows: scenario label, 3 depth dots (filled/empty), lesson count. Clicking a card could later expand to show linked lessons.

**Files**:
- `templates/profilo.html`
- `src/maestro/routes/profilo.py`

---

### 6.8 — Lesson history on profile page

**What**: Show a compact list of recent completed lessons with topic, scenario, and date.

**Route changes** (`routes/profilo.py`):

```python
recent_lessons = await Lesson.find(
    {"status": "completed"}
).sort(-Lesson.completed_at).limit(20).to_list()

# Batch-load scenario labels (one query, not N)
scenario_slugs = {l.scenario_slug for l in recent_lessons if l.scenario_slug}
scenarios_list = await CurriculumScenario.find(
    {"slug": {"$in": list(scenario_slugs)}}
).to_list() if scenario_slugs else []
scenario_labels = {s.slug: s.label for s in scenarios_list}

lesson_history = [
    {
        "lesson": lesson,
        "scenario_label": scenario_labels.get(lesson.scenario_slug, ""),
    }
    for lesson in recent_lessons
]
```

**Template** (`templates/profilo.html`):

New section at the bottom:

```html
<div class="lesson-history">
  <h2>Lezioni recenti</h2>
  <div class="history-list">
    {% for item in lesson_history %}
    <a href="/lezione/{{ item.lesson.id }}/complete" class="history-row">
      <span class="history-date">{{ item.lesson.completed_at.strftime('%d/%m') }}</span>
      <span class="history-topic">{{ item.lesson.topic_title or '—' }}</span>
      <span class="history-scenario">{{ item.scenario_label }}</span>
    </a>
    {% endfor %}
  </div>
</div>
```

**Files**:
- `templates/profilo.html`
- `src/maestro/routes/profilo.py`

---

### 6.9 — Drill reuse (follow-up)

**What**: Enable re-serving past drills for scenario review without regeneration.

This is a natural follow-up once scenario slugs are on drills. Two entry points:

1. **"Ripassa" on scenario card**: On the profile scenario map, completed scenarios show a "Ripassa" link. This creates a lesson that re-serves existing `GeneratedDrill` docs matching `scenario_slug`, shuffled and optionally at the same or higher depth.

2. **Planner fallback**: If content generation fails or the user wants a quick session, the planner can assemble a lesson purely from existing drills for a given scenario.

**Query**:
```python
past_drills = await GeneratedDrill.find({
    "scenario_slug": slug,
    "cefr_level": cefr_level,
}).to_list()
```

Pick drills the student hasn't seen recently or scored poorly on.

**Deferred**: This task can be implemented after the core flow (6.1-6.8) is working. It doesn't block any other task.

**Files** (when implemented):
- `src/maestro/lezione/planner.py` (new `prepare_review_lesson()` function)
- `src/maestro/routes/lezione.py` (new route or parameter on lesson creation)
- `templates/profilo.html` (ripassa link on scenario cards)

---

## Implementation order

```
6.1  Generate A1 scenario bank (script + YAML + review)
 |
6.2  Data model changes + migration script
 |     - Add: CurriculumScenario, StudentPersona, ScenarioProgress
 |     - Remove: LessonTopic, student_interests, topic_used
 |     - Change: Lesson (scenario_slug/depth, topic_title/description replace topic)
 |
6.3  Ingest scenarios
 |
6.4  Scenario selection + old system removal ← core behavioral change
 |     a. pick_scenario, update pick_grammar_points/pick_comm_functions signatures
 |     b. Rewrite planner (delete generate_topic, remove hint, use scenarios)
 |     c. Delete generate_topic prompt, update content prompt
 |     d. Route/template cleanup (remove hint, fix grammar-detail link, update topic refs)
 |
6.5  Update scenario progress on completion
 |
6.6  Student persona on profile page (delete interests endpoint)
 |
6.7  Scenario map on profile page
 |
6.8  Lesson history on profile page
 |
6.9  Drill reuse (follow-up, deferred)
```

Steps 6.1-6.5 are the critical path — they change how lessons are planned.
Steps 6.6-6.8 are the profile UI — can be done in parallel after 6.2.
Step 6.9 is a nice-to-have that builds on the data laid by 6.1-6.5.

## Artifacts removed (full list)

Tracking every old-system artifact to ensure nothing is left dangling:

| Artifact | Location | Disposition |
|---|---|---|
| `LessonTopic` BaseModel | `models.py:191-196` | **Delete**. Replace with `Lesson.topic_title` + `Lesson.topic_description` (plain strings) |
| `Lesson.topic` field | `models.py:221` | **Delete**. Migrate existing values to `topic_title`/`topic_description` |
| `LearningProfile.student_interests` | `models.py:121` | **Delete**. Migrate to `persona.tags` |
| `GeneratedDrill.topic_used` | `models.py:152` | **Delete**. Replaced by `scenario_slug` |
| `generate_topic()` | `planner.py:94-176` | **Delete** |
| `get_past_topics()` | `selection.py:114-124` | **Delete** |
| `generate_topic` prompt | `prompts/planner.yaml:3-27` | **Delete** |
| `hint` parameter | `planner.py`, `routes/lezione.py`, `lezione-new.html` | **Delete** from all locations |
| `focus_hint` link | `grammar-detail.html:22` | **Delete** (was already broken) |
| `POST /profilo/interests` | `routes/profilo.py:60-82` | **Delete**. Replaced by `POST /profilo/persona` |
| `student_interests` in profilo template | `profilo.html:86-106` | **Delete**. Replaced by persona card |
| `test_generate_topic_*` | `tests/integration/test_planner.py` | **Delete/rewrite** for `pick_scenario` |
| `test_topic_generation` | `tests/eval/test_planner_eval.py` | **Delete** |
| `planner_topic_cases.json` | `tests/eval/fixtures/` | **Delete** |
| `topic_used="test"` in test fixtures | `tests/integration/test_lesson_flow.py`, `test_lezione_routes.py` | **Update** (remove field or use `scenario_slug`) |

## Testing

- **Unit tests**: `pick_scenario` scoring logic (prioritizes unvisited, weak GPs, cooldown)
- **Unit tests**: `pick_grammar_points` / `pick_comm_functions` with `candidate_codes` filter
- **Unit tests**: scenario progress update logic
- **Integration tests**: full planner flow with mocked LLM — verify scenario slug lands on lesson and drills
- **Integration tests**: ingest idempotency for scenarios
- **Integration tests**: migration script correctness (student_interests → persona.tags, topic → topic_title)
- **Manual**: generate a few lessons, verify persona flavoring works, check profile page renders correctly
