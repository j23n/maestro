"""LLM eval tests for writing feedback task-completion accuracy."""
import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_writing_task_completion_accuracy(record_eval):
    """Measure accuracy of task-completion (objective_correct) for writing feedback."""
    from maestro.learning.analyzer import generate_writing_feedback

    cases = json.loads((FIXTURES_DIR / "writing_cases.json").read_text())

    tp = fp = fn = tn = 0
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

        if expected and got:
            tp += 1
        elif not expected and got:
            fp += 1
        elif expected and not got:
            fn += 1
        else:
            tn += 1

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

    n = len(cases)
    accuracy = (tp + tn) / max(1, n)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    fp_rate = fp / max(1, fp + tn)
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Writing: accuracy={accuracy:.2%}, precision={precision:.2%}, "
        f"recall={recall:.2%}, fp_rate={fp_rate:.2%}, failed={[r['id'] for r in failed]}"
    )
    record_eval("analyzer", {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fp_rate": round(fp_rate, 4),
        "n": n,
        "test": "writing",
    })

    assert accuracy >= 0.98, f"Writing task-completion accuracy too low: {accuracy:.2%} (failed: {failed})"
