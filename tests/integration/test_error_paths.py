"""Integration tests for error paths — verifying graceful degradation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from beanie import PydanticObjectId

from maestro.models import (
    DrillItem,
    ExerciseType,
    GrammarPoint,
    Lesson,
    LessonActivity,
    LearningProfile,
    ActivityType,
    ActivityStatus,
    LessonStatus,
)
from maestro import taxonomy


# ---------------------------------------------------------------------------
# 1. Malformed LLM JSON in scorer — falls back to all-incorrect
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_malformed_llm_json_raises(mock_scorer_client, db):
    """When LLM returns non-JSON, score_multi_item_drill raises (no silent fallback)."""
    from maestro.learning.scorer import score_multi_item_drill

    # Seed taxonomy with at least one GP
    gp = GrammarPoint(
        code="GP001",
        label="Test GP",
        cefr_level="A1",
        category="test",
        description="test",
    )
    await gp.insert()
    taxonomy.seed([gp], [])

    # Mock LLM to return non-JSON
    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="This is not JSON at all")]
    )

    items = [DrillItem(prompt="Il ___ è bello", correct_answer="gatto")]
    with pytest.raises(ValueError):
        await score_multi_item_drill(ExerciseType.FILL_BLANK, "GP001", items, ["cane"])


# ---------------------------------------------------------------------------
# 2. Missing drill returns 404 from activity route
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_missing_drill_returns_404(test_app, db, student):
    """Activity referencing a deleted/nonexistent drill returns 404."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.DRILL,
                title="Test Drill",
                description="test",
                status=ActivityStatus.ACTIVE,
                drill_id=PydanticObjectId(),  # points to nonexistent drill
            )
        ],
        current_index=0,
    )
    await lesson.insert()

    response = test_app.get(f"/lezione/{lesson.id}/activity/0")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 3. Background generation failure clears generating flag and sets error
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_background_generation_failure_sets_error(db, student):
    """If LLM call raises during generation, generating=False and generation_error is set."""
    from maestro.lezione.planner import generate_lesson_background
    from maestro.models import CurriculumScenario

    profile = LearningProfile(student_id=student.id, cefr_estimate="A1")
    await profile.insert()

    # Seed a scenario so pick_scenario can find one before hitting the LLM
    scenario = CurriculumScenario(
        slug="test-error",
        label="Test",
        description="",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=[],
        depths=["d1", "d2", "d3"],
    )
    await scenario.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        generating=True,
    )
    await lesson.insert()

    # Make the planner fail by patching the async client to raise
    with patch("maestro.llm.get_async_client") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(
            side_effect=Exception("API down")
        )

        with pytest.raises(Exception, match="API down"):
            await generate_lesson_background(lesson.id, 20)

    # Re-fetch from DB — generating flag should be cleared, error set
    lesson = await Lesson.get(lesson.id)
    assert lesson.generating is False
    assert lesson.generation_error is not None


# ---------------------------------------------------------------------------
# 4. Score reading with empty answers returns safe defaults
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_score_reading_empty_answers(mock_scorer_client, db):
    """Scoring with no student answers returns safe defaults."""
    from maestro.lezione.service import score_reading_activity

    overall_correct, feedback, _, _ = await score_reading_activity(
        questions=["What color?"],
        correct_answers=["Red"],
        student_answers=[],
    )
    # With 0 items (n=0), the 'if n > 0 else True' branch returns True
    assert overall_correct is True
    assert feedback["total"] == 0


# ---------------------------------------------------------------------------
# 5. Activity index out of range returns 404
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_activity_index_out_of_range(test_app, db, student):
    """Accessing an activity beyond the list redirects to /complete."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        generating=False,
        activities=[],
        current_index=0,
    )
    await lesson.insert()

    response = test_app.get(f"/lezione/{lesson.id}/activity/99", follow_redirects=False)
    assert response.status_code == 303
    assert f"/lezione/{lesson.id}/complete" in response.headers["location"]
