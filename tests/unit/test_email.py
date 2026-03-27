import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx


@pytest.fixture(autouse=True)
def reset_caches():
    from maestro.email import _get_client, _get_jinja_env, _get_css

    _get_client.cache_clear()
    _get_jinja_env.cache_clear()
    _get_css.cache_clear()
    yield
    _get_client.cache_clear()
    _get_jinja_env.cache_clear()
    _get_css.cache_clear()


@pytest.mark.unit
async def test_send_email_skips_when_no_api_key():
    """send_email returns False and makes no HTTP call when MAILJET_API_KEY is empty."""
    from maestro.email import send_email

    with patch("maestro.email._get_client") as mock_get_client:
        result = await send_email("user@example.com", "Subject", "<p>Body</p>")

    assert result is False
    mock_get_client.assert_not_called()


@pytest.mark.unit
async def test_send_email_success():
    """send_email returns True and POSTs to Mailjet on success."""
    from maestro.email import send_email

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with (
        patch("maestro.config.settings.MAILJET_API_KEY", "test-key"),
        patch("maestro.email._get_client", return_value=mock_client),
    ):
        result = await send_email("user@example.com", "Test Subject", "<p>Hello</p>")

    assert result is True
    mock_client.post.assert_awaited_once()
    call_kwargs = mock_client.post.call_args
    payload = (
        call_kwargs.kwargs.get("json") or call_kwargs.args[1]
        if len(call_kwargs.args) > 1
        else call_kwargs.kwargs["json"]
    )
    assert "Messages" in payload
    assert payload["Messages"][0]["To"][0]["Email"] == "user@example.com"
    assert payload["Messages"][0]["Subject"] == "Test Subject"


@pytest.mark.unit
async def test_send_email_http_error():
    """send_email returns False on HTTP error."""
    from maestro.email import send_email

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "400 Bad Request",
            request=httpx.Request("POST", "https://api.mailjet.com/v3.1/send"),
            response=httpx.Response(400),
        )
    )

    with (
        patch("maestro.config.settings.MAILJET_API_KEY", "test-key"),
        patch("maestro.email._get_client", return_value=mock_client),
    ):
        result = await send_email("user@example.com", "Subject", "<p>Body</p>")

    assert result is False
