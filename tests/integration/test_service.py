"""Integration tests for lezione/service.py helper functions."""
import pytest
from unittest.mock import MagicMock

from maestro.models import (
    Lesson, LessonActivity, LearningProfile,
    ActivityType, ActivityStatus, LessonStatus,
)
from maestro.utils import utcnow


@pytest.mark.integration
async def test_score_reading_activity_all_correct(mock_scorer_client, db):
    """All correct answers → overall_correct=True, correct_count matches."""
    from maestro.lezione.service import score_reading_activity

    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='[{"objective_correct": true, "objective_note": "Good", "grammar_errors": [], "tips": []}]')]
    )

    overall, feedback = await score_reading_activity(
        questions=["What color?"],
        correct_answers=["Red"],
        student_answers=["Red"],
    )
    assert overall is True
    assert feedback["correct_count"] == 1
    assert feedback["total"] == 1
    assert feedback["items"][0]["objective_correct"] is True


@pytest.mark.integration
async def test_score_reading_activity_below_threshold(mock_scorer_client, db):
    """Below 70% correct → overall_correct=False."""
    from maestro.lezione.service import score_reading_activity

    # 1 correct out of 3 = 33% < 70%
    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='[{"objective_correct": true, "objective_note": "", "grammar_errors": [], "tips": []}, {"objective_correct": false, "objective_note": "", "grammar_errors": [], "tips": []}, {"objective_correct": false, "objective_note": "", "grammar_errors": [], "tips": []}]')]
    )

    overall, feedback = await score_reading_activity(
        questions=["Q1", "Q2", "Q3"],
        correct_answers=["A1", "A2", "A3"],
        student_answers=["A1", "wrong", "wrong"],
    )
    assert overall is False
    assert feedback["correct_count"] == 1
    assert feedback["total"] == 3


@pytest.mark.integration
async def test_score_reading_activity_enriched_fields(mock_scorer_client, db):
    """Enriched feedback items contain prompt, correct_answer, and student_answer."""
    from maestro.lezione.service import score_reading_activity

    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text='[{"objective_correct": false, "objective_note": "Wrong color", "grammar_errors": ["GP001"], "tips": ["Check colors"]}]')]
    )

    _, feedback = await score_reading_activity(
        questions=["What color is the sky?"],
        correct_answers=["Blue"],
        student_answers=["Green"],
    )
    item = feedback["items"][0]
    assert item["prompt"] == "What color is the sky?"
    assert item["correct_answer"] == "Blue"
    assert item["student_answer"] == "Green"
    assert item["objective_note"] == "Wrong color"
    assert "GP001" in item["grammar_errors"]
    assert "Check colors" in item["tips"]


def _make_lesson(student_id, activities, **kwargs):
    """Helper to build an ACTIVE lesson with defaults."""
    return Lesson(
        student_id=student_id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=activities,
        current_index=kwargs.pop("current_index", 0),
        scenario_slug=kwargs.pop("scenario_slug", "test-scenario"),
        scenario_depth=kwargs.pop("scenario_depth", 1),
        **kwargs,
    )


@pytest.mark.integration
async def test_advance_lesson_creates_profile_and_updates_scenario_progress(db, student):
    """Complete last activity with no profile → profile created + scenario progress recorded."""
    from maestro.lezione.service import advance_lesson

    lesson = _make_lesson(student.id, [
        LessonActivity(type=ActivityType.GRAMMAR, title="G", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
    ], current_index=0)
    await lesson.insert()

    url = await advance_lesson(lesson, 0)
    assert "/complete" in url

    profile = await LearningProfile.find_one({"student_id": student.id})
    assert profile is not None
    assert "test-scenario" in profile.scenario_progress
    progress = profile.scenario_progress["test-scenario"]
    assert progress.depth == 1
    assert progress.lesson_count == 1


@pytest.mark.integration
async def test_advance_lesson_sweeps_leftover_activities(db, student):
    """Earlier PENDING/ACTIVE activities become SKIPPED when lesson completes."""
    from maestro.lezione.service import advance_lesson

    lesson = _make_lesson(student.id, [
        LessonActivity(type=ActivityType.GRAMMAR, title="A", description="", duration_minutes=3, status=ActivityStatus.PENDING),
        LessonActivity(type=ActivityType.GRAMMAR, title="B", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
        LessonActivity(type=ActivityType.GRAMMAR, title="C", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
    ], current_index=2, scenario_slug=None)
    await lesson.insert()

    url = await advance_lesson(lesson, 2)
    assert "/complete" in url

    refreshed = await Lesson.get(lesson.id)
    assert refreshed.activities[0].status == ActivityStatus.SKIPPED
    assert refreshed.activities[1].status == ActivityStatus.SKIPPED
    assert refreshed.activities[2].status == ActivityStatus.COMPLETED


@pytest.mark.integration
async def test_advance_lesson_normal_progression(db, student):
    """Complete activity 0 of 2 → activity 1 becomes ACTIVE."""
    from maestro.lezione.service import advance_lesson

    lesson = _make_lesson(student.id, [
        LessonActivity(type=ActivityType.GRAMMAR, title="A", description="", duration_minutes=3, status=ActivityStatus.ACTIVE),
        LessonActivity(type=ActivityType.GRAMMAR, title="B", description="", duration_minutes=3, status=ActivityStatus.PENDING),
    ], current_index=0, scenario_slug=None)
    await lesson.insert()

    url = await advance_lesson(lesson, 0)
    assert "/activity/1" in url

    refreshed = await Lesson.get(lesson.id)
    assert refreshed.activities[0].status == ActivityStatus.COMPLETED
    assert refreshed.activities[1].status == ActivityStatus.ACTIVE
    assert refreshed.current_index == 1
