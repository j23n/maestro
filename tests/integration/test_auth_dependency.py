"""Integration tests for the get_current_student auth dependency."""

import pytest
from unittest.mock import patch, AsyncMock
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


def _set_cookie_headers(response) -> list[str]:
    return [v for k, v in response.headers.items() if k.lower() == "set-cookie"]


@pytest.mark.integration
def test_garbled_account_id_clears_session_cookie(db):
    """Corrupted account_id (invalid ObjectId) → session cookie must be deleted."""
    from tests.integration.conftest import sign_session, patch_lifespan

    with patch_lifespan():
        from maestro.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            client.cookies.set("session", sign_session("not-a-valid-objectid"))
            response = client.get("/lezione/", follow_redirects=False)

            assert response.status_code in (302, 303, 307)
            assert "/auth/login" in response.headers["location"]
            set_cookies = _set_cookie_headers(response)
            assert any(
                "session=" in h and "max-age=0" in h.lower() for h in set_cookies
            ), f"Expected session cookie to be cleared; Set-Cookie: {set_cookies}"


@pytest.mark.integration
async def test_db_timeout_preserves_session_cookie(db, account):
    """Transient DB error → redirects to login but session cookie is NOT cleared."""
    from tests.integration.conftest import sign_session, patch_lifespan

    with patch_lifespan():
        from maestro.main import app

        with (
            patch(
                "maestro.auth.Account.get",
                new_callable=AsyncMock,
                side_effect=OSError("simulated timeout"),
            ),
            TestClient(app, raise_server_exceptions=False) as client,
        ):
            client.cookies.set("session", sign_session(str(account.id)))
            response = client.get("/lezione/", follow_redirects=False)

            assert response.status_code in (302, 303, 307)
            assert "/auth/login" in response.headers["location"]
            set_cookies = _set_cookie_headers(response)
            assert not any(
                "session=" in h and "max-age=0" in h.lower() for h in set_cookies
            ), f"Expected session cookie to be preserved; Set-Cookie: {set_cookies}"
