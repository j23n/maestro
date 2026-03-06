"""Integration tests for lezione/planner.py and lezione/selection.py."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from maestro.models import (
    GrammarPoint,
    CommunicativeFunction,
    DrillTemplate,
    GeneratedDrill,
    LearningProfile,
    Lesson,
    UserVocabularyCard,
    VocabularyWord,
)


# ---------------------------------------------------------------------------
# selection.py tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# generate_topic tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# prepare_lesson_immediate tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_prepare_lesson_immediate_creates_lesson(db):
    """Should create a Lesson with vocab_review activity and generating=True."""
    from maestro.lezione.planner import prepare_lesson_immediate

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


# ---------------------------------------------------------------------------
# generate_lesson_background tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_drill_materialization_creates_generated_drills(db):
    """Drill specs from LLM content should be materialized into GeneratedDrill documents."""
    from maestro.lezione.planner import generate_lesson_background

    profile = LearningProfile(cefr_estimate="A1")
    await profile.insert()

    gp = GrammarPoint(code="GP_001", label="Presente", cefr_level="A1", category="verbi", description="Present tense")
    await gp.insert()

    template = DrillTemplate(grammar_point_code="GP_001", cefr_level="A1", exercise_type="fill_blank")
    await template.insert()

    lesson = Lesson(status="active", duration_minutes=10, generating=True)
    await lesson.insert()

    topic_response = MagicMock(content=[MagicMock(
        text='{"title":"Test","description":"Test","cf_codes":[],"depth":1}'
    )])
    content_response = MagicMock(content=[MagicMock(text="""{
        "overview": "Test lesson",
        "grammar_motivations": [{"code": "GP_001", "text": "Important rule"}],
        "drills": [{"grammar_point_code": "GP_001", "items": [{"prompt": "Io ___ (mangiare)", "correct_answer": "mangio"}]}],
        "readings": [{"text": "Test reading.", "questions": ["Q1"], "answers": ["A1"]}],
        "writing": {"prompt": "Scrivi qualcosa."},
        "speakings": []
    }""")])

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = [topic_response, content_response]

    with patch("maestro.lezione.planner.get_async_client", return_value=mock_client), \
         patch("maestro.lezione.planner.get_chunks_for_refs", new_callable=AsyncMock, return_value=[]):
        await generate_lesson_background(lesson.id, 10, "", ["GP_001"])

    updated_lesson = await Lesson.get(lesson.id)
    assert updated_lesson.generating is False
    assert len(updated_lesson.activities) > 0

    drills = await GeneratedDrill.find_all().to_list()
    assert len(drills) >= 1
