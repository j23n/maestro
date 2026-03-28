"""LLM eval tests for writing feedback task-completion accuracy."""

import json
import logging
from pathlib import Path

import pytest
import yaml

_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data" / "it"

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_writing_task_completion_accuracy(db, record_eval, record_item):
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

    item_data: dict[str, dict] = {}
    for r in results:
        item_data[r["id"]] = {
            "pass": r["pass"],
            "got": r.get("got"),
            "expected": r.get("expected"),
        }

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
                f"Is the pass/fail assessment correct, and are any identified grammar errors accurate? "
                f"Do NOT penalise absence of improvement tips — the scorer only reports errors, not suggestions."
            )
            ok, reason = _judge(prompt)
        if ok:
            judge_passed += 1
        if case["id"] in item_data:
            item_data[case["id"]]["judge_pass"] = ok
            item_data[case["id"]]["judge_reason"] = reason
        logger.info(f"[eval] judge {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")

    for case_id, data in item_data.items():
        record_item("analyzer", {"test": "writing", "case_id": case_id, **data})

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


@pytest.mark.llm_eval
async def test_grammar_code_matching_by_level(db, record_eval, record_item):
    """Verify that a negation GP code is matched when it's in the code list (A1),
    but NOT matched when it's absent from the list (A2-only taxonomy seeded).

    This documents the known limitation: errors in below-current-level concepts
    are undetectable because _grammar_code_list only includes exact-level codes.
    """
    from types import SimpleNamespace
    from maestro.learning import grammar_cache
    from maestro.learning.scorer import generate_writing_feedback

    all_gps = yaml.safe_load((_DATA_DIR / "grammar_points.yaml").read_text())

    student_text = "Oggi no lo so come si dice in italiano."  # "no" instead of "non"
    writing_prompt = "Scrivi una frase sulla tua giornata."

    # --- A1 context: negation GP (a0_si_no_non) IS in the taxonomy ---
    a1_gps = [g for g in all_gps if g["cefr_level"] == "A1"]
    # Also include the A0 negation GP so it appears in the code list
    neg_gp = next((g for g in all_gps if g["code"] == "a0_si_no_non"), None)
    seed_gps = a1_gps + ([neg_gp] if neg_gp else [])
    grammar_cache.seed(gps=[SimpleNamespace(**g) for g in seed_gps])

    feedback_a1 = await generate_writing_feedback(
        prompt=writing_prompt,
        student_text=student_text,
        cefr_level="A1",
    )
    grammar_cache.invalidate()

    # --- A2 context: only A2 GPs seeded, negation GP absent ---
    a2_gps = [g for g in all_gps if g["cefr_level"] == "A2"]
    grammar_cache.seed(gps=[SimpleNamespace(**g) for g in a2_gps])

    feedback_a2 = await generate_writing_feedback(
        prompt=writing_prompt,
        student_text=student_text,
        cefr_level="A2",
    )
    grammar_cache.invalidate()

    a1_codes = feedback_a1.get("grammar_error_codes", [])
    a2_codes = feedback_a2.get("grammar_error_codes", [])
    a1_freetext = feedback_a1.get("grammar_errors", [])
    a2_freetext = feedback_a2.get("grammar_errors", [])

    logger.info(
        "[eval] grammar_code_matching_by_level",
        extra={
            "a1_error_codes": a1_codes,
            "a2_error_codes": a2_codes,
            "a1_freetext_errors": a1_freetext,
            "a2_freetext_errors": a2_freetext,
        },
    )

    record_eval(
        "analyzer",
        {
            "test": "grammar_code_matching_by_level",
            "a1_error_codes": a1_codes,
            "a2_error_codes": a2_codes,
            "a1_freetext_errors": a1_freetext,
            "a2_freetext_errors": a2_freetext,
            "a1_detected_code": bool(a1_codes),
            "a2_detected_code": bool(a2_codes),
        },
    )

    # A1: negation GP is in the list — LLM should tag it
    assert a1_codes, (
        f"Expected negation GP code in A1 context but got none. "
        f"Free-text errors: {a1_freetext}"
    )
    # A2: negation GP is absent from code list — LLM cannot tag it (known limitation)
    assert not a2_codes, (
        f"Expected no GP codes in A2 context (negation not in list) but got: {a2_codes}"
    )
