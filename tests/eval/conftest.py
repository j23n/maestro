import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from maestro.models import (
    ItalianChunk, VocabularyWord, VocabularyWordDefinition, UserVocabularyCard,
    GrammarPoint, GrammarPointExplanation, CommunicativeFunction,
    LearningEvent, LearningProfile, DrillTemplate, GeneratedDrill,
    DrillAttempt, Lesson,
)

ALL_MODELS = [
    ItalianChunk, VocabularyWord, VocabularyWordDefinition, UserVocabularyCard,
    GrammarPoint, GrammarPointExplanation, CommunicativeFunction,
    LearningEvent, LearningProfile, DrillTemplate, GeneratedDrill, DrillAttempt, Lesson,
]

_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data"


def pytest_collection_modifyitems(items):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key.startswith("test-") or not key:
        skip = pytest.mark.skip(reason="Real ANTHROPIC_API_KEY required for eval tests")
        for item in items:
            if "llm_eval" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def use_eval_model(monkeypatch):
    """Override LESSON_MODEL with EVAL_MODEL so eval tests use the evaluator model."""
    from maestro.config import settings
    monkeypatch.setattr(settings, "LESSON_MODEL", settings.EVAL_MODEL)


@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(database=client["test_maestro_eval"], document_models=ALL_MODELS)
    yield


@pytest.fixture
async def seeded_analyzer_cache(db):
    """Seed the analyzer module caches from JSON data files (no real DB needed)."""
    import maestro.learning.analyzer as analyzer_module

    gps = json.loads((_DATA_DIR / "grammar_points.json").read_text())
    cfs = json.loads((_DATA_DIR / "comm_functions.json").read_text())

    original_gp = analyzer_module._grammar_points_cache[:]
    original_cf = analyzer_module._comm_functions_cache[:]
    original_level = analyzer_module._student_level

    analyzer_module._grammar_points_cache = [SimpleNamespace(**g) for g in gps]
    # CFs in the JSON have no `description` field; supply the default so _build_prompt doesn't crash
    analyzer_module._comm_functions_cache = [
        SimpleNamespace(description="", **cf) for cf in cfs
    ]
    analyzer_module._student_level = "A1"

    yield

    analyzer_module._grammar_points_cache = original_gp
    analyzer_module._comm_functions_cache = original_cf
    analyzer_module._student_level = original_level
