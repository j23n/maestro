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
    import json as _json
    from maestro.learning.scorer import generate_writing_feedback
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "writing_cases.json").read_text())

    tp = fp = fn = tn = 0
    results = []
    case_feedbacks = []  # store (case, feedback) for judging

    for case in cases:
        feedback = await generate_writing_feedback(
            prompt=case["prompt"],
            student_text=case["student_text"],
            cefr_level="A1",
        )
        got = (
            feedback.get("objective_correct", True)
            if isinstance(feedback, dict)
            else True
        )
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

        results.append(
            {
                "id": case["id"],
                "got": got,
                "expected": expected,
                "pass": passed,
            }
        )
        case_feedbacks.append((case, feedback if isinstance(feedback, dict) else {}))
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

    # LLM judge: evaluate feedback quality per case (skip empty submissions)
    judge_passed = 0
    judge_total = 0
    for case, feedback in case_feedbacks:
        if not case["student_text"]:
            continue  # blank/nonsense submissions have no feedback to judge
        judge_total += 1
        scored_str = (
            "task completed ✓"
            if feedback.get("objective_correct")
            else "task not completed ✗"
        )
        grammar_errors = feedback.get("grammar_errors", [])
        tips = feedback.get("tips", [])
        generated = f"scored={scored_str}, grammar_errors={grammar_errors}, tips={tips}"
        expected_output = case.get("expected_output")
        if expected_output is not None:
            ok, reason = _judge_ref(
                generated=generated,
                reference=_json.dumps(expected_output, ensure_ascii=False),
                context=f'Writing feedback for prompt: "{case["prompt"]}"',
            )
        else:
            prompt = (
                f'Writing prompt: "{case["prompt"]}"\n'
                f'Student text: "{case["student_text"]}"\n'
                f"Scored: {scored_str}\n"
                f"Grammar errors identified: {grammar_errors}\n"
                f"Tips: {tips}\n\n"
                f"Is this feedback accurate and constructive for an A1 Italian learner?"
            )
            ok, reason = _judge(prompt)
        if ok:
            judge_passed += 1
        logger.info(f"[eval] judge {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Writing content_quality={content_quality:.2%}")

    record_eval(
        "analyzer",
        {
            "accuracy": round(accuracy, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "fp_rate": round(fp_rate, 4),
            "content_quality": round(content_quality, 4),
            "n": n,
            "test": "writing",
        },
    )

    assert accuracy >= 0.98, (
        f"Writing task-completion accuracy too low: {accuracy:.2%} (failed: {failed})"
    )
    assert content_quality >= 0.70, (
        f"Writing feedback content quality too low: {content_quality:.2%}"
    )
