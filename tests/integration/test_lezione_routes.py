"""Integration tests for lezione route form submissions."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from maestro.models import (
    Lesson,
    LessonActivity,
    GeneratedDrill,
    DrillTemplate,
    DrillItem,
)
from maestro.utils import utcnow

# test_app fixture provided by conftest.py (shares the db fixture's database)


@pytest.fixture
async def active_lesson_with_drill(db):
    """Active lesson with a single fill_blank drill activity."""
    template = DrillTemplate(grammar_point_code="GP_001", cefr_level="A1", exercise_type="fill_blank")
    await template.insert()

    drill = GeneratedDrill(
        template=template,
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type="fill_blank",
        prompt="",
        items=[DrillItem(prompt="Io ___ al parco.", correct_answer="vado")],
        scenario_slug="test",
    )
    await drill.insert()

    lesson = Lesson(
        status="active",
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type="drill",
                title="Test drill",
                description="Test",
                duration_minutes=3,
                status="active",
                drill_id=drill.id,
            ),
        ],
        current_index=0,
    )
    await lesson.insert()
    return lesson, drill


@pytest.mark.integration
def test_drill_submit_returns_result_page(test_app, active_lesson_with_drill):
    """POST drill-submit should return the drill result template."""
    lesson, drill = active_lesson_with_drill

    with patch("maestro.routes.lezione.score_attempt", new_callable=AsyncMock) as mock_score, \
         patch("maestro.routes.lezione.discover", new_callable=AsyncMock, return_value="annotated"):
        mock_score.return_value = (True, MagicMock(), {"items": [], "correct_count": 1, "total": 1}, [])
        response = test_app.post(
            f"/lezione/{lesson.id}/activity/0/drill-submit",
            data={"answers": "vado"},
        )

    assert response.status_code == 200


@pytest.mark.integration
def test_activity_skip_returns_redirect(test_app, active_lesson_with_drill):
    """POST skip should return 204 with HX-Redirect header."""
    lesson, _ = active_lesson_with_drill

    response = test_app.post(f"/lezione/{lesson.id}/activity/0/skip")
    assert response.status_code == 204
    assert "HX-Redirect" in response.headers


@pytest.mark.integration
def test_activity_complete_returns_redirect(test_app, active_lesson_with_drill):
    """POST complete should return 204 with HX-Redirect header."""
    lesson, _ = active_lesson_with_drill

    response = test_app.post(f"/lezione/{lesson.id}/activity/0/complete")
    assert response.status_code == 204
    assert "HX-Redirect" in response.headers


@pytest.mark.integration
async def test_writing_submit_returns_feedback(test_app, db):
    """POST writing-submit should call generate_writing_feedback and return result."""
    lesson = Lesson(
        status="active",
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type="writing",
                title="Scrittura",
                description="Test",
                duration_minutes=5,
                status="active",
                content="Descrivi la tua giornata.",
            ),
        ],
        current_index=0,
    )
    await lesson.insert()

    mock_feedback = {
        "objective_correct": True,
        "objective_note": "",
        "grammar_errors": [],
        "tips": [],
    }
    with patch("maestro.routes.lezione.generate_writing_feedback", new_callable=AsyncMock, return_value=mock_feedback):
        response = test_app.post(
            f"/lezione/{lesson.id}/activity/0/writing-submit",
            data={"answer": "Oggi ho mangiato la pizza."},
        )

    assert response.status_code == 200
