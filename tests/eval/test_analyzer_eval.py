"""LLM eval tests for grammar/CF tagging precision and recall."""
import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_analyzer_grammar_tagging(seeded_analyzer_cache, eval_student, record_eval):
    """Measure precision/recall of grammar code tagging against golden cases."""
    import json as _json
    from maestro.learning.analyzer import analyze_message
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "analyzer_cases.json").read_text())

    must_correct_hits = 0
    must_correct_total = 0
    must_error_hits = 0
    must_error_total = 0
    false_positive_cases = 0
    false_positive_total = 0

    results = []
    case_results_map = []  # store (case, result) for judging

    for case in cases:
        result = await analyze_message(case["text"], student_id=eval_student.id)

        case_result = {
            "id": case["id"],
            "text": case["text"],
            "grammar_correct": result.grammar_correct if result else [],
            "grammar_errors": result.grammar_errors if result else [],
            "pass": True,
            "failures": [],
        }

        for code in case.get("must_appear_in_correct", []):
            must_correct_total += 1
            correct_codes = result.grammar_correct if result else []
            if code in correct_codes:
                must_correct_hits += 1
            else:
                case_result["pass"] = False
                case_result["failures"].append(f"{code} not in grammar_correct")

        for code in case.get("must_appear_in_errors", []):
            must_error_total += 1
            error_codes = result.grammar_errors if result else []
            if code in error_codes:
                must_error_hits += 1
            else:
                case_result["pass"] = False
                case_result["failures"].append(f"{code} not in grammar_errors")

        for code in case.get("must_not_appear_in_errors", []):
            error_codes = result.grammar_errors if result else []
            if code in error_codes:
                case_result["pass"] = False
                case_result["failures"].append(f"{code} incorrectly in grammar_errors")

        if "max_error_count" in case:
            false_positive_total += 1
            error_count = len(result.grammar_errors) if result else 0
            if error_count <= case["max_error_count"]:
                false_positive_cases += 1
            else:
                case_result["pass"] = False
                case_result["failures"].append(
                    f"Too many errors: {error_count} > {case['max_error_count']}"
                )

        results.append(case_result)
        case_results_map.append((case, result))
        logger.info(f"[eval] {case['id']}: {'PASS' if case_result['pass'] else 'FAIL'} {case_result['failures']}")

    precision = must_correct_hits / max(1, must_correct_total)
    recall = must_error_hits / max(1, must_error_total)
    fp_rate = 1.0 - (false_positive_cases / max(1, false_positive_total))

    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Grammar tagging: precision={precision:.2%}, recall={recall:.2%}, "
        f"fp_rate={fp_rate:.2%}, failed_cases={[r['id'] for r in failed]}"
    )

    # LLM judge: evaluate analysis quality, skip max_error_count cases (no grammar to judge)
    judge_passed = 0
    judge_total = 0
    for case, result in case_results_map:
        if "max_error_count" in case:
            continue  # no specific grammar expectation to judge
        judge_total += 1
        correct_str = ", ".join(result.grammar_correct) if result and result.grammar_correct else "(none)"
        errors_str = ", ".join(result.grammar_errors) if result and result.grammar_errors else "(none)"
        generated = f"correct: [{correct_str}], errors: [{errors_str}]"
        expected_output = case.get("expected_output")
        if expected_output is not None:
            ok, reason = _judge_ref(
                generated=generated,
                reference=_json.dumps(expected_output, ensure_ascii=False),
                context=f"Grammar analysis of: \"{case['text']}\"",
            )
        else:
            prompt = (
                f'Student text: "{case["text"]}"\n'
                f"Identified correct grammar: [{correct_str}]\n"
                f"Identified errors: [{errors_str}]\n\n"
                f"Would a skilled Italian teacher agree this is a reasonable characterisation "
                f"of the student's grammar use?"
            )
            ok, reason = _judge(prompt)
        if ok:
            judge_passed += 1
        logger.info(f"[eval] judge {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Analyzer content_quality={content_quality:.2%}")

    record_eval("analyzer", {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fp_rate": round(fp_rate, 4),
        "content_quality": round(content_quality, 4),
        "n": len(cases),
        "test": "grammar_tagging",
    })

    assert precision >= 0.98, f"Grammar tagging precision too low: {precision:.2%} (failed: {failed})"
    if must_error_total > 0:
        assert recall >= 0.98, f"Grammar error recall too low: {recall:.2%} (failed: {failed})"
    if false_positive_total > 0:
        assert fp_rate <= 0.02, f"False positive rate too high: {fp_rate:.2%} (failed: {failed})"
    assert content_quality >= 0.70, f"Analyzer content quality too low: {content_quality:.2%}"
