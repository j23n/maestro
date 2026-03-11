"""Integration tests for error paths — verifying graceful degradation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from beanie import PydanticObjectId

from maestro.errors import APIUnavailableError
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
# 1b. Malformed LLM JSON in writing scorer — raises (no silent fallback)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_malformed_llm_json_writing_raises(mock_scorer_client, db):
    """When LLM returns non-JSON for writing feedback, generate_writing_feedback raises."""
    from maestro.learning.scorer import generate_writing_feedback

    gp = GrammarPoint(
        code="GP001",
        label="Test GP",
        cefr_level="A1",
        category="test",
    )
    await gp.insert()
    taxonomy.seed([gp], [])

    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text="Not JSON")]
    )

    with pytest.raises(ValueError):
        await generate_writing_feedback(
            prompt="Descrivi la tua giornata.",
            student_text="Oggi mangio pizza.",
            cefr_level="A1",
        )


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
                description="",
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


# ---------------------------------------------------------------------------
# 6. Scorer falls back gracefully on APIUnavailableError
# ---------------------------------------------------------------------------


def _seed_gp(gp_code="GP_TEST"):
    """Seed taxonomy with a single grammar point and return it."""
    gp = GrammarPoint(
        code=gp_code,
        label="Test GP",
        cefr_level="A1",
        category="test",
    )
    taxonomy.seed([gp], [])
    return gp


def _make_anthropic_rate_limit_error():
    """Build a real anthropic.RateLimitError for use as a side_effect."""
    import anthropic

    response = httpx.Response(
        429, request=httpx.Request("POST", "https://api.anthropic.com")
    )
    return anthropic.RateLimitError(
        message="rate limited", response=response, body=None
    )


@pytest.mark.integration
async def test_score_single_raises_on_api_unavailable(mock_scorer_client, db):
    """generate_writing_feedback lets APIUnavailableError propagate to the caller."""
    from maestro.learning.scorer import generate_writing_feedback

    _seed_gp()

    mock_scorer_client.messages.create = AsyncMock(
        side_effect=_make_anthropic_rate_limit_error()
    )

    with pytest.raises(APIUnavailableError):
        await generate_writing_feedback(
            prompt="Write about your day",
            student_text="Oggi ho mangiato una pizza.",
            cefr_level="A1",
        )


@pytest.mark.integration
async def test_score_multi_raises_on_api_unavailable(mock_scorer_client, db):
    """score_multi_item_drill lets APIUnavailableError propagate to the caller."""
    from maestro.learning.scorer import score_multi_item_drill

    gp = _seed_gp("GP_MULTI")
    await gp.insert()

    mock_scorer_client.messages.create = AsyncMock(
        side_effect=_make_anthropic_rate_limit_error()
    )

    items = [
        DrillItem(prompt="Il ___ è bello", correct_answer="gatto"),
        DrillItem(prompt="La ___ è bella", correct_answer="casa"),
    ]
    with pytest.raises(APIUnavailableError):
        await score_multi_item_drill(
            ExerciseType.FILL_BLANK, "GP_MULTI", items, ["cane", "porta"]
        )


# ---------------------------------------------------------------------------
# 7. Lesson generation with APIUnavailableError
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_background_generation_api_unavailable_sets_error(db, student):
    """APIUnavailableError from LLM sets generation_error and status=ABANDONED."""
    from maestro.lezione.planner import generate_lesson_background
    from maestro.models import CurriculumScenario

    profile = LearningProfile(student_id=student.id, cefr_estimate="A1")
    await profile.insert()

    scenario = CurriculumScenario(
        slug="test-api-error",
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

    with patch("maestro.llm.get_async_client") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(
            side_effect=_make_anthropic_rate_limit_error()
        )

        with pytest.raises(APIUnavailableError):
            await generate_lesson_background(lesson.id, 20)

    lesson = await Lesson.get(lesson.id)
    assert lesson.generating is False
    assert lesson.generation_error is not None
    assert lesson.status == LessonStatus.ABANDONED


@pytest.mark.integration
async def test_generation_error_message_is_user_friendly(db, student):
    """The stored generation_error does not contain raw status codes or provider names."""
    from maestro.lezione.planner import generate_lesson_background
    from maestro.models import CurriculumScenario

    profile = LearningProfile(student_id=student.id, cefr_estimate="A1")
    await profile.insert()

    scenario = CurriculumScenario(
        slug="test-friendly-error",
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

    with patch("maestro.llm.get_async_client") as mock_client:
        mock_client.return_value.messages.create = AsyncMock(
            side_effect=_make_anthropic_rate_limit_error()
        )

        with pytest.raises(APIUnavailableError):
            await generate_lesson_background(lesson.id, 20)

    lesson = await Lesson.get(lesson.id)
    error_msg = lesson.generation_error.lower()
    assert "429" not in error_msg
    assert "anthropic" not in error_msg
    assert "rate" not in error_msg


# ---------------------------------------------------------------------------
# 8. Generating page renders error with retry button
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_generating_page_shows_error_and_retry(test_app, db, student):
    """Lesson with generation_error shows error text and retry button, not a 500."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ABANDONED,
        generating=False,
        generation_error="Content generation failed. Please try again.",
        activities=[],
        current_index=0,
    )
    await lesson.insert()

    response = test_app.get(f"/lezione/{lesson.id}/generating")
    assert response.status_code == 200
    html = response.text
    assert "Content generation failed" in html
    assert "retry" in html.lower()
