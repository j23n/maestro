"""LLM eval tests for vocabulary definition generation quality."""
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.llm_eval
def test_vocab_definition_quality(record_eval):
    """Validate A1/A2 definition structure and field presence for common words."""
    from maestro.vocab.generate_definitions import _call_claude

    cases = json.loads((FIXTURES_DIR / "vocab_cases.json").read_text())

    # Build SimpleNamespace word mocks matching what _call_claude expects
    words = [
        SimpleNamespace(
            word=c["word"],
            part_of_speech=c["part_of_speech"],
            senses=[
                SimpleNamespace(definition=s["definition"], examples=s["examples"])
                for s in c["senses"]
            ],
        )
        for c in cases
    ]

    result = _call_claude(words)

    passed_count = 0
    results = []

    for word_ns in words:
        w = word_ns.word
        entry = result.get(w) or result.get(w.lower())
        failures = []

        if not entry:
            failures.append("word missing from response")
            results.append({"id": w, "pass": False, "failures": failures})
            logger.info(f"[eval] {w}: FAIL (missing from response)")
            continue

        # A1 and A2 keys must be present
        for level in ("A1", "A2"):
            level_data = entry.get(level, {})
            if not level_data:
                failures.append(f"{level} key missing or empty")
                continue
            senses = level_data.get("senses", [])
            if not senses:
                failures.append(f"{level}.senses is empty")
            else:
                for i, sense in enumerate(senses):
                    examples = sense.get("examples", [])
                    if len(examples) > 1:
                        failures.append(f"{level}.senses[{i}].examples has {len(examples)} items (max 1)")

        # Translation must be present and non-empty
        translation = entry.get("translation", "")
        if not translation or not translation.strip():
            failures.append("translation missing or empty")

        passed = not failures
        if passed:
            passed_count += 1

        results.append({"id": w, "pass": passed, "failures": failures})
        logger.info(f"[eval] {w}: {'PASS' if passed else 'FAIL'} {failures}")

    n = len(words)
    pass_rate = passed_count / max(1, n)
    failed = [r for r in results if not r["pass"]]
    logger.info(f"[eval] Vocab definitions: pass_rate={pass_rate:.2%}, failed={[r['id'] for r in failed]}")
    record_eval("vocab", {
        "pass_rate": round(pass_rate, 4),
        "n": n,
        "test": "definitions",
    })

    assert pass_rate >= 0.80, f"Vocab definition pass rate too low: {pass_rate:.2%} (failed: {failed})"
