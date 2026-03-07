"""Integration tests for _advance_lesson, _collect_free_texts, _collect_drill_gp_outcomes."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from beanie import PydanticObjectId

from maestro.models import (
    Lesson,
    LessonActivity,
    GeneratedDrill,
    DrillTemplate,
    DrillItem,
    GrammarPoint,
    LearningProfile,
    ActivityType,
    ActivityStatus,
    LessonStatus,
    ExerciseType,
)
from maestro.utils import utcnow

_FAKE_STUDENT_ID = PydanticObjectId()


def _make_lesson(activities: list[LessonActivity], generating: bool = False) -> Lesson:
    return Lesson(
        student_id=_FAKE_STUDENT_ID,
        status=LessonStatus.ACTIVE,
        duration_minutes=20,
        activities=activities,
        current_index=0,
        generating=generating,
        started_at=None,
    )


@pytest.mark.integration
async def test_advance_lesson_marks_current_completed(db):
    from maestro.lezione.service import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
        LessonActivity(type=ActivityType.DRILL, title="D1", description="", duration_minutes=3, status=ActivityStatus.PENDING),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    await _advance_lesson(lesson, 0)
    assert lesson.activities[0].status == ActivityStatus.COMPLETED

    # Verify DB was updated atomically
    refreshed = await Lesson.get(lesson.id)
    assert refreshed.activities[0].status == ActivityStatus.COMPLETED
    assert refreshed.activities[1].status == ActivityStatus.ACTIVE


@pytest.mark.integration
async def test_advance_lesson_activates_next_pending(db):
    from maestro.lezione.service import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
        LessonActivity(type=ActivityType.DRILL, title="D1", description="", duration_minutes=3, status=ActivityStatus.PENDING),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    redirect = await _advance_lesson(lesson, 0)
    assert lesson.activities[1].status == ActivityStatus.ACTIVE
    assert "/activity/1" in redirect


@pytest.mark.integration
async def test_advance_lesson_skip_does_not_mark_completed(db):
    from maestro.lezione.service import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
        LessonActivity(type=ActivityType.DRILL, title="D1", description="", duration_minutes=3, status=ActivityStatus.PENDING),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    await _advance_lesson(lesson, 0, skip=True)
    assert lesson.activities[0].status != ActivityStatus.COMPLETED


@pytest.mark.integration
async def test_advance_lesson_generating_redirect(db):
    from maestro.lezione.service import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
    ]
    lesson = _make_lesson(activities, generating=True)
    await lesson.insert()

    redirect = await _advance_lesson(lesson, 0)
    assert "generating" in redirect


@pytest.mark.integration
async def test_advance_lesson_all_done_marks_completed(db):
    from maestro.lezione.service import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
    ]
    lesson = _make_lesson(activities, generating=False)
    await lesson.insert()

    redirect = await _advance_lesson(lesson, 0)
    assert lesson.status == LessonStatus.COMPLETED
    assert "complete" in redirect

    # Verify DB was updated atomically
    refreshed = await Lesson.get(lesson.id)
    assert refreshed.status == LessonStatus.COMPLETED
    assert refreshed.completed_at is not None


@pytest.mark.integration
async def test_advance_lesson_persists_result(db):
    """The result parameter should be atomically persisted on the activity."""
    from maestro.lezione.service import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(type=ActivityType.DRILL, title="D1", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
        LessonActivity(type=ActivityType.GRAMMAR, title="G1", description="", duration_minutes=3, status=ActivityStatus.PENDING),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    result = {"correct": True, "student_answer": "gatto"}
    await _advance_lesson(lesson, 0, result=result)

    # Verify in-memory
    assert lesson.activities[0].result == result

    # Verify DB
    refreshed = await Lesson.get(lesson.id)
    assert refreshed.activities[0].result == result
    assert refreshed.activities[0].status == ActivityStatus.COMPLETED


@pytest.mark.integration
async def test_advance_lesson_generating_persists_atomically(db):
    """When generating=True, advance should persist status + current_index + result."""
    from maestro.lezione.service import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(type=ActivityType.DRILL, title="D1", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
    ]
    lesson = _make_lesson(activities, generating=True)
    await lesson.insert()

    result = {"correct": True, "student_answer": "gatto"}
    redirect = await _advance_lesson(lesson, 0, result=result)
    assert "generating" in redirect

    refreshed = await Lesson.get(lesson.id)
    assert refreshed.activities[0].status == ActivityStatus.COMPLETED
    assert refreshed.activities[0].result == result
    assert refreshed.current_index == 1


@pytest.mark.integration
async def test_advance_lesson_completion_persists_all_fields(db):
    """When all done (no generating), status/completed_at/result all persist atomically."""
    from maestro.lezione.service import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(type=ActivityType.DRILL, title="D1", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
    ]
    lesson = _make_lesson(activities, generating=False)
    await lesson.insert()

    result = {"correct": False, "student_answer": "cane"}
    redirect = await _advance_lesson(lesson, 0, result=result)
    assert "complete" in redirect

    refreshed = await Lesson.get(lesson.id)
    assert refreshed.status == LessonStatus.COMPLETED
    assert refreshed.completed_at is not None
    assert refreshed.activities[0].status == ActivityStatus.COMPLETED
    assert refreshed.activities[0].result == result


@pytest.mark.integration
async def test_collect_free_texts_writing(db):
    from maestro.learning.lesson_analyzer import _collect_free_texts

    activities = [
        LessonActivity(
            type=ActivityType.WRITING,
            title="W",
            description="",
            duration_minutes=5,
            status=ActivityStatus.COMPLETED,
            result={"student_answer": "Ho scritto qualcosa."},
        ),
    ]
    lesson = _make_lesson(activities)
    texts = _collect_free_texts(lesson)
    assert "Ho scritto qualcosa." in texts


@pytest.mark.integration
async def test_collect_free_texts_pending_skipped(db):
    from maestro.learning.lesson_analyzer import _collect_free_texts

    activities = [
        LessonActivity(
            type=ActivityType.WRITING,
            title="W",
            description="",
            duration_minutes=5,
            status=ActivityStatus.PENDING,  # not completed
            result=None,
        ),
    ]
    lesson = _make_lesson(activities)
    texts = _collect_free_texts(lesson)
    assert texts == []


@pytest.mark.integration
async def test_collect_free_texts_reading_joined(db):
    from maestro.learning.lesson_analyzer import _collect_free_texts

    activities = [
        LessonActivity(
            type=ActivityType.READING,
            title="R",
            description="",
            duration_minutes=5,
            status=ActivityStatus.COMPLETED,
            result={"student_answers": ["Risposta uno", "Risposta due"]},
        ),
    ]
    lesson = _make_lesson(activities)
    texts = _collect_free_texts(lesson)
    assert len(texts) == 1
    assert "Risposta uno" in texts[0]
    assert "Risposta due" in texts[0]
    assert " | " in texts[0]


@pytest.mark.integration
async def test_collect_free_texts_drill_answer_included(db):
    from maestro.learning.lesson_analyzer import _collect_free_texts

    activities = [
        LessonActivity(
            type=ActivityType.DRILL,
            title="D",
            description="",
            duration_minutes=3,
            status=ActivityStatus.COMPLETED,
            result={"student_answer": "sono andato"},
        ),
    ]
    lesson = _make_lesson(activities)
    texts = _collect_free_texts(lesson)
    assert "sono andato" in texts


@pytest.mark.integration
async def test_collect_drill_gp_outcomes_all_correct(db):
    from maestro.learning.lesson_analyzer import _collect_drill_gp_outcomes

    # Create a real DrillTemplate and GeneratedDrill
    template = DrillTemplate(
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
    )
    await template.insert()

    drill = GeneratedDrill(
        template=template,
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="",
        scenario_slug="test",
    )
    await drill.insert()

    activities = [
        LessonActivity(
            type=ActivityType.DRILL,
            title="D",
            description="",
            duration_minutes=3,
            status=ActivityStatus.COMPLETED,
            drill_id=drill.id,
            result={"correct": True},
        ),
    ]
    lesson = _make_lesson(activities)

    correct, errors, all_codes = await _collect_drill_gp_outcomes(lesson)
    assert "GP_001" in correct
    assert "GP_001" not in errors
    assert "GP_001" in all_codes


@pytest.mark.integration
async def test_collect_drill_gp_outcomes_any_error(db):
    from maestro.learning.lesson_analyzer import _collect_drill_gp_outcomes

    template = DrillTemplate(
        grammar_point_code="GP_002",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
    )
    await template.insert()

    drill = GeneratedDrill(
        template=template,
        grammar_point_code="GP_002",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="",
        scenario_slug="test",
    )
    await drill.insert()

    activities = [
        LessonActivity(
            type=ActivityType.DRILL,
            title="D",
            description="",
            duration_minutes=3,
            status=ActivityStatus.COMPLETED,
            drill_id=drill.id,
            result={"correct": False},
        ),
    ]
    lesson = _make_lesson(activities)

    correct, errors, all_codes = await _collect_drill_gp_outcomes(lesson)
    assert "GP_002" in errors
    assert "GP_002" not in correct


@pytest.mark.integration
async def test_collect_drill_gp_outcomes_no_result(db):
    from maestro.learning.lesson_analyzer import _collect_drill_gp_outcomes

    template = DrillTemplate(
        grammar_point_code="GP_003",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
    )
    await template.insert()

    drill = GeneratedDrill(
        template=template,
        grammar_point_code="GP_003",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="",
        scenario_slug="test",
    )
    await drill.insert()

    activities = [
        LessonActivity(
            type=ActivityType.DRILL,
            title="D",
            description="",
            duration_minutes=3,
            status=ActivityStatus.PENDING,
            drill_id=drill.id,
            result=None,  # no result yet
        ),
    ]
    lesson = _make_lesson(activities)

    correct, errors, all_codes = await _collect_drill_gp_outcomes(lesson)
    assert "GP_003" not in correct
    assert "GP_003" not in errors
    assert "GP_003" in all_codes  # still in all_codes


# ---------------------------------------------------------------------------
# Lesson completion flow tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def completed_lesson(db):
    """A lesson with mixed drill results — some correct, some incorrect, plus writing."""
    gp_ok = GrammarPoint(code="GP_OK", label="Presente", cefr_level="A1", category="test", description="Ok")
    gp_bad = GrammarPoint(code="GP_BAD", label="Passato", cefr_level="A1", category="test", description="Bad")
    await gp_ok.insert()
    await gp_bad.insert()

    template = DrillTemplate(grammar_point_code="GP_OK", cefr_level="A1", exercise_type=ExerciseType.FILL_BLANK)
    await template.insert()

    drill_ok = GeneratedDrill(
        template=template, grammar_point_code="GP_OK", cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK, prompt="", scenario_slug="test",
    )
    drill_bad = GeneratedDrill(
        template=template, grammar_point_code="GP_BAD", cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK, prompt="", scenario_slug="test",
    )
    await drill_ok.insert()
    await drill_bad.insert()

    lesson = Lesson(
        student_id=_FAKE_STUDENT_ID,
        status=LessonStatus.COMPLETED,
        duration_minutes=10,
        started_at=utcnow(),
        completed_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.DRILL, title="D1", description="", duration_minutes=3,
                status=ActivityStatus.COMPLETED, drill_id=drill_ok.id, result={"correct": True},
            ),
            LessonActivity(
                type=ActivityType.DRILL, title="D2", description="", duration_minutes=3,
                status=ActivityStatus.COMPLETED, drill_id=drill_bad.id, result={"correct": False},
            ),
            LessonActivity(
                type=ActivityType.WRITING, title="W", description="", duration_minutes=5,
                status=ActivityStatus.COMPLETED, result={"student_answer": "Ho scritto."},
            ),
        ],
        current_index=2,
    )
    await lesson.insert()
    return lesson


@pytest.mark.integration
async def test_get_weak_grammar_points(db, completed_lesson):
    """Should return grammar points for drills the student got wrong."""
    from maestro.lezione.service import get_weak_grammar_points

    weak = await get_weak_grammar_points(completed_lesson)
    codes = {gp.code for gp in weak}
    assert "GP_BAD" in codes
    assert "GP_OK" not in codes


@pytest.mark.integration
async def test_generate_lesson_feedback_returns_string(db, completed_lesson):
    """Feedback should return a non-empty string."""
    from maestro.lezione.service import generate_lesson_feedback

    mock_response = MagicMock(content=[MagicMock(text="Great work on present tense drills!")])
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response

    with patch("maestro.lezione.service.get_async_client", return_value=mock_client):
        feedback = await generate_lesson_feedback(completed_lesson, [])

    assert isinstance(feedback, str)
    assert len(feedback) > 0


@pytest.mark.integration
async def test_analyze_lesson_creates_learning_event(db, completed_lesson):
    """analyze_lesson should create a LearningEvent and update the profile."""
    from maestro.learning.lesson_analyzer import analyze_lesson
    from maestro.models import LearningEvent
    from maestro import taxonomy

    gps = await GrammarPoint.find_all().to_list()
    taxonomy.seed(gps=gps, cfs=[])

    profile = LearningProfile(student_id=_FAKE_STUDENT_ID, cefr_estimate="A1")
    await profile.insert()

    gp_response = MagicMock(content=[MagicMock(text='{"grammar_correct": [], "grammar_errors": []}')])
    cf_stage1_response = MagicMock(content=[MagicMock(text='{"categories": []}')])

    mock_client = AsyncMock()
    mock_client.messages.create.side_effect = [gp_response, cf_stage1_response]

    with patch("maestro.learning.lesson_analyzer.get_async_client", return_value=mock_client):
        await analyze_lesson(completed_lesson)

    events = await LearningEvent.find_all().to_list()
    assert len(events) == 1
    assert "GP_OK" in events[0].grammar_correct
    assert "GP_BAD" in events[0].grammar_errors
