"""Integration tests for activity materialization from LLM response."""

import pytest

from maestro.models import (
    GrammarPoint,
    GrammarExplanation,
    CommunicativeFunction,
    ActivityType,
    ExerciseType,
)
from maestro.lezione.materialize import materialize_activities
from maestro.lezione.schemas import (
    LessonContentResponse,
    DrillResponse,
    DrillItemResponse,
    ReadingResponse,
    SpeakingResponse,
    WritingResponse,
)


@pytest.fixture
async def grammar_gp(db):
    gp = GrammarPoint(
        code="GP_MAT",
        label="Articoli",
        cefr_level="A1",
        category="articles",
    )
    await gp.insert()
    return gp


@pytest.fixture
def grammar_explanation():
    return GrammarExplanation(explanation="Gli articoli definiti in italiano.")


@pytest.fixture
def grammar_explanation_with_spans():
    return GrammarExplanation(
        title='<span lang="en">Definite Articles: </span><span lang="it">il, la, lo</span>',
        explanation="Gli articoli definiti in italiano.",
    )


@pytest.mark.integration
async def test_materialize_grammar_activity(grammar_gp, db):
    content = LessonContentResponse()
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
async def test_materialize_single_grammar_block(grammar_gp, db):
    """Single grammar point: grammar first, then drills/reading/speaking/writing in block."""
    cf = CommunicativeFunction(
        code="CF_TEST",
        label="Test CF",
        macro_category="test",
        cefr_level="A1",
    )
    await cf.insert()

    content = LessonContentResponse(
        drills=[
            DrillResponse(
                grammar_point_code="GP_MAT",
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
        "grammar_point_code": "GP_MAT",
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
        shuffle_within_blocks=False,
    )
    # Grammar is always first; block contains drill, listening, reading, speaking, writing
    assert activities[0].type == ActivityType.GRAMMAR
    types = {a.type for a in activities}
    assert types == {
        ActivityType.GRAMMAR,
        ActivityType.LISTENING,
        ActivityType.READING,
        ActivityType.DRILL,
        ActivityType.SPEAKING,
        ActivityType.WRITING,
    }
    # Drill is tagged with the grammar point code
    drill_acts = [a for a in activities if a.type == ActivityType.DRILL]
    assert all(a.grammar_point_code == "GP_MAT" for a in drill_acts)


@pytest.mark.integration
async def test_materialize_grammar_label_field(grammar_gp, grammar_explanation, db):
    """Grammar activities get a `label` field set from the grammar point."""
    content = LessonContentResponse()
    activities = await materialize_activities(
        content=content,
        grammar_gps=[grammar_gp],
        grammar_explanations=[grammar_explanation],
        drill_specs=[],
        speaking_cfs=[],
        include_writing=False,
        reading_count=0,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
    )
    assert activities[0].grammar_label == "Articoli"


@pytest.mark.integration
async def test_materialize_explanations_length_mismatch(grammar_gp, db):
    """Mismatched grammar_explanations / grammar_gps lengths raise ValueError."""
    content = LessonContentResponse()
    with pytest.raises(ValueError, match="must match"):
        await materialize_activities(
            content=content,
            grammar_gps=[grammar_gp],
            grammar_explanations=[],  # length 0 vs 1 gp
            drill_specs=[],
            speaking_cfs=[],
            include_writing=False,
            reading_count=0,
            topic_title="Test",
            scenario_slug="test",
            cefr_level="A1",
            student_id=None,
        )


@pytest.mark.integration
async def test_materialize_drill_without_gp_code_dropped(
    grammar_gp, grammar_explanation, db
):
    """Drills that end up with no grammar_point_code are dropped from block assembly."""
    # Create a drill spec with an empty grammar_point_code
    content = LessonContentResponse(
        drills=[
            DrillResponse(
                grammar_point_code="",
                items=[DrillItemResponse(prompt="test", correct_answer="ans")],
            ),
            DrillResponse(
                grammar_point_code="GP_MAT",
                items=[DrillItemResponse(prompt="test2", correct_answer="ans2")],
            ),
        ],
    )
    specs = [
        {
            "grammar_point_code": "",
            "gp_label": "Unknown",
            "exercise_type": ExerciseType.FILL_BLANK,
            "rag_excerpt": "",
            "chunk_ref": None,
        },
        {
            "grammar_point_code": "GP_MAT",
            "gp_label": "Articoli",
            "exercise_type": ExerciseType.FILL_BLANK,
            "rag_excerpt": "",
            "chunk_ref": None,
        },
    ]
    activities = await materialize_activities(
        content=content,
        grammar_gps=[grammar_gp],
        grammar_explanations=[grammar_explanation],
        drill_specs=specs,
        speaking_cfs=[],
        include_writing=False,
        reading_count=0,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
        shuffle_within_blocks=False,
    )
    # Grammar + 1 valid drill (the empty-code drill is dropped)
    drill_acts = [a for a in activities if a.type == ActivityType.DRILL]
    assert len(drill_acts) == 1
    assert drill_acts[0].grammar_point_code == "GP_MAT"


@pytest.mark.integration
async def test_materialize_multi_grammar_blocks(db):
    """Two grammar points produce two blocks; drills are tied to the correct GP."""
    gp1 = GrammarPoint(
        code="GP_ONE",
        label="Presente",
        cefr_level="A1",
        category="verbs",
    )
    gp2 = GrammarPoint(
        code="GP_TWO",
        label="Imperfetto",
        cefr_level="A1",
        category="verbs",
    )
    await gp1.insert()
    await gp2.insert()
    exp1 = GrammarExplanation(explanation="Il presente indicativo.")
    exp2 = GrammarExplanation(explanation="L'imperfetto indicativo.")

    content = LessonContentResponse(
        drills=[
            DrillResponse(
                grammar_point_code="GP_ONE",
                items=[DrillItemResponse(prompt="p1", correct_answer="a1")],
            ),
            DrillResponse(
                grammar_point_code="GP_ONE",
                items=[DrillItemResponse(prompt="p2", correct_answer="a2")],
            ),
            DrillResponse(
                grammar_point_code="GP_TWO",
                items=[DrillItemResponse(prompt="p3", correct_answer="a3")],
            ),
            DrillResponse(
                grammar_point_code="GP_TWO",
                items=[DrillItemResponse(prompt="p4", correct_answer="a4")],
            ),
        ],
        readings=[
            ReadingResponse(text="read1", questions=["q1"], answers=["a1"]),
            ReadingResponse(text="read2", questions=["q2"], answers=["a2"]),
        ],
        writing=WritingResponse(prompt="write it"),
    )
    specs = [
        {
            "grammar_point_code": "GP_ONE",
            "gp_label": "Presente",
            "gp_description": "desc",
            "exercise_type": ExerciseType.FILL_BLANK,
            "rag_excerpt": "",
            "chunk_ref": None,
        },
        {
            "grammar_point_code": "GP_ONE",
            "gp_label": "Presente",
            "gp_description": "desc",
            "exercise_type": ExerciseType.FILL_BLANK,
            "rag_excerpt": "",
            "chunk_ref": None,
        },
        {
            "grammar_point_code": "GP_TWO",
            "gp_label": "Imperfetto",
            "gp_description": "desc",
            "exercise_type": ExerciseType.ERROR_CORRECTION,
            "rag_excerpt": "",
            "chunk_ref": None,
        },
        {
            "grammar_point_code": "GP_TWO",
            "gp_label": "Imperfetto",
            "gp_description": "desc",
            "exercise_type": ExerciseType.ERROR_CORRECTION,
            "rag_excerpt": "",
            "chunk_ref": None,
        },
    ]
    activities = await materialize_activities(
        content=content,
        grammar_gps=[gp1, gp2],
        grammar_explanations=[exp1, exp2],
        drill_specs=specs,
        speaking_cfs=[],
        include_writing=True,
        reading_count=2,
        listening_count=0,
        topic_title="Test",
        scenario_slug="test",
        cefr_level="A1",
        student_id=None,
        shuffle_within_blocks=False,
    )

    # First activity must be grammar 1
    assert activities[0].type == ActivityType.GRAMMAR
    assert activities[0].grammar_point_code == "GP_ONE"

    # Find second grammar activity
    grammar_indices = [
        i for i, a in enumerate(activities) if a.type == ActivityType.GRAMMAR
    ]
    assert len(grammar_indices) == 2
    g1_idx, g2_idx = grammar_indices
    assert activities[g2_idx].grammar_point_code == "GP_TWO"

    # Drills before second grammar block belong to GP_ONE
    block1_drills = [
        a for a in activities[g1_idx + 1 : g2_idx] if a.type == ActivityType.DRILL
    ]
    assert all(a.grammar_point_code == "GP_ONE" for a in block1_drills)

    # Drills after second grammar block belong to GP_TWO
    block2_drills = [
        a for a in activities[g2_idx + 1 :] if a.type == ActivityType.DRILL
    ]
    assert all(a.grammar_point_code == "GP_TWO" for a in block2_drills)

    # Writing ends up in the last block (after g2_idx)
    writing_acts = [a for a in activities if a.type == ActivityType.WRITING]
    assert len(writing_acts) == 1
    writing_idx = activities.index(writing_acts[0])
    assert writing_idx > g2_idx


@pytest.mark.integration
async def test_materialize_grammar_title_strips_spans(
    grammar_gp, grammar_explanation_with_spans, db
):
    """Grammar activity title should have span tags stripped (issue #38)."""
    content = LessonContentResponse()
    activities = await materialize_activities(
        content=content,
        grammar_gps=[grammar_gp],
        grammar_explanations=[grammar_explanation_with_spans],
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
    assert "<span" not in activities[0].title
    assert "Definite Articles" in activities[0].title
