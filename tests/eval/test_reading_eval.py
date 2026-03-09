"""LLM eval tests for reading comprehension scoring."""

import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_reading_comprehension_scoring(db, record_eval, record_item):
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
            got = (
                item.get("objective_correct", False)
                if isinstance(item, dict)
                else False
            )
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
            all_results.append(
                {"id": result_id, "got": got, "expected": expected, "pass": passed}
            )
            logger.info(
                f"[eval] {result_id}: {'PASS' if passed else 'FAIL'} got={got} expected={expected}"
            )

    item_data: dict[str, dict] = {}
    for r in all_results:
        item_data[r["id"]] = {
            "pass": r["pass"],
            "got": r.get("got"),
            "expected": r.get("expected"),
        }

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
        correct_mark = (
            "correct ✓"
            if (isinstance(item, dict) and item.get("objective_correct"))
            else "incorrect ✗"
        )
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
        # Propagate judge result to all questions of this passage
        q_idx = 1
        while f"{case['id']}_q{q_idx}" in item_data:
            item_data[f"{case['id']}_q{q_idx}"]["judge_pass"] = ok
            item_data[f"{case['id']}_q{q_idx}"]["judge_reason"] = reason
            q_idx += 1
        logger.info(
            f"[eval] judge reading {case['id']}: {'PASS' if ok else 'FAIL'} {reason}"
        )

    for case_id, data in item_data.items():
        record_item("analyzer", {"test": "reading", "case_id": case_id, **data})

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Reading content_quality={content_quality:.2%}")

    record_eval(
        "analyzer",
        {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "fp_rate": round(fp_rate, 4),
            "content_quality": round(content_quality, 4),
            "n": n,
            "test": "reading",
        },
    )

    assert accuracy >= 0.98, (
        f"Reading scoring accuracy too low: {accuracy:.2%} (failed: {failed})"
    )
    assert content_quality >= 0.70, (
        f"Reading feedback content quality too low: {content_quality:.2%}"
    )
