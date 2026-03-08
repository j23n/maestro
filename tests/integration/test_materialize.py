"""Integration tests for activity materialization from LLM response."""

import pytest

from maestro.models import (
    GrammarPoint,
    DrillTemplate,
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


@pytest.fixture
async def drill_template(db):
    t = DrillTemplate(
        grammar_point_code="GP_DRILL",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
    )
    await t.insert()
    return t


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
        drill_templates_used=[],
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
async def test_materialize_drill_creates_generated_drill(drill_template, db):
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
        drill_templates_used=[drill_template],
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
async def test_materialize_reading_activity(db):
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
        reading_count=1,
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
async def test_materialize_writing_activity(db):
    content = LessonContentResponse(
        writing=WritingResponse(prompt="Descrivi la tua giornata."),
    )
    activities = await materialize_activities(
        content=content,
        grammar_gps=[],
        grammar_explanations=[],
        drill_specs=[],
        drill_templates_used=[],
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
async def test_materialize_pedagogical_order(grammar_gp, drill_template, db):
    """Activities should follow: grammar → reading → drill → speaking → writing."""
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
        readings=[ReadingResponse(text="text", questions=["q"], answers=["a"])],
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
        drill_templates_used=[drill_template],
        speaking_cfs=[cf],
        include_writing=True,
        reading_count=1,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    types = [a.type for a in activities]
    assert types == [
        ActivityType.GRAMMAR,
        ActivityType.READING,
        ActivityType.DRILL,
        ActivityType.SPEAKING,
        ActivityType.WRITING,
    ]
