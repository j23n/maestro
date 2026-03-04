import pytest

from maestro.utils import parse_llm_json


@pytest.mark.unit
def test_plain_object():
    assert parse_llm_json('{"a": 1}') == {"a": 1}


@pytest.mark.unit
def test_plain_array():
    assert parse_llm_json('[1, 2, 3]') == [1, 2, 3]


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
    assert parse_llm_json('{invalid json}') is None


@pytest.mark.unit
def test_empty_string_returns_none():
    assert parse_llm_json('') is None


@pytest.mark.unit
def test_no_json_returns_none():
    assert parse_llm_json('just some plain text') is None


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
