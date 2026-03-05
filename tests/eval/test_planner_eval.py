"""LLM eval tests for lesson topic and content generation."""
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import anthropic
import pytest

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_DATA_DIR = Path(__file__).parent.parent.parent / "src" / "maestro" / "data"


@pytest.mark.llm_eval
async def test_topic_generation(db, record_eval):
    """Validate JSON schema and structural properties of generate_topic output."""
    from maestro.lezione.planner import generate_topic
    from maestro.models import LessonTopic

    cases = json.loads((FIXTURES_DIR / "planner_topic_cases.json").read_text())
    cfs_raw = json.loads((_DATA_DIR / "comm_functions.json").read_text())
    available_cfs = [SimpleNamespace(**cf) for cf in cfs_raw]

    client = anthropic.AsyncAnthropic()

    passed_count = 0
    results = []

    for case in cases:
        profile = SimpleNamespace(
            cefr_estimate=case["cefr"],
            student_interests=case["interests"],
            grammar_error_counts={},
            grammar_correct_counts={},
            functions_counts={},
            description="",
        )
        past_topics = [LessonTopic(**t) for t in case["past_topics"]]

        topic = await generate_topic(
            profile=profile,
            past_topics=past_topics,
            available_cfs=available_cfs,
            hint=case["hint"],
            client=client,
        )

        failures = []

        if not topic.title or not topic.title.strip():
            failures.append("title is empty")
        if not isinstance(topic.cf_codes, list):
            failures.append("cf_codes is not a list")
        if topic.depth not in (1, 2, 3):
            failures.append(f"depth {topic.depth} not in 1-3")
        if case["hint"] and case["hint"].lower() not in (topic.title + " " + topic.description).lower():
            # Soft check: hint topic should be reflected in title or description
            logger.warning(f"[eval] {case['id']}: hint {case['hint']!r} not obviously reflected in topic {topic.title!r}")
        if past_topics and topic.title == past_topics[0].title:
            failures.append(f"title repeats past topic: {topic.title!r}")

        passed = not failures
        if passed:
            passed_count += 1

        results.append({"id": case["id"], "title": topic.title, "pass": passed, "failures": failures})
        logger.info(
            f"[eval] {case['id']}: {'PASS' if passed else 'FAIL'} title={topic.title!r} "
            f"depth={topic.depth} cf_codes={topic.cf_codes} {failures}"
        )

    n = len(cases)
    pass_rate = passed_count / max(1, n)
    failed = [r for r in results if not r["pass"]]
    logger.info(f"[eval] Topic gen: pass_rate={pass_rate:.2%}, failed={[r['id'] for r in failed]}")
    record_eval("planner", {
        "pass_rate": round(pass_rate, 4),
        "n": n,
        "test": "topic",
    })

    assert pass_rate >= 0.75, f"Topic generation pass rate too low: {pass_rate:.2%} (failed: {failed})"


@pytest.mark.llm_eval
async def test_lesson_content_structure(db, record_eval):
    """Validate structural properties of _generate_lesson_content output."""
    from maestro.lezione.planner import _generate_lesson_content

    cases = json.loads((FIXTURES_DIR / "planner_content_cases.json").read_text())

    client = anthropic.AsyncAnthropic()

    passed_count = 0
    results = []

    for case in cases:
        grammar_gps = [SimpleNamespace(**gp) for gp in case["grammar_gps"]]
        speaking_cfs = [SimpleNamespace(**cf) for cf in case["speaking_cfs"]]

        content = await _generate_lesson_content(
            cefr_level=case["cefr_level"],
            topic=case["topic"],
            profile=None,
            grammar_gps=grammar_gps,
            drill_specs=case["drill_specs"],
            reading_count=case["reading_count"],
            include_writing=case["include_writing"],
            client=client,
            speaking_cfs=speaking_cfs,
        )

        failures = []

        if not content:
            failures.append("empty content returned")
            results.append({"id": case["id"], "pass": False, "failures": failures})
            logger.info(f"[eval] {case['id']}: FAIL (empty content)")
            continue

        # Check drills
        drills = content.get("drills", [])
        if len(drills) < case.get("expect_drills", 0):
            failures.append(f"expected {case['expect_drills']} drills, got {len(drills)}")
        for spec, drill in zip(case["drill_specs"], drills):
            if spec["exercise_type"] in ("fill_blank", "error_correction"):
                items = drill.get("items", []) if isinstance(drill, dict) else []
                expected_items = case.get(f"expect_items_per_{spec['exercise_type']}", 10)
                if len(items) < expected_items:
                    failures.append(
                        f"drill {spec['grammar_point_code']}: expected {expected_items} items, got {len(items)}"
                    )

        # Check readings
        readings = content.get("readings", [])
        if len(readings) < case.get("expect_readings", 0):
            failures.append(f"expected {case['expect_readings']} readings, got {len(readings)}")
        for i, reading in enumerate(readings):
            if isinstance(reading, dict):
                q_count = len(reading.get("questions", []))
                if q_count < 5:
                    failures.append(f"reading {i}: expected >=5 questions, got {q_count}")

        # Check writing
        if case.get("expect_writing") and not content.get("writing"):
            failures.append("expected writing activity but none returned")
        if not case.get("expect_writing") and content.get("writing"):
            failures.append("unexpected writing activity returned")

        # Check speakings
        speakings = content.get("speakings", [])
        if len(speakings) < case.get("expect_speakings", 0):
            failures.append(f"expected {case.get('expect_speakings', 0)} speakings, got {len(speakings)}")

        passed = not failures
        if passed:
            passed_count += 1

        results.append({"id": case["id"], "pass": passed, "failures": failures})
        logger.info(
            f"[eval] {case['id']}: {'PASS' if passed else 'FAIL'} "
            f"keys={list(content.keys())} {failures}"
        )

    n = len(cases)
    pass_rate = passed_count / max(1, n)
    failed = [r for r in results if not r["pass"]]
    logger.info(f"[eval] Content structure: pass_rate={pass_rate:.2%}, failed={[r['id'] for r in failed]}")
    record_eval("planner", {
        "pass_rate": round(pass_rate, 4),
        "n": n,
        "test": "content_structure",
    })

    assert pass_rate >= 0.75, f"Lesson content structure pass rate too low: {pass_rate:.2%} (failed: {failed})"
