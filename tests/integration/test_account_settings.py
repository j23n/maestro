import bcrypt as _bcrypt

import pytest

from maestro.models import Account, Student


def _hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


# ── GET /account ──


@pytest.mark.integration
async def test_account_page_renders(test_app, student, account):
    resp = test_app.get("/account")
    assert resp.status_code == 200
    assert "Account settings" in resp.text or "account" in resp.text.lower()
    assert student.name in resp.text
    assert account.email in resp.text


@pytest.mark.integration
async def test_account_page_unauthenticated(auth_app):
    resp = auth_app.get("/account", follow_redirects=True)
    # Should end up at login page
    assert "/auth/login" in str(resp.url)


# ── POST /account/name ──


@pytest.mark.integration
async def test_change_name_success(test_app, student):
    resp = test_app.post(
        "/account/name",
        data={"name": "New Name"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/account?saved=name"

    updated = await Student.get(student.id)
    assert updated.name == "New Name"


@pytest.mark.integration
async def test_change_name_empty(test_app, student):
    resp = test_app.post(
        "/account/name",
        data={"name": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=account_error_name_required" in resp.headers["location"]

    # Name unchanged
    updated = await Student.get(student.id)
    assert updated.name == student.name


@pytest.mark.integration
async def test_change_name_too_long(test_app, student):
    resp = test_app.post(
        "/account/name",
        data={"name": "A" * 31},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=account_error_name_too_long" in resp.headers["location"]


# ── POST /account/email ──


@pytest.mark.integration
async def test_change_email_success(test_app, account):
    # Need a real password hash for the account
    account.password_hash = _hash_password("password123")
    await account.save()

    resp = test_app.post(
        "/account/email",
        data={"email": "new@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/account?saved=email"

    updated = await Account.get(account.id)
    assert updated.email == "new@example.com"
    assert updated.email_verified is False


@pytest.mark.integration
async def test_change_email_wrong_password(test_app, account):
    account.password_hash = _hash_password("password123")
    await account.save()

    resp = test_app.post(
        "/account/email",
        data={"email": "new@example.com", "password": "wrongpassword"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=account_error_password_wrong" in resp.headers["location"]

    # Email unchanged
    updated = await Account.get(account.id)
    assert updated.email == "test@example.com"


@pytest.mark.integration
async def test_change_email_invalid(test_app, account):
    account.password_hash = _hash_password("password123")
    await account.save()

    resp = test_app.post(
        "/account/email",
        data={"email": "not-an-email", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=account_error_email_invalid" in resp.headers["location"]


@pytest.mark.integration
async def test_change_email_duplicate(test_app, account):
    account.password_hash = _hash_password("password123")
    await account.save()

    # Create another account with the target email
    other_student = Student(name="Other")
    await other_student.insert()
    other_account = Account(
        email="taken@example.com",
        password_hash=_hash_password("other"),
        student_id=other_student.id,
    )
    await other_account.insert()

    resp = test_app.post(
        "/account/email",
        data={"email": "taken@example.com", "password": "password123"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=account_error_email_taken" in resp.headers["location"]


# ── POST /account/password ──


@pytest.mark.integration
async def test_change_password_success(test_app, account):
    account.password_hash = _hash_password("oldpassword1")
    await account.save()

    resp = test_app.post(
        "/account/password",
        data={
            "current_password": "oldpassword1",
            "new_password": "newpassword1",
            "new_password_confirm": "newpassword1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/account?saved=password"

    updated = await Account.get(account.id)
    assert _bcrypt.checkpw(b"newpassword1", updated.password_hash.encode())


@pytest.mark.integration
async def test_change_password_wrong_current(test_app, account):
    account.password_hash = _hash_password("oldpassword1")
    await account.save()

    resp = test_app.post(
        "/account/password",
        data={
            "current_password": "wrongpassword",
            "new_password": "newpassword1",
            "new_password_confirm": "newpassword1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=account_error_password_wrong" in resp.headers["location"]


@pytest.mark.integration
async def test_change_password_too_short(test_app, account):
    account.password_hash = _hash_password("oldpassword1")
    await account.save()

    resp = test_app.post(
        "/account/password",
        data={
            "current_password": "oldpassword1",
            "new_password": "short",
            "new_password_confirm": "short",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=account_error_password_too_short" in resp.headers["location"]


@pytest.mark.integration
async def test_change_password_mismatch(test_app, account):
    account.password_hash = _hash_password("oldpassword1")
    await account.save()

    resp = test_app.post(
        "/account/password",
        data={
            "current_password": "oldpassword1",
            "new_password": "newpassword1",
            "new_password_confirm": "different999",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=account_error_password_mismatch" in resp.headers["location"]


# ── Unauthenticated access ──


@pytest.mark.integration
async def test_change_name_unauthenticated(auth_app):
    resp = auth_app.post(
        "/account/name",
        data={"name": "Hacker"},
        follow_redirects=True,
    )
    assert "/auth/login" in str(resp.url)


@pytest.mark.integration
async def test_change_email_unauthenticated(auth_app):
    resp = auth_app.post(
        "/account/email",
        data={"email": "hack@example.com", "password": "x"},
        follow_redirects=True,
    )
    assert "/auth/login" in str(resp.url)


@pytest.mark.integration
async def test_change_password_unauthenticated(auth_app):
    resp = auth_app.post(
        "/account/password",
        data={
            "current_password": "x",
            "new_password": "y",
            "new_password_confirm": "y",
        },
        follow_redirects=True,
    )
    assert "/auth/login" in str(resp.url)
