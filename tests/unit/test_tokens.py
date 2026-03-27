import pytest


@pytest.fixture(autouse=True)
def reset_serializer():
    import maestro.session

    maestro.session._serializer = None
    yield
    maestro.session._serializer = None


@pytest.mark.unit
def test_verify_token_roundtrip():
    from maestro.tokens import generate_verify_token, validate_verify_token

    token = generate_verify_token("abc123")
    assert validate_verify_token(token) == "abc123"


@pytest.mark.unit
def test_reset_token_roundtrip():
    from maestro.tokens import generate_reset_token, validate_reset_token

    token = generate_reset_token("xyz789")
    assert validate_reset_token(token) == "xyz789"


@pytest.mark.unit
def test_verify_token_cross_purpose_rejected():
    """A verify token must not validate as a reset token."""
    from maestro.tokens import generate_verify_token, validate_reset_token

    token = generate_verify_token("abc123")
    assert validate_reset_token(token) is None


@pytest.mark.unit
def test_reset_token_cross_purpose_rejected():
    """A reset token must not validate as a verify token."""
    from maestro.tokens import generate_reset_token, validate_verify_token

    token = generate_reset_token("abc123")
    assert validate_verify_token(token) is None


@pytest.mark.unit
def test_tampered_token_returns_none():
    from maestro.tokens import validate_verify_token, validate_reset_token

    assert validate_verify_token("tampered.garbage.value") is None
    assert validate_reset_token("tampered.garbage.value") is None


@pytest.mark.unit
def test_expired_verify_token(monkeypatch):
    from maestro import tokens
    from maestro.tokens import generate_verify_token, validate_verify_token

    token = generate_verify_token("abc123")
    # Use a negative max_age so the token is always considered expired
    monkeypatch.setattr(tokens, "VERIFY_MAX_AGE", -1)
    assert validate_verify_token(token) is None


@pytest.mark.unit
def test_expired_reset_token(monkeypatch):
    from maestro import tokens
    from maestro.tokens import generate_reset_token, validate_reset_token

    token = generate_reset_token("abc123")
    monkeypatch.setattr(tokens, "RESET_MAX_AGE", -1)
    assert validate_reset_token(token) is None
