from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request
from fastapi.responses import Response

_serializer = None

SESSION_COOKIE = "session"
MAX_AGE = 30 * 24 * 3600  # 30 days


def _get_serializer() -> URLSafeTimedSerializer:
    global _serializer
    if _serializer is None:
        from maestro.config import settings
        _serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
    return _serializer


def create_session_cookie(response: Response, account_id: str) -> None:
    from maestro.config import settings
    token = _get_serializer().dumps({"account_id": account_id})
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
    )


def read_session(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        return _get_serializer().loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def clear_session_cookie(response: Response) -> None:
    from maestro.config import settings
    response.delete_cookie(
        SESSION_COOKIE,
        httponly=True,
        samesite="lax",
        secure=settings.ENVIRONMENT == "production",
    )
