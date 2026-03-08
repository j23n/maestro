import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


@pytest.mark.integration
class TestCSRF:
    @pytest.fixture
    async def raw_client(self, db, student, account):
        """TestClient WITHOUT the automatic CSRF header (unlike test_app)."""
        from tests.integration.conftest import sign_session

        with (
            patch("maestro.main.init_db", new_callable=AsyncMock),
            patch("maestro.main.get_nlp", return_value=MagicMock()),
            patch("maestro.main.load_vocab", new_callable=AsyncMock),
        ):
            from maestro.main import app

            with TestClient(app, raise_server_exceptions=False) as client:
                client.cookies.set("session", sign_session(str(account.id)))
                yield client

    def test_post_without_csrf_token_returns_403(self, raw_client):
        resp = raw_client.post("/lezione/", data={"duration": "15"})
        assert resp.status_code == 403

    def test_post_with_valid_csrf_token_succeeds(self, test_app):
        # test_app fixture already includes CSRF token — POST should not 403
        resp = test_app.post("/lezione/", data={"duration": "15"})
        assert resp.status_code != 403

    def test_csrf_cookie_set_on_first_get(self, raw_client):
        raw_client.get("/")
        assert raw_client.cookies.get("csrftoken")

    def test_tampered_csrf_token_returns_403(self, raw_client):
        raw_client.get("/")
        resp = raw_client.post(
            "/lezione/",
            data={"duration": "15"},
            headers={"x-csrftoken": "wrong-token"},
        )
        assert resp.status_code == 403

    def test_csrf_token_in_form_body_succeeds(self, raw_client):
        """Plain form submissions send the token as a hidden field, not a header."""
        raw_client.get("/")
        token = raw_client.cookies.get("csrftoken")
        resp = raw_client.post(
            "/lezione/",
            data={"duration": "15", "csrftoken": token},
            # No x-csrftoken header — token only in form body
        )
        assert resp.status_code != 403

    def test_cookie_stable_across_gets(self, raw_client):
        """CSRF cookie should not change on subsequent GETs."""
        raw_client.get("/")
        token1 = raw_client.cookies.get("csrftoken")
        raw_client.get("/auth/login")
        token2 = raw_client.cookies.get("csrftoken")
        assert token1 == token2

    def test_empty_csrf_token_returns_403(self, raw_client):
        """Empty cookie + empty header must not pass validation."""
        raw_client.cookies.set("csrftoken", "")
        resp = raw_client.post(
            "/lezione/",
            data={"duration": "15"},
            headers={"x-csrftoken": ""},
        )
        assert resp.status_code == 403
