"""Integration tests for error pages and onboarding name validation."""
import pytest

from maestro.models import Student
from maestro.profile import save_onboarding_field


# ---------------------------------------------------------------------------
# Error pages
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_404_returns_html(test_app):
    response = test_app.get("/nonexistent-page")
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Pagina non trovata" in response.text


@pytest.mark.integration
def test_404_includes_nav(test_app):
    response = test_app.get("/nonexistent-page")
    assert response.status_code == 404
    assert "Maestro" in response.text or "nav" in response.text
    assert "Lezione" in response.text


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
