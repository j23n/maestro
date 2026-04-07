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

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates" / "email"


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
    return tmpl.render(t=t, **ctx)


def _parse_from_email(raw: str) -> tuple[str, str]:
    """Parse 'Name <addr>' or plain 'addr' into (email, name)."""
    if "<" in raw and ">" in raw:
        name = raw.split("<")[0].strip()
        email = raw.split("<")[1].rstrip(">").strip()
        return email, name or "Maestro"
    return raw.strip(), "Maestro"


async def send_email(
    to: str, subject: str, html_body: str, text_body: str = ""
) -> bool:
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

    from_email, from_name = _parse_from_email(settings.MAILJET_FROM_EMAIL)
    message: dict = {
        "From": {"Email": from_email, "Name": from_name},
        "To": [{"Email": to}],
        "Subject": subject,
        "HTMLPart": html_body,
    }
    if text_body:
        message["TextPart"] = text_body

    payload = {"Messages": [message]}

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
    text_body = (
        f"{t('email_verify_heading')}\n\n"
        f"{t('email_verify_body')}\n\n"
        f"{verify_url}\n\n"
        f"{t('email_verify_note')}"
    )
    return await send_email(email, t("email_verify_subject"), html_body, text_body)


async def send_reset_email(email: str, token: str) -> bool:
    from maestro.config import settings

    reset_url = f"{settings.SITE_URL.rstrip('/')}/auth/reset?token={token}"
    html_body = _render("reset.html", reset_url=reset_url)
    text_body = (
        f"{t('email_reset_heading')}\n\n"
        f"{t('email_reset_body')}\n\n"
        f"{reset_url}\n\n"
        f"{t('email_reset_note')}"
    )
    return await send_email(email, t("email_reset_subject"), html_body, text_body)


async def send_interest_confirm_email(email: str, token: str) -> bool:
    from maestro.config import settings

    confirm_url = f"{settings.SITE_URL.rstrip('/')}/register-interest/confirm/{token}"
    html_body = _render("interest_confirm.html", confirm_url=confirm_url)
    text_body = (
        f"Thanks for your interest in Maestro!\n\n"
        f"Please confirm your email address by visiting:\n\n"
        f"{confirm_url}\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )
    return await send_email(
        email, "Confirm your interest in Maestro", html_body, text_body
    )


async def send_welcome_email(email: str) -> bool:
    from maestro.config import settings

    lesson_url = f"{settings.SITE_URL.rstrip('/')}/lessons/"
    html_body = _render("welcome.html", lesson_url=lesson_url)
    text_body = (
        f"{t('email_welcome_heading')}\n\n{t('email_welcome_body')}\n\n{lesson_url}"
    )
    return await send_email(email, t("email_welcome_subject"), html_body, text_body)
