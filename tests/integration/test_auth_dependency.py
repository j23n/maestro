"""Integration tests for the get_current_student auth dependency."""
import pytest
from fastapi.testclient import TestClient


@pytest.mark.integration
def test_no_cookie_redirects_to_login(test_app):
    test_app.cookies.clear()
    response = test_app.get("/lezione/", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "/auth/login" in response.headers["location"]


@pytest.mark.integration
def test_valid_session_returns_200(test_app):
    response = test_app.get("/lezione/", follow_redirects=False)
    assert response.status_code == 200


@pytest.mark.integration
def test_tampered_cookie_redirects_to_login(test_app):
    test_app.cookies.set("session", "garbage.tampered.value")
    response = test_app.get("/lezione/", follow_redirects=False)
    assert response.status_code in (302, 303, 307)
    assert "/auth/login" in response.headers["location"]


@pytest.mark.integration
async def test_orphaned_student_redirects_to_login(db, account, student):
    """Account exists but its linked Student was deleted."""
    await student.delete()
    from tests.integration.conftest import sign_session, patch_lifespan

    with patch_lifespan():
        from maestro.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("session", sign_session(str(account.id)))
            response = client.get("/lezione/", follow_redirects=False)
            assert response.status_code in (302, 303, 307)
            assert "/auth/login" in response.headers["location"]


@pytest.mark.integration
def test_nonexistent_account_redirects_to_login(db):
    from beanie import PydanticObjectId
    from tests.integration.conftest import sign_session, patch_lifespan

    fake_account_id = str(PydanticObjectId())
    with patch_lifespan():
        from maestro.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("session", sign_session(fake_account_id))
            response = client.get("/lezione/", follow_redirects=False)
            assert response.status_code in (302, 303, 307)
            assert "/auth/login" in response.headers["location"]
