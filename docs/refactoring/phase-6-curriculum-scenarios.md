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

**What**: Add `CurriculumScenario` document, `StudentPersona` embedded model, scenario progress tracking on `LearningProfile`, and scenario linkage on `Lesson`/`GeneratedDrill`.

**Changes to `models.py`**:

```python
class CurriculumScenario(Document):
    slug: str                     # "al-bar" (unique)
    label: str                    # "Al bar"
    description: str              # English description of the scenario
    cefr_level: str               # "A1"
    cf_codes: List[str]           # CF codes exercised in this scenario
    gp_codes: List[str]           # GP codes exercised in this scenario
    depths: dict                  # {1: "...", 2: "...", 3: "..."}

    class Settings:
        name = "curriculum_scenarios"


class StudentPersona(BaseModel):
    tags: List[str] = []          # ["university student", "wine enthusiast", ...]
    freetext: str = ""            # optional free-form narrative
```

**Changes to `LearningProfile`**:
```python
class LearningProfile(Document):
    ...
    persona: StudentPersona = StudentPersona()
    scenario_progress: dict = {}  # slug -> {"depth": int, "last_visited": str, "lesson_count": int}
    # student_interests: removed after migration
```

**Changes to `Lesson`**:
```python
class Lesson(Document):
    ...
    scenario_slug: Optional[str] = None   # links to CurriculumScenario.slug
    scenario_depth: Optional[int] = None  # which depth level this lesson covered
```

**Changes to `GeneratedDrill`**:
```python
class GeneratedDrill(Document):
    ...
    scenario_slug: Optional[str] = None   # for reuse queries
```

**Changes to `db.py`**: register `CurriculumScenario` in `ALL_DOCUMENT_MODELS`.

**Migration**: existing `student_interests` values are copied to `persona.tags` on first profile load or via a one-time script. The `student_interests` field is removed after migration.

**Files**:
- `src/maestro/models.py`
- `src/maestro/db.py`

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

### 6.4 — Scenario selection in planner

**What**: Replace `generate_topic()` LLM call with deterministic scenario selection. The planner picks which scenario and depth to cover next based on the student's progress, GP weaknesses, and recency.

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

**Changes to `lezione/planner.py`**:

- Remove `generate_topic()` function and its prompt
- In `_generate_lesson_background()`:
  1. Call `pick_scenario(profile, cefr_level)` to get `(scenario, depth)`
  2. Set `lesson.scenario_slug = scenario.slug` and `lesson.scenario_depth = depth`
  3. GP selection becomes: pick from `scenario.gp_codes` (prioritized by weakness)
  4. CF selection becomes: pick from `scenario.cf_codes` (prioritized by least-practised)
  5. Pass scenario label, depth description, and persona to `_generate_lesson_content()`
- `LessonTopic` is still generated — but now by the content LLM as a creative title for this specific lesson instance, constrained to the scenario + depth

**Changes to `prompts/planner.yaml`**:

- Remove `generate_topic` prompt
- Update `lesson_content_header` / `lesson_content_footer` to include:
  - Scenario label and depth description as the structural frame
  - Student persona (tags + freetext) as the personalization context
  - Instruction to generate a `topic_title` and `topic_description` in the JSON output
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

**Files**:
- `src/maestro/lezione/selection.py`
- `src/maestro/lezione/planner.py`
- `prompts/planner.yaml`

---

### 6.5 — Update scenario progress on lesson completion

**What**: When a lesson completes, update `LearningProfile.scenario_progress` for the covered scenario.

**Where**: In the lesson completion flow (`routes/lezione.py` or `lezione/service.py`), after setting `lesson.status = "completed"`:

```python
if lesson.scenario_slug:
    progress = profile.scenario_progress.get(lesson.scenario_slug, {})
    progress["depth"] = max(progress.get("depth", 0), lesson.scenario_depth or 1)
    progress["last_visited"] = utcnow().isoformat()
    progress["lesson_count"] = progress.get("lesson_count", 0) + 1
    profile.scenario_progress[lesson.scenario_slug] = progress
    await profile.save()
```

Also set `scenario_slug` on each `GeneratedDrill` created during lesson generation (already in scope in `_generate_lesson_background`), enabling reuse queries later.

**Files**:
- `src/maestro/routes/lezione.py` (or `src/maestro/lezione/service.py`)
- `src/maestro/lezione/planner.py` (set slug on drills)

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
- Remove or redirect the old `POST /profilo/interests` endpoint

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
        "depth_completed": progress.get(s.slug, {}).get("depth", 0),
        "lesson_count": progress.get(s.slug, {}).get("lesson_count", 0),
        "last_visited": progress.get(s.slug, {}).get("last_visited"),
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

**What**: Show a compact list of recent completed lessons with topic, GPs covered, CFs practised, and date.

**Route changes** (`routes/profilo.py`):

```python
recent_lessons = await Lesson.find(
    {"status": "completed"}
).sort(-Lesson.completed_at).limit(20).to_list()
```

Derive GP codes and CF codes from lesson activities at render time (no new fields needed):
- Drill activities: look up `GeneratedDrill` by `drill_id` to get `grammar_point_code`
- Grammar activities: extract GP label from title
- Speaking activities: CFs from the lesson topic's `cf_codes`

Alternatively, for efficiency, pre-compute a lightweight summary list in the route:
```python
lesson_history = []
for lesson in recent_lessons:
    gp_codes = set()
    for a in lesson.activities:
        if a.type == "drill" and a.drill_id:
            drill = await GeneratedDrill.get(a.drill_id)
            if drill:
                gp_codes.add(drill.grammar_point_code)
    lesson_history.append({
        "lesson": lesson,
        "gp_codes": list(gp_codes),
        "scenario_label": ...,  # look up from scenario_slug
    })
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
      <span class="history-topic">{{ item.lesson.topic.title if item.lesson.topic else '—' }}</span>
      <span class="history-scenario">{{ item.scenario_label or '' }}</span>
      <span class="history-gps">{{ item.gp_codes | join(', ') }}</span>
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
6.2  Data model changes (CurriculumScenario, StudentPersona, scenario_progress)
 |
6.3  Ingest scenarios
 |
6.4  Scenario selection in planner ← core behavioral change
 |
6.5  Update scenario progress on completion
 |
6.6  Student persona on profile page
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

## Testing

- **Unit tests**: `pick_scenario` scoring logic (prioritizes unvisited, weak GPs, cooldown)
- **Unit tests**: scenario progress update logic
- **Integration tests**: full planner flow with mocked LLM — verify scenario slug lands on lesson and drills
- **Integration tests**: ingest idempotency for scenarios
- **Manual**: generate a few lessons, verify persona flavoring works, check profile page renders correctly
