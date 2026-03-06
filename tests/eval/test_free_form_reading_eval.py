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
    import json as _json
    from maestro.learning.scorer import score_free_form_drill
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "free_form_cases.json").read_text())

    tp = fp = fn = tn = 0
    results = []
    case_scores = []  # store (case, result) for judging

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
        case_scores.append((case, result if isinstance(result, dict) else {}))
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

    # LLM judge: evaluate feedback quality per case (skip blank/nonsense)
    judge_passed = 0
    judge_total = 0
    for case, scored in case_scores:
        if not case["student_text"] or len(case["student_text"]) < 3:
            continue
        judge_total += 1
        correct_mark = "correct ✓" if scored.get("objective_correct") else "incorrect ✗"
        tips = scored.get("tips", [])
        note = scored.get("objective_note", "")
        generated = f"scored={correct_mark}, tips={tips}, note={note!r}"
        expected_output = case.get("expected_output")
        if expected_output is not None:
            ok, reason = _judge_ref(
                generated=generated,
                reference=_json.dumps(expected_output, ensure_ascii=False),
                context=f'Free-form drill feedback for: "{case["prompt"]}"',
            )
        else:
            prompt = (
                f'Exercise prompt: "{case["prompt"]}"\n'
                f'Student text: "{case["student_text"]}"\n'
                f"Grammar point: {case['grammar_point_code']}\n"
                f"Scored: {correct_mark}\n"
                f"Tips: {tips}\n"
                f'Note: "{note}"\n\n'
                f"Is this feedback helpful and accurate for an Italian learner?"
            )
            ok, reason = _judge(prompt)
        if ok:
            judge_passed += 1
        logger.info(f"[eval] judge {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Free-form content_quality={content_quality:.2%}")

    record_eval("analyzer", {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fp_rate": round(fp_rate, 4),
        "content_quality": round(content_quality, 4),
        "n": n,
        "test": "free_form",
    })

    assert accuracy >= 0.98, f"Free-form scoring accuracy too low: {accuracy:.2%} (failed: {failed})"
    assert content_quality >= 0.70, f"Free-form feedback content quality too low: {content_quality:.2%}"


@pytest.mark.llm_eval
async def test_reading_comprehension_scoring(record_eval):
    """Measure precision/recall of reading comprehension answer scoring."""
    import json as _json
    from maestro.learning.scorer import score_reading_answers
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "reading_cases.json").read_text())

    tp = fp = fn = tn = 0
    all_results = []
    passage_scores = []  # store (case, scored_list) for judging

    for case in cases:
        scored = await score_reading_answers(
            questions=case["questions"],
            correct_answers=case["correct_answers"],
            student_answers=case["student_answers"],
        )
        passage_scores.append((case, scored))

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

    # LLM judge: evaluate per passage (judge first Q/A pair per passage)
    judge_passed = 0
    judge_total = 0
    for case, scored in passage_scores:
        if not scored or not case["questions"]:
            continue
        judge_total += 1
        # Judge the first question/answer pair as representative of the passage scoring
        q = case["questions"][0]
        expected_ans = case["correct_answers"][0]
        student_ans = case["student_answers"][0]
        item = scored[0] if scored else {}
        correct_mark = "correct ✓" if (isinstance(item, dict) and item.get("objective_correct")) else "incorrect ✗"
        note = item.get("objective_note", "") if isinstance(item, dict) else ""
        generated = f"scored={correct_mark}, note={note!r}"
        expected_output = case.get("expected_output")
        if expected_output is not None:
            ok, reason = _judge_ref(
                generated=generated,
                reference=_json.dumps(expected_output, ensure_ascii=False),
                context=f'Reading comprehension scoring for Q: "{q}"',
            )
        else:
            prompt = (
                f'Question: "{q}"\n'
                f'Expected answer: "{expected_ans}"\n'
                f'Student answer: "{student_ans}"\n'
                f"Scored: {correct_mark}\n"
                f'Feedback note: "{note}"\n\n'
                f"Is the scoring decision and note reasonable?"
            )
            ok, reason = _judge(prompt)
        if ok:
            judge_passed += 1
        logger.info(f"[eval] judge reading {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Reading content_quality={content_quality:.2%}")

    record_eval("analyzer", {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fp_rate": round(fp_rate, 4),
        "content_quality": round(content_quality, 4),
        "n": n,
        "test": "reading",
    })

    assert accuracy >= 0.98, f"Reading scoring accuracy too low: {accuracy:.2%} (failed: {failed})"
    assert content_quality >= 0.70, f"Reading feedback content quality too low: {content_quality:.2%}"
