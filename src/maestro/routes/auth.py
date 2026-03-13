import bcrypt as _bcrypt
import hashlib
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pymongo.errors import DuplicateKeyError

from maestro.rate_limit import limiter
from maestro.models import Account, Student
from maestro.session import create_session_cookie, clear_session_cookie, read_session
from maestro.templates import render_with_discover

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")


def _masked_email(email: str) -> str:
    if "@" not in email:
        return "<invalid>"
    local, domain = email.rsplit("@", 1)
    return f"{hashlib.sha256(local.encode()).hexdigest()[:8]}@{domain}"


@router.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    return await render_with_discover(request, "auth-signup.html", {"error": None})


@router.post("/signup", response_class=HTMLResponse)
@limiter.limit("3/minute")
async def signup(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    password_confirm = form.get("password_confirm") or ""

    # Validation
    error = None
    if not email:
        error = "signup_error_email_required"
    elif "@" not in email:
        error = "signup_error_email_invalid"
    elif not password:
        error = "signup_error_password_required"
    elif len(password) < 8:
        error = "signup_error_password_too_short"
    elif len(password) > 128:
        error = "signup_error_password_too_long"
    elif password != password_confirm:
        error = "signup_error_password_mismatch"

    if error:
        logger.warning("signup failed: %s", error)
        return await render_with_discover(
            request, "auth-signup.html", {"error": error, "email": email}
        )

    # Create student + account (unique index catches race conditions)
    student = Student()
    await student.insert()
    account = Account(
        email=email,
        password_hash=_bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode(),
        student_id=student.id,
    )
    try:
        await account.insert()
    except DuplicateKeyError:
        await student.delete()
        logger.warning("signup failed: duplicate email %s", _masked_email(email))
        return await render_with_discover(
            request,
            "auth-signup.html",
            {"error": "signup_error_email_taken", "email": email},
        )

    logger.info("signup success: %s", account.id)
    response = RedirectResponse(url="/lezione/", status_code=303)
    create_session_cookie(response, str(account.id))
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return await render_with_discover(request, "auth-login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def login(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""

    account = await Account.find_one({"email": email})
    if not account:
        # Dummy check keeps response time constant regardless of account existence
        _bcrypt.checkpw(password.encode(), _bcrypt.hashpw(b"dummy", _bcrypt.gensalt()))
        logger.warning("login failed: account not found for %s", _masked_email(email))
        return await render_with_discover(
            request, "auth-login.html", {"error": "login_error_invalid", "email": email}
        )
    if not _bcrypt.checkpw(password.encode(), account.password_hash.encode()):
        logger.warning("login failed: invalid credentials for %s", account.id)
        return await render_with_discover(
            request, "auth-login.html", {"error": "login_error_invalid", "email": email}
        )

    logger.info("login success: %s", account.id)
    response = RedirectResponse(url="/lezione/", status_code=303)
    create_session_cookie(response, str(account.id))
    return response


@router.post("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    payload = read_session(request)
    logger.info(
        "logout: account=%s", payload.get("account_id") if payload else "anonymous"
    )
    response = RedirectResponse(url="/", status_code=303)
    clear_session_cookie(response)
    return response
