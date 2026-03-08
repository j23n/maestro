import bcrypt as _bcrypt

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from maestro.models import Account, Student


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


@pytest.fixture
async def auth_app(db):
    """FastAPI TestClient without pre-set cookies."""
    with (
        patch("maestro.main.init_db", new_callable=AsyncMock),
        patch("maestro.main.get_nlp", return_value=MagicMock()),
        patch("maestro.main.load_vocab", new_callable=AsyncMock),
    ):
        from maestro.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


@pytest.mark.integration
async def test_signup_get_renders_form(auth_app):
    resp = auth_app.get("/auth/signup")
    assert resp.status_code == 200
    assert "signup" in resp.text.lower() or "Crea" in resp.text


@pytest.mark.integration
async def test_signup_success(auth_app):
    resp = auth_app.post(
        "/auth/signup",
        data={"email": "test@example.com", "password": "password123", "password_confirm": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/lezione/"

    # Verify session cookie is set
    assert "session" in resp.cookies

    # Verify exactly one Account and one Student created in DB
    account = await Account.find_one({"email": "test@example.com"})
    assert account is not None
    assert _bcrypt.checkpw(b"password123", account.password_hash.encode())
    assert await Account.find({"email": "test@example.com"}).count() == 1

    student = await Student.get(account.student_id)
    assert student is not None
    assert await Student.find_all().count() == 1


@pytest.mark.integration
async def test_signup_duplicate_email(auth_app):
    # Create existing account
    student = Student()
    await student.insert()
    account = Account(email="taken@example.com", password_hash=_hash_password("password123"), student_id=student.id)
    await account.insert()

    resp = auth_app.post(
        "/auth/signup",
        data={"email": "taken@example.com", "password": "password123", "password_confirm": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "signup_error_email_taken" in resp.text or "Esiste già" in resp.text


@pytest.mark.integration
async def test_signup_password_mismatch(auth_app):
    resp = auth_app.post(
        "/auth/signup",
        data={"email": "test@example.com", "password": "password123", "password_confirm": "different456"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "non corrispondono" in resp.text or "password_mismatch" in resp.text


@pytest.mark.integration
async def test_signup_password_too_short(auth_app):
    resp = auth_app.post(
        "/auth/signup",
        data={"email": "test@example.com", "password": "short", "password_confirm": "short"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "8 caratteri" in resp.text or "password_too_short" in resp.text


@pytest.mark.integration
async def test_login_get_renders_form(auth_app):
    resp = auth_app.get("/auth/login")
    assert resp.status_code == 200
    assert "login" in resp.text.lower() or "Accedi" in resp.text


@pytest.mark.integration
async def test_login_success(auth_app):
    # Create account first
    student = Student()
    await student.insert()
    account = Account(email="login@example.com", password_hash=_hash_password("password123"), student_id=student.id)
    await account.insert()

    resp = auth_app.post(
        "/auth/login",
        data={"email": "login@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/lezione/"
    assert "session" in resp.cookies


@pytest.mark.integration
async def test_login_wrong_password(auth_app):
    student = Student()
    await student.insert()
    account = Account(email="wrong@example.com", password_hash=_hash_password("password123"), student_id=student.id)
    await account.insert()

    resp = auth_app.post(
        "/auth/login",
        data={"email": "wrong@example.com", "password": "wrongpassword"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "non validi" in resp.text or "login_error_invalid" in resp.text


@pytest.mark.integration
async def test_login_nonexistent_email(auth_app):
    resp = auth_app.post(
        "/auth/login",
        data={"email": "nobody@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "non validi" in resp.text or "login_error_invalid" in resp.text


@pytest.mark.integration
async def test_logout_clears_cookies(auth_app):
    # First signup to get cookies
    auth_app.post(
        "/auth/signup",
        data={"email": "logout@example.com", "password": "password123", "password_confirm": "password123"},
        follow_redirects=False,
    )

    resp = auth_app.post("/auth/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    # Verify session cookie is cleared (set with max-age=0)
    set_cookies = resp.headers.get_list("set-cookie")
    session_cleared = any("session=" in c and ("Max-Age=0" in c or 'max-age=0' in c.lower()) for c in set_cookies)
    assert session_cleared
