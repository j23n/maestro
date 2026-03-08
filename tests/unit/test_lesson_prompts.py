"""Unit tests for lesson content prompt construction."""

import pytest
from types import SimpleNamespace

from maestro.lezione.prompts import build_lesson_content_prompt
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
        macro_category="interagire",
        cefr_level="A1",
        description="Greeting someone",
        examples=["Ciao!", "Buongiorno!"],
        patterns=["Ciao + name"],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
def test_prompt_contains_scenario_and_level():
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        grammar_gps=[],
        drill_specs=[],
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "A1" in prompt
    assert "Al bar" in prompt
    assert "depth 1" in prompt


@pytest.mark.unit
def test_prompt_contains_grammar_points():
    gp = _gp()
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        grammar_gps=[gp],
        drill_specs=[],
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "GP001" in prompt
    assert "Presente indicativo" in prompt


@pytest.mark.unit
def test_prompt_contains_drill_specs():
    spec = {
        "grammar_point_code": "GP001",
        "gp_label": "Presente indicativo",
        "gp_description": "Present tense",
        "exercise_type": ExerciseType.FILL_BLANK,
        "rag_excerpt": "",
        "chunk_ref": None,
    }
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        grammar_gps=[],
        drill_specs=[spec],
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "GP001" in prompt
    assert "fill_blank" in prompt


@pytest.mark.unit
def test_prompt_contains_speaking_cf():
    cf = _cf()
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        grammar_gps=[],
        drill_specs=[],
        reading_count=0,
        include_writing=False,
        speaking_cfs=[cf],
    )
    assert "Salutare" in prompt
    assert "CF001" in prompt


@pytest.mark.unit
def test_prompt_includes_persona(monkeypatch):
    # Force persona inclusion: random() < 0.7, randint → 2, sample returns first k
    import maestro.lezione.prompts as _mod

    monkeypatch.setattr(_mod.random, "random", lambda: 0.0)
    monkeypatch.setattr(_mod.random, "randint", lambda a, b: b)
    monkeypatch.setattr(_mod.random, "sample", lambda pop, k: pop[:k])

    profile = SimpleNamespace(
        persona=StudentPersona(
            background="wine enthusiast",
            interests="cooking",
            goal="travel to Italy",
        ),
        description="",
        grammar_error_counts={},
        grammar_correct_counts={},
    )
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=profile,
        grammar_gps=[],
        drill_specs=[],
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    # randint(1,2) returns 2 → picks first 2 fields (background, interests)
    assert "wine enthusiast" in prompt
    assert "cooking" in prompt
    # goal is the 3rd field, not selected when pick_count=2
    assert "travel to Italy" not in prompt


@pytest.mark.unit
def test_prompt_excludes_persona_when_random_skips(monkeypatch):
    # Force persona exclusion: random() >= 0.7
    import maestro.lezione.prompts as _mod

    monkeypatch.setattr(_mod.random, "random", lambda: 0.8)

    profile = SimpleNamespace(
        persona=StudentPersona(
            background="wine enthusiast",
            interests="cooking",
            goal="travel to Italy",
        ),
        description="",
        grammar_error_counts={},
        grammar_correct_counts={},
    )
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=profile,
        grammar_gps=[],
        drill_specs=[],
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "wine enthusiast" not in prompt
    assert "cooking" not in prompt
    assert "travel to Italy" not in prompt


@pytest.mark.unit
def test_prompt_reading_schema():
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        grammar_gps=[],
        drill_specs=[],
        reading_count=2,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "readings" in prompt


@pytest.mark.unit
def test_prompt_writing_schema():
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        grammar_gps=[],
        drill_specs=[],
        reading_count=0,
        include_writing=True,
        speaking_cfs=[],
    )
    assert "writing" in prompt


@pytest.mark.unit
def test_prompt_depth_description():
    """Depth description should come from scenario.depths[depth-1]."""
    scenario = _scenario(depths=["intro", "detailed", "mastery"])
    prompt = build_lesson_content_prompt(
        cefr_level="A1",
        scenario=scenario,
        depth=2,
        profile=None,
        grammar_gps=[],
        drill_specs=[],
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert "detailed" in prompt


@pytest.mark.unit
def test_student_persona_defaults_to_empty_strings():
    p = StudentPersona()
    assert p.background == ""
    assert p.interests == ""
    assert p.goal == ""
