"""LLM eval tests for grammar explanation generation quality."""

import json
import logging
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
async def test_grammar_explanation_quality(record_eval, record_item):
    """Validate that explanations are generated for all expected levels with sufficient content."""
    from generate_explanations import _call_api
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "grammar_explanation_cases.json").read_text())

    passed_count = 0
    results = []
    all_data: dict[str, dict] = {}  # code → {level: text}

    for case in cases:
        gp = {
            "code": case["code"],
            "label": case["label"],
            "cefr_level": case["cefr_level"],
            "description": case["description"],
        }
        # _call_api now generates one language at a time; call for each expected level
        data = {}
        for lang in case["expected_levels"]:
            result = await _call_api(gp, chunk_content="", lang=lang)
            if result:
                data[lang] = result
        all_data[case["code"]] = data

        failures = []

        if data is None:
            failures.append("_call_api returned None (parse error)")
            results.append({"id": case["code"], "pass": False, "failures": failures})
            logger.info(f"[eval] {case['code']}: FAIL (None returned)")
            continue

        for level in case["expected_levels"]:
            if level not in data:
                failures.append(f"level {level} missing from response")
                continue
            text = data[level]["explanation"]
            if len(text) < 100:
                failures.append(
                    f"level {level} explanation too short: {len(text)} chars"
                )
            # Check for at least one Italian-looking sentence (ends with period, contains vowels)
            sentences = [s.strip() for s in text.split(".") if s.strip()]
            has_italian = any(
                any(c in s.lower() for c in "àèéìòùáéíóú")
                or any(
                    w in s.lower()
                    for w in ("il ", "la ", "un ", "una ", "ho ", "hai ", "è ")
                )
                for s in sentences
            )
            if not has_italian:
                failures.append(
                    f"level {level} explanation lacks Italian example sentences"
                )

        passed = not failures
        if passed:
            passed_count += 1

        results.append(
            {
                "id": case["code"],
                "levels": list(data.keys()) if data else [],
                "pass": passed,
                "failures": failures,
            }
        )
        logger.info(
            f"[eval] {case['code']}: {'PASS' if passed else 'FAIL'} "
            f"levels={list(data.keys()) if data else []} {failures}"
        )

    item_data: dict[str, dict] = {}
    for r in results:
        item_data[r["id"]] = {"pass": r["pass"], "failures": r.get("failures", [])}

    n = len(cases)
    output_syntax = passed_count / max(1, n)
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Grammar explanations: output_syntax={output_syntax:.2%}, failed={[r['id'] for r in failed]}"
    )

    # LLM judge: evaluate per (GP, level) pair
    judge_passed = 0
    judge_total = 0
    case_judge: dict[str, list[bool]] = {}
    last_reason: dict[str, str] = {}
    for case in cases:
        data = all_data.get(case["code"])
        if not data:
            continue
        for level in case["expected_levels"]:
            text = data.get(level, {}).get("explanation", "")
            if not text:
                continue
            judge_total += 1
            snippet = text[:600]
            expected_output = case.get("expected_output")
            if expected_output is not None and level in expected_output:
                ok, reason = _judge_ref(
                    generated=snippet,
                    reference=str(expected_output[level]),
                    context=f"{level} explanation of '{case['label']}' for Italian learners",
                )
            else:
                prompt = (
                    f'Grammar rule: "{case["label"]}" ({case["cefr_level"]} Italian)\n'
                    f"Explanation for {level} learner:\n---\n{snippet}\n---\n\n"
                    f"Is this explanation: (1) factually correct Italian grammar, "
                    f"(2) includes at least 2 Italian example sentences, "
                    f"(3) complexity appropriate for {level}?"
                )
                ok, reason = _judge(prompt)
            if ok:
                judge_passed += 1
            case_judge.setdefault(case["code"], []).append(ok)
            last_reason[case["code"]] = reason
            logger.info(
                f"[eval] judge {case['code']}/{level}: {'PASS' if ok else 'FAIL'} {reason}"
            )

    for code, bools in case_judge.items():
        if code in item_data:
            item_data[code]["judge_pass"] = all(bools)
            item_data[code]["judge_reason"] = last_reason.get(code, "")

    for case_id, data in item_data.items():
        record_item("grammar", {"test": "explanations", "case_id": case_id, **data})

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Grammar content_quality={content_quality:.2%}")

    record_eval(
        "grammar",
        {
            "output_syntax": round(output_syntax, 4),
            "content_quality": round(content_quality, 4),
            "n": n,
            "test": "explanations",
        },
    )

    assert output_syntax >= 0.75, (
        f"Grammar explanation pass rate too low: {output_syntax:.2%} (failed: {failed})"
    )
    assert content_quality >= 0.70, (
        f"Grammar content quality too low: {content_quality:.2%}"
    )
