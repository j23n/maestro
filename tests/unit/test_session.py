import pytest
from starlette.requests import Request
from starlette.responses import Response


@pytest.fixture(autouse=True)
def reset_serializer():
    """Reset the cached serializer between tests."""
    import maestro.session
    maestro.session._serializer = None
    yield
    maestro.session._serializer = None


@pytest.mark.unit
def test_create_and_read_session_roundtrip():
    """Signed cookie can be created and read back."""
    from maestro.session import create_session_cookie, read_session

    response = Response()
    create_session_cookie(response, "abc123")

    # Extract the cookie value from the response
    cookie_header = response.headers.get("set-cookie")
    assert cookie_header is not None
    token = cookie_header.split("=", 1)[1].split(";")[0]

    # Build a mock request with the cookie
    scope = {"type": "http", "headers": [(b"cookie", f"session={token}".encode())]}
    request = Request(scope)

    payload = read_session(request)
    assert payload is not None
    assert payload["account_id"] == "abc123"


@pytest.mark.unit
def test_tampered_token_returns_none():
    """A tampered token should return None."""
    from maestro.session import read_session

    scope = {"type": "http", "headers": [(b"cookie", b"session=tampered.garbage.value")]}
    request = Request(scope)

    assert read_session(request) is None


@pytest.mark.unit
def test_missing_cookie_returns_none():
    """No session cookie should return None."""
    from maestro.session import read_session

    scope = {"type": "http", "headers": []}
    request = Request(scope)

    assert read_session(request) is None


@pytest.mark.unit
def test_clear_session_cookie():
    """clear_session_cookie should delete the session cookie."""
    from maestro.session import clear_session_cookie

    response = Response()
    clear_session_cookie(response)

    cookie_header = response.headers.get("set-cookie")
    assert cookie_header is not None
    assert "session=" in cookie_header
    # Deletion sets max-age=0
    assert 'Max-Age=0' in cookie_header or 'max-age=0' in cookie_header.lower()
