import bcrypt as _bcrypt
from unittest.mock import patch, AsyncMock

import pytest

from maestro.models import Account, Student
from maestro.tokens import generate_verify_token, generate_reset_token

FAKE_PW = "password123"


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


@pytest.mark.integration
async def test_health_returns_ok(auth_app):
    resp = auth_app.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.integration
async def test_signup_get_renders_form(auth_app):
    resp = auth_app.get("/auth/signup")
    assert resp.status_code == 200
    assert "signup" in resp.text.lower() or "Crea" in resp.text


@pytest.mark.integration
async def test_signup_success(auth_app):
    resp = auth_app.post(
        "/auth/signup",
        data={
            "email": "test@example.com",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/lessons/"

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
    account = Account(
        email="taken@example.com",
        password_hash=_hash_password("password123"),
        student_id=student.id,
    )
    await account.insert()

    resp = auth_app.post(
        "/auth/signup",
        data={
            "email": "taken@example.com",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "already exists" in resp.text


@pytest.mark.integration
async def test_signup_password_mismatch(auth_app):
    resp = auth_app.post(
        "/auth/signup",
        data={
            "email": "test@example.com",
            "password": "password123",
            "password_confirm": "different456",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "don\u2019t match" in resp.text


@pytest.mark.integration
async def test_signup_password_too_short(auth_app):
    resp = auth_app.post(
        "/auth/signup",
        data={
            "email": "test@example.com",
            "password": "short",
            "password_confirm": "short",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "8 characters" in resp.text


@pytest.mark.integration
async def test_login_get_renders_form(auth_app):
    resp = auth_app.get("/auth/login")
    assert resp.status_code == 200
    assert "Log in" in resp.text


@pytest.mark.integration
async def test_login_success(auth_app):
    # Create account first
    student = Student()
    await student.insert()
    account = Account(
        email="login@example.com",
        password_hash=_hash_password("password123"),
        student_id=student.id,
    )
    await account.insert()

    resp = auth_app.post(
        "/auth/login",
        data={"email": "login@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/lessons/"
    assert "session" in resp.cookies


@pytest.mark.integration
async def test_login_wrong_password(auth_app):
    student = Student()
    await student.insert()
    account = Account(
        email="wrong@example.com",
        password_hash=_hash_password("password123"),
        student_id=student.id,
    )
    await account.insert()

    resp = auth_app.post(
        "/auth/login",
        data={"email": "wrong@example.com", "password": "wrongpassword"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "Invalid email" in resp.text


@pytest.mark.integration
async def test_login_nonexistent_email(auth_app):
    resp = auth_app.post(
        "/auth/login",
        data={"email": "nobody@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "Invalid email" in resp.text


@pytest.mark.integration
async def test_logout_clears_cookies(auth_app):
    # First signup to get cookies
    auth_app.post(
        "/auth/signup",
        data={
            "email": "logout@example.com",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )

    resp = auth_app.post("/auth/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    # Verify session cookie is cleared (set with max-age=0)
    set_cookies = resp.headers.get_list("set-cookie")
    session_cleared = any(
        "session=" in c and ("Max-Age=0" in c or "max-age=0" in c.lower())
        for c in set_cookies
    )
    assert session_cleared


@pytest.mark.integration
async def test_login_rate_limit(auth_app):
    """6th login attempt within a minute returns 429."""
    for i in range(5):
        resp = auth_app.post(
            "/auth/login",
            data={"email": f"user{i}@example.com", "password": "wrong"},
            follow_redirects=False,
        )
        assert resp.status_code != 429, f"Rate limited too early on attempt {i + 1}"

    resp = auth_app.post(
        "/auth/login",
        data={"email": "user5@example.com", "password": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 429
    assert "Too many attempts" in resp.text


@pytest.mark.integration
async def test_signup_rate_limit(auth_app):
    """4th signup attempt within a minute returns 429."""
    for i in range(3):
        resp = auth_app.post(
            "/auth/signup",
            data={
                "email": f"u{i}@example.com",
                "password": "short",
                "password_confirm": "short",
            },
            follow_redirects=False,
        )
        assert resp.status_code != 429, f"Rate limited too early on attempt {i + 1}"

    resp = auth_app.post(
        "/auth/signup",
        data={
            "email": "u3@example.com",
            "password": "short",
            "password_confirm": "short",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 429
    assert "Too many attempts" in resp.text


@pytest.mark.integration
async def test_rate_limit_htmx_response(auth_app):
    """429 response returns HTML fragment for HTMX requests."""
    for i in range(3):
        auth_app.post(
            "/auth/signup",
            data={
                "email": f"h{i}@example.com",
                "password": "short",
                "password_confirm": "short",
            },
            follow_redirects=False,
        )

    resp = auth_app.post(
        "/auth/signup",
        data={
            "email": "h3@example.com",
            "password": "short",
            "password_confirm": "short",
        },
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert resp.status_code == 429
    assert "Too many attempts" in resp.text
    assert resp.headers.get("Retry-After") == "60"
    # HTMX response should be a fragment, not a full page
    assert resp.text.strip().startswith("<p")
    assert "<html" not in resp.text.lower()


# --- Email verification ---


@pytest.mark.integration
async def test_verify_valid_token(auth_app):
    student = Student()
    await student.insert()
    account = Account(
        email="verify@example.com",
        password_hash=_hash_password("password123"),
        student_id=student.id,
    )
    await account.insert()

    token = generate_verify_token(str(account.id))
    resp = auth_app.get(f"/auth/verify?token={token}")
    assert resp.status_code == 200
    assert "verified" in resp.text.lower() or "Verified" in resp.text

    updated = await Account.get(account.id)
    assert updated.email_verified is True


@pytest.mark.integration
async def test_verify_invalid_token(auth_app):
    resp = auth_app.get("/auth/verify?token=garbage.invalid.token")
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()


# --- Forgot password ---


@pytest.mark.integration
async def test_forgot_renders_form(auth_app):
    resp = auth_app.get("/auth/forgot")
    assert resp.status_code == 200
    assert "email" in resp.text.lower()


@pytest.mark.integration
async def test_forgot_post_existing_email(auth_app):
    student = Student()
    await student.insert()
    account = Account(
        email="forgot@example.com",
        password_hash=_hash_password("password123"),
        student_id=student.id,
    )
    await account.insert()

    with patch("maestro.routes.auth.send_reset_email", new_callable=AsyncMock):
        resp = auth_app.post(
            "/auth/forgot",
            data={"email": "forgot@example.com"},
            follow_redirects=False,
        )

    assert resp.status_code == 200
    # Should show success message
    assert "sent" in resp.text.lower() or "link" in resp.text.lower()


@pytest.mark.integration
async def test_forgot_post_nonexistent_email(auth_app):
    """Anti-enumeration: same response for unknown email."""
    resp = auth_app.post(
        "/auth/forgot",
        data={"email": "nobody@example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "sent" in resp.text.lower() or "link" in resp.text.lower()


@pytest.mark.integration
async def test_forgot_rate_limit(auth_app):
    """4th forgot attempt within a minute returns 429."""
    for i in range(3):
        resp = auth_app.post(
            "/auth/forgot",
            data={"email": f"rl{i}@example.com"},
            follow_redirects=False,
        )
        assert resp.status_code != 429, f"Rate limited too early on attempt {i + 1}"

    resp = auth_app.post(
        "/auth/forgot",
        data={"email": "rl3@example.com"},
        follow_redirects=False,
    )
    assert resp.status_code == 429


# --- Password reset ---


@pytest.mark.integration
async def test_reset_valid_token_renders_form(auth_app):
    student = Student()
    await student.insert()
    account = Account(
        email="reset@example.com",
        password_hash=_hash_password("password123"),
        student_id=student.id,
    )
    await account.insert()

    token = generate_reset_token(str(account.id), account.password_hash)
    resp = auth_app.get(f"/auth/reset?token={token}")
    assert resp.status_code == 200
    assert "password" in resp.text.lower()


@pytest.mark.integration
async def test_reset_invalid_token_shows_error(auth_app):
    resp = auth_app.get("/auth/reset?token=garbage.invalid.token")
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()


@pytest.mark.integration
async def test_reset_submit_success(auth_app):
    student = Student()
    await student.insert()
    account = Account(
        email="resetsubmit@example.com",
        password_hash=_hash_password("oldpassword"),
        student_id=student.id,
    )
    await account.insert()

    token = generate_reset_token(str(account.id), account.password_hash)
    resp = auth_app.post(
        "/auth/reset",
        data={
            "token": token,
            "password": "newpassword123",
            "password_confirm": "newpassword123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/auth/login" in resp.headers["location"]

    updated = await Account.get(account.id)
    assert _bcrypt.checkpw(b"newpassword123", updated.password_hash.encode())


@pytest.mark.integration
async def test_reset_submit_expired_token(auth_app):
    student = Student()
    await student.insert()
    account = Account(
        email="expired@example.com",
        password_hash=_hash_password("password123"),
        student_id=student.id,
    )
    await account.insert()

    resp = auth_app.post(
        "/auth/reset",
        data={
            "token": "garbage.invalid.token",
            "password": "newpassword123",
            "password_confirm": "newpassword123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "invalid" in resp.text.lower() or "expired" in resp.text.lower()


@pytest.mark.integration
async def test_reset_submit_password_too_short(auth_app):
    student = Student()
    await student.insert()
    account = Account(
        email="resetshort@example.com",
        password_hash=_hash_password("password123"),
        student_id=student.id,
    )
    await account.insert()

    token = generate_reset_token(str(account.id), account.password_hash)
    resp = auth_app.post(
        "/auth/reset",
        data={"token": token, "password": "short", "password_confirm": "short"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "8 characters" in resp.text


@pytest.mark.integration
async def test_signup_dispatches_emails(auth_app):
    """Signup should dispatch verification and welcome emails."""
    with (
        patch(
            "maestro.routes.auth.send_verification_email", new_callable=AsyncMock
        ) as mock_verify,
        patch(
            "maestro.routes.auth.send_welcome_email", new_callable=AsyncMock
        ) as mock_welcome,
    ):
        resp = auth_app.post(
            "/auth/signup",
            data={
                "email": "dispatch@example.com",
                "password": "password123",
                "password_confirm": "password123",
            },
            follow_redirects=False,
        )

    assert resp.status_code == 303

    from maestro.utils import drain_background_tasks

    await drain_background_tasks()

    mock_verify.assert_awaited_once()
    assert mock_verify.call_args[0][0] == "dispatch@example.com"
    mock_welcome.assert_awaited_once()
    assert mock_welcome.call_args[0][0] == "dispatch@example.com"


@pytest.mark.integration
async def test_login_shows_forgot_link(auth_app):
    resp = auth_app.get("/auth/login")
    assert resp.status_code == 200
    assert "/auth/forgot" in resp.text
