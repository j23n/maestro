"""FastAPI route smoke tests using mongomock DB and patched lifespan."""

import pytest

# test_app fixture is provided by tests/integration/conftest.py


@pytest.mark.integration
def test_vocab_page_ok(test_app):
    response = test_app.get("/vocab")
    assert response.status_code == 200


@pytest.mark.integration
def test_vocab_word_not_found(test_app):
    response = test_app.get("/vocab/word/NONEXISTENT-ID")
    assert response.status_code == 404


@pytest.mark.integration
def test_profile_page_ok(test_app):
    """Profile page renders even with no profile in DB."""
    response = test_app.get("/profile")
    assert response.status_code == 200


@pytest.mark.integration
async def test_profile_with_seeded_profile(test_app, student):
    """Profile page renders completed-level sections and lesson history labels."""
    from maestro.models import (
        CurriculumScenario,
        GrammarPoint,
        LanguageProgress,
        Lesson,
        LearningProfile,
        LessonStatus,
    )
    from maestro.learning import grammar_cache

    # Seed taxonomy (A0 + A1 grammar points)
    gp_a0 = GrammarPoint(code="gp_a0", label="GP A0", cefr_level="A0", category="test")
    gp_a1 = GrammarPoint(code="gp_a1", label="GP A1", cefr_level="A1", category="test")
    await gp_a0.insert()
    await gp_a1.insert()
    grammar_cache.seed(gps=[gp_a0, gp_a1], cfs=[])

    # Seed scenarios for A0 (completed) and A1 (current)
    sc_a0 = CurriculumScenario(
        slug="a0-intro",
        label="Intro",
        description="A0 intro",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=["gp_a0"],
        depths=["d1"],
        sequence=1,
    )
    sc_a1 = CurriculumScenario(
        slug="a1-bar",
        label="Al bar",
        description="A1 bar",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=["gp_a1"],
        depths=["d1", "d2", "d3"],
    )
    # A B1 scenario only reachable via lesson history (tests missing_slugs fallback)
    sc_b1 = CurriculumScenario(
        slug="b1-extra",
        label="Extra",
        description="B1 extra",
        cefr_level="B1",
        cf_codes=[],
        gp_codes=[],
        depths=["d1", "d2", "d3"],
    )
    await sc_a0.insert()
    await sc_a1.insert()
    await sc_b1.insert()

    # Create profile at A1 (so A0 is a completed level)
    profile = LearningProfile(
        student_id=student.id,
        progress={"it": LanguageProgress(cefr_estimate="A1")},
    )
    await profile.insert()

    # Create a completed lesson referencing the B1 scenario (missing_slugs path)
    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.COMPLETED,
        scenario_slug="b1-extra",
    )
    await lesson.insert()

    response = test_app.get("/profile")
    assert response.status_code == 200
    # Completed A0 scenario label should appear
    assert "Intro" in response.text
    # Current A1 scenario label should appear
    assert "Al bar" in response.text
    # B1 scenario label from lesson history (missing_slugs fallback) should appear
    assert "Extra" in response.text


@pytest.mark.integration
def test_grammar_nonexistent_returns_404(test_app):
    response = test_app.get("/grammar/NONEXISTENT")
    assert response.status_code == 404


@pytest.mark.integration
def test_lezione_index_no_active_shows_config(test_app):
    """With no active lesson, /lessons/ should show the lesson config screen."""
    response = test_app.get("/lessons/", follow_redirects=False)
    assert response.status_code == 200
    # A0 student with no progress sees the welcome card + first-lesson button
    assert "Start your first lesson" in response.text
