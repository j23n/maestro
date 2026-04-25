"""Unit tests for the lesson-content output schema builder."""

import pytest
from types import SimpleNamespace

from maestro.lessons.output_schema import build_output_schema
from maestro.models import ExerciseType


def _drill_spec(code="GP001", exercise_type=ExerciseType.FILL_BLANK):
    return {
        "grammar_point_code": code,
        "gp_label": "Some GP",
        "exercise_type": exercise_type,
        "rag_excerpt": "",
        "chunk_ref": None,
    }


def _cf(code="CF001", label="Salutare"):
    return SimpleNamespace(code=code, label=label, examples=[], patterns=[])


@pytest.mark.unit
def test_schema_minimal_has_only_topic_fields():
    schema = build_output_schema(
        language_name="Italian",
        cefr_level="A1",
        drill_specs=[],
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert set(schema.keys()) == {"topic_title", "topic_description", "overview"}


@pytest.mark.unit
def test_schema_includes_drills_when_specs_given():
    schema = build_output_schema(
        language_name="Italian",
        cefr_level="A1",
        drill_specs=[_drill_spec(), _drill_spec(code="GP002")],
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "drills" in schema
    assert len(schema["drills"]) == 2
    assert schema["drills"][0]["grammar_point_code"] == "GP001"


@pytest.mark.unit
def test_schema_includes_listenings_separately_from_readings():
    schema = build_output_schema(
        language_name="Italian",
        cefr_level="A1",
        drill_specs=[],
        listening_count=2,
        reading_count=1,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "listenings" in schema
    assert "readings" in schema
    assert len(schema["listenings"]) == 2
    assert len(schema["readings"]) == 1
    # Listenings carry the em-dash dialogue requirement
    assert "REQUIRED" in schema["listenings"][0]["text"]
    assert "em-dash" in schema["listenings"][0]["text"]
    # Readings emphasise visual / no audio
    assert "visual reading" in schema["readings"][0]["text"]


@pytest.mark.unit
def test_schema_listenings_omitted_when_count_zero():
    schema = build_output_schema(
        language_name="Italian",
        cefr_level="A1",
        drill_specs=[],
        listening_count=0,
        reading_count=2,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "listenings" not in schema
    assert "readings" in schema


@pytest.mark.unit
def test_schema_readings_omitted_when_count_zero():
    schema = build_output_schema(
        language_name="Italian",
        cefr_level="A1",
        drill_specs=[],
        listening_count=1,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "listenings" in schema
    assert "readings" not in schema


@pytest.mark.unit
def test_schema_includes_writing_and_speakings():
    schema = build_output_schema(
        language_name="Italian",
        cefr_level="A1",
        drill_specs=[],
        listening_count=0,
        reading_count=0,
        include_writing=True,
        speaking_cfs=[_cf(), _cf(code="CF002", label="Greeting")],
    )
    assert "writing" in schema
    assert len(schema["speakings"]) == 2


@pytest.mark.unit
def test_schema_word_count_pulled_from_cefr_level():
    schema_a1 = build_output_schema(
        language_name="Italian",
        cefr_level="A1",
        drill_specs=[],
        listening_count=1,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    schema_b2 = build_output_schema(
        language_name="Italian",
        cefr_level="B2",
        drill_specs=[],
        listening_count=1,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "200" in schema_a1["listenings"][0]["text"]
    assert "500" in schema_b2["listenings"][0]["text"]
