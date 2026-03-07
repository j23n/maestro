# Multi-Language Refactoring Plan

Support teaching languages other than Italian. This document details every
change needed, organized into sequential steps within three phases.

---

## Design Decisions

**Deployment model:** single language per deployment, configured via
`TARGET_LANGUAGE` in `.env`. Data lives in per-language subdirectories.
The `LearningProfile` stores the language so that, if the deployment model
later expands to per-user language choice, no migration is needed.

**Database strategy:** add a `language` field to language-specific documents
(default `"it"`). No separate collections per language. Filter by
`settings.TARGET_LANGUAGE` at query time.

**UI language:** the application UI (navigation, buttons, labels) is presented
in the *target language* with English fallback. Each language provides a
string table.

**Grammar point codes:** keep the existing scheme (descriptive slugs). Codes
are language-specific and live in per-language data files. Cross-language
analytics are not a goal.

---

## Phase 1 — Structural Isolation

Goal: all Italian-specific content is cleanly separated from application logic.
The app still only supports Italian at the end of this phase.


### Step 1.1 — Settings

**File:** `src/maestro/settings.py`

Add three fields:

```python
TARGET_LANGUAGE: str = "it"              # ISO 639-1
TARGET_LANGUAGE_NAME: str = "Italian"    # for LLM prompts
SPACY_MODEL: str = "it_core_news_md"    # per-language NLP model
```


### Step 1.2 — Rename ItalianChunk

Rename the model class and update every reference.

**`src/maestro/models.py`**

| Line | Before | After |
|------|--------|-------|
| 76 | `class ItalianChunk(Document):` | `class GrammarChunk(Document):` |
| 84 | `name = "italian_chunks"` | `name = "grammar_chunks"` |
| 149 | `# ItalianChunk.ref` (comment) | `# GrammarChunk.ref` |
| 237 | `# ItalianChunk.ref` (comment) | `# GrammarChunk.ref` |
| 262 | `class ItalianChunkResult:` | `class GrammarChunkResult:` |
| 263 | `chunk: ItalianChunk` | `chunk: GrammarChunk` |
| 330 | `ItalianChunk,` | `GrammarChunk,` |

**Other files importing `ItalianChunk` / `ItalianChunkResult`:**

| File | Lines | Change |
|------|-------|--------|
| `src/maestro/lezione/planner.py` | 30 | import `GrammarChunk` |
| `src/maestro/lezione/planner.py` | 273 | `await GrammarChunk.find_one(...)` |
| `src/maestro/lezione/materialize.py` | 18 | import `GrammarChunk` |
| `src/maestro/lezione/materialize.py` | 57 | `await GrammarChunk.find_one(...)` |
| `src/maestro/rag/retrieve.py` | 2, 16, 35-43 | all `ItalianChunk` -> `GrammarChunk`, `ItalianChunkResult` -> `GrammarChunkResult` |
| `src/maestro/rag/ingest.py` | 10 | import `GrammarChunk` |
| `src/maestro/routes/grammar.py` | imports + usage | `GrammarChunk` |
| `src/maestro/drills/scoring.py` | imports + usage | `GrammarChunk` |

**`src/maestro/db.py` line 21:**

```python
collection = client[settings.MONGODB_DB]["grammar_chunks"]
```

**MongoDB migration:** rename the collection:

```javascript
db.italian_chunks.renameCollection("grammar_chunks")
```


### Step 1.3 — Add `language` field to documents

Add `language: str = "it"` to these Document classes in `models.py`:

| Model | Notes |
|-------|-------|
| `GrammarChunk` | (the renamed class) |
| `GrammarPoint` | |
| `CommunicativeFunction` | |
| `CurriculumScenario` | |
| `VocabularyWord` | replaces implicit Italian assumption |
| `VocabularyWordDefinition` | |
| `GrammarPointExplanation` | |
| `DrillTemplate` | |
| `Lesson` | set at creation time from profile |
| `LearningProfile` | field name: `target_language` |

Models that do NOT need a language field (already language-agnostic):
- `Student` — just a name
- `LearningEvent` — uses GP/CF codes, tied to a student
- `UserVocabularyCard` — references VocabularyWord by Link
- `GeneratedDrill` — references DrillTemplate by Link; inherits language
- `DrillAttempt` — references GeneratedDrill by Link

**MongoDB migration script** (`scripts/migrate_multilang.py`):

```python
# Add language="it" to all existing documents in affected collections
for coll in [
    "grammar_chunks", "grammar_points", "comm_functions",
    "curriculum_scenarios", "vocabulary_words",
    "vocabulary_word_definitions", "grammar_point_explanations",
    "drill_templates", "lessons", "learning_profile",
]:
    db[coll].update_many(
        {"language": {"$exists": False}},
        {"$set": {"language": "it"}},
    )
# LearningProfile uses "target_language" field name
db["learning_profile"].update_many(
    {"target_language": {"$exists": False}},
    {"$set": {"target_language": "it"}},
)
```


### Step 1.4 — Reorganize data directory

Move Italian data files into a language subdirectory.

**Current layout:**
```
src/maestro/data/
  grammar_points.json
  comm_functions.json
  scenarios_a0.yaml
  scenarios_a1.yaml
  a0_lessons.yaml
  vocab_a0.json
  a0_grammar_explanations.json
  grammar_point_chunks.yaml
  chunk_enrichment.json
  dizionario_it_lex0.xml
  book_contents/           (grammar textbook for RAG)
```

**New layout:**
```
src/maestro/data/
  it/
    grammar_points.json
    comm_functions.json
    scenarios_a0.yaml
    scenarios_a1.yaml
    a0_lessons.yaml
    vocab_a0.json
    a0_grammar_explanations.json
    grammar_point_chunks.yaml
    chunk_enrichment.json
    dizionario_it_lex0.xml
    book_contents/
```

**`src/maestro/utils.py`** — change `DATA_DIR` to be language-aware:

```python
# Before (line 33)
DATA_DIR = Path(__file__).parent / "data"

# After
DATA_DIR_ROOT = Path(__file__).parent / "data"

def data_dir(language: str | None = None) -> Path:
    """Return the data directory for the given language."""
    if language is None:
        from maestro.config import settings
        language = settings.TARGET_LANGUAGE
    return DATA_DIR_ROOT / language
```

**Files that reference `DATA_DIR`** (update all to use `data_dir()`):

| File | Lines | Current usage |
|------|-------|---------------|
| `src/maestro/learning/ingest.py` | 31 | `DATA_DIR / "grammar_points.json"` etc. |
| `src/maestro/lezione/a0.py` | 19, 39 | `DATA_DIR / "a0_lessons.yaml"` |
| `src/maestro/rag/ingest.py` | 15, 18 | `DATA_DIR / "chunk_enrichment.json"`, `DATA_DIR / "book_contents/..."` |
| `src/maestro/vocab/ingest.py` | (none — reads from URLs, not DATA_DIR) | n/a |
| `src/maestro/vocab/epub_parser.py` | 25-26 | hardcoded paths to `dizionario_book` / `dizionario_it_lex0.xml` |


### Step 1.5 — Parameterize NLP model loading

**`src/maestro/vocab/nlp.py`:**

```python
from functools import lru_cache
import spacy

@lru_cache(maxsize=1)
def get_nlp():
    from maestro.config import settings
    return spacy.load(settings.SPACY_MODEL)
```

**`src/maestro/main.py` line 22** — remove the Italian-specific comment:

```python
get_nlp()        # warm up spaCy model
```


### Step 1.6 — Parameterize taxonomy cache

**`src/maestro/taxonomy.py`** — filter by language:

```python
async def ensure_loaded() -> None:
    global _grammar_points, _comm_functions, _loaded
    if _loaded:
        return
    from maestro.config import settings
    lang = settings.TARGET_LANGUAGE
    _grammar_points = await GrammarPoint.find(
        GrammarPoint.language == lang
    ).to_list()
    _comm_functions = await CommunicativeFunction.find(
        CommunicativeFunction.language == lang
    ).to_list()
    _loaded = True
```


### Step 1.7 — Parameterize ingest scripts

**`src/maestro/learning/ingest.py`** — use `data_dir()` for all file paths:

```python
from maestro.utils import data_dir

async def upsert_grammar_points() -> list[GrammarPoint]:
    with open(data_dir() / "grammar_points.json") as f:
        items = json.load(f)
    # ... same logic, but add language=settings.TARGET_LANGUAGE to each doc
```

Apply the same pattern to:
- `link_grammar_points_to_chunks()` — chunk mapping file path
- `upsert_comm_functions()` — comm_functions.json path
- `seed_scenarios()` — scenario YAML paths
- `seed_a0_vocab()` — vocab_a0.json path
- `seed_a0_grammar_explanations()` — a0_grammar_explanations.json path

**`src/maestro/lezione/a0.py` line 39** — use `data_dir()`:

```python
lessons_file = data_dir() / "a0_lessons.yaml"
```

**`src/maestro/rag/ingest.py`** — use `data_dir()` for book_contents and enrichment.


### Step 1.8 — Parameterize prompt templates

**Strategy:** add a `{{target_language}}` variable to prompts that reference
Italian by name. This is the minimal change — the prompt structure stays the same.

**`prompts/planner.yaml`:**

```yaml
lesson_content_header:
  user: |
    You are generating content for a {{target_language}} language lesson.
    Set all content in a context that matches the student's persona.
    Generate a creative {{target_language}} topic_title and topic_description for this lesson.

lesson_content_footer:
  user: |
    ...
    - fill_blank: ... each prompt is a {{target_language}} sentence with ___ as placeholder ...
    - error_correction: ... each prompt is a bare erroneous {{target_language}} sentence ...
    - free_form: ... open-ended {{target_language}} writing prompt ...
    - All content in {{target_language}}
    ...
```

**`prompts/analyzer.yaml`** — replace all 9 occurrences of "Italian" with
`{{target_language}}`:

| Section | Line | String to replace |
|---------|------|-------------------|
| `analyze_message` | 14 | "Analyze this Italian learner's message" |
| `score_multi_item` | 52 | "grading an Italian grammar exercise" |
| `task_fill_blank` | 79 | "fill a blank in an Italian sentence" |
| `task_error_correction` | 85 | "correct a grammatical error in an Italian sentence" |
| `generate_writing_feedback` | 96 | "Italian language teacher" |
| `score_free_form_drill` | 124 | "free-form Italian drill" |
| `score_reading_answers` | 152 | "Italian language learner" |
| `feedback_fill_blank` | 176 | "An Italian learner" |
| `evaluate_error_correction` | 193 | "Italian grammar exercise" |

**`prompts/grammar_explanations.yaml`** — replace "Italian" with
`{{target_language}}` in `explanations_system` (line 9) and level guidance
sections (lines 44-64).

**`prompts/vocab_definitions.yaml`** — replace "Italian" with
`{{target_language}}` in `definitions_system` (line 10, 18).

**`prompts/lesson_analyzer.yaml`** — replace "Italian" with
`{{target_language}}` in `analyze_gps` (line 9).

**Prompt rendering:** update `build_lesson_content_prompt()` and all other
prompt render sites to pass `target_language=settings.TARGET_LANGUAGE_NAME`.

**`src/maestro/lezione/prompts.py`** — update `build_lesson_content_prompt()`:

```python
parts: list[str] = [
    _prompts.lesson_content_header.render(
        target_language=settings.TARGET_LANGUAGE_NAME
    ),
    ...
]
```

Also update the schema dict (line 108):
```python
schema: dict = {
    "topic_title": f"A creative {settings.TARGET_LANGUAGE_NAME} title for this lesson (3-8 words)",
    "topic_description": "1-2 sentences describing the specific situation covered",
    "overview": f"2-3 sentences in {settings.TARGET_LANGUAGE_NAME}: what this lesson covers...",
}
```

And reading/writing/speaking schema entries that reference "Italian" (lines 141, 149, 154).

**Other files that render analyzer prompts** — pass `target_language`:
- `src/maestro/learning/scorer.py` — all `_prompts.*.render()` calls
- `src/maestro/learning/lesson_analyzer.py` — all `_prompts.*.render()` calls
- `src/maestro/drills/scoring.py` — all `_prompts.*.render()` calls
- `src/maestro/grammar/generate_explanations.py` — system prompt render
- `src/maestro/vocab/generate_definitions.py` — system prompt render

**`src/maestro/lezione/service.py` line 134-136** — parameterize the feedback prompt:

```python
# Before
prompt = (
    f"A student just completed an Italian lesson. Summary:\n..."
)

# After
prompt = (
    f"A student just completed a {settings.TARGET_LANGUAGE_NAME} lesson. Summary:\n..."
)
```


### Step 1.9 — Extract hardcoded UI strings

Create a string table module for activity titles and descriptions generated
in Python code.

**New file: `src/maestro/strings.py`**

```python
from maestro.config import settings

_STRINGS: dict[str, dict[str, str]] = {
    "it": {
        # materialize.py activity titles/descriptions
        "grammar_title": "Grammatica: {label}",
        "grammar_desc": "Ripassa la regola grammaticale: {label}",
        "reading_title_n": "Lettura {n}",
        "reading_title": "Lettura",
        "reading_desc": "Leggi un testo su: {topic}",
        "drill_title": "Esercizio: {label}",
        "speaking_title": "Parlare: {label}",
        "speaking_desc": "Pratica: {label}",
        "writing_title": "Scrittura",
        "writing_desc": "Scrivi un testo su: {topic}",
        # planner.py vocab activity
        "vocab_title": "Vocabolario ({count} parole)",
        "vocab_desc": "Ripassa le parole in scadenza oggi",
        # a0.py fallback titles
        "a0_drill_title": "Esercizio: {code}",
        "a0_reading_title": "Lettura",
    },
}

def t(key: str, **kwargs) -> str:
    lang = settings.TARGET_LANGUAGE
    table = _STRINGS.get(lang, _STRINGS["it"])
    return table[key].format(**kwargs)
```

**Update `src/maestro/lezione/materialize.py`** — replace all 8 hardcoded
Italian strings with `t()` calls:

| Line | Before | After |
|------|--------|-------|
| 65 | `f"Grammatica: {grammar_title}"` | `t("grammar_title", label=grammar_title)` |
| 66 | `f"Ripassa la regola grammaticale: {gp.label}"` | `t("grammar_desc", label=gp.label)` |
| 78 | `f"Lettura {i + 1}" if ... else "Lettura"` | `t("reading_title_n", n=i+1) if ... else t("reading_title")` |
| 79 | `f"Leggi un testo su: {topic_title}"` | `t("reading_desc", topic=topic_title)` |
| 132 | `f"Esercizio: {spec['gp_label']}"` | `t("drill_title", label=spec['gp_label'])` |
| 145 | `f"Parlare: {cf.label}"` | `t("speaking_title", label=cf.label)` |
| 146 | `f"Pratica: {cf.label}"` | `t("speaking_desc", label=cf.label)` |
| 157 | `"Scrittura"` | `t("writing_title")` |
| 158 | `f"Scrivi un testo su: {topic_title}"` | `t("writing_desc", topic=topic_title)` |

**Update `src/maestro/lezione/planner.py`** lines 161-162:

```python
# Before
title=f"Vocabolario ({len(due_cards)} parole)",
description="Ripassa le parole in scadenza oggi",

# After
title=t("vocab_title", count=len(due_cards)),
description=t("vocab_desc"),
```


### Step 1.10 — Template string extraction

HTML templates contain ~80 hardcoded strings (Italian UI text + English
references to "Italian"). These need a localization mechanism.

**Approach:** expose the string table to Jinja2 templates as a `t()` function
and a `lang` variable. Create a template strings file per language.

**New file: `src/maestro/i18n.py`**

```python
import json
from pathlib import Path
from maestro.config import settings

_ROOT = Path(__file__).parent / "i18n"
_cache: dict[str, dict] = {}

def _load(lang: str) -> dict:
    if lang not in _cache:
        with open(_ROOT / f"{lang}.json") as f:
            _cache[lang] = json.load(f)
    return _cache[lang]

def t(key: str, **kwargs) -> str:
    strings = _load(settings.TARGET_LANGUAGE)
    template = strings.get(key, key)
    return template.format(**kwargs) if kwargs else template
```

**New directory: `src/maestro/i18n/`**

**`src/maestro/i18n/it.json`** — contains all template-facing strings:

```json
{
  "nav_lesson": "Lezione",
  "nav_vocab": "Vocabolario",
  "nav_grammar": "Grammatica",
  "page_title_vocab": "Vocabolario",
  "page_title_grammar": "Grammatica",
  "page_title_reading": "Lettura",
  "page_title_writing": "Scrittura",
  "page_title_lesson_complete": "Lezione completata",
  "page_title_new_lesson": "Nuova Lezione",
  "page_title_lesson_plan": "Piano della Lezione",
  "page_title_profile": "Profilo",
  "page_title_generating": "Preparazione Lezione",
  "vocab_review_btn": "Ripassa",
  "vocab_total": "totale",
  "vocab_due": "da ripassare",
  "vocab_learning": "in corso",
  "vocab_mastered": "acquisite",
  "vocab_search_placeholder": "Cerca nel dizionario\u2026",
  "vocab_filter_all": "Tutti",
  "vocab_due_header": "Da ripassare",
  "vocab_learning_header": "In corso",
  "vocab_mastered_header": "Acquisite",
  "vocab_empty": "Nessuna parola ancora. Le parole appariranno qui durante le lezioni.",
  "vocab_italian_word": "What's the {language} word?",
  "vocab_how_say": "How do you say this in {language}?",
  "writing_placeholder": "Scrivi qui la tua risposta in {language_lower}\u2026",
  "reading_comprehension": "Comprensione",
  "reading_submit": "Invio risposte",
  "reading_answer_placeholder": "La tua risposta\u2026",
  "drill_fill_blank_instruction": "Scrivi la parola mancante nella forma corretta.",
  "drill_error_correction_instruction": "Trova e correggi l'errore grammaticale in ogni frase.",
  "drill_fill_blank_placeholder": "Parola mancante\u2026",
  "drill_error_correction_placeholder": "Frase corretta\u2026",
  "drill_free_form_placeholder": "Scrivi qui la tua risposta\u2026",
  "drill_submit_all": "Invia tutto",
  "drill_evaluating": "Valutazione\u2026",
  "lesson_complete_title": "Lezione completata!",
  "lesson_complete_subtitle": "Ottimo lavoro. Ecco il riepilogo.",
  "lesson_completed_label": "completate",
  "lesson_skipped_label": "saltate",
  "lesson_duration_label": "durata prevista",
  "lesson_activities_done": "Attivit\u00e0 svolte",
  "lesson_feedback_label": "Feedback",
  "lesson_review_label": "Da ripassare",
  "lesson_full_rule": "Regola completa \u2192",
  "lesson_new_btn": "Nuova lezione \u2192",
  "lesson_profile_btn": "Profilo",
  "generating_error": "Qualcosa \u00e8 andato storto",
  "generating_retry": "Riprova",
  "generating_wait": "Stiamo preparando la tua lezione\u2026",
  "generating_detail": "Grammatica, letture ed esercizi in arrivo. Un momento.",
  "new_lesson_subtitle": "Il tuo insegnante preparer\u00e0 una lezione su misura per te.",
  "new_lesson_duration": "Quanto tempo hai?",
  "new_lesson_minutes": "minuti",
  "new_lesson_start": "Inizia la lezione",
  "new_lesson_note": "La preparazione richiede qualche secondo.",
  "lesson_plan_title": "Piano della lezione",
  "lesson_plan_activities": "attivit\u00e0",
  "lesson_plan_start": "Inizia la lezione \u2192",
  "lesson_plan_regenerate": "Rigenera",
  "continue": "Continua \u2192",
  "skip": "Salta \u2192",
  "grammar_understood": "Ho capito \u2192",
  "grammar_why_matters": "Why this matters",
  "grammar_english_translation": "English translation",
  "grammar_full_rule": "Vedi la regola completa \u2192",
  "profile_path": "Percorso",
  "profile_lessons": "lezioni",
  "profile_grammar_short": "gramm",
  "profile_functions_short": "funz",
  "profile_grammar": "Grammatica",
  "profile_comm_functions": "Funzioni comunicative"
}
```

**Register `t()` as a Jinja2 global** in `src/maestro/templates.py`:

```python
from maestro.i18n import t as i18n_t

templates.env.globals["t"] = i18n_t
templates.env.globals["target_language"] = settings.TARGET_LANGUAGE_NAME
```

**Then update templates** — replace hardcoded strings with `{{ t("key") }}`
calls. For example in `templates/base.html`:

```html
<!-- Before -->
<a href="/lezione/">Lezione</a>

<!-- After -->
<a href="/lezione/">{{ t("nav_lesson") }}</a>
```

**`templates/landing.html`** — this is marketing copy. Keep it as a separate
per-language template (`landing-it.html`, `landing-es.html`) or use the
`t()` system. Given its size and unique content per language, separate
templates are simpler.


### Step 1.11 — Language-specific vocabulary processing

The clitic/reflexive handling in `src/maestro/vocab/ingest.py` (lines 76-141)
is Italian-specific. Isolate it behind a language dispatch.

**New file: `src/maestro/vocab/morphology/__init__.py`**

```python
from maestro.config import settings

def get_lookup_factory():
    if settings.TARGET_LANGUAGE == "it":
        from maestro.vocab.morphology.it import make_lookup
        return make_lookup
    raise ValueError(f"No morphology module for {settings.TARGET_LANGUAGE}")
```

**New file: `src/maestro/vocab/morphology/it.py`**

Move `_CLITIC_TRAILING_RE`, `_CLITIC_SUFFIX_RE`, and `make_lookup()` from
`vocab/ingest.py` into this file unchanged.

**`src/maestro/vocab/ingest.py`** — import from the dispatch:

```python
from maestro.vocab.morphology import get_lookup_factory

async def ingest():
    ...
    make_lookup = get_lookup_factory()
    lookup = make_lookup(by_form, nlp)
    ...
```

The `WORDLISTS` URLs and `POS_MAP` are also Italian-specific. Move them
into a config dict or into `morphology/it.py`.


### Step 1.12 — Update tests

**Unit tests** (`tests/unit/`):

- `test_utils.py` — no language changes needed (CEFR logic is universal)
- `test_vocab_lookup.py` — requires Italian spaCy model; add
  `skipUnless(settings.TARGET_LANGUAGE == "it")` or mock

**Integration tests** (`tests/integration/`):

- Fixtures creating `GrammarPoint`, `CommunicativeFunction`, etc. — add
  `language="it"` to all constructors
- Patch `ItalianChunk` → `GrammarChunk` everywhere:
  - `test_planner.py` line 271-272
  - `test_scoring.py` line 164
- Update `conftest.py` `db` fixture to set `settings.TARGET_LANGUAGE = "it"`
- Update `reset_taxonomy` fixture if it hardcodes assumptions

**Eval tests** (`tests/eval/`):

- These test Italian language quality specifically — gate them behind
  `settings.TARGET_LANGUAGE == "it"`


### Step 1.13 — Migration script

**New file: `scripts/migrate_multilang.py`**

```python
"""
Migration for multi-language support.

1. Rename italian_chunks → grammar_chunks collection
2. Add language="it" to all existing documents
3. Add target_language="it" to learning_profile documents
"""
```

Run once against the production database.


---


## Phase 2 — Add a Second Language

Goal: prove the architecture by adding support for German. This validates
every abstraction from Phase 1.


### Step 2.1 — Create language data files

**New directory: `src/maestro/data/de/`**

Required files and how to source them:

| File | Content | Source |
|------|---------|--------|
| `grammar_points.json` | German grammar taxonomy (A0-B2) | Goethe-Institut curriculum / Profile deutsch + manual curation |
| `comm_functions.json` | German communicative functions | Profile deutsch + CEFR framework adaptation |
| `scenarios_a0.yaml` | 8-10 sequential A0 scenarios | Author from scratch (pedagogical design) |
| `scenarios_a1.yaml` | 20-24 A1 scenarios | Author from scratch |
| `a0_lessons.yaml` | Static A0 lesson content | Author from scratch (German examples/dialogues) |
| `vocab_a0.json` | 20-30 essential A0 words | Goethe A1 word list / German frequency lists |
| `a0_grammar_explanations.json` | Pre-written A0 grammar explanations | Author or LLM-generate |
| `grammar_point_chunks.yaml` | GP-to-chunk mapping | Only if a RAG grammar reference is available |

**Grammar point structure** — same JSON schema as Italian, different content:

```json
[
  {
    "code": "a0_begruessung",
    "label": "Greetings and farewells",
    "cefr_level": "A0",
    "category": "basics",
    "description": "Common German greetings: hallo, guten Tag, tschuess..."
  }
]
```

**Communicative function structure** — same JSON schema:

```json
[
  {
    "code": "a0_begruessen",
    "label": "Begruessen",
    "macro_category": "interaktion_soziale_rituale",
    "cefr_level": "A0",
    "patterns": ["Hallo!", "Guten Tag!"],
    "examples": [],
    "description": "Greet someone in a social context"
  }
]
```


### Step 2.2 — German NLP setup

**spaCy model:** `de_core_news_md`

Install: `uv add spacy && python -m spacy download de_core_news_md`

**`.env` for German deployment:**

```
TARGET_LANGUAGE=de
TARGET_LANGUAGE_NAME=German
SPACY_MODEL=de_core_news_md
```


### Step 2.3 — German morphology module

**New file: `src/maestro/vocab/morphology/de.py`**

German-specific morphological processing:
- Separable prefix verbs (e.g., `anfangen` → lemma `anfangen`, but
  `ich fange an` needs prefix reattachment for lookup)
- Compound noun decomposition (`Handschuh` → `Hand` + `Schuh`) — optional,
  mainly for discovery enrichment
- Umlaut normalization for lookup fallback (`ae`/`oe`/`ue` ↔ `a`/`o`/`u`)

```python
import re

_SEPARABLE_PREFIXES = [
    "ab", "an", "auf", "aus", "bei", "ein", "mit",
    "nach", "vor", "zu", "zurueck", "weg", "hin", "her",
]

def make_lookup(by_form: dict, nlp):
    """German-specific word lookup with morphological fallbacks."""
    # Similar structure to Italian version but with
    # separable prefix and compound noun handling
    ...
```


### Step 2.4 — German vocabulary source

**Options for dictionary source:**
1. Wiktionary German entries (open data, API available)
2. DWDS (Digitales Woerterbuch der deutschen Sprache) — academic API available
3. A German learner dictionary EPUB, if available
4. Goethe-Institut A1/A2 word lists (publicly available PDFs)

**`src/maestro/vocab/ingest.py`** — the wordlist URLs need to be per-language.
Move them into a config:

```python
WORDLIST_SOURCES = {
    "it": [
        ("A1", "https://www.unistrapg.it/.../liste_lessicali_a1.html"),
        ...
    ],
    "de": [
        ("A1", "https://example.com/goethe_a1_wortliste"),
        ...
    ],
}
```

If no equivalent HTML wordlist exists for German, an alternative ingest
pipeline may be needed (e.g., Goethe word list PDF parsing + Wiktionary API).


### Step 2.5 — German UI strings

**New file: `src/maestro/i18n/de.json`**

```json
{
  "nav_lesson": "Lektion",
  "nav_vocab": "Wortschatz",
  "nav_grammar": "Grammatik",
  "vocab_title": "Wortschatz ({count} Woerter)",
  "vocab_desc": "Wiederhole die faelligen Woerter",
  "grammar_title": "Grammatik: {label}",
  ...
}
```

**Add German to `src/maestro/strings.py`:**

```python
_STRINGS["de"] = {
    "vocab_title": "Wortschatz ({count} Woerter)",
    "vocab_desc": "Wiederhole die faelligen Woerter",
    "grammar_title": "Grammatik: {label}",
    "grammar_desc": "Wiederhole die Grammatikregel: {label}",
    "reading_title": "Lesen",
    "reading_desc": "Lies einen Text ueber: {topic}",
    "drill_title": "Uebung: {label}",
    "speaking_title": "Sprechen: {label}",
    "speaking_desc": "Uebe: {label}",
    "writing_title": "Schreiben",
    "writing_desc": "Schreibe einen Text ueber: {topic}",
    ...
}
```


### Step 2.6 — German RAG grammar reference (optional)

If a German grammar textbook is available for RAG:
1. Parse and chunk it (adapt `rag/ingest.py`)
2. Generate embeddings (the multilingual-e5-large model already supports German)
3. Create `grammar_point_chunks.yaml` mapping
4. Create `chunk_enrichment.json`

If no textbook is available, the RAG system can be skipped for the new
language — grammar explanations rely on LLM knowledge plus the GP description.


### Step 2.7 — German landing page

Create `templates/landing-de.html` with German marketing copy, or make
`landing.html` use `t()` for all strings.

**`src/maestro/main.py`** — route the landing page by language:

```python
@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    if request.cookies.get("student_id"):
        return RedirectResponse(url="/lezione/")
    template = f"landing-{settings.TARGET_LANGUAGE}.html"
    return templates.TemplateResponse(request=request, name=template)
```


### Step 2.8 — End-to-end testing

1. Set `TARGET_LANGUAGE=de` in `.env`
2. Run `python -m maestro.learning.ingest` — verify all German data loads
3. Create a student, start an A0 lesson — verify static content renders
4. Complete A0 → verify A1 promotion
5. Start an A1 lesson — verify LLM generates German content
6. Check vocabulary discovery works with German text
7. Verify drill scoring works for German grammar


---


## Phase 3 — Per-User Language Selection (Future)

Goal: a single deployment serves multiple languages. Each student picks
their target language at signup.


### Step 3.1 — Language on LearningProfile

The `target_language` field added in Phase 1 becomes the source of truth
instead of `settings.TARGET_LANGUAGE`.

**Changes:**
- Onboarding flow adds a language selection step (before lesson 1)
- `LearningProfile.target_language` is set during onboarding
- All query functions accept an explicit `language` parameter


### Step 3.2 — Request-scoped language

**Add FastAPI middleware or dependency:**

```python
async def get_language(
    student: Student = Depends(get_current_student),
) -> str:
    profile = await get_profile(student.id)
    return profile.target_language if profile else settings.TARGET_LANGUAGE
```

Thread this through route handlers and into service functions.


### Step 3.3 — Multi-language taxonomy cache

The current `taxonomy.py` caches one language's data. For multi-language,
partition the cache by language:

```python
_grammar_points: dict[str, list[GrammarPoint]] = {}
_comm_functions: dict[str, list[CommunicativeFunction]] = {}
```


### Step 3.4 — Multi-language NLP

Replace the `@lru_cache(maxsize=1)` with a per-language cache:

```python
_nlp_cache: dict[str, spacy.Language] = {}

def get_nlp(language: str | None = None) -> spacy.Language:
    language = language or settings.TARGET_LANGUAGE
    if language not in _nlp_cache:
        model = SPACY_MODELS[language]
        _nlp_cache[language] = spacy.load(model)
    return _nlp_cache[language]
```


### Step 3.5 — Multi-language data loading

The `data_dir()` function already takes a language parameter. Ingest
scripts would run per-language:

```bash
TARGET_LANGUAGE=es python -m maestro.learning.ingest
TARGET_LANGUAGE=fr python -m maestro.learning.ingest
```

Or accept `--language` as a CLI argument.


---


## Reference: Complete File Change Index

Every file that needs modification, organized by phase.

### Phase 1 files

| File | Changes |
|------|---------|
| `src/maestro/settings.py` | Add `TARGET_LANGUAGE`, `TARGET_LANGUAGE_NAME`, `SPACY_MODEL` |
| `src/maestro/models.py` | Rename `ItalianChunk`→`GrammarChunk`, `ItalianChunkResult`→`GrammarChunkResult`; add `language` field to 10 models |
| `src/maestro/db.py` | Update collection name `italian_chunks`→`grammar_chunks` |
| `src/maestro/utils.py` | `DATA_DIR` → `data_dir()` function |
| `src/maestro/taxonomy.py` | Filter by `language` in `ensure_loaded()` |
| `src/maestro/config.py` | No change (just instantiates Settings) |
| `src/maestro/main.py` | Remove Italian-specific comment |
| `src/maestro/vocab/nlp.py` | Use `settings.SPACY_MODEL` |
| `src/maestro/vocab/discover.py` | No change (uses `get_nlp()` which is now parameterized) |
| `src/maestro/vocab/ingest.py` | Move Italian morphology to `morphology/it.py`; use language-aware wordlist config |
| `src/maestro/vocab/epub_parser.py` | Update paths to use `data_dir()` |
| `src/maestro/learning/ingest.py` | Use `data_dir()` for all file paths; add `language` to all docs |
| `src/maestro/lezione/planner.py` | `ItalianChunk`→`GrammarChunk`; `t()` for UI strings |
| `src/maestro/lezione/materialize.py` | `ItalianChunk`→`GrammarChunk`; `t()` for all 8 activity title/description strings |
| `src/maestro/lezione/prompts.py` | Pass `target_language` to prompt renders; update schema strings |
| `src/maestro/lezione/a0.py` | Use `data_dir()` |
| `src/maestro/lezione/service.py` | Parameterize feedback prompt language |
| `src/maestro/lezione/selection.py` | No change needed (queries by CEFR level; language filtering happens via taxonomy) |
| `src/maestro/rag/retrieve.py` | `ItalianChunk`→`GrammarChunk` |
| `src/maestro/rag/ingest.py` | `ItalianChunk`→`GrammarChunk`; use `data_dir()` |
| `src/maestro/routes/grammar.py` | `ItalianChunk`→`GrammarChunk` |
| `src/maestro/drills/scoring.py` | `ItalianChunk`→`GrammarChunk`; pass `target_language` to prompts |
| `src/maestro/learning/scorer.py` | Pass `target_language` to prompt renders |
| `src/maestro/learning/lesson_analyzer.py` | Pass `target_language` to prompt renders |
| `src/maestro/grammar/generate_explanations.py` | Pass `target_language` to prompt renders |
| `src/maestro/vocab/generate_definitions.py` | Pass `target_language` to prompt renders |
| `prompts/planner.yaml` | `Italian` → `{{target_language}}` |
| `prompts/analyzer.yaml` | `Italian` → `{{target_language}}` (9 locations) |
| `prompts/grammar_explanations.yaml` | `Italian` → `{{target_language}}` (5 locations) |
| `prompts/vocab_definitions.yaml` | `Italian` → `{{target_language}}` (2 locations) |
| `prompts/lesson_analyzer.yaml` | `Italian` → `{{target_language}}` (1 location) |
| 26 template files | Replace hardcoded strings with `{{ t("key") }}` calls |
| `tests/integration/conftest.py` | `ItalianChunk`→`GrammarChunk`; add `language` to fixtures |
| `tests/integration/test_planner.py` | `ItalianChunk`→`GrammarChunk` |
| `tests/integration/test_scoring.py` | `ItalianChunk`→`GrammarChunk` |
| `tests/unit/test_vocab_lookup.py` | Gate behind `TARGET_LANGUAGE=it` |

**New files:**

| File | Purpose |
|------|---------|
| `src/maestro/strings.py` | Python-side string table (activity titles/descriptions) |
| `src/maestro/i18n/__init__.py` | Template-side i18n module |
| `src/maestro/i18n/it.json` | Italian template strings |
| `src/maestro/vocab/morphology/__init__.py` | Language dispatch for morphological processing |
| `src/maestro/vocab/morphology/it.py` | Italian clitic/reflexive handling (extracted from `vocab/ingest.py`) |
| `scripts/migrate_multilang.py` | One-time MongoDB migration |
| `src/maestro/data/it/` | Directory containing all existing data files (moved) |

### Phase 2 additional files

| File | Purpose |
|------|---------|
| `src/maestro/data/de/grammar_points.json` | German grammar taxonomy |
| `src/maestro/data/de/comm_functions.json` | German communicative functions |
| `src/maestro/data/de/scenarios_a0.yaml` | German A0 scenarios |
| `src/maestro/data/de/scenarios_a1.yaml` | German A1 scenarios |
| `src/maestro/data/de/a0_lessons.yaml` | German static A0 lesson content |
| `src/maestro/data/de/vocab_a0.json` | German A0 vocabulary |
| `src/maestro/data/de/a0_grammar_explanations.json` | German A0 grammar explanations |
| `src/maestro/i18n/de.json` | German template strings |
| `src/maestro/vocab/morphology/de.py` | German morphological processing |
| `templates/landing-de.html` | German landing page |


---


## What is NOT language-specific

These components work unchanged for any language:

- **SRS algorithm** (`vocab/srs.py`) — pure SM-2, no language logic
- **CEFR framework** (`utils.py` `CEFR_ORDER`) — universal across European languages
- **Lesson state machine** (`lezione/service.py` `advance_lesson()`) — activity progression logic
- **Slot allocation** (`lezione/slots.py`) — time-based activity planning
- **Profile computation** (`profile.py`) — GP/CF code counting and CEFR estimation
- **Learning event recording** — stores codes, not language content
- **Authentication** (`auth.py`) — student cookie management
- **Background task infrastructure** (`utils.py` `create_background_task()`)
- **Embedding model** (`rag/retrieve.py`) — `multilingual-e5-large` supports 100+ languages
- **LLM JSON parsing** (`utils.py` `parse_llm_json()`)
- **Vocabulary cache** (`vocab/cache.py`) — caches by word ID, not by language
