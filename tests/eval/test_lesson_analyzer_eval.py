"""LLM eval tests for lesson_analyzer GP and CF detection."""
import json
import logging
from pathlib import Path

import anthropic
import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_batch_gp_analysis(seeded_lesson_analyzer_cache, record_eval):
    """Measure precision/recall of _analyze_gps on combined lesson text."""
    import json as _json
    from maestro.learning.lesson_analyzer import _analyze_gps
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "lesson_analyzer_cases.json").read_text())
    gp_cases = [c for c in cases if c["type"] == "gp"]

    client = anthropic.AsyncAnthropic()

    must_correct_hits = must_correct_total = 0
    must_not_error_passes = must_not_error_total = 0
    results = []
    case_analysis = []  # store (case, correct, errors) for judging

    for case in gp_cases:
        correct, errors = await _analyze_gps(
            combined=case["combined"],
            cefr_level=case["cefr_level"],
            lesson_gp_codes=case["lesson_gp_codes"],
            client=client,
        )
        case_result = {
            "id": case["id"],
            "correct": correct,
            "errors": errors,
            "pass": True,
            "failures": [],
        }

        for code in case.get("must_appear_in_correct", []):
            must_correct_total += 1
            if code in correct:
                must_correct_hits += 1
            else:
                case_result["pass"] = False
                case_result["failures"].append(f"{code} not in correct")

        for code in case.get("must_not_appear_in_errors", []):
            must_not_error_total += 1
            if code not in errors:
                must_not_error_passes += 1
            else:
                case_result["pass"] = False
                case_result["failures"].append(f"{code} incorrectly in errors")

        results.append(case_result)
        case_analysis.append((case, correct, errors))
        logger.info(
            f"[eval] {case['id']}: {'PASS' if case_result['pass'] else 'FAIL'} "
            f"correct={correct} errors={errors} {case_result['failures']}"
        )

    precision = must_correct_hits / max(1, must_correct_total)
    fp_rate = 1.0 - (must_not_error_passes / max(1, must_not_error_total))
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] GP analysis: precision={precision:.2%}, fp_rate={fp_rate:.2%}, "
        f"failed={[r['id'] for r in failed]}"
    )

    # LLM judge: evaluate correctness of the analysis for each case
    judge_passed = 0
    judge_total = 0
    for case, correct, errors in case_analysis:
        judge_total += 1
        correct_str = ", ".join(correct) if correct else "(none)"
        errors_str = ", ".join(errors) if errors else "(none)"
        generated = f"correct: [{correct_str}], errors: [{errors_str}]"
        expected_output = case.get("expected_output")
        if expected_output is not None:
            ok, reason = _judge_ref(
                generated=generated,
                reference=_json.dumps(expected_output, ensure_ascii=False),
                context=f"GP analysis of: \"{case['combined'][:200]}\"",
            )
        else:
            prompt = (
                f'Student text: "{case["combined"][:300]}"\n'
                f"Analysis result — correct usage: [{correct_str}]\n"
                f"Analysis result — errors: [{errors_str}]\n\n"
                f"Would a skilled Italian teacher agree this analysis is reasonable?"
            )
            ok, reason = _judge(prompt)
        if ok:
            judge_passed += 1
        logger.info(f"[eval] judge gp {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] GP content_quality={content_quality:.2%}")

    record_eval("lesson_analyzer", {
        "precision": round(precision, 4),
        "fp_rate": round(fp_rate, 4),
        "content_quality": round(content_quality, 4),
        "n": len(gp_cases),
        "test": "gp_batch",
    })

    assert precision >= 0.80, f"GP batch precision too low: {precision:.2%} (failed: {failed})"
    assert fp_rate <= 0.20, f"GP batch fp_rate too high: {fp_rate:.2%} (failed: {failed})"
    assert content_quality >= 0.70, f"GP analysis content quality too low: {content_quality:.2%}"


@pytest.mark.llm_eval
async def test_cf_detection(seeded_lesson_analyzer_cache, record_eval):
    """Measure macro-category recall of _analyze_cfs_staged."""
    import maestro.learning.lesson_analyzer as la_module
    import json as _json
    from maestro.learning.lesson_analyzer import _analyze_cfs_staged
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "lesson_analyzer_cases.json").read_text())
    cf_cases = [c for c in cases if c["type"] == "cf"]

    client = anthropic.AsyncAnthropic()

    # Build code → macro_category lookup from seeded cache
    code_to_macro = {
        cf.code: cf.macro_category
        for cf in la_module._comm_functions_cache
        if hasattr(cf, "macro_category")
    }

    macro_hits = macro_total = 0
    results = []
    case_detection = []  # store (case, cf_codes, detected_macros) for judging

    for case in cf_cases:
        cf_codes = await _analyze_cfs_staged(
            combined=case["combined"],
            cefr_level=case["cefr_level"],
            client=client,
        )
        detected_macros = {code_to_macro[code] for code in cf_codes if code in code_to_macro}
        case_result = {
            "id": case["id"],
            "cf_codes": cf_codes,
            "detected_macros": list(detected_macros),
            "pass": True,
            "failures": [],
        }

        for macro in case.get("expected_macro_categories", []):
            macro_total += 1
            if macro in detected_macros:
                macro_hits += 1
            else:
                case_result["pass"] = False
                case_result["failures"].append(f"macro {macro} not detected")

        results.append(case_result)
        case_detection.append((case, cf_codes, detected_macros))
        logger.info(
            f"[eval] {case['id']}: {'PASS' if case_result['pass'] else 'FAIL'} "
            f"detected_macros={detected_macros} {case_result['failures']}"
        )

    recall = macro_hits / max(1, macro_total)
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] CF detection: recall={recall:.2%}, failed={[r['id'] for r in failed]}"
    )

    # LLM judge: evaluate each CF detection result
    judge_passed = 0
    judge_total = 0
    for case, cf_codes, detected_macros in case_detection:
        judge_total += 1
        macros_str = ", ".join(sorted(detected_macros)) if detected_macros else "(none)"
        generated = f"[{macros_str}]"
        expected_output = case.get("expected_output")
        if expected_output is not None:
            ok, reason = _judge_ref(
                generated=generated,
                reference=_json.dumps(expected_output, ensure_ascii=False),
                context=f"CF macro-categories for: \"{case['combined'][:200]}\"",
            )
        else:
            prompt = (
                f'Student text: "{case["combined"][:300]}"\n'
                f"Detected communicative macro-categories: [{macros_str}]\n\n"
                f"Are these categories a reasonable characterisation of this student utterance?"
            )
            ok, reason = _judge(prompt)
        if ok:
            judge_passed += 1
        logger.info(f"[eval] judge cf {case['id']}: {'PASS' if ok else 'FAIL'} {reason}")

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] CF content_quality={content_quality:.2%}")

    record_eval("lesson_analyzer", {
        "recall": round(recall, 4),
        "content_quality": round(content_quality, 4),
        "n": len(cf_cases),
        "test": "cf_detection",
    })

    assert recall >= 0.70, f"CF macro-category recall too low: {recall:.2%} (failed: {failed})"
    assert content_quality >= 0.70, f"CF detection content quality too low: {content_quality:.2%}"
