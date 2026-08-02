"""The checked-in curriculum spec must always validate."""

from pathlib import Path

import pytest

from pydantic import ValidationError

from authoring.spec_schemas import DEMAND_RANK, Capstone, Revisit, Scenario
from authoring.validate_spec import load_spec, validate

pytestmark = pytest.mark.unit

SPEC_IT = Path(__file__).resolve().parents[2] / "spec" / "it"


def test_spec_it_validates():
    spec = load_spec(SPEC_IT)
    errors, _warnings = validate(spec)
    assert errors == []
    assert len(spec.grammar_points) >= 351
    assert len(spec.communicative_functions) >= 465
    assert len(spec.scenarios) >= 37
    assert len(spec.can_dos) >= 60
    assert len(spec.vocab) >= 300
    a0 = [v for v in spec.vocab if v.cefr_level == "A0"]
    assert len(a0) >= 140


def test_can_do_inventory_covers_levels_and_skills():
    """Every A0-A2 level keeps can-dos; A1/A2 cover all five CEFR skills."""
    spec = load_spec(SPEC_IT)
    by_level: dict[str, set[str]] = {}
    for cd in spec.can_dos:
        by_level.setdefault(cd.cefr_level, set()).add(cd.skill)
    all_skills = {
        "listening",
        "reading",
        "spoken_interaction",
        "spoken_production",
        "writing",
    }
    assert set(by_level) >= {"A0", "A1", "A2"}
    assert by_level["A1"] == all_skills
    assert by_level["A2"] == all_skills


def test_prerequisites_stay_within_or_below_level():
    """A grammar point may only require points at its own level or lower."""
    order = ["A0", "A1", "A2", "B1", "B2", "C1", "C2"]
    spec = load_spec(SPEC_IT)
    by_id = {g.id: g for g in spec.grammar_points}
    violations = [
        (g.id, p)
        for g in spec.grammar_points
        for p in g.prerequisites
        if order.index(by_id[p].cefr_level) > order.index(g.cefr_level)
    ]
    assert violations == []


def test_legacy_depth_strings_lift_into_lessons():
    """Depths were one-line framings before they were lessons. The old
    form still loads — the spec fill populates the rest — so every
    scenario keeps a lesson per depth with a derivable, stable id."""
    scenario = Scenario(
        id="al-bar",
        cefr_level="A1",
        label="Al bar",
        description="Coffee, standing up",
        depths=["Ordering at the counter", "A table outside", "Small talk"],
    )
    assert [lesson.id for lesson in scenario.depths] == [
        "al-bar.d1",
        "al-bar.d2",
        "al-bar.d3",
    ]
    assert scenario.lesson(1).summary == "Ordering at the counter"
    assert scenario.lesson(1).introduces.grammar == []
    # A depth with no level of its own is the scenario's level.
    assert scenario.level_at(3) == "A1"


def test_a_lesson_declares_its_homes_its_revisits_and_its_capstone():
    """The three blocks are what make coverage checkable: introduced once,
    revisited at a named rung, and proved by a capstone."""
    scenario = Scenario(
        id="al-bar",
        cefr_level="A1",
        label="Al bar",
        description="Coffee, standing up",
        depths=[
            {
                "id": "al-bar.d1",
                "label": "Al banco",
                "goal": "Order at the counter without switching to English.",
                "introduces": {"grammar": ["vorrei"], "vocab": ["caffè"]},
                "capstones": [{"cando": "a0.order_something", "demand": "use"}],
            },
            {
                "id": "al-bar.d2",
                "cefr_level": "A2",
                "revisits": {"grammar": [{"id": "vorrei", "demand": "perform"}]},
                "capstones": [{"cando": "a0.order_something", "demand": "perform"}],
            },
        ],
    )
    assert scenario.lesson(1).introduces.grammar == ["vorrei"]
    assert scenario.lesson(2).revisits.grammar[0].demand == "perform"
    # A scenario's band rises across its depths — this is where A2 lives.
    assert scenario.level_at(1) == "A1"
    assert scenario.level_at(2) == "A2"


def test_the_spirals_rungs_only_go_one_way():
    with pytest.raises(ValidationError):
        Revisit(id="vorrei", demand="master")
    # A capstone is a performance, never a recognition exercise.
    with pytest.raises(ValidationError):
        Capstone(cando="a0.order_something", demand="meet")
    assert DEMAND_RANK["meet"] < DEMAND_RANK["use"] < DEMAND_RANK["perform"]
