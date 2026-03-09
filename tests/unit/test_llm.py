"""Unit tests for llm.py — log_llm_usage helper."""

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
def test_log_llm_usage_emits_structured_log(caplog):
    """log_llm_usage emits an INFO record with correct extra fields."""
    from maestro.llm import log_llm_usage

    response = _make_response(input_tokens=120, output_tokens=40)

    with caplog.at_level(logging.INFO, logger="maestro.llm"):
        log_llm_usage(response, "plan", student_id="abc123", lesson_id="def456")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "llm_usage"
    assert record.call_type == "plan"
    assert record.model == "claude-haiku-4-5"
    assert record.input_tokens == 120
    assert record.output_tokens == 40
    assert record.student_id == "abc123"
    assert record.lesson_id == "def456"


@pytest.mark.unit
def test_log_llm_usage_omits_none_ids(caplog):
    """When student_id/lesson_id are None, those keys are absent from the log record."""
    from maestro.llm import log_llm_usage

    response = _make_response()

    with caplog.at_level(logging.INFO, logger="maestro.llm"):
        log_llm_usage(response, "vocab_definitions")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert not hasattr(record, "student_id")
    assert not hasattr(record, "lesson_id")


@pytest.mark.unit
def test_log_llm_usage_ids_cast_to_str(caplog):
    """student_id and lesson_id are cast to str (e.g. ObjectId → hex string)."""
    from maestro.llm import log_llm_usage

    response = _make_response()

    class FakeId:
        def __str__(self):
            return "deadbeef"

    with caplog.at_level(logging.INFO, logger="maestro.llm"):
        log_llm_usage(response, "score", student_id=FakeId(), lesson_id=FakeId())

    record = caplog.records[0]
    assert record.student_id == "deadbeef"
    assert record.lesson_id == "deadbeef"


@pytest.mark.unit
def test_log_llm_usage_survives_broken_response(caplog):
    """If the response has no .usage, log_llm_usage does not raise."""
    from maestro.llm import log_llm_usage

    bad_response = MagicMock(spec=[])  # no attributes

    with caplog.at_level(logging.DEBUG, logger="maestro.llm"):
        log_llm_usage(bad_response, "plan")  # must not raise

    # The failure is logged at DEBUG, not raised
    debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("log_llm_usage failed" in m for m in debug_msgs)
