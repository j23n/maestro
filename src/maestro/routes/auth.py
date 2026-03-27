import bcrypt as _bcrypt
import hashlib
import logging

from beanie import PydanticObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pymongo.errors import DuplicateKeyError

from maestro.email import send_reset_email, send_verification_email, send_welcome_email
from maestro.rate_limit import limiter
from maestro.models import Account, Student
from maestro.session import create_session_cookie, clear_session_cookie, read_session
from maestro.templates import render, render_with_discover
from maestro.tokens import (
    generate_reset_token,
    generate_verify_token,
    validate_reset_token,
    validate_verify_token,
)
from maestro.utils import create_background_task

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
    token = generate_verify_token(str(account.id))
    create_background_task(
        send_verification_email(account.email, token), name="verify-email"
    )
    create_background_task(send_welcome_email(account.email), name="welcome-email")
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


@router.get("/verify", response_class=HTMLResponse)
async def verify_email(request: Request):
    token = request.query_params.get("token", "")
    account_id = validate_verify_token(token)
    if not account_id:
        return render(request, "auth-verify-result.html", {"success": False})

    try:
        account = await Account.get(PydanticObjectId(account_id))
    except (InvalidId, ValueError):
        account = None
    if not account:
        return render(request, "auth-verify-result.html", {"success": False})

    account.email_verified = True
    await account.save()
    logger.info("email verified: account=%s", account.id)
    return render(request, "auth-verify-result.html", {"success": True})


@router.get("/forgot", response_class=HTMLResponse)
async def forgot_form(request: Request):
    return render(request, "auth-forgot.html", {"sent": False})


@router.post("/forgot", response_class=HTMLResponse)
@limiter.limit("3/minute")
async def forgot_submit(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()

    account = await Account.find_one({"email": email})
    if account:
        token = generate_reset_token(str(account.id))
        create_background_task(
            send_reset_email(account.email, token), name="reset-email"
        )
    else:
        logger.info("forgot password: no account for %s", _masked_email(email))

    # Always show same response (anti-enumeration)
    return render(request, "auth-forgot.html", {"sent": True})


@router.get("/reset", response_class=HTMLResponse)
async def reset_form(request: Request):
    token = request.query_params.get("token", "")
    account_id = validate_reset_token(token)
    if not account_id:
        return render(
            request, "auth-reset.html", {"error": "reset_error_invalid", "token": ""}
        )
    return render(request, "auth-reset.html", {"error": None, "token": token})


@router.post("/reset", response_class=HTMLResponse)
async def reset_submit(request: Request):
    form = await request.form()
    token = form.get("token") or ""
    password = form.get("password") or ""
    password_confirm = form.get("password_confirm") or ""

    account_id = validate_reset_token(token)
    if not account_id:
        return render(
            request, "auth-reset.html", {"error": "reset_error_invalid", "token": ""}
        )

    error = None
    if not password:
        error = "reset_error_password_required"
    elif len(password) < 8:
        error = "reset_error_password_too_short"
    elif len(password) > 128:
        error = "reset_error_password_too_long"
    elif password != password_confirm:
        error = "reset_error_password_mismatch"

    if error:
        return render(request, "auth-reset.html", {"error": error, "token": token})

    try:
        account = await Account.get(PydanticObjectId(account_id))
    except (InvalidId, ValueError):
        account = None
    if not account:
        return render(
            request, "auth-reset.html", {"error": "reset_error_invalid", "token": ""}
        )

    account.password_hash = _bcrypt.hashpw(
        password.encode(), _bcrypt.gensalt()
    ).decode()
    await account.save()
    logger.info("password reset: account=%s", account.id)
    return RedirectResponse(url="/auth/login?reset=1", status_code=303)
