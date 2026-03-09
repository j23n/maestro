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
    from maestro.llm import _record_llm_usage
    from maestro.models import CallType

    response = _make_response(
        input_tokens=120, output_tokens=40, model="claude-sonnet-4-6"
    )
    entity_id = PydanticObjectId()
    student_id = PydanticObjectId()

    # Patch LLMUsageRecord.insert so we don't need a real DB
    with patch("maestro.llm.LLMUsageRecord.insert", new_callable=AsyncMock):
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


@pytest.mark.unit
async def test_record_llm_usage_survives_broken_response(caplog):
    """If the response has no .usage, _record_llm_usage does not raise."""
    from beanie import PydanticObjectId
    from maestro.llm import _record_llm_usage
    from maestro.models import CallType

    bad_response = MagicMock(spec=[])  # no attributes
    entity_id = PydanticObjectId()

    with caplog.at_level(logging.DEBUG, logger="maestro.llm"):
        await _record_llm_usage(
            bad_response, entity_id, None, 0.0, CallType.SCORER_SINGLE
        )

    debug_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("record_llm_usage failed" in m for m in debug_msgs)
