"""Double-submit cookie CSRF protection middleware."""

import logging
import secrets
from urllib.parse import parse_qs

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = logging.getLogger(__name__)

COOKIE_NAME = "csrftoken"
HEADER_NAME = "x-csrftoken"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, cookie_secure: bool = False):
        super().__init__(app)
        self.cookie_secure = cookie_secure

    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE_METHODS:
            csrf_cookie = request.cookies.get(COOKIE_NAME, "")
            # Check header first (HTMX requests)
            csrf_token = request.headers.get(HEADER_NAME, "")
            # Fall back to form body (plain form submissions)
            if not csrf_token:
                content_type = request.headers.get("content-type", "")
                if "application/x-www-form-urlencoded" in content_type:
                    body = await request.body()
                    params = parse_qs(body.decode("utf-8"))
                    csrf_token = params.get(COOKIE_NAME, [""])[0]

            if not csrf_cookie or not csrf_token or not secrets.compare_digest(csrf_token, csrf_cookie):
                log.warning("CSRF validation failed: %s %s", request.method, request.url.path)
                return Response("CSRF token missing or invalid", status_code=403)

        response = await call_next(request)

        if COOKIE_NAME not in request.cookies:
            response.set_cookie(
                COOKIE_NAME,
                secrets.token_urlsafe(32),
                httponly=False,  # JS needs to read it
                samesite="lax",
                secure=self.cookie_secure,
                path="/",
            )

        return response
