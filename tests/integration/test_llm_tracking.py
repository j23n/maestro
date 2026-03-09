"""Integration tests for LLM cost tracking: track_llm_call(), LLMUsageRecord, Lesson rollup."""

import pytest
from unittest.mock import MagicMock

from beanie import PydanticObjectId

from maestro.models import CallType, Lesson, LLMUsageRecord, LessonStatus


def _mock_response(model="claude-sonnet-4-6", input_tokens=100, output_tokens=200):
    resp = MagicMock()
    resp.model = model
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


@pytest.mark.asyncio
async def test_track_llm_call_inserts_record(db):
    from maestro.llm import track_llm_call

    await track_llm_call(_mock_response(), CallType.LESSON_PLAN)

    records = await LLMUsageRecord.find_all().to_list()
    assert len(records) == 1
    r = records[0]
    assert r.call_type == CallType.LESSON_PLAN
    assert r.model == "claude-sonnet-4-6"
    assert r.input_tokens == 100
    assert r.output_tokens == 200
    assert r.cost_usd > 0


@pytest.mark.asyncio
async def test_track_llm_call_increments_lesson_cost(db):
    from maestro.llm import track_llm_call

    lesson = Lesson(status=LessonStatus.ACTIVE)
    await lesson.insert()

    await track_llm_call(
        _mock_response(input_tokens=100, output_tokens=200),
        CallType.LESSON_PLAN,
        lesson_id=lesson.id,
    )

    refreshed = await Lesson.get(lesson.id)
    assert refreshed.cost_usd > 0
    assert refreshed.token_usage.input_tokens == 100
    assert refreshed.token_usage.output_tokens == 200


@pytest.mark.asyncio
async def test_track_llm_call_no_lesson_id(db):
    from maestro.llm import track_llm_call

    # Should not raise
    await track_llm_call(_mock_response(), CallType.ANALYZER, lesson_id=None)

    records = await LLMUsageRecord.find_all().to_list()
    assert len(records) == 1
    assert records[0].lesson_id is None


@pytest.mark.asyncio
async def test_track_llm_call_swallows_bad_response(db):
    from maestro.llm import track_llm_call

    bad_response = MagicMock(spec=[])  # no .usage or .model attributes

    # Must not raise
    await track_llm_call(bad_response, CallType.SCORER_SINGLE)

    records = await LLMUsageRecord.find_all().to_list()
    assert len(records) == 0


@pytest.mark.asyncio
async def test_track_llm_call_accumulates_multiple_calls(db):
    from maestro.llm import track_llm_call

    lesson = Lesson(status=LessonStatus.ACTIVE)
    await lesson.insert()

    await track_llm_call(
        _mock_response(input_tokens=100, output_tokens=200),
        CallType.LESSON_PLAN,
        lesson_id=lesson.id,
    )
    await track_llm_call(
        _mock_response(input_tokens=100, output_tokens=200),
        CallType.LESSON_FEEDBACK,
        lesson_id=lesson.id,
    )

    refreshed = await Lesson.get(lesson.id)
    assert refreshed.token_usage.input_tokens == 200
    assert refreshed.token_usage.output_tokens == 400


@pytest.mark.asyncio
async def test_track_llm_call_student_id_stored(db):
    from maestro.llm import track_llm_call

    student_id = PydanticObjectId()
    await track_llm_call(_mock_response(), CallType.ANALYZER, student_id=student_id)

    records = await LLMUsageRecord.find_all().to_list()
    assert len(records) == 1
    assert records[0].student_id == student_id
