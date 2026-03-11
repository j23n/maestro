"""Unit tests for the provider-agnostic exception hierarchy in maestro.errors."""

import pytest

from maestro.errors import (
    APIUnavailableError,
    APIRateLimitError,
    APITimeoutError,
    APIStatusError,
)


# ---------------------------------------------------------------------------
# Subclass relationships
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_rate_limit_is_api_unavailable():
    assert issubclass(APIRateLimitError, APIUnavailableError)


@pytest.mark.unit
def test_api_timeout_is_api_unavailable():
    assert issubclass(APITimeoutError, APIUnavailableError)


@pytest.mark.unit
def test_api_status_error_is_api_unavailable():
    assert issubclass(APIStatusError, APIUnavailableError)


# ---------------------------------------------------------------------------
# Message and provider accessible
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_api_unavailable_str():
    err = APIUnavailableError("something broke", provider="anthropic")
    assert "something broke" in str(err)
    assert err.provider == "anthropic"


@pytest.mark.unit
def test_api_rate_limit_default_provider():
    err = APIRateLimitError("rate limited")
    assert err.provider is None
    assert "rate limited" in str(err)


@pytest.mark.unit
def test_api_status_error_carries_status_code():
    err = APIStatusError("server error", status_code=500, provider="azure")
    assert err.status_code == 500
    assert err.provider == "azure"


@pytest.mark.unit
def test_api_timeout_message():
    err = APITimeoutError("timed out after 60s", provider="anthropic")
    assert "timed out" in str(err)
