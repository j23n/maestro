"""Unit tests for lesson content prompt construction."""

import pytest
from types import SimpleNamespace

from maestro.lessons.prompts import build_lesson_content_prompt
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
        language="it",
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
        language="it",
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
        language="it",
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
        language="it",
    )
    assert "Salutare" in prompt
    assert "CF001" in prompt


@pytest.mark.unit
def test_prompt_includes_persona(monkeypatch):
    # Force persona inclusion: random() < 0.7, randint → 2, sample returns first k
    import maestro.lessons.prompts as _mod

    monkeypatch.setattr(_mod.random, "random", lambda: 0.0)
    monkeypatch.setattr(_mod.random, "randint", lambda a, b: b)
    monkeypatch.setattr(_mod.random, "sample", lambda pop, k: pop[:k])

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
        ),
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
        language="it",
    )
    # randint(1,2) returns 2 → picks first 2 fields (background, interests)
    assert "wine enthusiast" in prompt
    assert "cooking" in prompt
    # goal is the 3rd field, not selected when pick_count=2
    assert "travel to Italy" not in prompt


@pytest.mark.unit
def test_prompt_excludes_persona_when_random_skips(monkeypatch):
    # Force persona exclusion: random() >= 0.7
    import maestro.lessons.prompts as _mod

    monkeypatch.setattr(_mod.random, "random", lambda: 0.8)

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
        ),
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
        language="it",
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
        language="it",
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
        language="it",
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
        language="it",
    )
    assert "detailed" in prompt


@pytest.mark.unit
def test_student_persona_defaults_to_empty_strings():
    p = StudentPersona()
    assert p.background == ""
    assert p.interests == ""
    assert p.goal == ""


@pytest.mark.unit
@pytest.mark.parametrize(
    "archetype,expected_text",
    [
        ("introduction", "INTRODUCES new grammar"),
        ("consolidation", "PRACTICE lesson"),
        ("application", "IMMERSIVE scenario"),
    ],
)
def test_prompt_contains_archetype_guidance(archetype, expected_text):
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
        archetype=archetype,
        language="it",
    )
    assert expected_text in prompt


@pytest.mark.unit
def test_prompt_no_archetype_guidance_when_empty():
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
        archetype="",
        language="it",
    )
    assert "LESSON TYPE" not in prompt


def _recent_lesson(**kwargs):
    defaults = dict(
        topic_title="Ordering at the bar",
        topic_description="A quick café exchange over espresso.",
        scenario_slug="al-bar",
        archetype="consolidation",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
def test_prompt_includes_recent_lessons():
    recent = [
        _recent_lesson(topic_title="Ordering at the bar", scenario_slug="al-bar"),
        _recent_lesson(topic_title="At the train station", scenario_slug="in-stazione"),
    ]
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
        recent_lessons=recent,
        language="it",
    )
    assert "Recent lessons" in prompt
    assert "Ordering at the bar" in prompt
    assert "At the train station" in prompt
    assert "scenario: al-bar" in prompt
    assert "consolidation" in prompt


@pytest.mark.unit
def test_prompt_omits_recent_lessons_block_when_empty():
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
        recent_lessons=[],
        language="it",
    )
    assert "Recent lessons" not in prompt


@pytest.mark.unit
def test_prompt_recent_lessons_handles_missing_metadata():
    recent = [
        _recent_lesson(
            topic_title=None,
            topic_description=None,
            scenario_slug=None,
            archetype=None,
        ),
    ]
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
        recent_lessons=recent,
        language="it",
    )
    assert "Recent lessons" in prompt
    assert "(untitled)" in prompt
