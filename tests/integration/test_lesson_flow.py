"""Integration tests for _advance_lesson, _collect_free_texts, _collect_drill_gp_outcomes."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from maestro.models import (
    Lesson,
    LessonActivity,
    GeneratedDrill,
    DrillTemplate,
    DrillItem,
)


def _make_lesson(activities: list[LessonActivity], generating: bool = False) -> Lesson:
    return Lesson(
        status="active",
        duration_minutes=20,
        activities=activities,
        current_index=0,
        generating=generating,
        started_at=datetime.utcnow(),
    )


@pytest.mark.integration
async def test_advance_lesson_marks_current_completed(db):
    from maestro.routes.lezione import _advance_lesson

    activities = [
        LessonActivity(type="grammar", title="G1", description="", duration_minutes=3, status="active"),
        LessonActivity(type="drill", title="D1", description="", duration_minutes=3, status="pending"),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    await _advance_lesson(lesson, 0)
    assert lesson.activities[0].status == "completed"


@pytest.mark.integration
async def test_advance_lesson_activates_next_pending(db):
    from maestro.routes.lezione import _advance_lesson

    activities = [
        LessonActivity(type="grammar", title="G1", description="", duration_minutes=3, status="active"),
        LessonActivity(type="drill", title="D1", description="", duration_minutes=3, status="pending"),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    redirect = await _advance_lesson(lesson, 0)
    assert lesson.activities[1].status == "active"
    assert "/activity/1" in redirect


@pytest.mark.integration
async def test_advance_lesson_skip_does_not_mark_completed(db):
    from maestro.routes.lezione import _advance_lesson

    activities = [
        LessonActivity(type="grammar", title="G1", description="", duration_minutes=3, status="active"),
        LessonActivity(type="drill", title="D1", description="", duration_minutes=3, status="pending"),
    ]
    lesson = _make_lesson(activities)
    await lesson.insert()

    await _advance_lesson(lesson, 0, skip=True)
    assert lesson.activities[0].status != "completed"


@pytest.mark.integration
async def test_advance_lesson_generating_redirect(db):
    from maestro.routes.lezione import _advance_lesson

    activities = [
        LessonActivity(type="grammar", title="G1", description="", duration_minutes=3, status="active"),
    ]
    lesson = _make_lesson(activities, generating=True)
    await lesson.insert()

    redirect = await _advance_lesson(lesson, 0)
    assert "generating" in redirect


@pytest.mark.integration
async def test_advance_lesson_all_done_marks_completed(db):
    from maestro.routes.lezione import _advance_lesson

    activities = [
        LessonActivity(type="grammar", title="G1", description="", duration_minutes=3, status="active"),
    ]
    lesson = _make_lesson(activities, generating=False)
    await lesson.insert()

    redirect = await _advance_lesson(lesson, 0)
    assert lesson.status == "completed"
    assert "complete" in redirect


@pytest.mark.integration
async def test_collect_free_texts_writing(db):
    from maestro.learning.lesson_analyzer import _collect_free_texts

    activities = [
        LessonActivity(
            type="writing",
            title="W",
            description="",
            duration_minutes=5,
            status="completed",
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
            type="writing",
            title="W",
            description="",
            duration_minutes=5,
            status="pending",  # not completed
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
            type="reading",
            title="R",
            description="",
            duration_minutes=5,
            status="completed",
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
            type="drill",
            title="D",
            description="",
            duration_minutes=3,
            status="completed",
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
        exercise_type="fill_blank",
    )
    await template.insert()

    drill = GeneratedDrill(
        template=template,
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type="fill_blank",
        prompt="",
        topic_used="test",
    )
    await drill.insert()

    activities = [
        LessonActivity(
            type="drill",
            title="D",
            description="",
            duration_minutes=3,
            status="completed",
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
        exercise_type="fill_blank",
    )
    await template.insert()

    drill = GeneratedDrill(
        template=template,
        grammar_point_code="GP_002",
        cefr_level="A1",
        exercise_type="fill_blank",
        prompt="",
        topic_used="test",
    )
    await drill.insert()

    activities = [
        LessonActivity(
            type="drill",
            title="D",
            description="",
            duration_minutes=3,
            status="completed",
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
        exercise_type="fill_blank",
    )
    await template.insert()

    drill = GeneratedDrill(
        template=template,
        grammar_point_code="GP_003",
        cefr_level="A1",
        exercise_type="fill_blank",
        prompt="",
        topic_used="test",
    )
    await drill.insert()

    activities = [
        LessonActivity(
            type="drill",
            title="D",
            description="",
            duration_minutes=3,
            status="pending",
            drill_id=drill.id,
            result=None,  # no result yet
        ),
    ]
    lesson = _make_lesson(activities)

    correct, errors, all_codes = await _collect_drill_gp_outcomes(lesson)
    assert "GP_003" not in correct
    assert "GP_003" not in errors
    assert "GP_003" in all_codes  # still in all_codes
