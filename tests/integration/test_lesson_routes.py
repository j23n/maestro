"""Integration tests for lesson route form submissions."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from maestro.models import (
    Lesson,
    LessonActivity,
    LearningEvent,
    GeneratedDrill,
    DrillItem,
    QuestionItem,
    ActivityType,
    ActivityStatus,
    LessonStatus,
    ExerciseType,
)
from maestro.utils import utcnow

# test_app fixture provided by conftest.py (shares the db fixture's database)


@pytest.fixture
async def active_lesson_with_drill(db, student):
    """Active lesson with a single fill_blank drill activity."""
    drill = GeneratedDrill(
        student_id=student.id,
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="",
        items=[DrillItem(prompt="Io ___ al parco.", correct_answer="vado")],
        scenario_slug="test",
    )
    await drill.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.DRILL,
                title="Test drill",
                description="",
                duration_minutes=3,
                status=ActivityStatus.ACTIVE,
                drill_id=drill.id,
            ),
        ],
        current_index=0,
    )
    await lesson.insert()
    return lesson, drill


@pytest.mark.integration
def test_drill_submit_redirects_to_review(test_app, active_lesson_with_drill):
    """POST drill-submit should redirect to the activity review page."""
    lesson, drill = active_lesson_with_drill

    mock_event = MagicMock()
    mock_event.insert = AsyncMock()
    with (
        patch(
            "maestro.routes.lessons.score_attempt", new_callable=AsyncMock
        ) as mock_score,
        patch(
            "maestro.vocab.discover.discover",
            new_callable=AsyncMock,
            return_value="annotated",
        ),
    ):
        mock_score.return_value = (
            True,
            mock_event,
            {"items": [], "correct_count": 1, "total": 1},
            [],
        )
        response = test_app.post(
            f"/lessons/{lesson.id}/activity/0/drill-submit",
            data={"answers": "vado"},
        )

    assert response.status_code == 200
    assert "HX-Redirect" in response.headers


@pytest.mark.integration
def test_activity_skip_returns_redirect(test_app, active_lesson_with_drill):
    """POST skip should return 204 with HX-Redirect header."""
    lesson, _ = active_lesson_with_drill

    response = test_app.post(f"/lessons/{lesson.id}/activity/0/skip")
    assert response.status_code == 204
    assert "HX-Redirect" in response.headers


@pytest.mark.integration
def test_activity_complete_returns_redirect(test_app, active_lesson_with_drill):
    """POST complete should return 204 with HX-Redirect header."""
    lesson, _ = active_lesson_with_drill

    response = test_app.post(f"/lessons/{lesson.id}/activity/0/complete")
    assert response.status_code == 204
    assert "HX-Redirect" in response.headers


@pytest.mark.integration
async def test_writing_submit_returns_feedback(test_app, db, student):
    """POST writing-submit should call generate_writing_feedback and return result."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.WRITING,
                title="Scrittura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
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
        "grammar_correct_codes": [],
        "grammar_error_codes": [],
    }
    with patch(
        "maestro.routes.lessons.generate_writing_feedback",
        new_callable=AsyncMock,
        return_value=mock_feedback,
    ):
        response = test_app.post(
            f"/lessons/{lesson.id}/activity/0/writing-submit",
            data={"answer": "Oggi ho mangiato la pizza."},
        )

    assert response.status_code == 200


@pytest.mark.integration
async def test_lezione_create_abandons_active_and_creates_new(test_app, db, student):
    """POST /lessons/ with an existing ACTIVE lesson → abandons old, creates new."""
    old_lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.GRAMMAR,
                title="Test",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
            ),
        ],
        current_index=0,
    )
    await old_lesson.insert()

    response = test_app.post(
        "/lessons/", data={"duration": "20"}, follow_redirects=False
    )
    assert response.status_code == 303
    # Should redirect to the NEW lesson, not the old one
    assert f"/lessons/{old_lesson.id}" not in response.headers["location"]

    # Old lesson should be abandoned
    old_refreshed = await Lesson.get(old_lesson.id)
    assert old_refreshed.status == LessonStatus.ABANDONED

    # A new lesson was created
    count = await Lesson.find({"student_id": student.id}).count()
    assert count == 2


# ---------------------------------------------------------------------------
# LISTENING activity tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def active_lesson_with_listening(db, student):
    """Active lesson with a single LISTENING activity (with audio_url and questions)."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.LISTENING,
                title="Ascolto",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
                content="<span lang='it'>Marco va al bar.</span>",
                questions=[
                    QuestionItem(text="Dove va Marco?", correct_answer="Al bar")
                ],
                audio_path="/static/audio/lesson_test_0.wav",
            ),
        ],
        current_index=0,
    )
    await lesson.insert()
    return lesson


@pytest.mark.integration
def test_listening_activity_get_returns_200(test_app, active_lesson_with_listening):
    """GET /lessons/{id}/activity/0 for a LISTENING activity should return 200."""
    lesson = active_lesson_with_listening
    with patch(
        "maestro.vocab.discover.discover",
        new_callable=AsyncMock,
        side_effect=lambda html, **kw: html,
    ):
        response = test_app.get(f"/lessons/{lesson.id}/activity/0")
    assert response.status_code == 200


@pytest.mark.integration
def test_listening_activity_get_includes_audio_url(
    test_app, active_lesson_with_listening
):
    """GET response for a LISTENING activity should embed the audio URL."""
    lesson = active_lesson_with_listening
    with patch(
        "maestro.vocab.discover.discover",
        new_callable=AsyncMock,
        side_effect=lambda html, **kw: html,
    ):
        response = test_app.get(f"/lessons/{lesson.id}/activity/0")
    assert "/static/audio/lesson_test_0.wav" in response.text


@pytest.mark.integration
async def test_reading_submit_on_listening_records_listening_event(
    test_app, db, student, active_lesson_with_listening
):
    """POST reading-submit on a LISTENING activity should store activity_type='listening'."""
    lesson = active_lesson_with_listening
    with patch(
        "maestro.routes.lessons.score_reading_activity",
        new_callable=AsyncMock,
        return_value=(True, {}, [], []),
    ):
        response = test_app.post(
            f"/lessons/{lesson.id}/activity/0/reading-submit",
            data={"answers": "Al bar"},
        )
    assert response.status_code == 200

    events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()
    assert len(events) == 1
    assert events[0].activity_type == ActivityType.LISTENING.value


@pytest.mark.integration
async def test_reading_submit_on_reading_records_reading_event(test_app, db, student):
    """POST reading-submit on a READING activity should store activity_type='reading'."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.READING,
                title="Lettura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
                content="<span lang='it'>Testo.</span>",
                questions=[QuestionItem(text="Domanda?", correct_answer="Risposta")],
            ),
        ],
        current_index=0,
    )
    await lesson.insert()

    with patch(
        "maestro.routes.lessons.score_reading_activity",
        new_callable=AsyncMock,
        return_value=(True, {}, [], []),
    ):
        response = test_app.post(
            f"/lessons/{lesson.id}/activity/0/reading-submit",
            data={"answers": "Risposta"},
        )
    assert response.status_code == 200

    events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()
    assert len(events) == 1
    assert events[0].activity_type == ActivityType.READING.value


@pytest.mark.integration
async def test_lezione_abandon_route(test_app, db, student):
    """POST /lessons/{id}/abandon → sets status to ABANDONED, redirects to index."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.GRAMMAR,
                title="Test",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
            ),
        ],
        current_index=0,
    )
    await lesson.insert()

    response = test_app.post(f"/lessons/{lesson.id}/abandon", follow_redirects=False)
    assert response.status_code == 204
    assert response.headers["hx-redirect"] == "/lessons/"

    refreshed = await Lesson.get(lesson.id)
    assert refreshed.status == LessonStatus.ABANDONED


@pytest.mark.integration
async def test_abandoned_lessons_not_in_history(test_app, db, student):
    """Abandoned lessons don't appear in the lesson index history."""
    abandoned = Lesson(
        student_id=student.id,
        status=LessonStatus.ABANDONED,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[],
        current_index=0,
    )
    await abandoned.insert()

    response = test_app.get("/lessons/", follow_redirects=False)
    # Should render the index (no active lesson to redirect to)
    assert response.status_code == 200
    # Abandoned lesson should not show in history
    assert str(abandoned.id) not in response.text


# ---------------------------------------------------------------------------
# Per-activity LearningEvent creation tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_drill_submit_creates_learning_event(test_app, active_lesson_with_drill):
    """POST drill-submit should persist a LearningEvent with correct fields."""
    from maestro.learning import grammar_cache

    lesson, drill = active_lesson_with_drill
    grammar_cache.seed(gps=[MagicMock(code="GP_001", label="Test GP", cefr_level="A1")])

    event = LearningEvent(
        student_id=lesson.student_id,
        grammar_correct=["GP_001"],
        grammar_errors=[],
    )
    with (
        patch(
            "maestro.routes.lessons.score_attempt", new_callable=AsyncMock
        ) as mock_score,
        patch(
            "maestro.vocab.discover.discover",
            new_callable=AsyncMock,
            return_value="annotated",
        ),
    ):
        mock_score.return_value = (
            True,
            event,
            {"items": [], "correct_count": 1, "total": 1},
            [],
        )
        test_app.post(
            f"/lessons/{lesson.id}/activity/0/drill-submit",
            data={"answers": "vado"},
        )

    events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()
    assert len(events) == 1
    ev = events[0]
    assert ev.activity_type == "drill"
    assert ev.activity_index == 0
    assert ev.student_text == "vado"
    assert ev.lesson_id == lesson.id
    assert "GP_001" in ev.grammar_correct


@pytest.mark.integration
async def test_writing_submit_creates_learning_event(test_app, db, student):
    """POST writing-submit should persist a LearningEvent with GP codes from feedback."""
    from maestro.models import GrammarPoint

    gp = GrammarPoint(
        code="GP_W01",
        label="Test Writing GP",
        cefr_level="A1",
        category="test",
    )
    await gp.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.WRITING,
                title="Scrittura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
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
        "grammar_correct_codes": ["GP_W01"],
        "grammar_error_codes": [],
    }
    with patch(
        "maestro.routes.lessons.generate_writing_feedback",
        new_callable=AsyncMock,
        return_value=mock_feedback,
    ):
        test_app.post(
            f"/lessons/{lesson.id}/activity/0/writing-submit",
            data={"answer": "Oggi ho mangiato la pizza."},
        )

    events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()
    assert len(events) == 1
    ev = events[0]
    assert ev.activity_type == "writing"
    assert ev.student_text == "Oggi ho mangiato la pizza."
    assert "GP_W01" in ev.grammar_correct


@pytest.mark.integration
async def test_reading_submit_creates_learning_event(
    test_app, db, student, mock_scorer_client
):
    """POST reading-submit should persist a LearningEvent with aggregated GP codes."""
    from maestro.models import GrammarPoint

    gp = GrammarPoint(
        code="GP_R01",
        label="Test Reading GP",
        cefr_level="A1",
        category="test",
    )
    await gp.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        cefr_at_start="A1",
        activities=[
            LessonActivity(
                type=ActivityType.READING,
                title="Lettura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
                content="Il gatto è sul tavolo.",
                questions=[
                    QuestionItem(text="Dove è il gatto?", correct_answer="Sul tavolo")
                ],
            ),
        ],
        current_index=0,
    )
    await lesson.insert()

    mock_scorer_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='[{"objective_correct": true, "objective_note": "Good", "grammar_errors": [], "tips": [], "grammar_correct_codes": ["GP_R01"], "grammar_error_codes": []}]'
            )
        ]
    )

    test_app.post(
        f"/lessons/{lesson.id}/activity/0/reading-submit",
        data={"answers": "Sul tavolo"},
    )

    events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()
    assert len(events) == 1
    ev = events[0]
    assert ev.activity_type == "reading"
    assert "Sul tavolo" in ev.student_text
    assert "GP_R01" in ev.grammar_correct


@pytest.mark.integration
async def test_writing_submit_event_captures_error_codes(test_app, db, student):
    """POST writing-submit with grammar errors should persist error codes on the event."""
    from maestro.models import GrammarPoint

    gp = GrammarPoint(
        code="GP_ERR",
        label="Test Error GP",
        cefr_level="A1",
        category="test",
    )
    await gp.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.WRITING,
                title="Scrittura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
                content="Descrivi la tua giornata.",
            ),
        ],
        current_index=0,
    )
    await lesson.insert()

    mock_feedback = {
        "objective_correct": False,
        "objective_note": "Grammar issue",
        "grammar_errors": ["Wrong verb form"],
        "tips": [],
        "grammar_correct_codes": [],
        "grammar_error_codes": ["GP_ERR"],
    }
    with patch(
        "maestro.routes.lessons.generate_writing_feedback",
        new_callable=AsyncMock,
        return_value=mock_feedback,
    ):
        test_app.post(
            f"/lessons/{lesson.id}/activity/0/writing-submit",
            data={"answer": "Ieri io mangiare la pizza."},
        )

    events = await LearningEvent.find({"lesson_id": lesson.id}).to_list()
    assert len(events) == 1
    ev = events[0]
    assert "GP_ERR" in ev.grammar_errors


# ---------------------------------------------------------------------------
# Tier-limit tests for POST /lessons/
# ---------------------------------------------------------------------------


def _make_a1_lesson(student_id, status=LessonStatus.COMPLETED):
    return Lesson(
        student_id=student_id,
        status=status,
        duration_minutes=10,
        cefr_at_start="A1",
        generating=False,
        activities=[],
        current_index=0,
    )


@pytest.mark.integration
async def test_free_tier_a1_limit_blocks_after_cap(
    test_app, db, student, account, monkeypatch
):
    """Free-tier student with 10 A1 lessons gets a 402 on POST /lessons/."""
    import maestro.routes.lessons as _lessons_routes
    from maestro.learning.profile import LearningProfile
    from maestro.models import LanguageProgress

    monkeypatch.setattr(_lessons_routes._settings, "FREE_TIER_LESSON_LIMIT_EX_A0", 10)

    profile = LearningProfile(
        student_id=student.id,
        progress={"it": LanguageProgress(cefr_estimate="A1")},
    )
    await profile.insert()

    for _ in range(10):
        await _make_a1_lesson(student.id).insert()

    response = test_app.post(
        "/lessons/", data={"duration": "20"}, follow_redirects=False
    )
    assert response.status_code == 402


@pytest.mark.integration
async def test_free_tier_a1_under_limit_creates_lesson(test_app, db, student, account):
    """Free-tier student with 9 A1 lessons can create a 10th."""
    from maestro.learning.profile import LearningProfile
    from maestro.models import LanguageProgress

    profile = LearningProfile(
        student_id=student.id,
        progress={"it": LanguageProgress(cefr_estimate="A1")},
    )
    await profile.insert()

    for _ in range(9):
        await _make_a1_lesson(student.id).insert()

    response = test_app.post(
        "/lessons/", data={"duration": "20"}, follow_redirects=False
    )
    assert response.status_code == 303


@pytest.mark.integration
async def test_pro_tier_no_a1_limit(test_app, db, student, account):
    """Pro-tier student is never blocked regardless of A1 lesson count."""
    from maestro.learning.profile import LearningProfile
    from maestro.models import LanguageProgress

    profile = LearningProfile(
        student_id=student.id,
        progress={"it": LanguageProgress(cefr_estimate="A1")},
    )
    await profile.insert()

    await account.update({"$set": {"subscription_tier": "pro"}})

    for _ in range(15):
        await _make_a1_lesson(student.id).insert()

    response = test_app.post(
        "/lessons/", data={"duration": "20"}, follow_redirects=False
    )
    assert response.status_code == 303


@pytest.mark.integration
async def test_a0_student_always_allowed(test_app, db, student, account):
    """A0 student on free tier is never blocked, even with many lessons."""
    from maestro.learning.profile import LearningProfile
    from maestro.models import LanguageProgress

    profile = LearningProfile(
        student_id=student.id,
        progress={"it": LanguageProgress(cefr_estimate="A0")},
    )
    await profile.insert()

    # Insert many A0 lessons — cap should never apply
    for _ in range(20):
        await Lesson(
            student_id=student.id,
            status=LessonStatus.COMPLETED,
            duration_minutes=10,
            cefr_at_start="A0",
            generating=False,
            activities=[],
            current_index=0,
        ).insert()

    response = test_app.post(
        "/lessons/", data={"duration": "20"}, follow_redirects=False
    )
    assert response.status_code == 303


@pytest.mark.integration
async def test_free_tier_limit_response_contains_upgrade_text(
    test_app, db, student, account, monkeypatch
):
    """The 402 response body contains the upgrade prompt."""
    import maestro.routes.lessons as _lessons_routes
    from maestro.learning.profile import LearningProfile
    from maestro.models import LanguageProgress

    monkeypatch.setattr(_lessons_routes._settings, "FREE_TIER_LESSON_LIMIT_EX_A0", 10)

    profile = LearningProfile(
        student_id=student.id,
        progress={"it": LanguageProgress(cefr_estimate="A1")},
    )
    await profile.insert()

    for _ in range(10):
        await _make_a1_lesson(student.id).insert()

    response = test_app.post(
        "/lessons/", data={"duration": "20"}, follow_redirects=False
    )
    assert response.status_code == 402
    assert "Limit reached" in response.text


# ---------------------------------------------------------------------------
# Scoring failure → user-friendly message tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_drill_scoring_failure_redirects_to_review(test_app, active_lesson_with_drill):
    """When score_attempt raises, handler redirects to the activity review page."""
    lesson, drill = active_lesson_with_drill

    with patch(
        "maestro.routes.lessons.score_attempt",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM down"),
    ):
        response = test_app.post(
            f"/lessons/{lesson.id}/activity/0/drill-submit",
            data={"answers": "vado"},
        )

    assert response.status_code == 200
    assert "HX-Redirect" in response.headers
    assert f"/lessons/{lesson.id}/activity/0" in response.headers["HX-Redirect"]


@pytest.mark.integration
async def test_writing_scoring_failure_redirects_to_review(test_app, db, student):
    """When generate_writing_feedback raises, handler redirects to the activity review page."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.WRITING,
                title="Scrittura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
                content="Descrivi la tua giornata.",
            ),
        ],
        current_index=0,
    )
    await lesson.insert()

    with patch(
        "maestro.routes.lessons.generate_writing_feedback",
        new_callable=AsyncMock,
        side_effect=ValueError("bad LLM response"),
    ):
        response = test_app.post(
            f"/lessons/{lesson.id}/activity/0/writing-submit",
            data={"answer": "Oggi ho mangiato la pizza."},
        )

    assert response.status_code == 200
    assert "HX-Redirect" in response.headers
    assert f"/lessons/{lesson.id}/activity/0" in response.headers["HX-Redirect"]


@pytest.mark.integration
async def test_reading_scoring_failure_redirects_to_review(test_app, db, student):
    """When score_reading_activity raises, handler redirects to the activity review page."""
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        cefr_at_start="A1",
        activities=[
            LessonActivity(
                type=ActivityType.READING,
                title="Lettura",
                description="",
                duration_minutes=5,
                status=ActivityStatus.ACTIVE,
                content="Il gatto è sul tavolo.",
                questions=[
                    QuestionItem(text="Dove è il gatto?", correct_answer="Sul tavolo")
                ],
            ),
        ],
        current_index=0,
    )
    await lesson.insert()

    with patch(
        "maestro.routes.lessons.score_reading_activity",
        new_callable=AsyncMock,
        side_effect=ValueError("bad LLM response"),
    ):
        response = test_app.post(
            f"/lessons/{lesson.id}/activity/0/reading-submit",
            data={"answers": "Sul tavolo"},
        )

    assert response.status_code == 200
    assert "HX-Redirect" in response.headers
    assert f"/lessons/{lesson.id}/activity/0" in response.headers["HX-Redirect"]


# ---------------------------------------------------------------------------
# Review navigation tests (progress pills → past activities)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_completed_drill_with_feedback_returns_200(test_app, db, student):
    """GET a completed drill activity with stored feedback should return 200 (result page)."""
    drill = GeneratedDrill(
        student_id=student.id,
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="",
        items=[DrillItem(prompt="Io ___ al parco.", correct_answer="vado")],
        scenario_slug="test",
    )
    await drill.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.DRILL,
                title="Test drill",
                description="",
                duration_minutes=3,
                status=ActivityStatus.COMPLETED,
                drill_id=drill.id,
                result={
                    "correct": True,
                    "student_answer": "vado",
                    "feedback": {"items": [], "correct_count": 1, "total": 1},
                },
            ),
            LessonActivity(
                type=ActivityType.GRAMMAR,
                title="Grammar",
                description="",
                duration_minutes=3,
                status=ActivityStatus.ACTIVE,
            ),
        ],
        current_index=1,
    )
    await lesson.insert()

    with patch(
        "maestro.vocab.discover.discover",
        new_callable=AsyncMock,
        side_effect=lambda html, **kw: html,
    ):
        response = test_app.get(f"/lessons/{lesson.id}/activity/0")

    assert response.status_code == 200
    assert "continue-btn" in response.text


@pytest.mark.integration
async def test_completed_drill_without_feedback_returns_200(test_app, db, student):
    """GET a completed drill with no stored feedback falls through to is_review template."""
    drill = GeneratedDrill(
        student_id=student.id,
        grammar_point_code="GP_001",
        cefr_level="A1",
        exercise_type=ExerciseType.FILL_BLANK,
        prompt="",
        items=[DrillItem(prompt="Io ___ al parco.", correct_answer="vado")],
        scenario_slug="test",
    )
    await drill.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
        activities=[
            LessonActivity(
                type=ActivityType.DRILL,
                title="Test drill",
                description="",
                duration_minutes=3,
                status=ActivityStatus.COMPLETED,
                drill_id=drill.id,
                result={"correct": True, "student_answer": "vado"},
            ),
            LessonActivity(
                type=ActivityType.GRAMMAR,
                title="Grammar",
                description="",
                duration_minutes=3,
                status=ActivityStatus.ACTIVE,
            ),
        ],
        current_index=1,
    )
    await lesson.insert()

    with patch(
        "maestro.vocab.discover.discover",
        new_callable=AsyncMock,
        side_effect=lambda html, **kw: html,
    ):
        response = test_app.get(f"/lessons/{lesson.id}/activity/0")

    # Falls through to drill template with is_review — shows review banner, not redirect
    assert response.status_code == 200
    assert "review-banner" in response.text
