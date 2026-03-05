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

    cases = json.loads((FIXTURES_DIR / "grammar_explanation_cases.json").read_text())
    client = anthropic.Anthropic()

    passed_count = 0
    results = []

    for case in cases:
        gp = SimpleNamespace(
            code=case["code"],
            label=case["label"],
            cefr_level=case["cefr_level"],
            description=case["description"],
        )
        levels = _target_levels(gp)
        data = _call_claude(gp, levels, rag_content="", client=client)

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
                failures.append(f"level {level} explanation too short: {len(text)} chars")
            # Check for at least one Italian-looking sentence (ends with period, contains vowels)
            sentences = [s.strip() for s in text.split(".") if s.strip()]
            has_italian = any(
                any(c in s.lower() for c in "àèéìòùáéíóú") or
                any(w in s.lower() for w in ("il ", "la ", "un ", "una ", "ho ", "hai ", "è "))
                for s in sentences
            )
            if not has_italian:
                failures.append(f"level {level} explanation lacks Italian example sentences")

        passed = not failures
        if passed:
            passed_count += 1

        results.append({"id": case["code"], "levels": list(data.keys()) if data else [], "pass": passed, "failures": failures})
        logger.info(
            f"[eval] {case['code']}: {'PASS' if passed else 'FAIL'} "
            f"levels={list(data.keys()) if data else []} {failures}"
        )

    n = len(cases)
    pass_rate = passed_count / max(1, n)
    failed = [r for r in results if not r["pass"]]
    logger.info(f"[eval] Grammar explanations: pass_rate={pass_rate:.2%}, failed={[r['id'] for r in failed]}")
    record_eval("grammar", {
        "pass_rate": round(pass_rate, 4),
        "n": n,
        "test": "explanations",
    })

    assert pass_rate >= 0.75, f"Grammar explanation pass rate too low: {pass_rate:.2%} (failed: {failed})"
