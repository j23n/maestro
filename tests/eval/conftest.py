import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from maestro.models import ALL_DOCUMENT_MODELS

_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data" / "it"


def pytest_collection_modifyitems(items):
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key.startswith("test-") or not key:
        skip = pytest.mark.skip(reason="Real ANTHROPIC_API_KEY required for eval tests")
        for item in items:
            if "llm_eval" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def use_eval_model(monkeypatch):
    """Override LESSON_MODEL and SCORING_MODEL with EVAL_MODEL so eval tests use
    the evaluator model for both lesson generation and scoring.

    Also patches CHAT_MODEL on module-level Settings instances in vocab and grammar
    modules, which create their own Settings() instances independently of maestro.config.
    """
    from maestro.config import settings

    monkeypatch.setattr(settings, "LESSON_MODEL", settings.EVAL_MODEL)
    monkeypatch.setattr(settings, "SCORING_MODEL", settings.EVAL_MODEL)

    import maestro.vocab.generate_definitions as _vocab_mod
    import maestro.grammar.generate_explanations as _grammar_mod

    monkeypatch.setattr(_vocab_mod.settings, "CHAT_MODEL", settings.EVAL_MODEL)
    monkeypatch.setattr(_grammar_mod.settings, "EXPLANATION_MODEL", settings.EVAL_MODEL)


@pytest.fixture
async def db():
    client = AsyncMongoMockClient()
    await init_beanie(
        database=client["test_maestro_eval"], document_models=ALL_DOCUMENT_MODELS
    )
    yield


_RESULTS_FILE = Path(__file__).parent.parent.parent / "evals" / "results.jsonl"


@pytest.fixture
def record_eval():
    """Call at the end of an eval test to persist metrics to evals/results.jsonl.

    Usage:
        def test_foo(record_eval):
            ...
            record_eval("analyzer", {"precision": 0.97, "recall": 0.95, "n": 30})
    """
    from maestro import prompts as prompt_module

    def _record(prompt_file: str, metrics: dict) -> None:
        pf = getattr(prompt_module, prompt_file, None)
        version = pf.version if pf else "unknown"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt_file,
            "version": version,
            **metrics,
        }
        _RESULTS_FILE.parent.mkdir(exist_ok=True)
        with _RESULTS_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    return _record


@pytest.fixture
async def seeded_lesson_analyzer_cache(db):
    """Seed the taxonomy cache from JSON data files for lesson_analyzer tests."""
    from maestro import taxonomy

    gps = json.loads((_DATA_DIR / "grammar_points.json").read_text())
    cfs = json.loads((_DATA_DIR / "comm_functions.json").read_text())

    taxonomy.seed(
        gps=[SimpleNamespace(**g) for g in gps],
        cfs=[SimpleNamespace(**c) for c in cfs],
    )

    yield

    taxonomy.invalidate()


@pytest.fixture
async def eval_student(db):
    """Create a test student with A1 profile for eval tests that need student context."""
    from maestro.models import Student, LearningProfile

    s = Student(name="Eval Student")
    await s.insert()
    p = LearningProfile(student_id=s.id, cefr_estimate="A1")
    await p.insert()
    return s


@pytest.fixture
async def seeded_analyzer_cache(db):
    """Seed the taxonomy cache from JSON data files for analyzer tests."""
    from maestro import taxonomy

    gps = json.loads((_DATA_DIR / "grammar_points.json").read_text())
    cfs = json.loads((_DATA_DIR / "comm_functions.json").read_text())

    taxonomy.seed(
        gps=[SimpleNamespace(**g) for g in gps],
        # CFs in the JSON have no `description` field; supply the default so _build_prompt doesn't crash
        cfs=[SimpleNamespace(description="", **cf) for cf in cfs],
    )

    yield

    taxonomy.invalidate()
