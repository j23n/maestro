import logging

import sentry_sdk
from bson.errors import InvalidId
from fastapi import HTTPException, Request
from beanie import PydanticObjectId

from maestro.models import Account, Student
from maestro.session import read_session

logger = logging.getLogger(__name__)


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
    except (InvalidId, ValueError):
        raise RedirectToLogin(clear_cookie=True)  # corrupted session → clear it
    except Exception:
        logger.exception("failed to fetch account from session")
        sentry_sdk.capture_exception()
        raise RedirectToLogin()  # transient error → preserve session
    if account is None:
        raise RedirectToLogin(clear_cookie=True)

    try:
        student = await Student.get(account.student_id)
    except Exception:
        logger.exception("failed to fetch student for account %s", account.id)
        sentry_sdk.capture_exception()
        raise RedirectToLogin()  # transient error → preserve session
    if student is None:
        raise RedirectToLogin(clear_cookie=True)

    request.state.account = account
    request.state.student = student
    return student


async def get_admin_account(request: Request) -> Account:
    """Require an authenticated admin user, otherwise 403."""
    await get_current_student(request)  # sets request.state.account
    if not request.state.account.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return request.state.account
