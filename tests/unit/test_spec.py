"""The checked-in curriculum spec must always validate."""

from pathlib import Path

import pytest

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
