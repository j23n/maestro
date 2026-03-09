"""Integration tests for LLM cost tracking: llm_messages_create, LLMUsageRecord."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from beanie import PydanticObjectId

from maestro.models import CallType, LLMUsageRecord


def _mock_anthropic_client(
    model="claude-sonnet-4-6", input_tokens=100, output_tokens=200
):
    """Return a mock AsyncAnthropic client whose messages.create returns a fake response."""
    resp = MagicMock()
    resp.model = model
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    resp.content = [MagicMock(text="{}")]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=resp)
    return mock_client


@pytest.mark.integration
async def test_llm_messages_create_inserts_record(db):
    from maestro.llm import llm_messages_create

    entity_id = PydanticObjectId()
    mock_client = _mock_anthropic_client()

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        await llm_messages_create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            system="Test system prompt.",
            messages=[{"role": "user", "content": "Hello"}],
            entity_id=entity_id,
            call_type=CallType.LESSON_PLAN,
        )

    records = await LLMUsageRecord.find_all().to_list()
    assert len(records) == 1
    r = records[0]
    assert r.call_type == CallType.LESSON_PLAN
    assert r.model == "claude-sonnet-4-6"
    assert r.input_tokens == 100
    assert r.output_tokens == 200
    assert r.cost_usd > 0
    assert r.entity_id == entity_id
    assert r.duration_ms >= 0


@pytest.mark.integration
async def test_llm_messages_create_stores_student_id(db):
    from maestro.llm import llm_messages_create

    entity_id = PydanticObjectId()
    student_id = PydanticObjectId()
    mock_client = _mock_anthropic_client()

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        await llm_messages_create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            system="Test.",
            messages=[{"role": "user", "content": "Hello"}],
            entity_id=entity_id,
            call_type=CallType.ANALYZER,
            student_id=student_id,
        )

    records = await LLMUsageRecord.find_all().to_list()
    assert len(records) == 1
    assert records[0].student_id == student_id
    assert records[0].entity_id == entity_id


@pytest.mark.integration
async def test_llm_messages_create_swallows_bad_response(db):
    from maestro.llm import llm_messages_create

    entity_id = PydanticObjectId()
    bad_resp = MagicMock(spec=[])  # no .usage or .model attributes
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=bad_resp)

    # Must not raise — swallows tracking errors
    with patch("maestro.llm.get_async_client", return_value=mock_client):
        result = await llm_messages_create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            system="Test.",
            messages=[{"role": "user", "content": "Hello"}],
            entity_id=entity_id,
            call_type=CallType.SCORER_SINGLE,
        )

    assert result is bad_resp
    records = await LLMUsageRecord.find_all().to_list()
    assert len(records) == 0


@pytest.mark.integration
async def test_llm_messages_create_returns_response(db):
    from maestro.llm import llm_messages_create

    entity_id = PydanticObjectId()
    mock_client = _mock_anthropic_client()

    with patch("maestro.llm.get_async_client", return_value=mock_client):
        result = await llm_messages_create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            system="Test.",
            messages=[{"role": "user", "content": "Hello"}],
            entity_id=entity_id,
            call_type=CallType.LESSON_PLAN,
        )

    assert result is mock_client.messages.create.return_value
