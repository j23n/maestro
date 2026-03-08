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
    import json as _json
    from maestro.vocab.generate_definitions import _call_claude
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

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
                        failures.append(
                            f"{level}.senses[{i}].examples has {len(examples)} items (max 1)"
                        )

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
    output_syntax = passed_count / max(1, n)
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Vocab definitions: output_syntax={output_syntax:.2%}, failed={[r['id'] for r in failed]}"
    )

    # LLM judge: evaluate per (word, level) pair
    judge_passed = 0
    judge_total = 0
    for c in cases:
        w = c["word"]
        entry = result.get(w) or result.get(w.lower())
        if not entry:
            continue
        translation = entry.get("translation", "")
        for level in ("A1", "A2"):
            level_data = entry.get(level)
            if not level_data:
                continue
            judge_total += 1
            senses = level_data.get("senses", [])
            sense_text = (
                "; ".join(s.get("definition", "") for s in senses[:2])
                if senses
                else "(none)"
            )
            example = (
                senses[0].get("examples", [""])[0]
                if senses and senses[0].get("examples")
                else ""
            )
            generated = f"{sense_text} / {translation}"
            expected_output = c.get("expected_output")
            if expected_output is not None and level in expected_output:
                ok, reason = _judge_ref(
                    generated=generated,
                    reference=_json.dumps(expected_output[level], ensure_ascii=False),
                    context=f"A{level} Italian vocabulary entry for '{w}' ({c['part_of_speech']})",
                )
            else:
                prompt = (
                    f'Italian word: "{w}" ({c["part_of_speech"]})\n'
                    f"Level: {level}\n"
                    f'Generated definition: "{sense_text}"\n'
                    f'Generated translation: "{translation}"\n'
                    f'Example: "{example}"\n\n'
                    f"Is this {level} vocabulary entry: (1) factually correct, "
                    f"(2) appropriately simplified for beginners, (3) translation accurate?"
                )
                ok, reason = _judge(prompt)
            if ok:
                judge_passed += 1
            logger.info(
                f"[eval] judge {w}/{level}: {'PASS' if ok else 'FAIL'} {reason}"
            )

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Vocab content_quality={content_quality:.2%}")

    record_eval(
        "vocab",
        {
            "output_syntax": round(output_syntax, 4),
            "content_quality": round(content_quality, 4),
            "n": n,
            "test": "definitions",
        },
    )

    assert output_syntax >= 0.80, (
        f"Vocab definition pass rate too low: {output_syntax:.2%} (failed: {failed})"
    )
    assert content_quality >= 0.70, (
        f"Vocab content quality too low: {content_quality:.2%}"
    )
