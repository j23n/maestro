"""Unit tests for individual XML section builders."""

import pytest
from types import SimpleNamespace

from maestro.lessons.sections import (
    pick_persona_lines,
    section_drills,
    section_grammar_targets,
    section_lesson_shape,
    section_output_schema,
    section_recent_lessons,
    section_scenario,
    section_speaking,
    section_student,
)
from maestro.models import ExerciseType, StudentPersona


class _FakeRng:
    def __init__(self, *, random_value=0.0, randint_value=2, sample_take_first=True):
        self._random = random_value
        self._randint = randint_value
        self._sample_first = sample_take_first

    def random(self):
        return self._random

    def randint(self, a, b):
        return self._randint

    def sample(self, pop, k):
        return pop[:k] if self._sample_first else list(reversed(pop))[:k]


@pytest.mark.unit
def test_section_student_minimal():
    s = section_student(
        cefr_level="A1", persona_lines=[], lesson_context="", profile=None
    )
    assert s.startswith("<student>")
    assert s.endswith("</student>")
    assert "Estimated level: A1" in s


@pytest.mark.unit
def test_section_student_with_persona_and_context():
    profile = SimpleNamespace(
        active_progress=SimpleNamespace(description="Recent narrative blah")
    )
    s = section_student(
        cefr_level="A2",
        persona_lines=["Background: hiker", "Goal: travel"],
        lesson_context="Restaurants this week please",
        profile=profile,
    )
    assert "Background: hiker" in s
    assert "Restaurants this week please" in s
    assert "Recent narrative" in s


@pytest.mark.unit
def test_pick_persona_lines_skips_when_random_above_threshold():
    persona = StudentPersona(background="x", interests="y", goal="z")
    rng = _FakeRng(random_value=0.8)
    assert pick_persona_lines(persona, rng=rng) == []


@pytest.mark.unit
def test_pick_persona_lines_returns_two_fields():
    persona = StudentPersona(background="x", interests="y", goal="z")
    rng = _FakeRng(random_value=0.0, randint_value=2)
    lines = pick_persona_lines(persona, rng=rng)
    assert len(lines) == 2


@pytest.mark.unit
def test_pick_persona_lines_handles_no_persona():
    rng = _FakeRng(random_value=0.0)
    assert pick_persona_lines(None, rng=rng) == []


@pytest.mark.unit
def test_pick_persona_lines_handles_all_empty_fields():
    persona = StudentPersona()
    rng = _FakeRng(random_value=0.0)
    assert pick_persona_lines(persona, rng=rng) == []


@pytest.mark.unit
def test_section_recent_lessons_empty_returns_empty_string():
    assert section_recent_lessons([]) == ""


@pytest.mark.unit
def test_section_recent_lessons_with_data():
    recent = [
        SimpleNamespace(
            topic_title="At the bar",
            topic_description="Quick coffee.",
            scenario_slug="al-bar",
            archetype="introduction",
        ),
        SimpleNamespace(
            topic_title=None,
            topic_description=None,
            scenario_slug=None,
            archetype=None,
        ),
    ]
    s = section_recent_lessons(recent)
    assert "<recent_lessons>" in s
    assert "At the bar" in s
    assert "introduction" in s
    assert "(untitled)" in s


@pytest.mark.unit
def test_section_scenario_uses_depth_description():
    scenario = SimpleNamespace(
        label="Al ristorante", depths=["greeting", "ordering", "paying"]
    )
    s = section_scenario(scenario, depth=2)
    assert "Al ristorante" in s
    assert "depth 2" in s
    assert "ordering" in s


@pytest.mark.unit
def test_section_scenario_clamps_depth_to_last():
    scenario = SimpleNamespace(label="X", depths=["a", "b"])
    s = section_scenario(scenario, depth=99)
    assert "b" in s


@pytest.mark.unit
def test_section_lesson_shape_lists_all_activity_counts():
    s = section_lesson_shape(
        archetype_block="Type: CONSOLIDATION",
        listening_count=1,
        reading_count=2,
        drill_count=3,
        speaking_count=1,
        include_writing=True,
    )
    assert "1 listening" in s
    assert "2 reading" in s
    assert "3 drill" in s
    assert "1 speaking" in s
    assert "1 writing" in s
    assert "CONSOLIDATION" in s


@pytest.mark.unit
def test_section_lesson_shape_empty_returns_empty_string():
    s = section_lesson_shape(
        archetype_block="",
        listening_count=0,
        reading_count=0,
        drill_count=0,
        speaking_count=0,
        include_writing=False,
    )
    assert s == ""


@pytest.mark.unit
def test_section_grammar_targets_uses_mastery_label():
    gp = SimpleNamespace(code="GP001", label="Presente")
    profile = SimpleNamespace(
        active_progress=SimpleNamespace(grammar_mastery_scores={"GP001": 0.9})
    )
    s = section_grammar_targets([gp], profile)
    assert "Presente (GP001)" in s
    assert "consolidated" in s


@pytest.mark.unit
def test_section_grammar_targets_no_profile_means_new():
    gp = SimpleNamespace(code="GP001", label="Presente")
    s = section_grammar_targets([gp], None)
    assert "mastery: new" in s


@pytest.mark.unit
def test_section_drills_empty():
    assert section_drills([]) == ""


@pytest.mark.unit
def test_section_drills_with_rag_excerpt():
    spec = {
        "grammar_point_code": "GP001",
        "gp_label": "Presente",
        "exercise_type": ExerciseType.FILL_BLANK,
        "rag_excerpt": "Some grammar reference text",
        "chunk_ref": "ref1",
    }
    s = section_drills([spec])
    assert "GP001" in s
    assert "fill_blank" in s
    assert "RAG: Some grammar reference text" in s


@pytest.mark.unit
def test_section_speaking_with_patterns_and_examples():
    cf = SimpleNamespace(
        code="CF001",
        label="Salutare",
        category="interagire",
        patterns=["Ciao + name"],
        examples=["Ciao!", "Buongiorno!"],
    )
    s = section_speaking([cf])
    assert "<speaking>" in s
    assert "Salutare" in s
    assert "Ciao + name" in s
    assert "Ciao!" in s


@pytest.mark.unit
def test_section_speaking_empty():
    assert section_speaking([]) == ""


@pytest.mark.unit
def test_section_output_schema_serialises_to_json():
    schema = {"topic_title": "...", "drills": []}
    s = section_output_schema(schema)
    assert "<output_schema>" in s
    assert '"topic_title"' in s
    assert '"drills"' in s
