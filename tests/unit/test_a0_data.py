"""Validate A0 data files: every scenario has lesson content, GP/CF codes match."""
import json

import pytest
import yaml

from maestro.utils import DATA_DIR

SCENARIOS_FILE = DATA_DIR / "scenarios_a0.yaml"
LESSONS_FILE = DATA_DIR / "a0_lessons.yaml"
GRAMMAR_POINTS_FILE = DATA_DIR / "grammar_points.json"
COMM_FUNCTIONS_FILE = DATA_DIR / "comm_functions.json"


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
    """All gp_codes referenced by A0 scenarios exist in grammar_points.json."""
    with open(SCENARIOS_FILE) as f:
        scenarios = yaml.safe_load(f)["scenarios"]
    with open(GRAMMAR_POINTS_FILE) as f:
        gps = json.load(f)

    gp_codes = {gp["code"] for gp in gps}
    referenced = set()
    for s in scenarios:
        referenced.update(s.get("gp_codes", []))
    missing = referenced - gp_codes
    assert not missing, f"A0 scenario gp_codes not in grammar_points.json: {missing}"


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
