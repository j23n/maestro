"""Integration tests for activity materialization from LLM response."""

import pytest

from maestro.models import (
    GrammarPoint,
    CommunicativeFunction,
    ActivityType,
    ExerciseType,
)
from maestro.lezione.materialize import materialize_activities
from maestro.lezione.schemas import (
    LessonContentResponse,
    GrammarMotivation,
    DrillResponse,
    DrillItemResponse,
    ReadingResponse,
    WritingResponse,
    SpeakingResponse,
)


@pytest.fixture
async def grammar_gp(db):
    gp = GrammarPoint(
        code="GP_MAT",
        label="Articoli",
        cefr_level="A1",
        category="articles",
        description="Definite articles",
    )
    await gp.insert()
    return gp


@pytest.mark.integration
async def test_materialize_grammar_activity(grammar_gp, db):
    content = LessonContentResponse(
        grammar_motivations=[
            GrammarMotivation(code="GP_MAT", text="Articles are essential")
        ],
    )
    activities = await materialize_activities(
        content=content,
        grammar_gps=[grammar_gp],
        grammar_explanations=[None],
        drill_specs=[],
        speaking_cfs=[],
        include_writing=False,
        reading_count=0,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    assert len(activities) == 1
    assert activities[0].type == ActivityType.GRAMMAR
    assert activities[0].grammar_point_code == "GP_MAT"
    assert "Articoli" in activities[0].title
    assert activities[0].why_important == "Articles are essential"


@pytest.mark.integration
async def test_materialize_drill_creates_generated_drill(db):
    content = LessonContentResponse(
        drills=[
            DrillResponse(
                grammar_point_code="GP_DRILL",
                items=[
                    DrillItemResponse(prompt="Il ___ è bello", correct_answer="gatto"),
                    DrillItemResponse(prompt="La ___ è grande", correct_answer="casa"),
                ],
            )
        ],
    )
    spec = {
        "grammar_point_code": "GP_DRILL",
        "gp_label": "Test Drill GP",
        "gp_description": "desc",
        "exercise_type": ExerciseType.FILL_BLANK,
        "rag_excerpt": "",
        "chunk_ref": None,
    }
    activities = await materialize_activities(
        content=content,
        grammar_gps=[],
        grammar_explanations=[],
        drill_specs=[spec],
        speaking_cfs=[],
        include_writing=False,
        reading_count=0,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    assert len(activities) == 1
    assert activities[0].type == ActivityType.DRILL
    assert activities[0].drill_id is not None


@pytest.mark.integration
async def test_materialize_listening_activity(db):
    """listening_count=1 produces a LISTENING activity."""
    content = LessonContentResponse(
        readings=[
            ReadingResponse(
                text="Marco va al bar.",
                questions=["Dove va Marco?"],
                answers=["Al bar"],
            )
        ],
    )
    activities = await materialize_activities(
        content=content,
        grammar_gps=[],
        grammar_explanations=[],
        drill_specs=[],
        drill_templates_used=[],
        speaking_cfs=[],
        include_writing=False,
        reading_count=0,
        listening_count=1,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    assert len(activities) == 1
    assert activities[0].type == ActivityType.LISTENING
    assert activities[0].content == "Marco va al bar."
    assert activities[0].questions == ["Dove va Marco?"]


@pytest.mark.integration
async def test_materialize_reading_activity(db):
    """reading_count=1 (no listening) produces a plain READING activity."""
    content = LessonContentResponse(
        readings=[
            ReadingResponse(
                text="Marco va al bar.",
                questions=["Dove va Marco?"],
                answers=["Al bar"],
            )
        ],
    )
    activities = await materialize_activities(
        content=content,
        grammar_gps=[],
        grammar_explanations=[],
        drill_specs=[],
        speaking_cfs=[],
        include_writing=False,
        reading_count=1,
        listening_count=0,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    assert len(activities) == 1
    assert activities[0].type == ActivityType.READING
    assert activities[0].content == "Marco va al bar."
    assert activities[0].questions == ["Dove va Marco?"]


@pytest.mark.integration
async def test_materialize_mixed_listening_and_reading(db):
    """listening_count=1 + reading_count=1 → LISTENING first, then READING."""
    content = LessonContentResponse(
        readings=[
            ReadingResponse(text="Ascolto.", questions=["Capito?"], answers=["Sì"]),
            ReadingResponse(text="Lettura.", questions=["Letto?"], answers=["Sì"]),
        ],
    )
    activities = await materialize_activities(
        content=content,
        grammar_gps=[],
        grammar_explanations=[],
        drill_specs=[],
        drill_templates_used=[],
        speaking_cfs=[],
        include_writing=False,
        reading_count=1,
        listening_count=1,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    assert len(activities) == 2
    assert activities[0].type == ActivityType.LISTENING
    assert activities[0].content == "Ascolto."
    assert activities[1].type == ActivityType.READING
    assert activities[1].content == "Lettura."


@pytest.mark.integration
async def test_materialize_writing_activity(db):
    content = LessonContentResponse(
        writing=WritingResponse(prompt="Descrivi la tua giornata."),
    )
    activities = await materialize_activities(
        content=content,
        grammar_gps=[],
        grammar_explanations=[],
        drill_specs=[],
        speaking_cfs=[],
        include_writing=True,
        reading_count=0,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    assert len(activities) == 1
    assert activities[0].type == ActivityType.WRITING
    assert "giornata" in activities[0].content


@pytest.mark.integration
async def test_materialize_pedagogical_order(grammar_gp, db):
    """Activities follow: grammar → listening → reading → drill → speaking → writing."""
    cf = CommunicativeFunction(
        code="CF_TEST",
        label="Test CF",
        macro_category="test",
        cefr_level="A1",
    )
    await cf.insert()

    content = LessonContentResponse(
        grammar_motivations=[GrammarMotivation(code="GP_MAT", text="motivation")],
        drills=[
            DrillResponse(
                grammar_point_code="GP_DRILL",
                items=[DrillItemResponse(prompt="test", correct_answer="ans")],
            )
        ],
        readings=[
            ReadingResponse(text="listen", questions=["q"], answers=["a"]),
            ReadingResponse(text="read", questions=["q2"], answers=["a2"]),
        ],
        writing=WritingResponse(prompt="write"),
        speakings=[SpeakingResponse(prompt="speak")],
    )
    spec = {
        "grammar_point_code": "GP_DRILL",
        "gp_label": "Label",
        "gp_description": "desc",
        "exercise_type": ExerciseType.FILL_BLANK,
        "rag_excerpt": "",
        "chunk_ref": None,
    }
    activities = await materialize_activities(
        content=content,
        grammar_gps=[grammar_gp],
        grammar_explanations=[None],
        drill_specs=[spec],
        speaking_cfs=[cf],
        include_writing=True,
        reading_count=1,
        listening_count=1,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    types = [a.type for a in activities]
    assert types == [
        ActivityType.GRAMMAR,
        ActivityType.LISTENING,
        ActivityType.READING,
        ActivityType.DRILL,
        ActivityType.SPEAKING,
        ActivityType.WRITING,
    ]
