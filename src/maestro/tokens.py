from itsdangerous import BadSignature, SignatureExpired

from maestro.session import _get_serializer

VERIFY_MAX_AGE = 24 * 3600  # 24 hours
RESET_MAX_AGE = 3600  # 1 hour


def generate_verify_token(account_id: str) -> str:
    return _get_serializer().dumps(
        {"account_id": account_id, "purpose": "verify"}, salt="email-verify"
    )


def validate_verify_token(token: str) -> str | None:
    """Return account_id or None."""
    try:
        data = _get_serializer().loads(
            token, salt="email-verify", max_age=VERIFY_MAX_AGE
        )
        if data.get("purpose") != "verify":
            return None
        return data["account_id"]
    except (BadSignature, SignatureExpired):
        return None


def generate_reset_token(account_id: str) -> str:
    return _get_serializer().dumps(
        {"account_id": account_id, "purpose": "reset"}, salt="password-reset"
    )


def validate_reset_token(token: str) -> str | None:
    """Return account_id or None."""
    try:
        data = _get_serializer().loads(
            token, salt="password-reset", max_age=RESET_MAX_AGE
        )
        if data.get("purpose") != "reset":
            return None
        return data["account_id"]
    except (BadSignature, SignatureExpired):
        return None
