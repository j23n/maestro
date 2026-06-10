"""Unit tests for the static content bank: loader and lesson assembly."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from maestro.lessons import bank
from maestro.lessons.bank_assembly import try_assemble_from_bank
from maestro.models import ExerciseType, ScenarioProgress

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def bank_caches():
    bank.invalidate()
    yield
    bank.invalidate()


@pytest.fixture
def bank_data(tmp_path, monkeypatch):
    """Write a minimal bank to tmp_path and point the loader at it."""
    monkeypatch.setattr(bank, "data_dir", lambda lang: tmp_path / lang)
    root = tmp_path / "it" / "banks" / "a1"
    (root / "drills").mkdir(parents=True)
    (root / "texts").mkdir(parents=True)

    (root / "drills" / "gp_essere.yaml").write_text(
        yaml.safe_dump(
            {
                "grammar_point_code": "gp_essere",
                "items": [
                    {
                        "exercise_type": "fill_blank",
                        "prompt": f"Io ___ Marco. ({i})",
                        "correct_answer": "sono",
                    }
                    for i in range(8)
                ]
                + [
                    {
                        "exercise_type": "error_correction",
                        "prompt": f"Io è Marco. ({i})",
                        "correct_answer": "Io sono Marco.",
                    }
                    for i in range(4)
                ],
            }
        )
    )
    (root / "texts" / "al-bar.yaml").write_text(
        yaml.safe_dump(
            {
                "scenario": "al-bar",
                "speakings": [
                    {"cf_code": "cf_salutare", "prompt": "Saluta il barista."},
                    {"cf_code": "cf_ordinare", "prompt": "Ordina un caffè."},
                ],
                "depths": {
                    1: {
                        "listenings": [
                            {
                                "text": "— Buongiorno!\n— Un caffè, per favore.",
                                "questions": [
                                    {
                                        "text": "Cosa ordina?",
                                        "correct_answer": "Un caffè",
                                    }
                                ],
                                "vocab_annotations": [
                                    {
                                        "surface_forms": ["caffè"],
                                        "lemma": "caffè",
                                        "upos": "NOUN",
                                    }
                                ],
                            }
                        ],
                        "readings": [
                            {"text": "Il bar è aperto.", "questions": []},
                            {"text": "Anna prende un cornetto.", "questions": []},
                        ],
                        "writings": [{"prompt": "Scrivi un dialogo al bar."}],
                    }
                },
            }
        )
    )
    return root


def _scenario(slug="al-bar"):
    return SimpleNamespace(slug=slug)


def _profile(lesson_count=0):
    sp = ScenarioProgress(depth=0, lesson_count=lesson_count)
    return SimpleNamespace(
        active_progress=SimpleNamespace(scenario_progress={"al-bar": sp})
    )


def _cf(code):
    return SimpleNamespace(code=code)


def _spec(gp_code="gp_essere", exercise_type=ExerciseType.FILL_BLANK, **kw):
    return {
        "grammar_point_code": gp_code,
        "gp_label": gp_code,
        "exercise_type": exercise_type,
        **kw,
    }


def test_load_drill_bank(bank_data):
    loaded = bank.load_drill_bank("it", "A1")
    assert set(loaded) == {"gp_essere"}
    assert len(loaded["gp_essere"].items) == 12


def test_load_text_bank_coerces_depth_keys(bank_data):
    loaded = bank.load_text_bank("it", "A1")
    assert loaded["al-bar"].depths[1].listenings[0].text.startswith("— Buongiorno")


def test_loader_skips_invalid_files(bank_data):
    (bank_data / "drills" / "broken.yaml").write_text("items: 12")
    bank.invalidate()
    assert set(bank.load_drill_bank("it", "A1")) == {"gp_essere"}


def test_assemble_full_lesson(bank_data):
    specs = [_spec(), _spec()]
    content = try_assemble_from_bank(
        language="it",
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=_profile(),
        drill_specs=specs,
        listening_count=1,
        reading_count=1,
        include_writing=True,
        speaking_cfs=[_cf("cf_salutare")],
    )
    assert content is not None
    assert len(content.drills) == 2
    assert all(len(d.items) >= 3 for d in content.drills)
    # Items sampled without replacement across the lesson
    prompts = [i.prompt for d in content.drills for i in d.items]
    assert len(prompts) == len(set(prompts))
    assert len(content.listenings) == 1
    assert content.listenings[0].vocab_annotations[0].lemma == "caffè"
    assert len(content.readings) == 1
    assert content.writing is not None
    assert content.speakings[0].prompt == "Saluta il barista."


def test_assemble_returns_none_for_unknown_scenario(bank_data):
    content = try_assemble_from_bank(
        language="it",
        cefr_level="A1",
        scenario=_scenario("in-stazione"),
        depth=1,
        profile=None,
        drill_specs=[],
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert content is None


def test_assemble_returns_none_for_missing_depth(bank_data):
    content = try_assemble_from_bank(
        language="it",
        cefr_level="A1",
        scenario=_scenario(),
        depth=2,
        profile=None,
        drill_specs=[],
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert content is None


def test_assemble_returns_none_for_uncovered_gp(bank_data):
    specs = [_spec("gp_avere")]
    content = try_assemble_from_bank(
        language="it",
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        drill_specs=specs,
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert content is None


def test_assemble_drops_optional_uncovered_spec(bank_data):
    specs = [_spec(), _spec("gp_avere", optional=True)]
    content = try_assemble_from_bank(
        language="it",
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        drill_specs=specs,
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert content is not None
    # Optional spec dropped in place — specs stay aligned with drills
    assert [s["grammar_point_code"] for s in specs] == ["gp_essere"]
    assert len(content.drills) == 1


def test_assemble_returns_none_for_missing_cf_prompt(bank_data):
    content = try_assemble_from_bank(
        language="it",
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        drill_specs=[],
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[_cf("cf_unknown")],
    )
    assert content is None


def test_assemble_rotates_reading_variants_by_lesson_count(bank_data):
    def _pick(lesson_count):
        content = try_assemble_from_bank(
            language="it",
            cefr_level="A1",
            scenario=_scenario(),
            depth=1,
            profile=_profile(lesson_count=lesson_count),
            drill_specs=[],
            listening_count=0,
            reading_count=1,
            include_writing=False,
            speaking_cfs=[],
        )
        return content.readings[0].text

    assert _pick(0) != _pick(1)
    assert _pick(0) == _pick(2)


def test_assemble_caps_counts_at_available_variants(bank_data):
    content = try_assemble_from_bank(
        language="it",
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        drill_specs=[],
        listening_count=1,
        reading_count=3,  # only 2 variants exist
        include_writing=False,
        speaking_cfs=[],
    )
    assert content is not None
    assert len(content.readings) == 2
    texts = [r.text for r in content.readings]
    assert len(texts) == len(set(texts))


def test_assemble_rewrites_spec_exercise_type_to_match_items(bank_data):
    # Ask for more error_correction drills than the pool can supply: the
    # sampler falls back to fill_blank items and rewrites the spec type.
    specs = [_spec(exercise_type=ExerciseType.ERROR_CORRECTION) for _ in range(2)]
    content = try_assemble_from_bank(
        language="it",
        cefr_level="A1",
        scenario=_scenario(),
        depth=1,
        profile=None,
        drill_specs=specs,
        listening_count=0,
        reading_count=0,
        include_writing=False,
        speaking_cfs=[],
    )
    assert content is not None
    assert len(content.drills) == 2
    # 4 error_correction items exist: first spec keeps its type, second
    # falls back to fill_blank — and the spec records what was sampled.
    assert specs[0]["exercise_type"] == ExerciseType.ERROR_CORRECTION
    assert specs[1]["exercise_type"] == ExerciseType.FILL_BLANK
