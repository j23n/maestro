"""Unit tests for llm.py — logging via _record_llm_usage."""

import logging
import pytest
from unittest.mock import MagicMock


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
