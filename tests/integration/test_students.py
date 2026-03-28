"""Integration tests for error pages and onboarding name validation."""

import pytest

from maestro.models import Student
from maestro.learning.profile import save_onboarding_field


# ---------------------------------------------------------------------------
# Error pages
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_404_returns_html(test_app):
    response = test_app.get("/nonexistent-page")
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Page not found" in response.text


@pytest.mark.integration
def test_404_includes_nav(test_app):
    response = test_app.get("/nonexistent-page")
    assert response.status_code == 404
    assert "Maestro" in response.text or "nav" in response.text
    assert "Lesson" in response.text


@pytest.mark.integration
def test_404_shows_custom_icon(test_app):
    response = test_app.get("/nonexistent-page")
    assert response.status_code == 404
    # Compass SVG icon for 404
    assert "<circle cx=" in response.text
    assert "<polygon" in response.text


@pytest.mark.integration
def test_404_htmx_returns_fragment(test_app):
    response = test_app.get("/nonexistent-page", headers={"HX-Request": "true"})
    assert response.status_code == 404
    assert "<nav" not in response.text
    assert "generating-error-card" in response.text


@pytest.mark.integration
def test_500_returns_friendly_page(test_app):
    response = test_app.get("/sentry-debug")
    assert response.status_code == 500
    assert "Server error" in response.text or "Errore del server" in response.text


@pytest.mark.integration
def test_500_htmx_returns_fragment(test_app):
    response = test_app.get("/sentry-debug", headers={"HX-Request": "true"})
    assert response.status_code == 500
    assert "<nav" not in response.text
    assert "generating-error-card" in response.text


# ---------------------------------------------------------------------------
# Onboarding name validation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_onboarding_name_truncated_to_30(db, student):
    long_name = "A" * 50
    await save_onboarding_field(student, "name", long_name)
    refreshed = await Student.get(student.id)
    assert len(refreshed.name) == 30
    assert refreshed.name == "A" * 30
