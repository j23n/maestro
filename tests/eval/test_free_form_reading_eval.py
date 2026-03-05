"""LLM eval tests for free-form drill scoring and reading comprehension scoring."""
import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_free_form_drill_scoring(record_eval):
    """Measure precision/recall of free-form drill objective_correct scoring."""
    from maestro.learning.analyzer import score_free_form_drill

    cases = json.loads((FIXTURES_DIR / "free_form_cases.json").read_text())

    tp = fp = fn = tn = 0
    results = []

    for case in cases:
        result = await score_free_form_drill(
            prompt=case["prompt"],
            student_text=case["student_text"],
            grammar_point_code=case["grammar_point_code"],
            cefr_level=case["cefr_level"],
        )
        got = result.get("objective_correct", True) if isinstance(result, dict) else True
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

        results.append({"id": case["id"], "got": got, "expected": expected, "pass": passed})
        logger.info(f"[eval] {case['id']}: {'PASS' if passed else 'FAIL'} got={got} expected={expected}")

    n = len(cases)
    accuracy = (tp + tn) / max(1, n)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    fp_rate = fp / max(1, fp + tn)
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Free-form: accuracy={accuracy:.2%}, precision={precision:.2%}, "
        f"recall={recall:.2%}, fp_rate={fp_rate:.2%}, failed={[r['id'] for r in failed]}"
    )
    record_eval("analyzer", {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fp_rate": round(fp_rate, 4),
        "n": n,
        "test": "free_form",
    })

    assert accuracy >= 0.98, f"Free-form scoring accuracy too low: {accuracy:.2%} (failed: {failed})"


@pytest.mark.llm_eval
async def test_reading_comprehension_scoring(record_eval):
    """Measure precision/recall of reading comprehension answer scoring."""
    from maestro.learning.analyzer import score_reading_answers

    cases = json.loads((FIXTURES_DIR / "reading_cases.json").read_text())

    tp = fp = fn = tn = 0
    all_results = []

    for case in cases:
        scored = await score_reading_answers(
            questions=case["questions"],
            correct_answers=case["correct_answers"],
            student_answers=case["student_answers"],
        )
        for i, (item, expected) in enumerate(zip(scored, case["expected_results"])):
            got = item.get("objective_correct", False) if isinstance(item, dict) else False
            passed = got == expected

            if expected and got:
                tp += 1
            elif not expected and got:
                fp += 1
            elif expected and not got:
                fn += 1
            else:
                tn += 1

            result_id = f"{case['id']}_q{i + 1}"
            all_results.append({"id": result_id, "got": got, "expected": expected, "pass": passed})
            logger.info(f"[eval] {result_id}: {'PASS' if passed else 'FAIL'} got={got} expected={expected}")

    n = tp + fp + fn + tn
    accuracy = (tp + tn) / max(1, n)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    fp_rate = fp / max(1, fp + tn)
    failed = [r for r in all_results if not r["pass"]]
    logger.info(
        f"[eval] Reading: accuracy={accuracy:.2%}, precision={precision:.2%}, "
        f"recall={recall:.2%}, fp_rate={fp_rate:.2%}, failed={[r['id'] for r in failed]}"
    )
    record_eval("analyzer", {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fp_rate": round(fp_rate, 4),
        "n": n,
        "test": "reading",
    })

    assert accuracy >= 0.98, f"Reading scoring accuracy too low: {accuracy:.2%} (failed: {failed})"
