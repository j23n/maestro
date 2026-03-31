import bcrypt as _bcrypt
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pymongo.errors import DuplicateKeyError

from maestro.auth import get_current_student, invalidate_profile_cache
from maestro.email import send_verification_email
from maestro.tokens import generate_verify_token
from maestro.utils import create_background_task
from maestro.models import (
    Account,
    DrillAttempt,
    GeneratedDrill,
    LearningEvent,
    LearningProfile,
    Lesson,
    LLMUsageRecord,
    Student,
    UserVocabularyCard,
)
from maestro.rate_limit import limiter
from maestro.session import clear_session_cookie
from maestro.templates import render

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account")


@router.get("", response_class=HTMLResponse)
async def account_page(
    request: Request, student: Student = Depends(get_current_student)
):
    from maestro.language import LANGUAGES

    account: Account = request.state.account
    profile = request.state.profile
    return render(
        request,
        "account.html",
        {
            "student": student,
            "account": account,
            "profile": profile,
            "languages": LANGUAGES,
            "saved": request.query_params.get("saved"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/language")
async def change_language(
    request: Request, student: Student = Depends(get_current_student)
):
    from maestro.language import LANGUAGES
    from maestro.learning.profile import get_or_create_profile

    form = await request.form()
    language = (form.get("language") or "").strip()

    if language not in LANGUAGES:
        return RedirectResponse(
            url="/account?error=account_error_invalid_language", status_code=303
        )

    profile = await get_or_create_profile(student.id)
    profile.target_language = language
    _ = profile.active_progress  # ensure LanguageProgress entry exists for new language
    await profile.save()

    invalidate_profile_cache(student.id)
    logger.info("language changed to %s: student=%s", language, student.id)
    return RedirectResponse(url="/account?saved=language", status_code=303)


@router.post("/name")
async def change_name(
    request: Request, student: Student = Depends(get_current_student)
):
    form = await request.form()
    name = (form.get("name") or "").strip()

    if not name:
        return RedirectResponse(
            url="/account?error=account_error_name_required", status_code=303
        )
    if len(name) > 30:
        return RedirectResponse(
            url="/account?error=account_error_name_too_long", status_code=303
        )

    student.name = name
    await student.save()
    logger.info("name changed: account=%s", request.state.account.id)
    return RedirectResponse(url="/account?saved=name", status_code=303)


@router.post("/email")
@limiter.limit("3/minute")
async def change_email(
    request: Request, student: Student = Depends(get_current_student)
):
    account: Account = request.state.account
    form = await request.form()
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""

    if not email:
        return RedirectResponse(
            url="/account?error=account_error_email_required", status_code=303
        )
    if "@" not in email:
        return RedirectResponse(
            url="/account?error=account_error_email_invalid", status_code=303
        )
    if not _bcrypt.checkpw(password.encode(), account.password_hash.encode()):
        return RedirectResponse(
            url="/account?error=account_error_password_wrong", status_code=303
        )

    # Check for duplicate before saving (unique index is the safety net)
    existing = await Account.find_one(Account.email == email)
    if existing and existing.id != account.id:
        return RedirectResponse(
            url="/account?error=account_error_email_taken", status_code=303
        )

    account.email = email
    account.email_verified = False
    try:
        await account.save()
    except DuplicateKeyError:
        return RedirectResponse(
            url="/account?error=account_error_email_taken", status_code=303
        )

    logger.info("email changed: account=%s", account.id)
    token = generate_verify_token(str(account.id))
    create_background_task(
        send_verification_email(account.email, token), name="verify-email"
    )
    return RedirectResponse(url="/account?saved=email", status_code=303)


@router.post("/password")
@limiter.limit("3/minute")
async def change_password(
    request: Request, student: Student = Depends(get_current_student)
):
    account: Account = request.state.account
    form = await request.form()
    current_password = form.get("current_password") or ""
    new_password = form.get("new_password") or ""
    new_password_confirm = form.get("new_password_confirm") or ""

    if not _bcrypt.checkpw(current_password.encode(), account.password_hash.encode()):
        return RedirectResponse(
            url="/account?error=account_error_password_wrong", status_code=303
        )
    if not new_password:
        return RedirectResponse(
            url="/account?error=account_error_password_required", status_code=303
        )
    if len(new_password) < 8:
        return RedirectResponse(
            url="/account?error=account_error_password_too_short", status_code=303
        )
    if len(new_password) > 128:
        return RedirectResponse(
            url="/account?error=account_error_password_too_long", status_code=303
        )
    if new_password != new_password_confirm:
        return RedirectResponse(
            url="/account?error=account_error_password_mismatch", status_code=303
        )

    account.password_hash = _bcrypt.hashpw(
        new_password.encode(), _bcrypt.gensalt()
    ).decode()
    await account.save()
    logger.info("password changed: account=%s", account.id)
    return RedirectResponse(url="/account?saved=password", status_code=303)


@router.delete("")
async def delete_account(
    request: Request, student: Student = Depends(get_current_student)
):
    """GDPR right to erasure — delete all user data."""
    account: Account = request.state.account
    sid = student.id

    logger.info("account deletion requested: account=%s student=%s", account.id, sid)

    await LearningEvent.find(LearningEvent.student_id == sid).delete()
    await LearningProfile.find(LearningProfile.student_id == sid).delete()
    await Lesson.find(Lesson.student_id == sid).delete()
    await GeneratedDrill.find(GeneratedDrill.student_id == sid).delete()
    await DrillAttempt.find(DrillAttempt.student_id == sid).delete()
    await UserVocabularyCard.find(UserVocabularyCard.student_id == sid).delete()
    await LLMUsageRecord.find(LLMUsageRecord.student_id == sid).delete()
    await student.delete()
    await account.delete()

    logger.info("account deletion complete: account=%s", account.id)

    response = RedirectResponse(url="/", status_code=303)
    clear_session_cookie(response)
    return response


@router.get("/export")
async def export_data(
    request: Request, student: Student = Depends(get_current_student)
):
    """GDPR right to portability — export all user data as JSON."""
    account: Account = request.state.account
    sid = student.id

    profile = await LearningProfile.find_one(LearningProfile.student_id == sid)
    lessons = await Lesson.find(Lesson.student_id == sid).to_list()
    events = await LearningEvent.find(LearningEvent.student_id == sid).to_list()
    cards = await UserVocabularyCard.find(
        UserVocabularyCard.student_id == sid
    ).to_list()

    def _doc(doc):
        """Serialize a Beanie document to a JSON-safe dict."""
        if doc is None:
            return None
        d = doc.model_dump(mode="json")
        d.pop("revision_id", None)
        return d

    account_data = _doc(account)
    account_data.pop("password_hash", None)

    export = {
        "account": account_data,
        "student": _doc(student),
        "learning_profile": _doc(profile),
        "lessons": [_doc(ls) for ls in lessons],
        "learning_events": [_doc(e) for e in events],
        "vocabulary_cards": [_doc(c) for c in cards],
    }

    return JSONResponse(
        content=export,
        headers={
            "Content-Disposition": 'attachment; filename="maestro-export.json"',
        },
    )
