"""LLM eval tests for grammar explanation generation quality."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
def test_grammar_explanation_quality(record_eval):
    """Validate that explanations are generated for all expected levels with sufficient content."""
    from maestro.grammar.generate_explanations import _call_claude, _target_levels
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "grammar_explanation_cases.json").read_text())
    client = anthropic.Anthropic()

    passed_count = 0
    results = []
    all_data: dict[str, dict] = {}  # code → {level: text}

    for case in cases:
        gp = SimpleNamespace(
            code=case["code"],
            label=case["label"],
            cefr_level=case["cefr_level"],
            description=case["description"],
        )
        levels = _target_levels(gp)
        data = _call_claude(gp, levels, rag_content="", client=client)
        all_data[case["code"]] = data or {}

        failures = []

        if data is None:
            failures.append("_call_claude returned None (parse error)")
            results.append({"id": case["code"], "pass": False, "failures": failures})
            logger.info(f"[eval] {case['code']}: FAIL (None returned)")
            continue

        for level in case["expected_levels"]:
            if level not in data:
                failures.append(f"level {level} missing from response")
                continue
            text = data[level]
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

    n = len(cases)
    output_syntax = passed_count / max(1, n)
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Grammar explanations: output_syntax={output_syntax:.2%}, failed={[r['id'] for r in failed]}"
    )

    # LLM judge: evaluate per (GP, level) pair
    judge_passed = 0
    judge_total = 0
    for case in cases:
        data = all_data.get(case["code"])
        if not data:
            continue
        for level in case["expected_levels"]:
            text = data.get(level, "")
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
            logger.info(
                f"[eval] judge {case['code']}/{level}: {'PASS' if ok else 'FAIL'} {reason}"
            )

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
