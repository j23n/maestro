"""LLM eval tests for writing feedback task-completion accuracy."""
import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_writing_task_completion_accuracy():
    """Measure accuracy of task-completion (objective_correct) for writing feedback."""
    from maestro.learning.analyzer import generate_writing_feedback

    cases = json.loads((FIXTURES_DIR / "writing_cases.json").read_text())

    correct_count = 0
    results = []

    for case in cases:
        feedback = await generate_writing_feedback(
            prompt=case["prompt"],
            student_text=case["student_text"],
            cefr_level="A1",
        )
        got = feedback.get("objective_correct", True) if isinstance(feedback, dict) else True
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
        logger.info(
            f"[eval] {case['id']}: {'PASS' if passed else 'FAIL'} "
            f"got={got} expected={expected}"
        )

    accuracy = correct_count / max(1, len(cases))
    failed = [r for r in results if not r["pass"]]
    logger.info(f"[eval] Writing accuracy={accuracy:.2%}, failed={[r['id'] for r in failed]}")

    assert accuracy >= 0.98, f"Writing task-completion accuracy too low: {accuracy:.2%} (failed: {failed})"
