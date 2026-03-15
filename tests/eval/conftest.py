import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from mongomock_motor import AsyncMongoMockClient
from beanie import init_beanie

from maestro.models import ALL_DOCUMENT_MODELS

_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data" / "it"
_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_LOCK_FILE = _PROMPTS_DIR / "versions.lock"


def pytest_configure(config):
    """Abort the eval session if any prompt file has drifted from versions.lock."""
    if not _LOCK_FILE.exists():
        pytest.exit(
            "prompts/versions.lock not found — run scripts/update_prompt_lock.py",
            returncode=1,
        )
    lock_data = json.loads(_LOCK_FILE.read_text())
    failures = []
    for path in sorted(_PROMPTS_DIR.glob("*.yaml")):
        actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.name not in lock_data:
            failures.append(f"prompts/{path.name} is not in versions.lock")
        elif actual_sha != lock_data[path.name].get("sha256", ""):
            failures.append(
                f"prompts/{path.name} has changed without a version bump — "
                "run scripts/update_prompt_lock.py after bumping version: in the YAML"
            )
    if failures:
        pytest.exit(
            "Prompt version mismatch — eval aborted:\n"
            + "\n".join(f"  {f}" for f in failures),
            returncode=1,
        )


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
_ITEMS_FILE = Path(__file__).parent.parent.parent / "evals" / "items.jsonl"


def _result_key(entry: dict) -> tuple:
    """Identity key for deduplication: one result per (prompt, version, test[, subtest, model])."""
    return (
        entry.get("prompt"),
        entry.get("version"),
        entry.get("test"),
        entry.get("subtest"),
        entry.get("model"),
    )


@pytest.fixture
def record_eval():
    """Call at the end of an eval test to persist metrics to evals/results.jsonl.

    Upserts by (prompt, version, test) — a given prompt version gets exactly one
    result entry per eval test. Re-running the same eval replaces the previous result.

    Usage:
        def test_foo(record_eval):
            ...
            record_eval("analyzer", {"precision": 0.97, "recall": 0.95, "n": 30})
    """
    from maestro import prompts as prompt_module

    def _record(prompt_file: str, metrics: dict) -> None:
        from maestro.config import settings
        from maestro.prompts import judge as _judge_prompts

        pf = getattr(prompt_module, prompt_file, None)
        version = pf.version if pf else "unknown"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt_file,
            "version": version,
            "judge_model": settings.EVAL_MODEL,
            "judge_version": _judge_prompts.version,
            **metrics,
        }
        _RESULTS_FILE.parent.mkdir(exist_ok=True)
        existing = []
        if _RESULTS_FILE.exists():
            for line in _RESULTS_FILE.read_text().splitlines():
                line = line.strip()
                if line:
                    existing.append(json.loads(line))
        key = _result_key(entry)
        updated = [e for e in existing if _result_key(e) != key]
        updated.append(entry)
        with _RESULTS_FILE.open("w") as f:
            for e in updated:
                f.write(json.dumps(e) + "\n")

    return _record


@pytest.fixture
def record_item():
    """Record per-item eval results to evals/items.jsonl.

    All items recorded in a single test share a run_ts, so the failures
    subcommand can group them by run and show which cases failed.

    Usage:
        async def test_foo(record_item):
            for case in cases:
                ...
                record_item("scorer", {
                    "test": "scoring_compare",
                    "model": model_name,
                    "case_id": case["id"],
                    "pass": passed,
                    "got": got,
                    "expected": expected,
                    # optional: "reason": "why it failed"
                })
    """
    from maestro import prompts as prompt_module

    run_ts = datetime.now(timezone.utc).isoformat()

    def _record(prompt_file: str, item: dict) -> None:
        from maestro.config import settings
        from maestro.prompts import judge as _judge_prompts

        pf = getattr(prompt_module, prompt_file, None)
        version = pf.version if pf else "unknown"
        entry = {
            "run_ts": run_ts,
            "ts": datetime.now(timezone.utc).isoformat(),
            "prompt": prompt_file,
            "version": version,
            "judge_model": settings.EVAL_MODEL,
            "judge_version": _judge_prompts.version,
            **item,
        }
        _ITEMS_FILE.parent.mkdir(exist_ok=True)
        # items.jsonl grows unbounded; use `compare.py failures --latest` to filter
        # to the most-recent run per (prompt, version, test, model, subtest) group.
        with _ITEMS_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    return _record


@pytest.fixture
async def seeded_lesson_analyzer_cache(db):
    """Seed the taxonomy cache from JSON data files for lesson_analyzer tests."""
    from maestro import taxonomy

    gps = yaml.safe_load((_DATA_DIR / "grammar_points.yaml").read_text())
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

    gps = yaml.safe_load((_DATA_DIR / "grammar_points.yaml").read_text())
    cfs = json.loads((_DATA_DIR / "comm_functions.json").read_text())

    taxonomy.seed(
        gps=[SimpleNamespace(**g) for g in gps],
        cfs=[SimpleNamespace(**cf) for cf in cfs],
    )

    yield

    taxonomy.invalidate()
