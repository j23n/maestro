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
    """All grammar_point_code values in a0_lessons.yaml must exist in grammar_points.yaml."""
    with open(LESSONS_FILE) as f:
        lessons = yaml.safe_load(f)
    with open(GRAMMAR_POINTS_FILE) as f:
        gps = yaml.safe_load(f)

    json_gp_codes = {gp["code"] for gp in gps}
    yaml_gp_codes: set[str] = set()
    for lesson_data in lessons.values():
        for act in lesson_data.get("activities", []):
            code = act.get("grammar_point_code")
            if code:
                yaml_gp_codes.add(code)

    missing = yaml_gp_codes - json_gp_codes
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
    """Lessons a0-04, a0-05, a0-07 should have speaking activities."""
    with open(LESSONS_FILE) as f:
        lessons = yaml.safe_load(f)

    expected = ["a0-04-si-e-no", "a0-05-per-favore", "a0-07-io-sono"]
    for slug in expected:
        lesson_data = lessons.get(slug)
        assert lesson_data, f"Missing lesson {slug}"
        types = [a["type"] for a in lesson_data.get("activities", [])]
        assert "speaking" in types, (
            f"{slug} should have a speaking activity, has: {types}"
        )
