"""Validate A0 data files: every scenario has lesson content, GP/CF codes match."""

import json

import pytest
import yaml

from maestro.utils import iter_language_dirs

# Discover all languages that have A0 lesson data
_LANG_DIRS = [d for d in iter_language_dirs() if (d / "a0_lessons.yaml").exists()]
_LANG_IDS = [d.name for d in _LANG_DIRS]


@pytest.fixture(params=_LANG_DIRS, ids=_LANG_IDS)
def lang_dir(request):
    return request.param


@pytest.mark.unit
def test_every_a0_scenario_has_lesson_content(lang_dir):
    """Every slug in scenarios_a0.yaml must have an entry in a0_lessons.yaml."""
    with open(lang_dir / "scenarios_a0.yaml") as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(lang_dir / "a0_lessons.yaml") as f:
        lessons = yaml.safe_load(f)

    scenario_slugs = {s["slug"] for s in scenarios}
    lesson_slugs = set(lessons.keys())
    missing = scenario_slugs - lesson_slugs
    assert not missing, (
        f"[{lang_dir.name}] A0 scenarios with no lesson content: {missing}"
    )


@pytest.mark.unit
def test_a0_scenario_gp_codes_exist(lang_dir):
    """All gp_codes referenced by A0 scenarios exist in grammar_points.yaml."""
    gp_file = lang_dir / "grammar_points.yaml"
    if not gp_file.exists():
        pytest.skip(f"[{lang_dir.name}] grammar_points.yaml not found")
    with open(lang_dir / "scenarios_a0.yaml") as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(gp_file) as f:
        gps = yaml.safe_load(f)

    gp_codes = {gp["code"] for gp in gps}
    referenced = set()
    for s in scenarios:
        referenced.update(s.get("gp_codes", []))
    missing = referenced - gp_codes
    assert not missing, (
        f"[{lang_dir.name}] A0 scenario gp_codes not in grammar_points.yaml: {missing}"
    )


@pytest.mark.unit
def test_a0_scenario_cf_codes_exist(lang_dir):
    """All cf_codes referenced by A0 scenarios exist in comm_functions.json."""
    cf_file = lang_dir / "comm_functions.json"
    if not cf_file.exists():
        pytest.skip(f"[{lang_dir.name}] comm_functions.json not found")
    with open(lang_dir / "scenarios_a0.yaml") as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(cf_file) as f:
        cfs = json.load(f)

    cf_codes = {cf["code"] for cf in cfs}
    referenced = set()
    for s in scenarios:
        referenced.update(s.get("cf_codes", []))
    missing = referenced - cf_codes
    assert not missing, (
        f"[{lang_dir.name}] A0 scenario cf_codes not in comm_functions.json: {missing}"
    )


@pytest.mark.unit
def test_a0_scenarios_have_sequential_ordering(lang_dir):
    """All A0 scenarios must have a sequence field with no gaps."""
    with open(lang_dir / "scenarios_a0.yaml") as f:
        scenarios = yaml.safe_load(f)["scenarios"]

    sequences = sorted(s["sequence"] for s in scenarios)
    assert sequences == list(range(1, len(scenarios) + 1)), (
        f"[{lang_dir.name}] A0 scenario sequences should be 1..{len(scenarios)}, got {sequences}"
    )


@pytest.mark.unit
def test_a0_lesson_gp_codes_exist_in_grammar_points(lang_dir):
    """All grammar_point_code values in a0_lessons.yaml must exist in grammar_points.yaml."""
    gp_file = lang_dir / "grammar_points.yaml"
    if not gp_file.exists():
        pytest.skip(f"[{lang_dir.name}] grammar_points.yaml not found")
    with open(lang_dir / "a0_lessons.yaml") as f:
        lessons = yaml.safe_load(f)
    with open(gp_file) as f:
        gps = yaml.safe_load(f)

    valid_gp_codes = {gp["code"] for gp in gps}
    referenced: set[str] = set()
    for lesson_data in lessons.values():
        for act in lesson_data.get("activities", []):
            code = act.get("grammar_point_code")
            if code:
                referenced.add(code)
            for item in act.get("items", []):
                item_code = item.get("grammar_point_code")
                if item_code:
                    referenced.add(item_code)
            for q in act.get("questions", []):
                if isinstance(q, dict):
                    for gp in q.get("grammar_point_codes", []):
                        referenced.add(gp)
            for gp in act.get("grammar_point_codes", []):
                referenced.add(gp)

    missing = referenced - valid_gp_codes
    assert not missing, (
        f"[{lang_dir.name}] a0_lessons.yaml grammar_point_codes not in grammar_points.yaml: {missing}"
    )


@pytest.mark.unit
def test_a0_no_why_important(lang_dir):
    """No activities should have why_important after cleanup."""
    with open(lang_dir / "a0_lessons.yaml") as f:
        lessons = yaml.safe_load(f)

    found = []
    for slug, lesson_data in lessons.items():
        for i, act in enumerate(lesson_data.get("activities", [])):
            if "why_important" in act:
                found.append(f"{slug} activity {i} ({act.get('title', '?')})")

    assert not found, f"[{lang_dir.name}] Activities still have why_important: {found}"


@pytest.mark.unit
def test_a0_speaking_activities_exist(lang_dir):
    """At least half of A0 lessons (excluding the first and ripasso) should have speaking activities."""
    with open(lang_dir / "a0_lessons.yaml") as f:
        lessons = yaml.safe_load(f)

    slugs_with_speaking = []
    for slug, lesson_data in lessons.items():
        types = [a["type"] for a in lesson_data.get("activities", [])]
        if "speaking" in types:
            slugs_with_speaking.append(slug)

    non_intro = [s for s in lessons if not s.endswith(("-ripasso", "-wiederholung"))]
    threshold = len(non_intro) // 2
    assert len(slugs_with_speaking) >= threshold, (
        f"[{lang_dir.name}] Only {len(slugs_with_speaking)} lessons have speaking activities "
        f"(expected at least {threshold}): {slugs_with_speaking}"
    )


@pytest.mark.unit
def test_a0_review_drills_have_per_item_gp_codes(lang_dir):
    """Review drills (last drill in each lesson) must have explicit grammar_point_code on every item."""
    with open(lang_dir / "a0_lessons.yaml") as f:
        lessons = yaml.safe_load(f)

    problems = []
    for slug, lesson_data in lessons.items():
        activities = lesson_data.get("activities", [])
        drills = [
            (i, act) for i, act in enumerate(activities) if act.get("type") == "drill"
        ]
        if len(drills) < 2:
            continue

        last_idx, last_drill = drills[-1]
        items = last_drill.get("items", [])
        has_any_override = any(it.get("grammar_point_code") for it in items)
        if not has_any_override:
            title = last_drill.get("title", "").lower()
            if any(
                kw in title
                for kw in ("review", "ripasso", "everything", "wiederholung", "alles")
            ):
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
        f"[{lang_dir.name}] Review drills missing per-item grammar_point_code:\n"
        + "\n".join(problems)
    )


@pytest.mark.unit
def test_a0_reading_listening_have_structured_questions(lang_dir):
    """Reading/listening activities must use structured question format (text + correct_answer)."""
    with open(lang_dir / "a0_lessons.yaml") as f:
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
                    elif not isinstance(q["correct_answer"], str):
                        problems.append(
                            f"{slug} activity {i} question {j}: correct_answer must be "
                            f"a string, got {type(q['correct_answer']).__name__}: {q['correct_answer']!r} "
                            f"(hint: quote bare true/false/yes/no in YAML)"
                        )
            if "correct_answers" in act:
                problems.append(
                    f"{slug} activity {i} ({act.get('title', '?')}): "
                    f"still has 'correct_answers' key (should be removed)"
                )

    assert not problems, (
        f"[{lang_dir.name}] Structured question format issues:\n" + "\n".join(problems)
    )
