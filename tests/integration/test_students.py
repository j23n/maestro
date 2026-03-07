"""Integration tests for student management: error pages, deletion, name validation."""
import pytest

from beanie import PydanticObjectId

from maestro.models import Student, LearningProfile
from maestro.profile import save_onboarding_field


# ---------------------------------------------------------------------------
# Step 1: Error pages
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
# Step 2: Delete student
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_delete_student_success(test_app, db, student):
    response = test_app.request("DELETE", f"/students/{student.id}")
    assert response.status_code == 200
    deleted = await Student.get(student.id)
    assert deleted is None


@pytest.mark.integration
def test_delete_student_invalid_id(test_app):
    fake_id = str(PydanticObjectId())
    response = test_app.request("DELETE", f"/students/{fake_id}")
    assert response.status_code == 404


@pytest.mark.integration
async def test_delete_student_cascades_profile(test_app, db, student):
    profile = LearningProfile(student_id=student.id)
    await profile.insert()
    response = test_app.request("DELETE", f"/students/{student.id}")
    assert response.status_code == 200
    remaining = await LearningProfile.find_one({"student_id": student.id})
    assert remaining is None


# ---------------------------------------------------------------------------
# Step 3: Student creation (no name — set during onboarding)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_student_no_name(test_app, db):
    response = test_app.post("/students/", follow_redirects=False)
    assert response.status_code == 303
    created = await Student.find_one({"name": ""})
    assert created is not None


@pytest.mark.integration
async def test_onboarding_name_truncated_to_30(db, student):
    long_name = "A" * 50
    await save_onboarding_field(student, "name", long_name)
    refreshed = await Student.get(student.id)
    assert len(refreshed.name) == 30
    assert refreshed.name == "A" * 30
