"""Validate A0 data files: every scenario has lesson content, GP/CF codes match."""

import json

import pytest
import yaml

from maestro.utils import data_dir

SCENARIOS_FILE = data_dir("it") / "scenarios_a0.yaml"
LESSONS_FILE = data_dir("it") / "a0_lessons.yaml"
GRAMMAR_POINTS_FILE = data_dir("it") / "grammar_points.yaml"
COMM_FUNCTIONS_FILE = data_dir("it") / "comm_functions.json"


@pytest.mark.unit
def test_every_a0_scenario_has_lesson_content():
    """Every slug in scenarios_a0.yaml must have an entry in a0_lessons.yaml."""
    with open(SCENARIOS_FILE) as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(LESSONS_FILE) as f:
        lessons = yaml.safe_load(f)

    scenario_slugs = {s["slug"] for s in scenarios}
    lesson_slugs = set(lessons.keys())
    missing = scenario_slugs - lesson_slugs
    assert not missing, f"A0 scenarios with no lesson content: {missing}"


@pytest.mark.unit
def test_a0_scenario_gp_codes_exist():
    """All gp_codes referenced by A0 scenarios exist in grammar_points.yaml."""
    with open(SCENARIOS_FILE) as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(GRAMMAR_POINTS_FILE) as f:
        gps = yaml.safe_load(f)

    gp_codes = {gp["code"] for gp in gps}
    referenced = set()
    for s in scenarios:
        referenced.update(s.get("gp_codes", []))
    missing = referenced - gp_codes
    assert not missing, f"A0 scenario gp_codes not in grammar_points.yaml: {missing}"


@pytest.mark.unit
def test_a0_scenario_cf_codes_exist():
    """All cf_codes referenced by A0 scenarios exist in comm_functions.json."""
    with open(SCENARIOS_FILE) as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(COMM_FUNCTIONS_FILE) as f:
        cfs = json.load(f)

    cf_codes = {cf["code"] for cf in cfs}
    referenced = set()
    for s in scenarios:
        referenced.update(s.get("cf_codes", []))
    missing = referenced - cf_codes
    assert not missing, f"A0 scenario cf_codes not in comm_functions.json: {missing}"


@pytest.mark.unit
def test_a0_scenarios_have_sequential_ordering():
    """All A0 scenarios must have a sequence field with no gaps."""
    with open(SCENARIOS_FILE) as f:
        scenarios = yaml.safe_load(f)["scenarios"]

    sequences = sorted(s["sequence"] for s in scenarios)
    assert sequences == list(range(1, len(scenarios) + 1)), (
        f"A0 scenario sequences should be 1..{len(scenarios)}, got {sequences}"
    )


@pytest.mark.unit
def test_a0_lesson_gp_codes_exist_in_grammar_points():
    """All grammar_point_code values in a0_lessons.yaml must exist in grammar_points.yaml.

    Checks: activity-level grammar_point_code, per-item grammar_point_code on drills,
    grammar_point_codes on questions/writing/speaking.
    """
    with open(LESSONS_FILE) as f:
        lessons = yaml.safe_load(f)
    with open(GRAMMAR_POINTS_FILE) as f:
        gps = yaml.safe_load(f)

    valid_gp_codes = {gp["code"] for gp in gps}
    referenced: set[str] = set()
    for lesson_data in lessons.values():
        for act in lesson_data.get("activities", []):
            # Activity-level GP code
            code = act.get("grammar_point_code")
            if code:
                referenced.add(code)
            # Per-item GP codes on drill items
            for item in act.get("items", []):
                item_code = item.get("grammar_point_code")
                if item_code:
                    referenced.add(item_code)
            # GP codes on structured questions (reading/listening)
            for q in act.get("questions", []):
                if isinstance(q, dict):
                    for gp in q.get("grammar_point_codes", []):
                        referenced.add(gp)
            # GP codes on writing/speaking activities
            for gp in act.get("grammar_point_codes", []):
                referenced.add(gp)

    missing = referenced - valid_gp_codes
    assert not missing, (
        f"a0_lessons.yaml grammar_point_codes not in grammar_points.yaml: {missing}"
    )


@pytest.mark.unit
def test_a0_no_why_important():
    """No activities should have why_important after cleanup."""
    with open(LESSONS_FILE) as f:
        lessons = yaml.safe_load(f)

    found = []
    for slug, lesson_data in lessons.items():
        for i, act in enumerate(lesson_data.get("activities", [])):
            if "why_important" in act:
                found.append(f"{slug} activity {i} ({act.get('title', '?')})")

    assert not found, f"Activities still have why_important: {found}"


@pytest.mark.unit
def test_a0_speaking_activities_exist():
    """At least half of A0 lessons (excluding the first and ripasso) should have speaking activities."""
    with open(LESSONS_FILE) as f:
        lessons = yaml.safe_load(f)

    slugs_with_speaking = []
    for slug, lesson_data in lessons.items():
        types = [a["type"] for a in lesson_data.get("activities", [])]
        if "speaking" in types:
            slugs_with_speaking.append(slug)

    # Exclude first lesson and ripasso from the count
    non_intro = [s for s in lessons if not s.endswith("-ripasso")]
    threshold = len(non_intro) // 2
    assert len(slugs_with_speaking) >= threshold, (
        f"Only {len(slugs_with_speaking)} lessons have speaking activities "
        f"(expected at least {threshold}): {slugs_with_speaking}"
    )


@pytest.mark.unit
def test_a0_review_drills_have_per_item_gp_codes():
    """Review drills (last drill in each lesson) must have explicit grammar_point_code on every item."""
    with open(LESSONS_FILE) as f:
        lessons = yaml.safe_load(f)

    problems = []
    for slug, lesson_data in lessons.items():
        activities = lesson_data.get("activities", [])
        # Find all drill activities
        drills = [
            (i, act) for i, act in enumerate(activities) if act.get("type") == "drill"
        ]
        if len(drills) < 2:
            # Lesson has 0 or 1 drill — no review drill to check
            continue

        # The last drill is the review drill (may have multiple review drills at end)
        # Check: any drill where at least one item has a different GP than the drill level
        # For simplicity, check the LAST drill in each lesson
        last_idx, last_drill = drills[-1]
        items = last_drill.get("items", [])
        has_any_override = any(it.get("grammar_point_code") for it in items)
        if not has_any_override:
            # If the last drill is truly a review (title contains "review" or "ripasso"
            # or "everything"), it should have per-item GP codes
            title = last_drill.get("title", "").lower()
            if any(kw in title for kw in ("review", "ripasso", "everything")):
                missing_items = [
                    f"item {j}: {it.get('prompt', '')[:40]}"
                    for j, it in enumerate(items)
                    if not it.get("grammar_point_code")
                ]
                if missing_items:
                    problems.append(
                        f"{slug} '{last_drill.get('title')}': {missing_items}"
                    )

    assert not problems, (
        "Review drills missing per-item grammar_point_code:\n" + "\n".join(problems)
    )


@pytest.mark.unit
def test_a0_reading_listening_have_structured_questions():
    """Reading/listening activities must use structured question format (text + correct_answer)."""
    with open(LESSONS_FILE) as f:
        lessons = yaml.safe_load(f)

    problems = []
    for slug, lesson_data in lessons.items():
        for i, act in enumerate(lesson_data.get("activities", [])):
            if act.get("type") not in ("reading", "listening"):
                continue
            questions = act.get("questions", [])
            if not questions:
                continue
            for j, q in enumerate(questions):
                if isinstance(q, str):
                    problems.append(
                        f"{slug} activity {i} ({act.get('title', '?')}) "
                        f"question {j}: still a plain string"
                    )
                elif isinstance(q, dict):
                    if "text" not in q:
                        problems.append(
                            f"{slug} activity {i} question {j}: missing 'text' key"
                        )
                    if "correct_answer" not in q:
                        problems.append(
                            f"{slug} activity {i} question {j}: missing 'correct_answer'"
                        )
            # Should not have old correct_answers key
            if "correct_answers" in act:
                problems.append(
                    f"{slug} activity {i} ({act.get('title', '?')}): "
                    f"still has 'correct_answers' key (should be removed)"
                )

    assert not problems, "Structured question format issues:\n" + "\n".join(problems)
