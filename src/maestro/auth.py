import logging
import time

import sentry_sdk
from bson.errors import InvalidId
from fastapi import HTTPException, Request
from beanie import PydanticObjectId

from maestro.language import get_language_config
from maestro.models import Account, Student
from maestro.session import read_session

logger = logging.getLogger(__name__)

# Short-lived per-student profile cache to avoid a DB round-trip on every
# authenticated request.  Entries expire after _PROFILE_TTL seconds.
_PROFILE_TTL = 60  # seconds
_profile_cache: dict[
    PydanticObjectId, tuple[float, object]
] = {}  # student_id → (ts, profile)


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

    # Load profile and resolve per-student language config.
    # Uses a short-lived in-memory cache to avoid a DB query on every request.
    now = time.monotonic()
    cached = _profile_cache.get(student.id)
    if cached and (now - cached[0]) < _PROFILE_TTL:
        profile = cached[1]
    else:
        from maestro.learning.profile import get_or_create_profile

        profile = await get_or_create_profile(student.id)
        _profile_cache[student.id] = (now, profile)

    request.state.profile = profile
    request.state.lang_ctx = get_language_config(profile.target_language)

    return student


async def get_admin_account(request: Request) -> Account:
    """Require an authenticated admin user, otherwise 403."""
    await get_current_student(request)  # sets request.state.account
    if not request.state.account.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return request.state.account
