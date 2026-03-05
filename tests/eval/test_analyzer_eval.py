"""LLM eval tests for grammar/CF tagging precision and recall."""
import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_analyzer_grammar_tagging(seeded_analyzer_cache, record_eval):
    """Measure precision/recall of grammar code tagging against golden cases."""
    from maestro.learning.analyzer import analyze_message

    cases = json.loads((FIXTURES_DIR / "analyzer_cases.json").read_text())

    must_correct_hits = 0
    must_correct_total = 0
    must_error_hits = 0
    must_error_total = 0
    false_positive_cases = 0
    false_positive_total = 0

    results = []
    for case in cases:
        result = await analyze_message(case["text"])

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
        logger.info(f"[eval] {case['id']}: {'PASS' if case_result['pass'] else 'FAIL'} {case_result['failures']}")

    precision = must_correct_hits / max(1, must_correct_total)
    recall = must_error_hits / max(1, must_error_total)
    fp_rate = 1.0 - (false_positive_cases / max(1, false_positive_total))

    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Grammar tagging: precision={precision:.2%}, recall={recall:.2%}, "
        f"fp_rate={fp_rate:.2%}, failed_cases={[r['id'] for r in failed]}"
    )
    record_eval("analyzer", {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "fp_rate": round(fp_rate, 4),
        "n": len(cases),
        "test": "grammar_tagging",
    })

    assert precision >= 0.98, f"Grammar tagging precision too low: {precision:.2%} (failed: {failed})"
    if must_error_total > 0:
        assert recall >= 0.98, f"Grammar error recall too low: {recall:.2%} (failed: {failed})"
    if false_positive_total > 0:
        assert fp_rate <= 0.02, f"False positive rate too high: {fp_rate:.2%} (failed: {failed})"
