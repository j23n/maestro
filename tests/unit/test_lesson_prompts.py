"""Unit tests for lesson content prompt assembly (orchestration level)."""

import pytest
from types import SimpleNamespace

from maestro.lessons.prompts import (
    build_lesson_content_prompt,
    build_lesson_content_system,
)
from maestro.models import ExerciseType, StudentPersona


def _scenario(**kwargs):
    defaults = dict(
        slug="al-bar",
        label="Al bar",
        description="Ordering at a bar",
        cefr_level="A1",
        cf_codes=[],
        gp_codes=[],
        depths=["greeting", "ordering", "paying"],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _gp(**kwargs):
    defaults = dict(
        code="GP001",
        label="Presente indicativo",
        cefr_level="A1",
        category="verbs",
        description="Present tense of regular verbs",
        chunk_ref=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _cf(**kwargs):
    defaults = dict(
        code="CF001",
        label="Salutare",
        category="interagire",
        cefr_level="A1",
        description="Greeting someone",
        examples=["Ciao!", "Buongiorno!"],
        patterns=["Ciao + name"],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _build(**overrides):
    """Call build_lesson_content_prompt with sensible defaults."""
    defaults = dict(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        grammar_gps=[],
        drill_specs=[],
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
        language="it",
    )
    defaults.update(overrides)
    return build_lesson_content_prompt(**defaults)


@pytest.mark.unit
def test_prompt_contains_scenario_and_level():
    prompt = _build()
    assert "<student>" in prompt
    assert "Estimated level: A1" in prompt
    assert "<scenario>" in prompt
    assert "Al bar" in prompt
    assert "depth 1" in prompt


@pytest.mark.unit
def test_prompt_contains_grammar_targets_and_mastery_label():
    prompt = _build(grammar_gps=[_gp()])
    assert "<grammar_targets>" in prompt
    assert "Presente indicativo (GP001) — mastery: new" in prompt


@pytest.mark.unit
def test_prompt_grammar_mastery_labels_reflect_scores():
    gps = [
        _gp(code="GP_A", label="Strong"),
        _gp(code="GP_B", label="Mid"),
        _gp(code="GP_C", label="Struggle"),
    ]
    profile = SimpleNamespace(
        persona=StudentPersona(),
        active_progress=SimpleNamespace(
            description="",
            grammar_error_counts={},
            grammar_correct_counts={},
            grammar_mastery_scores={"GP_A": 0.9, "GP_B": 0.6, "GP_C": -0.2},
        ),
    )
    prompt = _build(grammar_gps=gps, profile=profile)
    assert "Strong (GP_A) — mastery: consolidated" in prompt
    assert "Mid (GP_B) — mastery: developing" in prompt
    assert "Struggle (GP_C) — mastery: weak" in prompt


@pytest.mark.unit
def test_prompt_contains_drill_specs():
    spec = {
        "grammar_point_code": "GP001",
        "gp_label": "Presente indicativo",
        "exercise_type": ExerciseType.FILL_BLANK,
        "rag_excerpt": "",
        "chunk_ref": None,
    }
    prompt = _build(drill_specs=[spec])
    assert "<drills>" in prompt
    assert "GP001" in prompt
    assert "fill_blank" in prompt


@pytest.mark.unit
def test_prompt_contains_speaking_section():
    prompt = _build(speaking_cfs=[_cf()])
    assert "<speaking>" in prompt
    assert "Salutare" in prompt
    assert "CF001" in prompt


@pytest.mark.unit
def test_prompt_includes_persona(monkeypatch):
    """Persona injection: forced inclusion + 2 fields sampled."""
    import maestro.lessons.sections as _mod

    # pick_persona_lines uses rng=random; monkeypatch the random module instead.
    import random as _random_mod

    monkeypatch.setattr(_random_mod, "random", lambda: 0.0)
    monkeypatch.setattr(_random_mod, "randint", lambda a, b: b)
    monkeypatch.setattr(_random_mod, "sample", lambda pop, k: pop[:k])

    profile = SimpleNamespace(
        persona=StudentPersona(
            background="wine enthusiast",
            interests="cooking",
            goal="travel to Italy",
        ),
        active_progress=SimpleNamespace(
            description="",
            grammar_error_counts={},
            grammar_correct_counts={},
            grammar_mastery_scores={},
        ),
    )
    prompt = _build(profile=profile)
    assert "wine enthusiast" in prompt
    assert "cooking" in prompt
    # 3rd field not sampled when pick_count=2
    assert "travel to Italy" not in prompt
    # mention `_mod` to satisfy unused-import checks
    assert _mod.section_student is not None


@pytest.mark.unit
def test_prompt_excludes_persona_when_random_skips(monkeypatch):
    import random as _random_mod

    monkeypatch.setattr(_random_mod, "random", lambda: 0.8)

    profile = SimpleNamespace(
        persona=StudentPersona(
            background="wine enthusiast",
            interests="cooking",
            goal="travel to Italy",
        ),
        active_progress=SimpleNamespace(
            description="",
            grammar_error_counts={},
            grammar_correct_counts={},
            grammar_mastery_scores={},
        ),
    )
    prompt = _build(profile=profile)
    assert "wine enthusiast" not in prompt
    assert "cooking" not in prompt


@pytest.mark.unit
def test_prompt_includes_listening_when_requested():
    prompt = _build(listening_count=1)
    assert "<output_schema>" in prompt
    assert '"listenings"' in prompt
    assert "em-dash" in prompt or "— " in prompt


@pytest.mark.unit
def test_prompt_includes_reading_when_requested():
    prompt = _build(reading_count=2)
    assert '"readings"' in prompt
    assert "Optimise for visual reading" in prompt


@pytest.mark.unit
def test_prompt_listening_and_reading_are_distinct_sections():
    prompt = _build(listening_count=1, reading_count=1)
    assert '"listenings"' in prompt
    assert '"readings"' in prompt
    # The em-dash REQUIRED instruction should attach to listening only
    listenings_idx = prompt.index('"listenings"')
    readings_idx = prompt.index('"readings"')
    required_idx = prompt.find("REQUIRED format")
    assert listenings_idx < required_idx < readings_idx, (
        "REQUIRED dialogue rule should fall between listenings and readings"
    )


@pytest.mark.unit
def test_prompt_writing_schema():
    prompt = _build(include_writing=True)
    assert '"writing"' in prompt


@pytest.mark.unit
def test_prompt_recent_lessons_block():
    recent = [
        SimpleNamespace(
            topic_title="Un caffè al volo",
            topic_description="Quick espresso at a Milan bar.",
            scenario_slug="al-bar",
            archetype="introduction",
        ),
    ]
    prompt = _build(recent_lessons=recent)
    assert "<recent_lessons>" in prompt
    assert "Un caffè al volo" in prompt
    assert "introduction" in prompt


@pytest.mark.unit
def test_prompt_omits_recent_lessons_when_empty():
    prompt = _build(recent_lessons=[])
    assert "<recent_lessons>" not in prompt


@pytest.mark.unit
def test_prompt_lesson_shape_includes_archetype():
    prompt = _build(archetype="consolidation")
    assert "<lesson_shape>" in prompt
    assert "PRACTICE lesson" in prompt


@pytest.mark.unit
def test_prompt_lesson_shape_lists_activity_counts():
    prompt = _build(
        listening_count=1,
        reading_count=1,
        include_writing=True,
        speaking_cfs=[_cf()],
        drill_specs=[
            {
                "grammar_point_code": "GP001",
                "gp_label": "Presente",
                "exercise_type": ExerciseType.FILL_BLANK,
                "rag_excerpt": "",
                "chunk_ref": None,
            }
        ],
    )
    assert "1 listening" in prompt
    assert "1 reading" in prompt
    assert "1 drill" in prompt
    assert "1 speaking" in prompt
    assert "1 writing" in prompt


@pytest.mark.unit
def test_system_prompt_carries_universal_rules():
    system = build_lesson_content_system("it")
    assert "experienced language teacher" in system
    assert "<lesson_principles>" in system
    assert "<drill_rules>" in system
    assert "<output_format>" in system
    assert "fill_blank" in system
    assert "error_correction" in system


@pytest.mark.unit
def test_user_prompt_does_not_repeat_drill_rules():
    """Drill rules should live in the system prompt only — no duplication."""
    prompt = _build(
        drill_specs=[
            {
                "grammar_point_code": "GP001",
                "gp_label": "Presente",
                "exercise_type": ExerciseType.FILL_BLANK,
                "rag_excerpt": "",
                "chunk_ref": None,
            }
        ]
    )
    assert "EXACTLY 10 objects" not in prompt


@pytest.mark.unit
def test_grammar_motivations_not_in_prompt():
    prompt = _build(grammar_gps=[_gp()])
    assert "grammar_motivations" not in prompt
    assert "motivation object" not in prompt


@pytest.mark.unit
def test_student_persona_defaults_to_empty_strings():
    p = StudentPersona()
    assert p.background == ""
    assert p.interests == ""
    assert p.goal == ""


# ---------------------------------------------------------------------------
# Storyline + staleness
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_prompt_includes_storyline_when_set():
    storyline = "Elena moved to Bologna last month and is settling in."
    prompt = _build(storyline=storyline)
    assert "<storyline>" in prompt
    assert storyline in prompt


@pytest.mark.unit
def test_prompt_omits_storyline_when_empty():
    prompt = _build(storyline="")
    assert "<storyline>" not in prompt


@pytest.mark.unit
def test_prompt_omits_storyline_when_whitespace_only():
    prompt = _build(storyline="   \n  ")
    assert "<storyline>" not in prompt


@pytest.mark.unit
def test_prompt_stale_note_only_when_storyline_present():
    # Stale flag without storyline — no dangling stale instruction.
    prompt_no_story = _build(storyline="", stale=True)
    assert "two weeks" not in prompt_no_story

    prompt_with_story = _build(storyline="A short story.", stale=True)
    assert "two weeks" in prompt_with_story


@pytest.mark.unit
def test_prompt_storyline_appears_above_recent_lessons():
    storyline = "Elena's arc so far."
    recent = [
        SimpleNamespace(
            topic_title="Un caffè al volo",
            topic_description="Quick espresso at a Milan bar.",
            scenario_slug="al-bar",
            archetype="introduction",
        ),
    ]
    prompt = _build(storyline=storyline, recent_lessons=recent)
    assert prompt.index("<storyline>") < prompt.index("<recent_lessons>")
