import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from maestro.auth import get_current_student
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
from maestro.session import clear_session_cookie

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/account")


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
