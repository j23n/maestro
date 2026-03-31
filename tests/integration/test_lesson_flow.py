"""Integration tests for advance_lesson, _collect_activity_events, lesson completion flow."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from beanie import PydanticObjectId

from maestro.models import (
    Lesson,
    LessonActivity,
    LearningEvent,
    GeneratedDrill,
    GrammarPoint,
    LearningProfile,
    LanguageProgress,
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
    from maestro.lessons.lifecycle import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(
            type=ActivityType.GRAMMAR,
            title="G1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.ACTIVE,
        ),
        LessonActivity(
            type=ActivityType.DRILL,
            title="D1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.PENDING,
        ),
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
    from maestro.lessons.lifecycle import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(
            type=ActivityType.GRAMMAR,
            title="G1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.ACTIVE,
        ),
        LessonActivity(
            type=ActivityType.DRILL,
            title="D1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.PENDING,
        ),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    redirect = await _advance_lesson(lesson, 0)
    assert lesson.activities[1].status == ActivityStatus.ACTIVE
    assert "/activity/1" in redirect


@pytest.mark.integration
async def test_advance_lesson_skip_does_not_mark_completed(db):
    from maestro.lessons.lifecycle import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(
            type=ActivityType.GRAMMAR,
            title="G1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.ACTIVE,
        ),
        LessonActivity(
            type=ActivityType.DRILL,
            title="D1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.PENDING,
        ),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    await _advance_lesson(lesson, 0, skip=True)
    assert lesson.activities[0].status != ActivityStatus.COMPLETED


@pytest.mark.integration
async def test_advance_lesson_generating_redirect(db):
    from maestro.lessons.lifecycle import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(
            type=ActivityType.GRAMMAR,
            title="G1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.ACTIVE,
        ),
    ]
    lesson = _make_lesson(activities, generating=True)
    await lesson.insert()

    redirect = await _advance_lesson(lesson, 0)
    assert "generating" in redirect


@pytest.mark.integration
async def test_advance_lesson_all_done_marks_completed(db):
    from maestro.lessons.lifecycle import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(
            type=ActivityType.GRAMMAR,
            title="G1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.ACTIVE,
        ),
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
    from maestro.lessons.lifecycle import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(
            type=ActivityType.DRILL,
            title="D1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.ACTIVE,
        ),
        LessonActivity(
            type=ActivityType.GRAMMAR,
            title="G1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.PENDING,
        ),
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
    from maestro.lessons.lifecycle import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(
            type=ActivityType.DRILL,
            title="D1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.ACTIVE,
        ),
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
    from maestro.lessons.lifecycle import advance_lesson as _advance_lesson

    activities = [
        LessonActivity(
            type=ActivityType.DRILL,
            title="D1",
            description="",
            duration_minutes=3,
            status=ActivityStatus.ACTIVE,
        ),
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
async def test_collect_activity_events_aggregates_gp_codes(db):
    """Events for a lesson should be aggregated by GP codes."""
    from maestro.learning.lesson_analyzer import _collect_activity_events

    lesson = _make_lesson([])
    await lesson.insert()

    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="drill",
        student_text="sono andato",
        grammar_correct=["GP_001"],
        grammar_errors=["GP_002"],
    ).insert()
    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="writing",
        student_text="Ho scritto qualcosa.",
        grammar_correct=["GP_001", "GP_003"],
        grammar_errors=[],
    ).insert()

    correct, errors, combined = await _collect_activity_events(lesson)
    assert "GP_001" in correct
    assert "GP_003" in correct
    assert "GP_002" in errors
    assert "sono andato" in combined
    assert "Ho scritto qualcosa." in combined


@pytest.mark.integration
async def test_collect_activity_events_no_events(db):
    """No events → empty results."""
    from maestro.learning.lesson_analyzer import _collect_activity_events

    lesson = _make_lesson([])
    await lesson.insert()

    correct, errors, combined = await _collect_activity_events(lesson)
    assert correct == []
    assert errors == []
    assert combined == ""


@pytest.mark.integration
async def test_collect_activity_events_deduplicates_codes(db):
    """Same GP code from multiple events should be deduplicated per-lesson."""
    from maestro.learning.lesson_analyzer import _collect_activity_events

    lesson = _make_lesson([])
    await lesson.insert()

    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="drill",
        grammar_correct=["GP_001"],
    ).insert()
    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="drill",
        grammar_correct=["GP_001"],
    ).insert()

    correct, errors, _ = await _collect_activity_events(lesson)
    assert correct.count("GP_001") == 1  # deduplicated


# ---------------------------------------------------------------------------
# Lesson completion flow tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def completed_lesson(db):
    """A lesson with mixed drill results — some correct, some incorrect, plus writing.

    Per-activity LearningEvents are also created (as the routes would do).
    """
    gp_ok = GrammarPoint(
        code="GP_OK",
        label="Presente",
        cefr_level="A1",
        category="test",
        description="Ok",
    )
    gp_bad = GrammarPoint(
        code="GP_BAD",
        label="Passato",
        cefr_level="A1",
        category="test",
        description="Bad",
    )
    await gp_ok.insert()
    await gp_bad.insert()

    drill_ok = GeneratedDrill(
        grammar_point_code="GP_OK",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="",
        scenario_slug="test",
    )
    drill_bad = GeneratedDrill(
        grammar_point_code="GP_BAD",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="",
        scenario_slug="test",
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
                type=ActivityType.DRILL,
                title="D1",
                description="",
                duration_minutes=3,
                status=ActivityStatus.COMPLETED,
                drill_id=drill_ok.id,
                result={"correct": True},
            ),
            LessonActivity(
                type=ActivityType.DRILL,
                title="D2",
                description="",
                duration_minutes=3,
                status=ActivityStatus.COMPLETED,
                drill_id=drill_bad.id,
                result={"correct": False},
            ),
            LessonActivity(
                type=ActivityType.WRITING,
                title="W",
                description="",
                duration_minutes=5,
                status=ActivityStatus.COMPLETED,
                result={"student_answer": "Ho scritto."},
            ),
        ],
        current_index=2,
    )
    await lesson.insert()

    # Create per-activity LearningEvents (as the routes would do)
    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="drill",
        activity_index=0,
        student_text="gatto",
        grammar_correct=["GP_OK"],
        grammar_errors=[],
    ).insert()
    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="drill",
        activity_index=1,
        student_text="sbagliato",
        grammar_correct=[],
        grammar_errors=["GP_BAD"],
    ).insert()
    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="writing",
        activity_index=2,
        student_text="Ho scritto.",
        grammar_correct=[],
        grammar_errors=[],
    ).insert()

    return lesson


@pytest.mark.integration
async def test_get_weak_grammar_points(db, completed_lesson):
    """Should return grammar points for drills the student got wrong."""
    from maestro.lessons.lifecycle import get_weak_grammar_points

    weak = await get_weak_grammar_points(completed_lesson)
    codes = {gp.code for gp in weak}
    assert "GP_BAD" in codes
    assert "GP_OK" not in codes


@pytest.mark.integration
async def test_generate_lesson_feedback_returns_string(db, completed_lesson):
    """Feedback should return a non-empty string."""
    from maestro.lessons.lifecycle import generate_lesson_feedback

    mock_response = MagicMock(
        content=[MagicMock(text="Great work on present tense drills!")]
    )
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        feedback = await generate_lesson_feedback(completed_lesson, [])

    assert isinstance(feedback, str)
    assert len(feedback) > 0


@pytest.mark.integration
async def test_generate_lesson_feedback_uses_prefetched_events(db):
    """Passing events avoids a DB query and groups errors by activity index."""
    from maestro.lessons.lifecycle import generate_lesson_feedback

    lesson = Lesson(
        student_id=_FAKE_STUDENT_ID,
        status=LessonStatus.COMPLETED,
        duration_minutes=10,
        started_at=utcnow(),
        completed_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.WRITING,
                title="W1",
                description="",
                duration_minutes=5,
                status=ActivityStatus.COMPLETED,
            ),
            LessonActivity(
                type=ActivityType.WRITING,
                title="W2",
                description="",
                duration_minutes=5,
                status=ActivityStatus.COMPLETED,
            ),
        ],
        current_index=1,
    )
    await lesson.insert()

    # W1 has no errors, W2 has 1 error — must not conflate
    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="writing",
        activity_index=0,
        grammar_correct=["GP_OK"],
        grammar_errors=[],
    ).insert()
    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="writing",
        activity_index=1,
        grammar_correct=[],
        grammar_errors=["GP_BAD"],
    ).insert()

    events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()

    mock_response = MagicMock(content=[MagicMock(text="Nice job!")])
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = mock_response

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        feedback = await generate_lesson_feedback(lesson, [], events)

    assert isinstance(feedback, str)
    prompt_sent = mock_client.messages.create.call_args[1]["messages"][0]["content"]
    # W1 had no errors — just "completed"
    assert "W1: completed\n" in prompt_sent
    # W2 had 1 error — should show grammar issues
    assert "W2: completed (1 grammar issues)" in prompt_sent


@pytest.mark.integration
async def test_analyze_lesson_creates_summary_event(db, completed_lesson):
    """analyze_lesson should aggregate per-activity events and create a summary event."""
    from maestro.learning.lesson_analyzer import analyze_lesson
    from maestro.learning import grammar_cache

    gps = await GrammarPoint.find_all().to_list()
    grammar_cache.seed(gps=gps, cfs=[])

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={"it": LanguageProgress(cefr_estimate="A1")},
    )
    await profile.insert()

    # Only CF stage1 LLM call needed (no GP LLM calls)
    cf_stage1_response = MagicMock(content=[MagicMock(text='{"categories": []}')])
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = cf_stage1_response

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        await analyze_lesson(completed_lesson)

    # 3 per-activity events + 1 summary event = 4
    events = await LearningEvent.find_all().to_list()
    assert len(events) == 4
    summary = [e for e in events if e.activity_type is None]
    assert len(summary) == 1
    assert "GP_OK" in summary[0].grammar_correct
    assert "GP_BAD" in summary[0].grammar_errors


# ---------------------------------------------------------------------------
# End-to-end lifecycle test
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_lesson_lifecycle_events_to_profile(db, completed_lesson):
    """Full pipeline: per-activity events → analyze_lesson → profile updated."""
    from maestro.learning.lesson_analyzer import analyze_lesson
    from maestro.learning import grammar_cache

    gps = await GrammarPoint.find_all().to_list()
    grammar_cache.seed(gps=gps, cfs=[])

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={"it": LanguageProgress(cefr_estimate="A1")},
    )
    await profile.insert()

    cf_stage1_response = MagicMock(content=[MagicMock(text='{"categories": []}')])
    mock_client = AsyncMock()
    mock_client.messages.create.return_value = cf_stage1_response

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        await analyze_lesson(completed_lesson)

    # Profile should reflect the per-activity events
    refreshed = await LearningProfile.find_one({"student_id": _FAKE_STUDENT_ID})
    assert refreshed.active_progress.grammar_correct_counts.get("GP_OK", 0) >= 1
    assert refreshed.active_progress.grammar_error_counts.get("GP_BAD", 0) >= 1
    # GP_OK should not be in errors, GP_BAD should not be in correct
    assert refreshed.active_progress.grammar_correct_counts.get("GP_BAD", 0) == 0
    assert refreshed.active_progress.grammar_error_counts.get("GP_OK", 0) == 0


@pytest.mark.integration
async def test_analyze_lesson_no_text_skips_cf_analysis(db):
    """Lesson with only drill events (no student_text) → no LLM call."""
    from maestro.learning.lesson_analyzer import analyze_lesson
    from maestro.learning import grammar_cache

    gp = GrammarPoint(
        code="GP_ONLY", label="Solo", cefr_level="A1", category="t", description=""
    )
    await gp.insert()
    grammar_cache.seed(gps=[gp], cfs=[])

    lesson = Lesson(
        student_id=_FAKE_STUDENT_ID,
        status=LessonStatus.COMPLETED,
        duration_minutes=5,
        started_at=utcnow(),
        completed_at=utcnow(),
        generating=False,
        activities=[],
        current_index=0,
    )
    await lesson.insert()

    # Drill event with no student_text
    await LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        lesson_id=lesson.id,
        activity_type="drill",
        student_text="",
        grammar_correct=["GP_ONLY"],
        grammar_errors=[],
    ).insert()

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={"it": LanguageProgress(cefr_estimate="A1")},
    )
    await profile.insert()

    mock_client = AsyncMock()
    with patch("maestro.llm.get_async_client", return_value=mock_client):
        await analyze_lesson(lesson)

    # No LLM calls should have been made (no text for CF analysis)
    mock_client.messages.create.assert_not_called()

    # But GP codes should still be aggregated into profile
    refreshed = await LearningProfile.find_one({"student_id": _FAKE_STUDENT_ID})
    assert refreshed.active_progress.grammar_correct_counts.get("GP_ONLY", 0) >= 1


@pytest.mark.integration
async def test_get_weak_grammar_points_no_events(db):
    """Lesson with no LearningEvents → empty weak list."""
    from maestro.lessons.lifecycle import get_weak_grammar_points

    lesson = Lesson(
        student_id=_FAKE_STUDENT_ID,
        status=LessonStatus.COMPLETED,
        duration_minutes=5,
        started_at=utcnow(),
        completed_at=utcnow(),
        generating=False,
        activities=[],
        current_index=0,
    )
    await lesson.insert()

    weak = await get_weak_grammar_points(lesson)
    assert weak == []
