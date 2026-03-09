"""LLM eval tests for lesson content generation."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data" / "it"


@pytest.mark.llm_eval
async def test_lesson_content_structure(db, record_eval, record_item):
    """Validate structural properties of _generate_lesson_content output."""
    import json as _json
    from maestro.lezione.planner import _generate_lesson_content
    from maestro.models import CurriculumScenario
    from tests.eval.judge import judge as _judge, judge_against_reference as _judge_ref

    cases = json.loads((FIXTURES_DIR / "planner_content_cases.json").read_text())

    passed_count = 0
    results = []
    generated_content = []  # store (case, content) for judging

    for case in cases:
        grammar_gps = [SimpleNamespace(**gp) for gp in case["grammar_gps"]]
        speaking_cfs = [SimpleNamespace(**cf) for cf in case["speaking_cfs"]]
        scenario = CurriculumScenario(
            slug="test",
            label=case.get("topic", "Test"),
            description=case.get("topic", "Test scenario"),
            cefr_level=case["cefr_level"],
            cf_codes=[],
            gp_codes=[],
            depths=[case.get("topic", "Test"), "Depth 2", "Depth 3"],
        )

        content = await _generate_lesson_content(
            cefr_level=case["cefr_level"],
            scenario=scenario,
            depth=1,
            profile=None,
            grammar_gps=grammar_gps,
            drill_specs=case["drill_specs"],
            reading_count=case["reading_count"],
            include_writing=case["include_writing"],
            speaking_cfs=speaking_cfs,
        )

        failures = []

        if not content.model_fields_set:
            failures.append("empty content returned")
            results.append({"id": case["id"], "pass": False, "failures": failures})
            generated_content.append((case, None))
            logger.info(f"[eval] {case['id']}: FAIL (empty content)")
            continue

        # Check drills
        drills = content.drills
        if len(drills) < case.get("expect_drills", 0):
            failures.append(
                f"expected {case['expect_drills']} drills, got {len(drills)}"
            )
        for spec, drill in zip(case["drill_specs"], drills):
            if spec["exercise_type"] in ("fill_blank", "error_correction"):
                items = drill.items
                expected_items = case.get(
                    f"expect_items_per_{spec['exercise_type']}", 10
                )
                if len(items) < expected_items:
                    failures.append(
                        f"drill {spec['grammar_point_code']}: expected {expected_items} items, got {len(items)}"
                    )

        # Check readings
        readings = content.readings
        if len(readings) < case.get("expect_readings", 0):
            failures.append(
                f"expected {case['expect_readings']} readings, got {len(readings)}"
            )
        for i, reading in enumerate(readings):
            q_count = len(reading.questions)
            if q_count < 5:
                failures.append(f"reading {i}: expected >=5 questions, got {q_count}")

        # Check writing
        if case.get("expect_writing") and not content.writing:
            failures.append("expected writing activity but none returned")
        if not case.get("expect_writing") and content.writing:
            failures.append("unexpected writing activity returned")

        # Check speakings
        speakings = content.speakings
        if len(speakings) < case.get("expect_speakings", 0):
            failures.append(
                f"expected {case.get('expect_speakings', 0)} speakings, got {len(speakings)}"
            )

        passed = not failures
        if passed:
            passed_count += 1

        results.append({"id": case["id"], "pass": passed, "failures": failures})
        generated_content.append((case, content))
        logger.info(
            f"[eval] {case['id']}: {'PASS' if passed else 'FAIL'} "
            f"fields={list(content.model_fields_set)} {failures}"
        )

    item_data: dict[str, dict] = {}
    for r in results:
        item_data[r["id"]] = {"pass": r["pass"], "failures": r.get("failures", [])}

    n = len(cases)
    output_syntax = passed_count / max(1, n)
    failed = [r for r in results if not r["pass"]]
    logger.info(
        f"[eval] Content structure: output_syntax={output_syntax:.2%}, failed={[r['id'] for r in failed]}"
    )

    # LLM judge: evaluate first drill item and first reading per case
    judge_passed = 0
    judge_total = 0
    case_judge: dict[str, list[bool]] = {}
    last_reason: dict[str, str] = {}
    for case, content in generated_content:
        if not content:
            continue
        drills = content.drills
        # Judge first drill item
        if drills and case.get("drill_specs"):
            spec = case["drill_specs"][0]
            drill = drills[0]
            items = drill.items
            if items:
                first_item = items[0]
                judge_total += 1
                generated = f"{first_item.prompt} → {first_item.correct_answer or ''}"
                expected_output = case.get("expected_output", {}).get("drill")
                if expected_output is not None:
                    ok, reason = _judge_ref(
                        generated=generated,
                        reference=_json.dumps(expected_output, ensure_ascii=False),
                        context=f"{spec['exercise_type']} drill for {spec['grammar_point_code']} ({case['cefr_level']})",
                    )
                else:
                    prompt = (
                        f'Grammar point: "{spec["grammar_point_code"]}" ({spec["exercise_type"]}, {case["cefr_level"]})\n'
                        f'Drill item prompt: "{first_item.prompt}"\n'
                        f'Correct answer: "{first_item.correct_answer or ""}"\n\n'
                        f"Is this item: (1) testing the stated grammar point, "
                        f"(2) using natural Italian, (3) unambiguous?"
                    )
                    ok, reason = _judge(prompt)
                if ok:
                    judge_passed += 1
                case_judge.setdefault(case["id"], []).append(ok)
                last_reason[case["id"]] = reason
                logger.info(
                    f"[eval] judge drill {case['id']}: {'PASS' if ok else 'FAIL'} {reason}"
                )

        # Judge first reading text
        readings = content.readings
        if readings:
            reading = readings[0]
            text = reading.text
            if text:
                judge_total += 1
                snippet = text[:200]
                expected_output = case.get("expected_output", {}).get("reading")
                if expected_output is not None:
                    ok, reason = _judge_ref(
                        generated=snippet,
                        reference=_json.dumps(expected_output, ensure_ascii=False),
                        context=f"{case['cefr_level']} Italian reading text",
                    )
                else:
                    prompt = (
                        f"CEFR level: {case['cefr_level']}\n"
                        f'Reading text (first 200 chars): "{snippet}"\n\n'
                        f"Is this reading: (1) grammatically correct Italian, "
                        f"(2) vocabulary appropriate for {case['cefr_level']}, (3) coherent?"
                    )
                    ok, reason = _judge(prompt)
                if ok:
                    judge_passed += 1
                case_judge.setdefault(case["id"], []).append(ok)
                last_reason[case["id"]] = reason
                logger.info(
                    f"[eval] judge reading {case['id']}: {'PASS' if ok else 'FAIL'} {reason}"
                )

    for case_id, bools in case_judge.items():
        if case_id in item_data:
            item_data[case_id]["judge_pass"] = all(bools)
            item_data[case_id]["judge_reason"] = last_reason.get(case_id, "")

    for case_id, data in item_data.items():
        record_item(
            "planner", {"test": "content_structure", "case_id": case_id, **data}
        )

    content_quality = judge_passed / max(1, judge_total)
    logger.info(f"[eval] Content content_quality={content_quality:.2%}")

    record_eval(
        "planner",
        {
            "output_syntax": round(output_syntax, 4),
            "content_quality": round(content_quality, 4),
            "n": n,
            "test": "content_structure",
        },
    )

    assert output_syntax >= 0.75, (
        f"Lesson content structure pass rate too low: {output_syntax:.2%} (failed: {failed})"
    )
    assert content_quality >= 0.70, (
        f"Lesson content quality too low: {content_quality:.2%}"
    )
