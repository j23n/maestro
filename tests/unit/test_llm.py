"""Unit tests for llm.py — logging, error translation, and client config."""

import logging
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

import httpx


def _make_response(input_tokens=100, output_tokens=50, model="claude-haiku-4-5"):
    """Build a minimal fake Anthropic response with usage."""
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    response = MagicMock()
    response.model = model
    response.usage = usage
    return response


@pytest.mark.unit
async def test_record_llm_usage_emits_structured_log(caplog):
    """_record_llm_usage emits an INFO record with correct extra fields."""
    from beanie import PydanticObjectId
    from unittest.mock import patch, AsyncMock
    from maestro.llm import _record_llm_usage, compute_cost_usd
    from maestro.models import CallType

    response = _make_response(
        input_tokens=120, output_tokens=40, model="claude-sonnet-4-6"
    )
    entity_id = PydanticObjectId()
    student_id = PydanticObjectId()

    mock_record = MagicMock()
    mock_record.insert = AsyncMock()
    with patch("maestro.llm.LLMUsageRecord", return_value=mock_record):
        with caplog.at_level(logging.INFO, logger="maestro.llm"):
            await _record_llm_usage(
                response, entity_id, student_id, 42.5, CallType.LESSON_PLAN
            )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "llm_usage"
    # Extra fields are merged directly into the LogRecord by Python's logging
    assert record.call_type == "lesson_plan"
    assert record.model == "claude-sonnet-4-6"
    assert record.input_tokens == 120
    assert record.output_tokens == 40
    assert record.duration_ms == 42.5
    assert record.entity_id == str(entity_id)
    assert record.student_id == str(student_id)
    expected_cost = compute_cost_usd("claude-sonnet-4-6", 120, 40)
    assert record.cost_usd == pytest.approx(expected_cost)


@pytest.mark.unit
async def test_record_llm_usage_rounds_duration_ms(caplog):
    """_record_llm_usage rounds duration_ms to 1 decimal place."""
    from beanie import PydanticObjectId
    from unittest.mock import patch, AsyncMock
    from maestro.llm import _record_llm_usage
    from maestro.models import CallType

    response = _make_response(model="claude-sonnet-4-6")
    entity_id = PydanticObjectId()

    mock_record = MagicMock()
    mock_record.insert = AsyncMock()
    with patch("maestro.llm.LLMUsageRecord", return_value=mock_record):
        with caplog.at_level(logging.INFO, logger="maestro.llm"):
            await _record_llm_usage(
                response, entity_id, None, 42.56, CallType.LESSON_PLAN
            )

    assert caplog.records[0].duration_ms == pytest.approx(42.6)


@pytest.mark.unit
async def test_record_llm_usage_none_entity_id_logs_warning(caplog):
    """_record_llm_usage with entity_id=None emits the usage log but skips DB insert."""
    from unittest.mock import patch, AsyncMock
    from maestro.llm import _record_llm_usage
    from maestro.models import CallType

    response = _make_response(model="claude-sonnet-4-6")

    mock_record = MagicMock()
    mock_record.insert = AsyncMock()
    with patch("maestro.llm.LLMUsageRecord", return_value=mock_record) as mock_cls:
        with caplog.at_level(logging.WARNING, logger="maestro.llm"):
            await _record_llm_usage(response, None, None, 10.0, CallType.ANALYZER)

    mock_cls.assert_not_called()
    warning_msgs = [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("entity_id is None" in m for m in warning_msgs)


@pytest.mark.unit
async def test_record_llm_usage_survives_broken_response(caplog):
    """If the response has no .usage, _record_llm_usage does not raise."""
    from beanie import PydanticObjectId
    from maestro.llm import _record_llm_usage
    from maestro.models import CallType

    bad_response = MagicMock(spec=[])  # no attributes
    entity_id = PydanticObjectId()

    with caplog.at_level(logging.WARNING, logger="maestro.llm"):
        await _record_llm_usage(
            bad_response, entity_id, None, 0.0, CallType.SCORER_SINGLE
        )

    warning_msgs = [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("failed to extract usage" in m for m in warning_msgs)


@pytest.mark.unit
async def test_llm_messages_create_logs_warning_on_api_failure(caplog):
    """llm_messages_create logs a WARNING and re-raises when the API call fails."""
    from beanie import PydanticObjectId
    from unittest.mock import patch, AsyncMock
    from maestro.llm import llm_messages_create
    from maestro.models import CallType

    entity_id = PydanticObjectId()
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=RuntimeError("timeout"))

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="maestro.llm"):
            with pytest.raises(RuntimeError, match="timeout"):
                await llm_messages_create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    system="Test.",
                    messages=[{"role": "user", "content": "Hello"}],
                    entity_id=entity_id,
                    call_type=CallType.LESSON_PLAN,
                )

    warning_msgs = [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("API call failed" in m for m in warning_msgs)


@pytest.mark.unit
def test_compute_cost_unknown_short_model_logs_warning(caplog):
    """compute_cost_usd warns and uses Sonnet fallback for unversioned model names."""
    from maestro.llm import compute_cost_usd

    with caplog.at_level(logging.WARNING, logger="maestro.llm"):
        cost = compute_cost_usd("claude-haiku-4-5", 1_000_000, 1_000_000)

    sonnet_cost = compute_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert cost == pytest.approx(sonnet_cost)
    assert any("unknown model" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Helpers for constructing Anthropic SDK exceptions
# ---------------------------------------------------------------------------


def _make_anthropic_rate_limit_error():
    """Build an anthropic.RateLimitError with minimal plumbing."""
    import anthropic

    response = httpx.Response(
        429, request=httpx.Request("POST", "https://api.anthropic.com")
    )
    return anthropic.RateLimitError(
        message="rate limited", response=response, body=None
    )


def _make_anthropic_timeout_error():
    """Build an anthropic.APITimeoutError with minimal plumbing."""
    import anthropic

    request = httpx.Request("POST", "https://api.anthropic.com")
    return anthropic.APITimeoutError(request=request)


def _make_anthropic_status_error(status_code: int = 500):
    """Build an anthropic.APIStatusError with minimal plumbing."""
    import anthropic

    response = httpx.Response(
        status_code, request=httpx.Request("POST", "https://api.anthropic.com")
    )
    return anthropic.APIStatusError(
        message=f"Error {status_code}", response=response, body=None
    )


# ---------------------------------------------------------------------------
# Error translation: Anthropic → provider-agnostic
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_llm_messages_create_raises_api_rate_limit_on_429(caplog):
    """Anthropic RateLimitError is translated to APIRateLimitError."""
    from beanie import PydanticObjectId
    from maestro.llm import llm_messages_create
    from maestro.models import CallType
    from maestro.errors import APIRateLimitError

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        side_effect=_make_anthropic_rate_limit_error()
    )

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="maestro.llm"):
            with pytest.raises(APIRateLimitError):
                await llm_messages_create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    system="Test.",
                    messages=[{"role": "user", "content": "Hello"}],
                    entity_id=PydanticObjectId(),
                    call_type=CallType.LESSON_PLAN,
                )

    assert any("llm_rate_limited" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
async def test_llm_messages_create_raises_api_timeout(caplog):
    """Anthropic APITimeoutError is translated to our APITimeoutError."""
    from beanie import PydanticObjectId
    from maestro.llm import llm_messages_create
    from maestro.models import CallType
    from maestro.errors import APITimeoutError

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=_make_anthropic_timeout_error())

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        with caplog.at_level(logging.WARNING, logger="maestro.llm"):
            with pytest.raises(APITimeoutError):
                await llm_messages_create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    system="Test.",
                    messages=[{"role": "user", "content": "Hello"}],
                    entity_id=PydanticObjectId(),
                    call_type=CallType.LESSON_PLAN,
                )

    assert any("llm_timeout" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
async def test_llm_messages_create_raises_api_status_error_on_500(caplog):
    """Anthropic APIStatusError is translated to our APIStatusError."""
    from beanie import PydanticObjectId
    from maestro.llm import llm_messages_create
    from maestro.models import CallType
    from maestro.errors import APIStatusError

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(
        side_effect=_make_anthropic_status_error(500)
    )

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        with caplog.at_level(logging.ERROR, logger="maestro.llm"):
            with pytest.raises(APIStatusError) as exc_info:
                await llm_messages_create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    system="Test.",
                    messages=[{"role": "user", "content": "Hello"}],
                    entity_id=PydanticObjectId(),
                    call_type=CallType.LESSON_PLAN,
                )

    assert exc_info.value.status_code == 500
    assert any("llm_api_error" in r.getMessage() for r in caplog.records)


@pytest.mark.unit
async def test_llm_messages_create_success_passes_through():
    """Normal response is returned unchanged."""
    from beanie import PydanticObjectId
    from maestro.llm import llm_messages_create
    from maestro.models import CallType

    response = _make_response(model="claude-sonnet-4-6")
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=response)

    mock_record = MagicMock()
    mock_record.insert = AsyncMock()

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        with patch("maestro.llm.LLMUsageRecord", return_value=mock_record):
            result = await llm_messages_create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                system="Test.",
                messages=[{"role": "user", "content": "Hello"}],
                entity_id=PydanticObjectId(),
                call_type=CallType.LESSON_PLAN,
            )

    assert result is response


@pytest.mark.unit
async def test_llm_messages_create_preserves_cause_chain():
    """__cause__ of the raised error is the original Anthropic exception."""
    from beanie import PydanticObjectId
    from maestro.llm import llm_messages_create
    from maestro.models import CallType
    from maestro.errors import APIRateLimitError
    import anthropic

    original = _make_anthropic_rate_limit_error()
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=original)

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        with pytest.raises(APIRateLimitError) as exc_info:
            await llm_messages_create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                system="Test.",
                messages=[{"role": "user", "content": "Hello"}],
                entity_id=PydanticObjectId(),
                call_type=CallType.LESSON_PLAN,
            )

    assert isinstance(exc_info.value.__cause__, anthropic.RateLimitError)


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_async_client_has_timeout():
    """get_async_client() returns a client with the expected timeout."""
    from maestro.llm import get_async_client

    get_async_client.cache_clear()
    try:
        client = get_async_client()
        timeout = client.timeout
        assert timeout.connect == 5.0
        assert timeout.read == 60.0 or timeout.pool == 60.0
    finally:
        get_async_client.cache_clear()


@pytest.mark.unit
def test_async_client_max_retries_is_2():
    """max_retries reduced from 3 to 2."""
    from maestro.llm import get_async_client

    get_async_client.cache_clear()
    try:
        client = get_async_client()
        assert client.max_retries == 2
    finally:
        get_async_client.cache_clear()
