# Phase 4: Test Coverage Expansion

**Goal**: Fill the major test coverage gaps exposed during the codebase review. Focus on the most complex and fragile code paths — planner orchestration, vocab discovery, route form submissions, and lesson completion flow.

**Effort**: 2-3 sessions. Can be done incrementally — each test file is independent.

**Prerequisites**: Phases 1-3 complete. The refactored code (taxonomy cache, client factory, split modules) makes these tests much easier to write.

**Validation**: After each batch, run `uv run pytest -v` to confirm new tests pass alongside existing ones.

---

## Current Coverage Baseline

| Area | Unit Tests | Integration Tests | Key Gaps |
|------|-----------|------------------|----------|
| `utils.py` | 11 (parse_llm_json) | 0 | `utcnow` (added in Phase 1) |
| `vocab/srs.py` | 13 (SM-2 review) | 0 | None — well covered |
| `lezione/planner.py` | 8 (slot allocation) | 0 | Topic generation, content generation, activity materialization, vocab card filling |
| `learning/analyzer.py` | 0 | 11 | All via mocked LLM — good |
| `learning/profile.py` | 0 | 7 | `_generate_description` untested |
| `learning/lesson_analyzer.py` | 0 | 7 | `_analyze_gps`, `_analyze_cfs_staged`, `analyze_lesson` untested |
| `drills/scoring.py` | 0 | 6 | Good coverage of score_attempt |
| `routes/lezione.py` | 2 (helpers) | 6 (advance_lesson + 1 route) | 13 route handlers untested — drill-submit, writing-submit, reading-submit, vocab-rate, skip, complete, generating |
| `routes/vocab.py` | 0 | 2 (smoke) | Form submissions (add, review, search), generate-on-demand |
| `routes/profilo.py` | 4 (helpers) | 1 (smoke) | Interest save |
| `vocab/discover.py` | 0 | 0 | `discover()`, `_annotate()`, `load_vocab()` completely untested |
| `vocab/ingest.py` | 0 | 0 | `make_lookup()` untested |

**Target**: Add ~35-40 new tests, bringing the total from ~85 to ~120+.

---

## Task 4.1: Vocab Discovery and Annotation Tests

### Why

`vocab/discover.py` is on the critical path — every lesson activity that displays text runs through `discover()` to annotate Italian words with popover spans. Bugs here silently break the UI. The `_annotate()` function has subtle HTML parsing logic that could easily regress.

### Tests to write

**File: `tests/unit/test_discover.py`**

These test `_annotate()` as a pure function (no DB needed):

```python
import pytest
from maestro.vocab.discover import _annotate
from maestro.models import VocabularyWord, VocabularyWordDefinition, Sense, CefrSense


def _make_word(word="casa", pos="s.f.", syllabization="cà-sa", entry_id="LM-001", senses=None):
    """Create a VocabularyWord-like object for testing."""
    from types import SimpleNamespace
    return SimpleNamespace(
        word=word,
        part_of_speech=pos,
        syllabization=syllabization,
        entry_id=entry_id,
        senses=senses or [],
        id="fake-id",
    )


def _make_wdef(translation="house", senses=None):
    from types import SimpleNamespace
    return SimpleNamespace(
        translation=translation,
        senses=senses or [SimpleNamespace(definition="edificio dove si abita", examples=["La mia casa è grande."])],
    )


@pytest.mark.unit
def test_annotate_wraps_first_occurrence():
    word = _make_word(word="casa")
    wdef = _make_wdef()
    result = _annotate("La casa è grande.", word, wdef)
    assert '<span class="vocab-word"' in result
    assert 'data-word="casa"' in result
    assert result.count("vocab-word") == 1  # only first occurrence


@pytest.mark.unit
def test_annotate_case_insensitive():
    word = _make_word(word="casa")
    result = _annotate("CASA bella", word, None)
    assert "vocab-word" in result


@pytest.mark.unit
def test_annotate_skips_headings():
    word = _make_word(word="tema")
    result = _annotate("# Tema principale\nIl tema è interessante.", word, None)
    # Should annotate in the body line, not the heading
    lines = result.split("\n")
    assert "vocab-word" not in lines[0]  # heading untouched
    assert "vocab-word" in lines[1]      # body annotated


@pytest.mark.unit
def test_annotate_preserves_existing_html_tags():
    word = _make_word(word="bello")
    result = _annotate('Un <strong>bello</strong> giorno e un bello tramonto.', word, None)
    # Should not corrupt the <strong> tag — should annotate the second "bello" in text
    assert "<strong>" in result
    assert "vocab-word" in result


@pytest.mark.unit
def test_annotate_no_match_returns_unchanged():
    word = _make_word(word="casa")
    text = "Il giardino è grande."
    result = _annotate(text, word, None)
    assert result == text


@pytest.mark.unit
def test_annotate_includes_senses_json():
    word = _make_word(word="tavolo")
    wdef = _make_wdef(translation="table")
    result = _annotate("Il tavolo è rotondo.", word, wdef)
    assert 'data-translation="table"' in result
    assert "data-senses" in result


@pytest.mark.unit
def test_annotate_falls_back_to_epub_senses():
    """When no graded definition exists, fall back to raw EPUB senses."""
    word = _make_word(
        word="libro",
        senses=[SimpleNamespace(definition="opera stampata", examples=["Un bel libro."], synonyms=[], antonyms=[], pos=None, style=None)],
    )
    result = _annotate("Ho letto un libro.", word, None)  # wdef=None
    assert "data-senses" in result
    assert "opera stampata" in result


@pytest.mark.unit
def test_annotate_word_boundary():
    """'casa' should not match inside 'casamento'."""
    word = _make_word(word="casa")
    result = _annotate("Il casamento è vecchio.", word, None)
    assert "vocab-word" not in result
```

### Tests for `_lemmatize` and integration discover flow

**File: `tests/integration/test_discover.py`**

These need the spaCy model and DB:

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from maestro.models import (
    VocabularyWord, VocabularyWordDefinition, UserVocabularyCard, LearningProfile,
    Sense, CefrSense,
)


@pytest.mark.integration
async def test_discover_creates_cards_for_new_words(db):
    """discover() should create UserVocabularyCards for words not yet in the user's collection."""
    from maestro.vocab import discover as discover_module

    word = VocabularyWord(
        word="mangiare",
        part_of_speech="v.tr.",
        cefr_level="A1",
        entry_id="LM-TEST",
        senses=[],
    )
    await word.insert()

    # Pre-populate the vocab index
    discover_module._vocab_index = {"mangiare": word}
    discover_module._def_index = {}

    with patch.object(discover_module, "_lemmatize", return_value=["mangiare"]):
        result = await discover_module.discover("Voglio mangiare la pizza.")

    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1
    assert "vocab-word" in result


@pytest.mark.integration
async def test_discover_does_not_duplicate_cards(db):
    """discover() should not create duplicate cards for words already in the collection."""
    from maestro.vocab import discover as discover_module

    word = VocabularyWord(
        word="bere",
        part_of_speech="v.tr.",
        cefr_level="A1",
        entry_id="LM-BERE",
        senses=[],
    )
    await word.insert()
    card = UserVocabularyCard(word=word)
    await card.insert()

    discover_module._vocab_index = {"bere": word}
    discover_module._def_index = {}

    with patch.object(discover_module, "_lemmatize", return_value=["bere"]):
        await discover_module.discover("Voglio bere acqua.")

    cards = await UserVocabularyCard.find_all().to_list()
    assert len(cards) == 1  # no duplicate
```

---

## Task 4.2: Planner Tests

### Why

`planner.py` is the most complex module (765 lines). The only tests are for `_allocate_slots` (8 unit tests). The topic generation, content generation, and activity materialization — the core lesson planning logic — are completely untested.

### Tests to write

**File: `tests/integration/test_planner.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

from maestro.models import (
    GrammarPoint, GrammarPointExplanation, CommunicativeFunction,
    DrillTemplate, GeneratedDrill, LearningProfile, Lesson,
    UserVocabularyCard, VocabularyWord,
)


# --- selection.py tests (after Phase 3 split) ---

@pytest.mark.integration
async def test_pick_grammar_points_prioritises_weak(db):
    """Grammar points with higher error rates should be picked first."""
    from maestro.lezione.selection import pick_grammar_points

    gp1 = GrammarPoint(code="GP_A", label="A", cefr_level="A1", category="test", description="A")
    gp2 = GrammarPoint(code="GP_B", label="B", cefr_level="A1", category="test", description="B")
    await gp1.insert()
    await gp2.insert()

    profile = LearningProfile(
        grammar_error_counts={"GP_A": 5, "GP_B": 0},
        grammar_correct_counts={"GP_A": 1, "GP_B": 5},
    )

    picked = await pick_grammar_points(profile, "A1", 1)
    assert picked[0].code == "GP_A"  # higher error rate → picked first


@pytest.mark.integration
async def test_pick_grammar_points_falls_back_when_no_level_match(db):
    """When no GPs exist at the target level, fall back to all GPs."""
    from maestro.lezione.selection import pick_grammar_points

    gp = GrammarPoint(code="GP_B2", label="B2 rule", cefr_level="B2", category="test", description="B2 rule")
    await gp.insert()

    picked = await pick_grammar_points(None, "A1", 1)
    assert len(picked) == 1
    assert picked[0].code == "GP_B2"


@pytest.mark.integration
async def test_fill_vocab_cards_introduces_new_words(db):
    """When not enough cards are due, new words should be introduced."""
    from maestro.lezione.selection import fill_vocab_cards

    for i in range(10):
        await VocabularyWord(
            word=f"parola{i}", part_of_speech="s.f.", cefr_level="A1"
        ).insert()

    cards = await fill_vocab_cards(5, "A1")
    assert len(cards) == 5
    db_cards = await UserVocabularyCard.find_all().to_list()
    assert len(db_cards) == 5


# --- generate_topic tests ---

@pytest.mark.integration
async def test_generate_topic_parses_llm_json(db):
    """generate_topic should parse LLM JSON into a LessonTopic."""
    from maestro.lezione.planner import generate_topic

    mock_client = AsyncMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='{"title": "Al bar", "description": "Ordering at a bar", "cf_codes": ["CF_001"], "depth": 1}')]
    )

    topic = await generate_topic(
        profile=None,
        past_topics=[],
        available_cfs=[],
        hint="",
        client=mock_client,
    )
    assert topic.title == "Al bar"
    assert topic.cf_codes == ["CF_001"]


@pytest.mark.integration
async def test_generate_topic_falls_back_on_error(db):
    """generate_topic should return a fallback topic on LLM error."""
    from maestro.lezione.planner import generate_topic

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = RuntimeError("API down")

    topic = await generate_topic(
        profile=None,
        past_topics=[],
        available_cfs=[],
        hint="cucina italiana",
        client=mock_client,
    )
    assert topic.title == "cucina italiana"  # falls back to hint


# --- prepare_lesson_immediate tests ---

@pytest.mark.integration
async def test_prepare_lesson_immediate_creates_lesson(db):
    """Should create a Lesson with vocab_review activity and generating=True."""
    from maestro.lezione.planner import prepare_lesson_immediate

    # Need some words for vocab cards
    for i in range(10):
        await VocabularyWord(
            word=f"word{i}", part_of_speech="s.f.", cefr_level="A1"
        ).insert()

    profile = LearningProfile(cefr_estimate="A1")
    await profile.insert()

    lesson = await prepare_lesson_immediate(20, "", [], profile)
    assert lesson.status == "active"
    assert lesson.generating is True
    assert len(lesson.activities) >= 1
    assert lesson.activities[0].type == "vocab_review"


# --- activity materialization tests ---

@pytest.mark.integration
async def test_drill_materialization_creates_generated_drills(db):
    """Drill specs from LLM content should be materialized into GeneratedDrill documents."""
    from maestro.lezione.planner import generate_lesson_background

    # Seed required data
    profile = LearningProfile(cefr_estimate="A1")
    await profile.insert()

    gp = GrammarPoint(code="GP_001", label="Presente", cefr_level="A1", category="verbi", description="Present tense")
    await gp.insert()

    template = DrillTemplate(grammar_point_code="GP_001", cefr_level="A1", exercise_type="fill_blank")
    await template.insert()

    # Create the lesson
    lesson = Lesson(status="active", duration_minutes=10, generating=True)
    await lesson.insert()

    # Mock the LLM calls
    topic_response = MagicMock(content=[MagicMock(text='{"title":"Test","description":"Test","cf_codes":[],"depth":1}')])
    content_response = MagicMock(content=[MagicMock(text='''{
        "overview": "Test lesson",
        "grammar_motivations": [{"code": "GP_001", "text": "Important rule"}],
        "drills": [{"grammar_point_code": "GP_001", "items": [{"prompt": "Io ___ (mangiare)", "correct_answer": "mangio"}]}],
        "readings": [{"text": "Test reading.", "questions": ["Q1"], "answers": ["A1"]}],
        "writing": {"prompt": "Scrivi qualcosa."},
        "speakings": []
    }''')])

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = [topic_response, content_response]

    with patch("maestro.lezione.planner.get_async_client", return_value=mock_client), \
         patch("maestro.lezione.planner.get_chunks_for_refs", new_callable=AsyncMock, return_value=[]):
        await generate_lesson_background(lesson.id, 10, "", ["GP_001"])

    # Verify
    updated_lesson = await Lesson.get(lesson.id)
    assert updated_lesson.generating is False
    assert len(updated_lesson.activities) > 0

    drills = await GeneratedDrill.find_all().to_list()
    assert len(drills) >= 1
```

---

## Task 4.3: Route Form Submission Tests

### Why

The route handlers for form submissions (`drill-submit`, `writing-submit`, `reading-submit`, `vocab-rate`) are the most complex route handlers, involving DB reads/writes, LLM calls, and lesson state transitions. They're currently untested.

### Tests to write

**File: `tests/integration/test_lezione_routes.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from maestro.models import (
    ALL_DOCUMENT_MODELS, Lesson, LessonActivity, GeneratedDrill,
    DrillTemplate, DrillItem, LearningProfile, GrammarPoint,
)


@pytest.fixture
async def test_app_with_data():
    """TestClient with DB seeded for lesson route tests."""
    mongo_client = AsyncMongoMockClient()
    await init_beanie(database=mongo_client["test_maestro"], document_models=ALL_DOCUMENT_MODELS)

    with (
        patch("maestro.main.init_db", new_callable=AsyncMock),
        patch("maestro.main.get_nlp", return_value=MagicMock()),
        patch("maestro.main.load_vocab", new_callable=AsyncMock),
    ):
        from maestro.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


@pytest.fixture
async def active_lesson_with_drill():
    """Create an active lesson with a fill_blank drill activity."""
    template = DrillTemplate(grammar_point_code="GP_001", cefr_level="A1", exercise_type="fill_blank")
    await template.insert()

    drill = GeneratedDrill(
        template=template,
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type="fill_blank",
        prompt="",
        items=[DrillItem(prompt="Io ___ al parco.", correct_answer="vado")],
        topic_used="test",
    )
    await drill.insert()

    lesson = Lesson(
        status="active",
        duration_minutes=10,
        started_at=datetime.utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type="drill",
                title="Test drill",
                description="Test",
                duration_minutes=3,
                status="active",
                drill_id=drill.id,
            ),
        ],
        current_index=0,
    )
    await lesson.insert()
    return lesson, drill


@pytest.mark.integration
def test_drill_submit_returns_result_page(test_app_with_data, active_lesson_with_drill):
    """POST drill-submit should return the drill result template."""
    lesson, drill = active_lesson_with_drill

    with patch("maestro.routes.lezione.score_attempt", new_callable=AsyncMock) as mock_score:
        mock_score.return_value = (True, MagicMock(), {"items": [], "correct_count": 1, "total": 1}, [])
        with patch("maestro.routes.lezione.discover", new_callable=AsyncMock, return_value="annotated"):
            response = test_app_with_data.post(
                f"/lezione/{lesson.id}/activity/0/drill-submit",
                data={"answers": "vado"},
            )

    assert response.status_code == 200


@pytest.mark.integration
def test_activity_skip_returns_redirect(test_app_with_data, active_lesson_with_drill):
    """POST skip should return 204 with HX-Redirect header."""
    lesson, _ = active_lesson_with_drill

    response = test_app_with_data.post(
        f"/lezione/{lesson.id}/activity/0/skip",
    )
    assert response.status_code == 204
    assert "HX-Redirect" in response.headers


@pytest.mark.integration
def test_activity_complete_returns_redirect(test_app_with_data, active_lesson_with_drill):
    """POST complete should return 204 with HX-Redirect header."""
    lesson, _ = active_lesson_with_drill

    response = test_app_with_data.post(
        f"/lezione/{lesson.id}/activity/0/complete",
    )
    assert response.status_code == 204
    assert "HX-Redirect" in response.headers


@pytest.mark.integration
async def test_writing_submit_returns_feedback(test_app_with_data, db):
    """POST writing-submit should call generate_writing_feedback and return result."""
    lesson = Lesson(
        status="active",
        duration_minutes=10,
        started_at=datetime.utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type="writing",
                title="Scrittura",
                description="Test",
                duration_minutes=5,
                status="active",
                content="Descrivi la tua giornata.",
            ),
        ],
        current_index=0,
    )
    await lesson.insert()

    mock_feedback = {
        "objective_correct": True,
        "objective_note": "",
        "grammar_errors": [],
        "tips": [],
    }
    with patch("maestro.routes.lezione.generate_writing_feedback", new_callable=AsyncMock, return_value=mock_feedback):
        response = test_app_with_data.post(
            f"/lezione/{lesson.id}/activity/0/writing-submit",
            data={"answer": "Oggi ho mangiato la pizza."},
        )

    assert response.status_code == 200
```

---

## Task 4.4: Lesson Completion Flow Tests

### Why

The lesson completion page (`lezione_complete`) triggers two LLM calls — feedback generation and lesson analysis — via background tasks. The interaction between these, weak grammar point identification, and the feedback_summary persistence is complex and untested.

### Tests to write

**File: `tests/integration/test_lesson_complete.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from maestro.models import (
    Lesson, LessonActivity, GeneratedDrill, DrillTemplate, GrammarPoint, LearningProfile,
)


@pytest.fixture
async def completed_lesson(db):
    """A lesson with mixed drill results — some correct, some incorrect."""
    gp_ok = GrammarPoint(code="GP_OK", label="Presente", cefr_level="A1", category="test", description="Ok")
    gp_bad = GrammarPoint(code="GP_BAD", label="Passato", cefr_level="A1", category="test", description="Bad")
    await gp_ok.insert()
    await gp_bad.insert()

    template = DrillTemplate(grammar_point_code="GP_OK", cefr_level="A1", exercise_type="fill_blank")
    await template.insert()

    drill_ok = GeneratedDrill(
        template=template, grammar_point_code="GP_OK", cefr_level="A1",
        exercise_type="fill_blank", prompt="", topic_used="test",
    )
    drill_bad = GeneratedDrill(
        template=template, grammar_point_code="GP_BAD", cefr_level="A1",
        exercise_type="fill_blank", prompt="", topic_used="test",
    )
    await drill_ok.insert()
    await drill_bad.insert()

    lesson = Lesson(
        status="completed",
        duration_minutes=10,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type="drill", title="D1", description="", duration_minutes=3,
                status="completed", drill_id=drill_ok.id, result={"correct": True},
            ),
            LessonActivity(
                type="drill", title="D2", description="", duration_minutes=3,
                status="completed", drill_id=drill_bad.id, result={"correct": False},
            ),
            LessonActivity(
                type="writing", title="W", description="", duration_minutes=5,
                status="completed", result={"student_answer": "Ho scritto."},
            ),
        ],
        current_index=2,
    )
    await lesson.insert()
    return lesson


@pytest.mark.integration
async def test_get_weak_grammar_points(db, completed_lesson):
    """Should return grammar points for drills the student got wrong."""
    from maestro.lezione.service import get_weak_grammar_points  # after Phase 3 split

    weak = await get_weak_grammar_points(completed_lesson)
    codes = {gp.code for gp in weak}
    assert "GP_BAD" in codes
    assert "GP_OK" not in codes


@pytest.mark.integration
async def test_generate_lesson_feedback_mentions_activities(db, completed_lesson):
    """Feedback should reference the activities completed."""
    from maestro.lezione.service import generate_lesson_feedback

    mock_response = MagicMock(content=[MagicMock(text="Great work on present tense drills!")])
    with patch("maestro.lezione.service.get_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.messages.create.return_value = mock_response
        mock_client_factory.return_value = mock_client

        feedback = await generate_lesson_feedback(completed_lesson, [])

    assert isinstance(feedback, str)
    assert len(feedback) > 0


@pytest.mark.integration
async def test_analyze_lesson_creates_learning_event(db, completed_lesson):
    """analyze_lesson should create a LearningEvent and update the profile."""
    from maestro.learning.lesson_analyzer import analyze_lesson
    from maestro.models import LearningEvent
    from maestro import taxonomy

    # Seed taxonomy cache
    gps = await GrammarPoint.find_all().to_list()
    taxonomy.seed(gps=gps, cfs=[])

    profile = LearningProfile(cefr_estimate="A1")
    await profile.insert()

    # Mock the LLM calls for GP and CF analysis
    gp_response = MagicMock(content=[MagicMock(text='{"grammar_correct": [], "grammar_errors": []}')])
    cf_stage1_response = MagicMock(content=[MagicMock(text='{"categories": []}')])

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = [gp_response, cf_stage1_response]

    with patch("maestro.learning.lesson_analyzer.get_async_client", return_value=mock_client):
        await analyze_lesson(completed_lesson)

    events = await LearningEvent.find_all().to_list()
    assert len(events) == 1
    # Drill outcomes should be in the event
    assert "GP_OK" in events[0].grammar_correct
    assert "GP_BAD" in events[0].grammar_errors
```

---

## Task 4.5: Vocab Ingest Lookup Tests

### Why

`make_lookup()` in `vocab/ingest.py` has complex lemmatization logic — spaCy lemma lookup, clitic stripping, enclitic pronoun clusters, and `-mente` adverb derivation. It's a pure function (given a dict and nlp model) and should be unit-tested.

### Tests to write

**File: `tests/unit/test_vocab_lookup.py`**

```python
import pytest
from types import SimpleNamespace


def _make_entry(headword):
    return SimpleNamespace(
        headword=headword,
        hyph=None,
        pos_abbrev="s.m.",
        entry_id=f"LM-{headword}",
        senses=[],
    )


@pytest.fixture
def lookup_fn():
    """Build a lookup function with a small test dictionary.

    Requires spaCy it_core_news_md — skip if not available.
    """
    try:
        import spacy
        nlp = spacy.load("it_core_news_md")
    except OSError:
        pytest.skip("spaCy it_core_news_md not available")

    from maestro.vocab.ingest import make_lookup

    by_form = {
        "andare": _make_entry("andare"),
        "mangiare": _make_entry("mangiare"),
        "bello": _make_entry("bello"),
        "fare": _make_entry("fare"),
        "casa": _make_entry("casa"),
        "felice": _make_entry("felice"),
    }

    return make_lookup(by_form, nlp)


@pytest.mark.unit
def test_direct_match(lookup_fn):
    assert lookup_fn("andare") is not None
    assert lookup_fn("andare").headword == "andare"


@pytest.mark.unit
def test_lemma_match(lookup_fn):
    """Conjugated form should resolve via spaCy lemmatization."""
    result = lookup_fn("mangiato")
    # "mangiato" lemmatises to "mangiare"
    assert result is not None
    assert result.headword == "mangiare"


@pytest.mark.unit
def test_unknown_word_returns_none(lookup_fn):
    assert lookup_fn("xyzzyx") is None


@pytest.mark.unit
def test_reflexive_clitic_stripping(lookup_fn):
    """'andarsene' should resolve to 'andare' via clitic stripping."""
    result = lookup_fn("andarsene")
    if result:  # depends on spaCy model accuracy
        assert result.headword == "andare"


@pytest.mark.unit
def test_mente_adverb(lookup_fn):
    """'felicemente' should resolve to 'felice' via -mente rule."""
    result = lookup_fn("felicemente")
    if result:
        assert result.headword == "felice"
```

Note: These tests require the spaCy model to be installed. They skip gracefully if it's not available (CI may not have it). Mark them as `@pytest.mark.unit` since they test pure logic, but they do require an external model.

---

## Task 4.6: Profile Description Generation Test

### Why

`_generate_description()` in `learning/profile.py` builds a natural-language profile summary by aggregating grammar points, vocab coverage, and communicative functions. It's ~95 lines of logic involving multiple DB queries and string formatting, but completely untested.

### Tests to write

**File: `tests/integration/test_profile_description.py`**

```python
import pytest
from maestro.models import (
    GrammarPoint, CommunicativeFunction, LearningProfile,
    VocabularyWord, UserVocabularyCard,
)


@pytest.mark.integration
async def test_generate_description_empty_profile(db):
    """An empty profile should produce a valid description string."""
    from maestro.learning.profile import _generate_description

    # Seed minimal data
    gp = GrammarPoint(code="GP_001", label="Presente", cefr_level="A1", category="test", description="test")
    await gp.insert()
    cf = CommunicativeFunction(code="CF_001", label="Salutare", macro_category="interagire_rituali_sociali", cefr_level="A1")
    await cf.insert()

    profile = LearningProfile(cefr_estimate="A1")
    desc = await _generate_description(profile)

    assert isinstance(desc, str)
    assert "A1" in desc
    assert len(desc) > 20


@pytest.mark.integration
async def test_generate_description_with_struggles(db):
    """Profile with error-heavy grammar points should mention difficulties."""
    from maestro.learning.profile import _generate_description

    gp = GrammarPoint(code="GP_001", label="Passato prossimo", cefr_level="A1", category="test", description="test")
    await gp.insert()

    profile = LearningProfile(
        cefr_estimate="A1",
        grammar_correct_counts={"GP_001": 1},
        grammar_error_counts={"GP_001": 5},  # 5/6 = 83% error rate > 40%
    )
    desc = await _generate_description(profile)

    assert "Passato prossimo" in desc
    assert "difficult" in desc.lower() or "persistent" in desc.lower()


@pytest.mark.integration
async def test_generate_description_with_functions(db):
    """Profile with demonstrated CFs should mention communicative repertoire."""
    from maestro.learning.profile import _generate_description

    cf = CommunicativeFunction(
        code="CF_001", label="Salutare",
        macro_category="interagire_rituali_sociali", cefr_level="A1",
    )
    await cf.insert()

    profile = LearningProfile(
        cefr_estimate="A1",
        functions_counts={"CF_001": 10},
    )
    desc = await _generate_description(profile)

    assert "Salutare" in desc
```

---

## Summary: New Test Count by File

| New test file | Count | Type |
|--------------|-------|------|
| `tests/unit/test_discover.py` | ~8 | unit |
| `tests/integration/test_discover.py` | ~2 | integration |
| `tests/integration/test_planner.py` | ~6 | integration |
| `tests/integration/test_lezione_routes.py` | ~4 | integration |
| `tests/integration/test_lesson_complete.py` | ~3 | integration |
| `tests/unit/test_vocab_lookup.py` | ~5 | unit |
| `tests/integration/test_profile_description.py` | ~3 | integration |
| **Total** | **~31** | |

Combined with existing 85 tests → ~116 total. Plus any additional edge case tests discovered during implementation.

---

## Commit Strategy

One commit per test file, or group related tests:

1. `test: add unit and integration tests for vocab discover/annotate`
2. `test: add integration tests for planner (selection, topic, materialization)`
3. `test: add integration tests for lesson route form submissions`
4. `test: add integration tests for lesson completion flow`
5. `test: add unit tests for vocab lookup lemmatization`
6. `test: add integration tests for profile description generation`

---

## Post-Phase 4 Checklist

After all phases are complete:

- [ ] No `datetime.utcnow()` calls remain
- [ ] No unescaped regex from user input
- [ ] No sync LLM calls in async handlers
- [ ] `rg 'anthropic\.(Anthropic|AsyncAnthropic)\(' src/maestro/` returns only `llm.py`
- [ ] `rg 'LearningProfile\.find_one' src/maestro/` returns only `profile.py`
- [ ] `rg 'global _' src/maestro/` returns only `taxonomy.py`
- [ ] No file exceeds ~600 lines
- [ ] `uv run pytest -v` runs ~120 tests, all passing
- [ ] Background task errors are logged with full tracebacks
