import hashlib

from itsdangerous import BadSignature, SignatureExpired

from maestro.session import get_serializer

VERIFY_MAX_AGE = 24 * 3600  # 24 hours
RESET_MAX_AGE = 3600  # 1 hour


def _pw_fingerprint(password_hash: str) -> str:
    """Short hash of the password_hash — changes when the password changes."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def generate_verify_token(account_id: str) -> str:
    return get_serializer().dumps(
        {"account_id": account_id, "purpose": "verify"}, salt="email-verify"
    )


def validate_verify_token(token: str) -> str | None:
    """Return account_id or None."""
    try:
        data = get_serializer().loads(
            token, salt="email-verify", max_age=VERIFY_MAX_AGE
        )
        if data.get("purpose") != "verify":
            return None
        return data["account_id"]
    except (BadSignature, SignatureExpired):
        return None


def generate_reset_token(account_id: str, password_hash: str) -> str:
    return get_serializer().dumps(
        {
            "account_id": account_id,
            "purpose": "reset",
            "pwfp": _pw_fingerprint(password_hash),
        },
        salt="password-reset",
    )


def decode_reset_token(token: str) -> str | None:
    """Return account_id from a reset token (signature + expiry check only).

    Use for the GET form — shows the form if the token is structurally valid.
    The POST handler must call validate_reset_token to also check the
    password fingerprint.
    """
    try:
        data = get_serializer().loads(
            token, salt="password-reset", max_age=RESET_MAX_AGE
        )
        if data.get("purpose") != "reset":
            return None
        return data["account_id"]
    except (BadSignature, SignatureExpired):
        return None


def validate_reset_token(token: str, password_hash: str) -> str | None:
    """Return account_id or None. Rejects token if password has changed since issuance."""
    try:
        data = get_serializer().loads(
            token, salt="password-reset", max_age=RESET_MAX_AGE
        )
        if data.get("purpose") != "reset":
            return None
        if data.get("pwfp") != _pw_fingerprint(password_hash):
            return None
        return data["account_id"]
    except (BadSignature, SignatureExpired):
        return None
