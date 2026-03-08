import asyncio
import pytest

from maestro.utils import parse_llm_json, create_background_task, strip_lang_spans


@pytest.mark.unit
def test_strip_lang_spans_removes_tags():
    assert strip_lang_spans('<span lang="it">ciao</span>') == "ciao"


@pytest.mark.unit
def test_strip_lang_spans_preserves_other_html():
    assert strip_lang_spans("<p>hello</p>") == "<p>hello</p>"


@pytest.mark.unit
def test_plain_object():
    assert parse_llm_json('{"a": 1}') == {"a": 1}


@pytest.mark.unit
def test_plain_array():
    assert parse_llm_json("[1, 2, 3]") == [1, 2, 3]


@pytest.mark.unit
def test_markdown_fenced_json():
    text = '```json\n{"key": "value"}\n```'
    assert parse_llm_json(text) == {"key": "value"}


@pytest.mark.unit
def test_markdown_fenced_no_lang():
    text = '```\n{"key": "value"}\n```'
    assert parse_llm_json(text) == {"key": "value"}


@pytest.mark.unit
def test_preamble_then_json():
    text = 'Here is the result:\n{"answer": 42}'
    assert parse_llm_json(text) == {"answer": 42}


@pytest.mark.unit
def test_invalid_json_returns_none():
    assert parse_llm_json("{invalid json}") is None


@pytest.mark.unit
def test_empty_string_returns_none():
    assert parse_llm_json("") is None


@pytest.mark.unit
def test_no_json_returns_none():
    assert parse_llm_json("just some plain text") is None


@pytest.mark.unit
def test_nested_objects():
    text = '{"outer": {"inner": [1, 2]}}'
    result = parse_llm_json(text)
    assert result == {"outer": {"inner": [1, 2]}}


@pytest.mark.unit
def test_array_of_objects():
    text = '[{"a": 1}, {"b": 2}]'
    result = parse_llm_json(text)
    assert result == [{"a": 1}, {"b": 2}]


@pytest.mark.unit
def test_whitespace_trimmed():
    assert parse_llm_json('  {"x": 1}  ') == {"x": 1}


@pytest.mark.unit
async def test_background_task_runs_to_completion():
    result = []

    async def work():
        result.append(1)

    task = create_background_task(work(), name="test")
    await task
    assert result == [1]


@pytest.mark.unit
async def test_background_task_logs_exception(caplog):
    async def failing():
        raise ValueError("boom")

    create_background_task(failing(), name="test-fail")
    await asyncio.sleep(0.05)
    assert any("boom" in r.message for r in caplog.records)


@pytest.mark.unit
async def test_enable_test_mode_collects_tasks():
    """In test mode, tasks are added to pending list."""
    from maestro.utils import (
        enable_test_mode,
        disable_test_mode,
        drain_background_tasks,
        _pending_tasks,
    )

    enable_test_mode()
    try:

        async def dummy():
            pass

        create_background_task(dummy(), name="test-task")
        assert len(_pending_tasks) == 1

        await drain_background_tasks()
        assert len(_pending_tasks) == 0
    finally:
        disable_test_mode()


@pytest.mark.unit
async def test_drain_handles_failing_tasks():
    """drain_background_tasks swallows exceptions from failed tasks."""
    from maestro.utils import (
        enable_test_mode,
        disable_test_mode,
        drain_background_tasks,
        _pending_tasks,
    )

    enable_test_mode()
    try:

        async def failing():
            raise ValueError("boom")

        create_background_task(failing(), name="fail-task")
        assert len(_pending_tasks) == 1

        await drain_background_tasks()  # should not raise
        assert len(_pending_tasks) == 0
    finally:
        disable_test_mode()


@pytest.mark.unit
async def test_normal_mode_does_not_collect():
    """Without test mode, tasks are not collected in pending list."""
    from maestro.utils import _pending_tasks, disable_test_mode

    disable_test_mode()  # ensure not in test mode

    async def dummy():
        pass

    create_background_task(dummy(), name="normal-task")
    assert len(_pending_tasks) == 0
