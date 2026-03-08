from fastapi import Request
from beanie import PydanticObjectId

from maestro.models import Account, Student
from maestro.session import read_session


class RedirectToLogin(Exception):
    def __init__(self, clear_cookie: bool = False):
        self.clear_cookie = clear_cookie


async def get_current_student(request: Request) -> Student:
    """Extract student from signed session cookie → Account → Student."""
    payload = read_session(request)
    if payload is None:
        raise RedirectToLogin()

    account_id = payload.get("account_id")
    if not account_id:
        raise RedirectToLogin(clear_cookie=True)

    try:
        account = await Account.get(PydanticObjectId(account_id))
    except Exception:
        account = None
    if account is None:
        raise RedirectToLogin(clear_cookie=True)

    try:
        student = await Student.get(account.student_id)
    except Exception:
        student = None
    if student is None:
        raise RedirectToLogin(clear_cookie=True)

    request.state.student = student
    return student
