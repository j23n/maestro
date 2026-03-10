"""End-to-end integration test: submit activities via routes, verify events + profile."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from maestro.models import (
    GrammarPoint,
    GeneratedDrill,
    DrillItem,
    LearningEvent,
    LearningProfile,
    Lesson,
    LessonActivity,
    ActivityType,
    ActivityStatus,
    LessonStatus,
    ExerciseType,
)
from maestro.utils import utcnow


@pytest.fixture
async def a1_lesson(db, student):
    """An A1 lesson with drill + writing + reading, all wired up."""
    gp_a = GrammarPoint(
        code="GP_A",
        label="Presente indicativo",
        cefr_level="A1",
        category="verbs",
        description="",
    )
    gp_b = GrammarPoint(
        code="GP_B",
        label="Articoli determinativi",
        cefr_level="A1",
        category="articles",
        description="",
    )
    gp_c = GrammarPoint(
        code="GP_C",
        label="Plurali regolari",
        cefr_level="A1",
        category="nouns",
        description="",
    )
    await gp_a.insert()
    await gp_b.insert()
    await gp_c.insert()

    drill = GeneratedDrill(
        student_id=student.id,
        grammar_point_code="GP_A",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="Fill in the blank.",
        items=[DrillItem(prompt="Io ___ al parco.", correct_answer="vado")],
        scenario_slug="test-scenario",
    )
    await drill.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=15,
        started_at=utcnow(),
        generating=False,
        cefr_at_start="A1",
        scenario_slug="test-scenario",
        scenario_depth=1,
        activities=[
            LessonActivity(
                type=ActivityType.DRILL,
                title="Drill 1",
                description="",
                duration_minutes=3,
                status=ActivityStatus.ACTIVE,
                drill_id=drill.id,
            ),
            LessonActivity(
                type=ActivityType.WRITING,
                title="Scrittura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.PENDING,
                content="Descrivi la tua giornata.",
            ),
            LessonActivity(
                type=ActivityType.READING,
                title="Lettura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.PENDING,
                content="Il gatto dorme sul divano.",
                questions=["Dove dorme il gatto?"],
                correct_answers=["Sul divano"],
            ),
        ],
        current_index=0,
    )
    await lesson.insert()
    return lesson, drill


@pytest.mark.integration
async def test_full_lesson_events_match_answers(
    test_app, a1_lesson, mock_scorer_client
):
    """Submit all activities via routes, verify LearningEvents match the answers given."""
    from maestro import taxonomy

    lesson, drill = a1_lesson
    gps = await GrammarPoint.find_all().to_list()
    taxonomy.seed(gps=gps, cfs=[])

    # --- 1. Drill submit (correct) ---
    # score_attempt returns a LearningEvent with GP_A correct
    drill_event = LearningEvent(
        student_id=lesson.student_id,
        grammar_correct=["GP_A"],
        grammar_errors=[],
    )
    with (
        patch(
            "maestro.routes.lezione.score_attempt", new_callable=AsyncMock
        ) as mock_score,
        patch(
            "maestro.routes.lezione.discover",
            new_callable=AsyncMock,
            return_value="annotated",
        ),
    ):
        mock_score.return_value = (
            True,
            drill_event,
            {"items": [], "correct_count": 1, "total": 1},
            [],
        )
        resp = test_app.post(
            f"/lezione/{lesson.id}/activity/0/drill-submit", data={"answers": "vado"}
        )
    assert resp.status_code == 200

    # --- 2. Writing submit (GP_B correct, GP_C error) ---
    writing_feedback = {
        "objective_correct": True,
        "objective_note": "",
        "grammar_errors": [],
        "tips": [],
        "grammar_correct_codes": ["GP_B"],
        "grammar_error_codes": ["GP_C"],
    }
    with patch(
        "maestro.routes.lezione.generate_writing_feedback",
        new_callable=AsyncMock,
        return_value=writing_feedback,
    ):
        resp = test_app.post(
            f"/lezione/{lesson.id}/activity/1/writing-submit",
            data={"answer": "Oggi ho mangiato la pizza."},
        )
    assert resp.status_code == 200

    # --- 3. Reading submit (GP_B correct) ---
    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='[{"objective_correct": true, "objective_note": "Correct", "grammar_errors": [], "tips": [], "grammar_correct_codes": ["GP_B"], "grammar_error_codes": []}]'
            )
        ]
    )
    resp = test_app.post(
        f"/lezione/{lesson.id}/activity/2/reading-submit",
        data={"answers": "Sul divano"},
    )
    assert resp.status_code == 200

    # --- Verify lesson is completed ---
    refreshed = await Lesson.get(lesson.id)
    assert refreshed.status == LessonStatus.COMPLETED

    # --- Verify LearningEvents ---
    events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()
    # Should have exactly 3 per-activity events (no summary yet)
    assert len(events) == 3

    ev_by_idx = {ev.activity_index: ev for ev in events}

    # Drill event (idx=0): GP_A correct
    assert ev_by_idx[0].activity_type == "drill"
    assert "GP_A" in ev_by_idx[0].grammar_correct
    assert ev_by_idx[0].grammar_errors == []
    assert ev_by_idx[0].student_text == "vado"

    # Writing event (idx=1): GP_B correct, GP_C error
    assert ev_by_idx[1].activity_type == "writing"
    assert "GP_B" in ev_by_idx[1].grammar_correct
    assert "GP_C" in ev_by_idx[1].grammar_errors
    assert ev_by_idx[1].student_text == "Oggi ho mangiato la pizza."

    # Reading event (idx=2): GP_B correct
    assert ev_by_idx[2].activity_type == "reading"
    assert "GP_B" in ev_by_idx[2].grammar_correct
    assert ev_by_idx[2].grammar_errors == []
    assert "Sul divano" in ev_by_idx[2].student_text


@pytest.mark.integration
async def test_full_lesson_profile_updated_after_analysis(
    test_app, a1_lesson, mock_scorer_client
):
    """After analyze_lesson runs, the profile should reflect aggregated GP counts."""
    from maestro import taxonomy
    from maestro.learning.lesson_analyzer import analyze_lesson

    lesson, drill = a1_lesson
    gps = await GrammarPoint.find_all().to_list()
    taxonomy.seed(gps=gps, cfs=[])

    # Create a LearningProfile for the student
    profile = LearningProfile(student_id=lesson.student_id, cefr_estimate="A1")
    await profile.insert()

    # --- Submit all 3 activities (same as above) ---
    drill_event = LearningEvent(
        student_id=lesson.student_id,
        grammar_correct=["GP_A"],
        grammar_errors=[],
    )
    with (
        patch(
            "maestro.routes.lezione.score_attempt", new_callable=AsyncMock
        ) as mock_score,
        patch(
            "maestro.routes.lezione.discover",
            new_callable=AsyncMock,
            return_value="annotated",
        ),
    ):
        mock_score.return_value = (
            True,
            drill_event,
            {"items": [], "correct_count": 1, "total": 1},
            [],
        )
        test_app.post(
            f"/lezione/{lesson.id}/activity/0/drill-submit", data={"answers": "vado"}
        )

    writing_feedback = {
        "objective_correct": True,
        "objective_note": "",
        "grammar_errors": [],
        "tips": [],
        "grammar_correct_codes": ["GP_B"],
        "grammar_error_codes": ["GP_C"],
    }
    with patch(
        "maestro.routes.lezione.generate_writing_feedback",
        new_callable=AsyncMock,
        return_value=writing_feedback,
    ):
        test_app.post(
            f"/lezione/{lesson.id}/activity/1/writing-submit",
            data={"answer": "Oggi ho mangiato la pizza."},
        )

    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='[{"objective_correct": true, "objective_note": "Correct", "grammar_errors": [], "tips": [], "grammar_correct_codes": ["GP_B"], "grammar_error_codes": []}]'
            )
        ]
    )
    test_app.post(
        f"/lezione/{lesson.id}/activity/2/reading-submit",
        data={"answers": "Sul divano"},
    )

    # --- Run analyze_lesson (normally background, here direct) ---
    refreshed_lesson = await Lesson.get(lesson.id)
    assert refreshed_lesson.status == LessonStatus.COMPLETED

    # Mock the CF analysis LLM call (no CFs to detect)
    cf_response = MagicMock(content=[MagicMock(text='{"categories": []}')])
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = cf_response

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        await analyze_lesson(refreshed_lesson)

    # --- Verify profile ---
    updated_profile = await LearningProfile.find_one({"student_id": lesson.student_id})

    # GP_A: 1 correct (from drill)
    assert updated_profile.grammar_correct_counts.get("GP_A", 0) == 1
    assert updated_profile.grammar_error_counts.get("GP_A", 0) == 0

    # GP_B: 2 correct (writing + reading), count-preserving across activities
    assert updated_profile.grammar_correct_counts.get("GP_B", 0) == 2

    # GP_C: 1 error (from writing)
    assert updated_profile.grammar_error_counts.get("GP_C", 0) == 1
    assert updated_profile.grammar_correct_counts.get("GP_C", 0) == 0

    # recent_outcomes should reflect the counts
    assert updated_profile.grammar_recent_outcomes.get("GP_A") == [True]
    assert updated_profile.grammar_recent_outcomes.get("GP_B") == [True, True]
    assert updated_profile.grammar_recent_outcomes.get("GP_C") == [False]

    # Summary event should exist (activity_type=None)
    all_events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()
    summary_events = [e for e in all_events if e.activity_type is None]
    assert len(summary_events) == 1
    summary = summary_events[0]
    # Summary GP_A: 1, GP_B: 2 (count-preserving)
    assert summary.grammar_correct.count("GP_A") == 1
    assert summary.grammar_correct.count("GP_B") == 2
    assert summary.grammar_errors.count("GP_C") == 1
