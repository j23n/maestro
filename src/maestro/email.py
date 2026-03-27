"""Transactional email via Mailjet v3.1 Send API.

Skips silently when MAILJET_API_KEY is not set, so dev/test work without
an email service.
"""

import logging
from functools import lru_cache
from pathlib import Path

import httpx
import jinja2

from maestro.i18n import t

logger = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _PKG_DIR.parent.parent / "templates" / "email"
_CSS_PATH = _PKG_DIR / "static" / "email.css"


@lru_cache(maxsize=1)
def _get_css() -> str:
    try:
        return _CSS_PATH.read_text()
    except FileNotFoundError:
        return ""


@lru_cache(maxsize=1)
def _get_jinja_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )


@lru_cache(maxsize=1)
def _get_client() -> httpx.AsyncClient:
    from maestro.config import settings

    return httpx.AsyncClient(
        base_url="https://api.mailjet.com/v3.1/",
        auth=httpx.BasicAuth(settings.MAILJET_API_KEY, settings.MAILJET_SECRET_KEY),
        timeout=30.0,
    )


def _render(template_name: str, **ctx: str) -> str:
    env = _get_jinja_env()
    tmpl = env.get_template(template_name)
    return tmpl.render(css=_get_css(), t=t, **ctx)


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an email via Mailjet. Returns True on success, False on skip/error."""
    from maestro.config import settings

    if not settings.MAILJET_API_KEY:
        logger.info(
            "MAILJET_API_KEY not set — email not sent:\n  To: %s\n  Subject: %s\n  Body (first 500 chars):\n%s",
            to,
            subject,
            html_body[:500],
        )
        return False

    payload = {
        "Messages": [
            {
                "From": {
                    "Email": settings.MAILJET_FROM_EMAIL.split("<")[-1]
                    .rstrip(">")
                    .strip(),
                    "Name": settings.MAILJET_FROM_EMAIL.split("<")[0].strip()
                    or "Maestro",
                },
                "To": [{"Email": to}],
                "Subject": subject,
                "HTMLPart": html_body,
            }
        ]
    }

    try:
        resp = await _get_client().post("send", json=payload)
        resp.raise_for_status()
        logger.info("email sent to %s subject=%r", to, subject)
        return True
    except httpx.HTTPError as exc:
        logger.error("email send failed to %s: %s", to, exc)
        return False


async def send_verification_email(email: str, token: str) -> bool:
    from maestro.config import settings

    verify_url = f"{settings.SITE_URL.rstrip('/')}/auth/verify?token={token}"
    html_body = _render("verify.html", verify_url=verify_url)
    return await send_email(email, t("email_verify_subject"), html_body)


async def send_reset_email(email: str, token: str) -> bool:
    from maestro.config import settings

    reset_url = f"{settings.SITE_URL.rstrip('/')}/auth/reset?token={token}"
    html_body = _render("reset.html", reset_url=reset_url)
    return await send_email(email, t("email_reset_subject"), html_body)


async def send_welcome_email(email: str) -> bool:
    from maestro.config import settings

    lesson_url = f"{settings.SITE_URL.rstrip('/')}/lezione/"
    html_body = _render("welcome.html", lesson_url=lesson_url)
    return await send_email(email, t("email_welcome_subject"), html_body)
