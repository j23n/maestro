"""LLM eval tests for drill scoring accuracy."""
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data"


def _make_item(prompt: str, correct_answer: str) -> MagicMock:
    item = MagicMock()
    item.prompt = prompt
    item.correct_answer = correct_answer
    return item


@pytest.fixture(autouse=True)
def seed_cache_for_scoring():
    """Seed analyzer cache with only the GPs referenced in the scoring fixtures.

    Using the full 231-GP list makes the grammar_code_list section of the
    score_multi_item_drill prompt enormous and degrades model accuracy.
    """
    import maestro.learning.analyzer as analyzer_module

    cases = json.loads((FIXTURES_DIR / "scoring_cases.json").read_text())
    codes = {c["grammar_point_code"] for c in cases}

    gps = json.loads((_DATA_DIR / "grammar_points.json").read_text())
    relevant = [g for g in gps if g["code"] in codes]

    original = analyzer_module._grammar_points_cache[:]
    analyzer_module._grammar_points_cache = [SimpleNamespace(**g) for g in relevant]
    analyzer_module._student_level = "A1"

    yield

    analyzer_module._grammar_points_cache = original


@pytest.mark.llm_eval
async def test_scoring_accuracy(db):
    """Measure accuracy of fill_blank and error_correction scoring against golden cases."""
    from maestro.learning.analyzer import score_multi_item_drill

    cases = json.loads((FIXTURES_DIR / "scoring_cases.json").read_text())

    correct_count = 0
    results = []

    for case in cases:
        item = _make_item(case["prompt"], case["correct_answer"])
        raw = await score_multi_item_drill(
            exercise_type=case["exercise_type"],
            grammar_point_code=case["grammar_point_code"],
            items=[item],
            student_answers=[case["student_answer"]],
        )
        got = raw[0]["objective_correct"] if raw else False
        expected = case["expected_objective_correct"]
        passed = got == expected

        if passed:
            correct_count += 1

        results.append({
            "id": case["id"],
            "got": got,
            "expected": expected,
            "pass": passed,
        })
        logger.info(f"[eval] {case['id']}: {'PASS' if passed else 'FAIL'} got={got} expected={expected}")

    accuracy = correct_count / max(1, len(cases))
    failed = [r for r in results if not r["pass"]]
    logger.info(f"[eval] Scoring accuracy={accuracy:.2%}, failed={[r['id'] for r in failed]}")

    assert accuracy >= 0.98, f"Scoring accuracy too low: {accuracy:.2%} (failed: {failed})"
