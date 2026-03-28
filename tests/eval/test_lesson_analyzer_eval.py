"""LLM eval tests for lesson_analyzer CF detection."""

import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_cf_detection(seeded_lesson_analyzer_cache, record_eval, record_item):
    """Measure macro-category recall of _analyze_cfs_staged."""
    import json as _json
    from maestro.learning.lesson_analyzer import _analyze_cfs_staged
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "lesson_analyzer_cases.json").read_text())
    cf_cases = [c for c in cases if c["type"] == "cf"]

    # Build code → macro_category lookup from seeded cache
    from maestro.learning import grammar_cache

    code_to_macro = {
        cf.code: cf.macro_category
        for cf in grammar_cache.comm_functions()
        if hasattr(cf, "macro_category")
    }

    macro_hits = macro_total = 0
    results = []
    case_detection = []  # store (case, cf_codes, detected_macros) for judging

    for case in cf_cases:
        cf_codes = await _analyze_cfs_staged(
            combined=case["combined"],
            cefr_level=case["cefr_level"],
        )
        detected_macros = {
            code_to_macro[code] for code in cf_codes if code in code_to_macro
        }
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

    item_data: dict[str, dict] = {}
    for r in results:
        item_data[r["id"]] = {"pass": r["pass"], "failures": r.get("failures", [])}

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
                context=f'CF macro-categories for: "{case["combined"][:200]}"',
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
        if case["id"] in item_data:
            item_data[case["id"]]["judge_pass"] = ok
            item_data[case["id"]]["judge_reason"] = reason
        logger.info(
            f"[eval] judge cf {case['id']}: {'PASS' if ok else 'FAIL'} {reason}"
        )

    for case_id, data in item_data.items():
        record_item(
            "lesson_analyzer", {"test": "cf_detection", "case_id": case_id, **data}
        )

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] CF content_quality={content_quality:.2%}")

    record_eval(
        "lesson_analyzer",
        {
            "recall": round(recall, 4),
            "content_quality": round(content_quality, 4),
            "n": len(cf_cases),
            "test": "cf_detection",
        },
    )

    assert recall >= 0.70, (
        f"CF macro-category recall too low: {recall:.2%} (failed: {failed})"
    )
    assert content_quality >= 0.70, (
        f"CF detection content quality too low: {content_quality:.2%}"
    )
