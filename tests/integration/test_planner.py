"""Integration tests for lezione/planner.py and lezione/selection.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from beanie import PydanticObjectId

from maestro.models import (
    CurriculumScenario,
    GrammarPoint,
    GrammarExplanation,
    CommunicativeFunction,
    GeneratedDrill,
    LearningProfile,
    Lesson,
    ScenarioProgress,
    UserVocabularyCard,
    VocabularyWord,
    LessonStatus,
)

_FAKE_STUDENT_ID = PydanticObjectId()


# ---------------------------------------------------------------------------
# selection.py tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_pick_grammar_points_prioritises_weak(db):
    """Grammar points with higher error rates should be picked first."""
    from maestro.lezione.selection import pick_grammar_points

    gp1 = GrammarPoint(
        code="GP_A", label="A", cefr_level="A1", category="test", description="A"
    )
    gp2 = GrammarPoint(
        code="GP_B", label="B", cefr_level="A1", category="test", description="B"
    )
    await gp1.insert()
    await gp2.insert()

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        grammar_error_counts={"GP_A": 5, "GP_B": 0},
        grammar_correct_counts={"GP_A": 1, "GP_B": 5},
    )

    picked = await pick_grammar_points(profile, "A1", 1)
    assert picked[0].code == "GP_A"  # higher error rate → picked first


@pytest.mark.integration
async def test_pick_grammar_points_falls_back_when_no_level_match(db):
    """When no GPs exist at the target level, fall back to all GPs."""
    from maestro.lezione.selection import pick_grammar_points

    gp = GrammarPoint(
        code="GP_B2",
        label="B2 rule",
        cefr_level="B2",
        category="test",
    )
    await gp.insert()

    picked = await pick_grammar_points(None, "A1", 1)
    assert len(picked) == 1
    assert picked[0].code == "GP_B2"


@pytest.mark.integration
async def test_pick_grammar_points_with_candidate_codes(db):
    """When candidate_codes is provided, filter to those codes."""
    from maestro.lezione.selection import pick_grammar_points

    gp1 = GrammarPoint(
        code="GP_A", label="A", cefr_level="A1", category="test", description="A"
    )
    gp2 = GrammarPoint(
        code="GP_B", label="B", cefr_level="A1", category="test", description="B"
    )
    gp3 = GrammarPoint(
        code="GP_C", label="C", cefr_level="A1", category="test", description="C"
    )
    await gp1.insert()
    await gp2.insert()
    await gp3.insert()

    picked = await pick_grammar_points(None, "A1", 2, candidate_codes=["GP_A", "GP_C"])
    codes = {g.code for g in picked}
    assert codes <= {"GP_A", "GP_C"}
    assert "GP_B" not in codes


@pytest.mark.integration
async def test_pick_comm_functions_with_candidate_codes(db):
    """When candidate_codes is provided, filter to those codes."""
    from maestro.lezione.selection import pick_comm_functions

    cf1 = CommunicativeFunction(
        code="CF_A", label="A", macro_category="test", cefr_level="A1"
    )
    cf2 = CommunicativeFunction(
        code="CF_B", label="B", macro_category="test", cefr_level="A1"
    )
    await cf1.insert()
    await cf2.insert()

    picked = await pick_comm_functions(None, "A1", 1, candidate_codes=["CF_A"])
    assert len(picked) == 1
    assert picked[0].code == "CF_A"


@pytest.mark.integration
async def test_get_due_vocab_cards_only_returns_existing(db):
    """get_due_vocab_cards should never introduce new words."""
    from maestro.lezione.selection import get_due_vocab_cards

    for i in range(10):
        await VocabularyWord(
            word=f"parola{i}", part_of_speech="s.f.", cefr_level="A1"
        ).insert()

    cards = await get_due_vocab_cards(5, student_id=_FAKE_STUDENT_ID)
    assert len(cards) == 0
    db_cards = await UserVocabularyCard.find({"student_id": _FAKE_STUDENT_ID}).to_list()
    assert len(db_cards) == 0


# ---------------------------------------------------------------------------
# pick_scenario tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_pick_scenario_prefers_unvisited(db):
    """Unvisited scenarios should be strongly preferred."""
    from maestro.lezione.selection import pick_scenario

    s1 = CurriculumScenario(
        slug="visited",
        label="V",
        description="",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=[],
        depths=["d1", "d2", "d3"],
    )
    s2 = CurriculumScenario(
        slug="unvisited",
        label="U",
        description="",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=[],
        depths=["d1", "d2", "d3"],
    )
    await s1.insert()
    await s2.insert()

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        scenario_progress={"visited": ScenarioProgress(depth=1, lesson_count=2)},
    )
    await profile.insert()

    scenario, depth = await pick_scenario(profile, "A1")
    assert scenario.slug == "unvisited"
    assert depth == 1


@pytest.mark.integration
async def test_pick_scenario_cooldown_with_naive_datetime(db):
    """last_visited as a naive datetime (as returned by MongoDB without tz_aware)
    must not crash when compared with timezone-aware utcnow()."""
    from datetime import datetime, timedelta
    from maestro.lezione.selection import pick_scenario

    s = CurriculumScenario(
        slug="recent",
        label="R",
        description="",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=[],
        depths=["d1", "d2", "d3"],
    )
    await s.insert()

    # Simulate a naive datetime as MongoDB would return without tz_aware codec
    naive_last_visited = datetime.utcnow() - timedelta(minutes=5)
    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        scenario_progress={
            "recent": ScenarioProgress(
                depth=1,
                lesson_count=1,
                last_visited=naive_last_visited,
            )
        },
    )
    await profile.insert()

    # Should not raise "can't subtract offset-naive and offset-aware datetimes"
    scenario, depth = await pick_scenario(profile, "A1")
    assert scenario.slug == "recent"


@pytest.mark.integration
async def test_pick_scenario_weak_gp_boost(db):
    """Scenarios with weak GP overlap should get a boost."""
    from maestro.lezione.selection import pick_scenario

    s1 = CurriculumScenario(
        slug="no-overlap",
        label="A",
        description="",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=["GP_X"],
        depths=["d1", "d2", "d3"],
    )
    s2 = CurriculumScenario(
        slug="weak-overlap",
        label="B",
        description="",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=["GP_WEAK1", "GP_WEAK2"],
        depths=["d1", "d2", "d3"],
    )
    await s1.insert()
    await s2.insert()

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        grammar_error_counts={"GP_WEAK1": 5, "GP_WEAK2": 5},
        grammar_correct_counts={"GP_WEAK1": 1, "GP_WEAK2": 1},
    )
    await profile.insert()

    # Both are unvisited, so weak GP overlap should be the tiebreaker
    scenario, _ = await pick_scenario(profile, "A1")
    assert scenario.slug == "weak-overlap"


# ---------------------------------------------------------------------------
# prepare_lesson_immediate tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_prepare_lesson_immediate_creates_lesson(db):
    """Should create a Lesson with generating=True; no vocab_review without due cards."""
    from maestro.lezione.planner import prepare_lesson_immediate

    profile = LearningProfile(student_id=_FAKE_STUDENT_ID, cefr_estimate="A1")
    await profile.insert()

    lesson = await prepare_lesson_immediate(20, profile, student_id=_FAKE_STUDENT_ID)
    assert lesson.status == LessonStatus.ACTIVE
    assert lesson.generating is True
    assert lesson.student_id == _FAKE_STUDENT_ID
    # No due vocab cards → no vocab_review activity
    assert len(lesson.activities) == 0


# ---------------------------------------------------------------------------
# generate_lesson_background tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_drill_materialization_creates_generated_drills(db):
    """Drill specs from LLM content should be materialized into GeneratedDrill documents."""
    from maestro.lezione.planner import generate_lesson_background

    profile = LearningProfile(student_id=_FAKE_STUDENT_ID, cefr_estimate="A1")
    await profile.insert()

    gp = GrammarPoint(
        code="GP_001",
        label="Presente",
        cefr_level="A1",
        category="verbi",
    )
    await gp.insert()
    gp.explanations = {"en": GrammarExplanation(explanation="Il presente indicativo.")}
    await gp.save()

    scenario = CurriculumScenario(
        slug="test-scenario",
        label="Test",
        description="",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=["GP_001"],
        depths=["depth 1", "depth 2", "depth 3"],
    )
    await scenario.insert()

    lesson = Lesson(
        student_id=_FAKE_STUDENT_ID,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        generating=True,
    )
    await lesson.insert()

    content_response = MagicMock(
        content=[
            MagicMock(
                text="""{
        "topic_title": "Al bar",
        "topic_description": "Ordering at a bar",
        "overview": "Test lesson",
        "grammar_motivations": [{"code": "GP_001", "text": "Important rule"}],
        "drills": [{"grammar_point_code": "GP_001", "items": [{"prompt": "Io ___ (mangiare)", "correct_answer": "mangio"}]}],
        "readings": [{"text": "Test reading.", "questions": ["Q1"], "answers": ["A1"]}],
        "writing": {"prompt": "Scrivi qualcosa."},
        "speakings": []
    }"""
            )
        ],
        model="claude-sonnet-4-6",
        usage=MagicMock(input_tokens=100, output_tokens=200),
    )

    mock_client = AsyncMock()
    mock_client.messages.create.return_value = content_response

    with (
        patch("maestro.llm.get_async_client", return_value=mock_client),
        patch(
            "maestro.lezione.planner.GrammarChunk.find_one",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await generate_lesson_background(lesson.id, 10)

    updated_lesson = await Lesson.get(lesson.id)
    assert updated_lesson.generating is False
    assert updated_lesson.scenario_slug == "test-scenario"
    assert updated_lesson.topic_title == "Al bar"
    assert len(updated_lesson.activities) > 0

    drills = await GeneratedDrill.find_all().to_list()
    assert len(drills) >= 1
    assert drills[0].scenario_slug == "test-scenario"
    assert drills[0].student_id == _FAKE_STUDENT_ID
