import bcrypt as _bcrypt

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pymongo.errors import DuplicateKeyError

from maestro.rate_limit import limiter
from maestro.models import Account, Student
from maestro.session import create_session_cookie, clear_session_cookie
from maestro.templates import templates

router = APIRouter(prefix="/auth")


@router.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request):
    return templates.TemplateResponse(
        request=request, name="auth-signup.html", context={"error": None}
    )


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
        return templates.TemplateResponse(
            request=request,
            name="auth-signup.html",
            context={"error": error, "email": email},
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
        return templates.TemplateResponse(
            request=request,
            name="auth-signup.html",
            context={"error": "signup_error_email_taken", "email": email},
        )

    response = RedirectResponse(url="/lezione/", status_code=303)
    create_session_cookie(response, str(account.id))
    return response


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse(
        request=request, name="auth-login.html", context={"error": None}
    )


@router.post("/login", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def login(request: Request):
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""

    account = await Account.find_one({"email": email})
    if not account or not _bcrypt.checkpw(
        password.encode(), account.password_hash.encode()
    ):
        return templates.TemplateResponse(
            request=request,
            name="auth-login.html",
            context={"error": "login_error_invalid", "email": email},
        )

    response = RedirectResponse(url="/lezione/", status_code=303)
    create_session_cookie(response, str(account.id))
    return response


@router.post("/logout", response_class=HTMLResponse)
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    clear_session_cookie(response)
    return response
