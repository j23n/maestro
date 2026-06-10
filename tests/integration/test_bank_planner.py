"""Integration tests: planner assembles A1 lessons from the content bank."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from beanie import PydanticObjectId

from maestro.lessons import bank
from maestro.models import (
    ActivityType,
    CommunicativeFunction,
    CurriculumScenario,
    GeneratedDrill,
    GrammarPoint,
    LanguageProgress,
    LearningProfile,
    Lesson,
    LessonStatus,
)
from maestro.utils import utcnow
from maestro.vocab import cache as _vocab_cache

pytestmark = pytest.mark.integration

_STUDENT_ID = PydanticObjectId()

_GP_CODES = ["gp_essere", "gp_articoli"]
_CF_CODES = ["cf_salutare", "cf_ordinare"]


@pytest.fixture(autouse=True)
def clean_caches():
    bank.invalidate()
    _vocab_cache.seed(words={}, defs={}, language="it")
    yield
    bank.invalidate()
    _vocab_cache.invalidate("it")


@pytest.fixture
async def curriculum(db):
    scenario = CurriculumScenario(
        slug="al-bar",
        label="Al bar",
        description="Ordering at a cafe",
        overview="Una lezione al bar.",
        cefr_level="A1",
        cf_codes=_CF_CODES,
        gp_codes=_GP_CODES,
        depths=["order coffee", "chat", "complain"],
        phase=1,
        language="it",
    )
    await scenario.insert()
    for code in _GP_CODES:
        await GrammarPoint(
            code=code,
            label=code,
            cefr_level="A1",
            category="test",
            language="it",
            explanations={},
        ).insert()
    for code in _CF_CODES:
        await CommunicativeFunction(
            code=code, label=code, category="test", cefr_level="A1", language="it"
        ).insert()
    await LearningProfile(
        student_id=_STUDENT_ID,
        target_language="it",
        progress={"it": LanguageProgress(cefr_level_override="A1")},
    ).insert()
    return scenario


@pytest.fixture
def bank_files(tmp_path, monkeypatch):
    monkeypatch.setattr(bank, "data_dir", lambda lang: tmp_path / lang)
    root = tmp_path / "it" / "banks" / "a1"
    (root / "drills").mkdir(parents=True)
    (root / "texts").mkdir(parents=True)
    for code in _GP_CODES:
        (root / "drills" / f"{code}.yaml").write_text(
            yaml.safe_dump(
                {
                    "grammar_point_code": code,
                    "items": [
                        {
                            "exercise_type": "fill_blank",
                            "prompt": f"{code} prompt {i} ___.",
                            "correct_answer": f"answer{i}",
                        }
                        for i in range(8)
                    ]
                    + [
                        {
                            "exercise_type": "error_correction",
                            "prompt": f"{code} wrong {i}.",
                            "correct_answer": f"{code} right {i}.",
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
                    {"cf_code": code, "prompt": f"Parla: {code}"} for code in _CF_CODES
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
                            {
                                "text": "Il bar del centro è sempre pieno.",
                                "questions": [
                                    {"text": "Com'è il bar?", "correct_answer": "Pieno"}
                                ],
                                "vocab_annotations": [
                                    {
                                        "surface_forms": ["pieno"],
                                        "lemma": "pieno",
                                        "upos": "ADJ",
                                    }
                                ],
                            }
                        ],
                        "writings": [{"prompt": "Scrivi un dialogo al bar."}],
                    }
                },
            }
        )
    )
    return root


def _adapt_response():
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                text=json.dumps(
                    {
                        "topic_title": "Un caffè con Anna",
                        "topic_description": "Ordering for two at the bar.",
                        "overview": "Oggi ordiniamo al bar.",
                    }
                )
            )
        ]
    )


async def _new_lesson() -> Lesson:
    lesson = Lesson(
        student_id=_STUDENT_ID,
        duration_minutes=20,
        cefr_at_start="A1",
        language="it",
        status=LessonStatus.ACTIVE,
        started_at=utcnow(),
        generating=True,
        activities=[],
        current_index=0,
    )
    await lesson.insert()
    return lesson


async def test_bank_path_builds_lesson_without_generation_llm(
    curriculum, bank_files
):
    from maestro.lessons.planner import _generate_lesson_background

    lesson = await _new_lesson()
    with (
        patch(
            "maestro.lessons.planner._generate_lesson_content",
            new_callable=AsyncMock,
        ) as mock_generate,
        patch(
            "maestro.lessons.adapt.llm_messages_create",
            new_callable=AsyncMock,
            return_value=_adapt_response(),
        ) as mock_adapt,
        patch(
            "maestro.tts.generate_lesson_audio",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await _generate_lesson_background(lesson.id, 20)

    mock_generate.assert_not_called()
    mock_adapt.assert_called_once()

    lesson = await Lesson.get(lesson.id)
    assert lesson.generating is False
    assert lesson.content_source == "bank"
    assert lesson.scenario_slug == "al-bar"
    # Adaptation framing applied
    assert lesson.topic_title == "Un caffè con Anna"
    assert lesson.overview == "Oggi ordiniamo al bar."

    types = [a.type for a in lesson.activities]
    assert types.count(ActivityType.GRAMMAR) == 2
    assert types.count(ActivityType.DRILL) == 6
    assert ActivityType.LISTENING in types
    assert ActivityType.READING in types
    assert ActivityType.WRITING in types
    assert ActivityType.SPEAKING in types

    # Drill content comes verbatim from the bank with verified answer keys
    drill_act = next(a for a in lesson.activities if a.type == ActivityType.DRILL)
    drill = await GeneratedDrill.get(drill_act.drill_id)
    assert drill.items and all(i.correct_answer for i in drill.items)
    assert drill.items[0].prompt.startswith(drill.grammar_point_code)

    # Bank texts carry their pre-verified annotations
    reading = next(a for a in lesson.activities if a.type == ActivityType.READING)
    assert reading.vocab_annotated is True
    assert [a.lemma for a in reading.vocab_annotations] == ["pieno"]

    # Speaking prompt matches the picked CF
    speaking = next(a for a in lesson.activities if a.type == ActivityType.SPEAKING)
    assert speaking.content.startswith("Parla: ")
    assert speaking.cf_codes[0] in _CF_CODES


async def test_bank_path_falls_back_to_scenario_framing_on_adapt_failure(
    curriculum, bank_files
):
    from maestro.lessons.planner import _generate_lesson_background

    lesson = await _new_lesson()
    with (
        patch(
            "maestro.lessons.planner._generate_lesson_content",
            new_callable=AsyncMock,
        ) as mock_generate,
        patch(
            "maestro.lessons.adapt.llm_messages_create",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM down"),
        ),
        patch(
            "maestro.tts.generate_lesson_audio",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await _generate_lesson_background(lesson.id, 20)

    mock_generate.assert_not_called()
    lesson = await Lesson.get(lesson.id)
    assert lesson.generating is False
    assert lesson.content_source == "bank"
    # Scenario metadata fallback
    assert lesson.topic_title == "Al bar"
    assert lesson.overview == "Una lezione al bar."


async def test_missing_bank_falls_back_to_llm_generation(curriculum, tmp_path, monkeypatch):
    from maestro.lessons.planner import _generate_lesson_background
    from maestro.lessons.schemas import LessonContentResponse

    # Empty bank directory → no coverage
    monkeypatch.setattr(bank, "data_dir", lambda lang: tmp_path / lang)

    lesson = await _new_lesson()
    with (
        patch(
            "maestro.lessons.planner._generate_lesson_content",
            new_callable=AsyncMock,
            return_value=LessonContentResponse(topic_title="LLM lesson"),
        ) as mock_generate,
        patch(
            "maestro.lessons.adapt.llm_messages_create",
            new_callable=AsyncMock,
        ) as mock_adapt,
        patch(
            "maestro.tts.generate_lesson_audio",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        await _generate_lesson_background(lesson.id, 20)

    mock_generate.assert_called_once()
    mock_adapt.assert_not_called()
    lesson = await Lesson.get(lesson.id)
    assert lesson.content_source == "llm"
    assert lesson.topic_title == "LLM lesson"
