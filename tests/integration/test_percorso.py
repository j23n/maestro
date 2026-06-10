"""Integration tests for the percorso progression data (routes.profile).

Covers the graduation-gate computation, per-scenario coverage badges, and
the deterministic "recommended next" scenario added for the coverage-driven
curriculum.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from maestro.models import (
    LanguageProgress,
    LearningProfile,
    ScenarioProgress,
)
from maestro.routes.profile import _build_cf_by_level, _build_percorso

pytestmark = pytest.mark.integration


def _gp(code, prerequisites=None):
    return SimpleNamespace(
        code=code,
        label=code,
        cefr_level="A1",
        category="test",
        prerequisites=prerequisites or [],
    )


def _cf(code):
    return SimpleNamespace(code=code, label=code, cefr_level="A1", category="test")


def _scenario(slug, gp_codes, cf_codes, phase=1):
    return SimpleNamespace(
        slug=slug,
        label=slug,
        description=slug,
        cefr_level="A1",
        phase=phase,
        gp_codes=list(gp_codes),
        cf_codes=list(cf_codes),
        depths=["d1", "d2", "d3"],
    )


def _profile(mastery=None, fn_counts=None, introduced=None, scenario_progress=None):
    return LearningProfile(
        target_language="it",
        progress={
            "it": LanguageProgress(
                grammar_mastery_scores=mastery or {},
                functions_counts=fn_counts or {},
                grammar_introduced=introduced or [],
                scenario_progress=scenario_progress or {},
            )
        },
    )


def _grammar_by_level(grammar_points, mastered_codes):
    return {
        "A1": [
            {"point": gp, "mastered": gp.code in mastered_codes}
            for gp in grammar_points
        ]
    }


@pytest.fixture
def curriculum(db):
    gps = [_gp("gp_a"), _gp("gp_b"), _gp("gp_c"), _gp("gp_d", prerequisites=["gp_a"])]
    cfs = [_cf("cf_1"), _cf("cf_2"), _cf("cf_3"), _cf("cf_4")]
    scenarios = {
        "A1": [
            _scenario("uno", ["gp_a", "gp_b"], ["cf_1", "cf_2"]),
            _scenario("due", ["gp_c", "gp_d"], ["cf_3", "cf_4"]),
            _scenario("tre", ["gp_a"], ["cf_1"], phase=2),
        ]
    }
    return gps, cfs, scenarios


def _build(profile, gps, cfs, scenarios, mastered=()):
    cf_items = _build_cf_by_level(cfs, profile)["A1"]
    return _build_percorso(
        profile,
        "A1",
        gps,
        _grammar_by_level(gps, set(mastered)),
        scenarios,
        cf_items,
    )


def test_gates_reflect_mastery_and_demonstration(curriculum):
    gps, cfs, scenarios = curriculum
    profile = _profile(
        mastery={"gp_a": 0.9},
        fn_counts={"cf_1": 3, "cf_2": 5, "cf_3": 2},
        introduced=["gp_a"],
    )
    percorso = _build(profile, gps, cfs, scenarios, mastered=["gp_a"])

    gates = percorso["gates"]
    assert gates["next_level"] == "A2"
    assert gates["gp_total"] == 4
    assert gates["gp_done"] == 1
    assert gates["gp_target"] == 4  # ceil(0.9 * 4)
    assert gates["cf_total"] == 4
    assert gates["cf_done"] == 2  # cf_1 and cf_2 at >= 3 uses
    assert gates["cf_pct"] == 50


def test_scenario_coverage_badges(curriculum):
    gps, cfs, scenarios = curriculum
    profile = _profile(
        mastery={"gp_a": 0.9},
        fn_counts={"cf_1": 3},
        introduced=["gp_a"],
    )
    percorso = _build(profile, gps, cfs, scenarios, mastered=["gp_a"])

    phase1 = percorso["phases"][0]
    by_slug = {item["scenario"].slug: item for item in phase1["scenarios"]}
    # "uno": gp_a mastered, gp_b not; cf_1 demonstrated, cf_2 not
    assert by_slug["uno"]["advances_gp"] == 1
    assert by_slug["uno"]["advances_cf"] == 1
    # "due": neither GP mastered, neither CF demonstrated
    assert by_slug["due"]["advances_gp"] == 2
    assert by_slug["due"]["advances_cf"] == 2


def test_recommended_prefers_higher_coverage_in_current_phase(curriculum):
    gps, cfs, scenarios = curriculum
    profile = _profile(
        mastery={"gp_a": 0.9},
        fn_counts={"cf_1": 3},
        introduced=["gp_a"],
    )
    percorso = _build(profile, gps, cfs, scenarios, mastered=["gp_a"])

    # "due" advances more gate gaps than "uno"; "tre" is phase 2 (locked)
    assert percorso["recommended_slug"] == "due"


def test_recommended_ignores_locked_phase_scenarios(curriculum):
    gps, cfs, scenarios = curriculum
    # Master everything in phase 1 so phase-2 "tre" would score highest
    # if it were eligible — it must not be recommended while locked.
    profile = _profile(
        mastery={"gp_a": 0.9, "gp_b": 0.9, "gp_c": 0.9, "gp_d": 0.9},
        fn_counts={"cf_1": 3, "cf_2": 3, "cf_3": 3, "cf_4": 3},
        introduced=["gp_a", "gp_b", "gp_c", "gp_d"],
    )
    percorso = _build(
        profile, gps, cfs, scenarios, mastered=["gp_a", "gp_b", "gp_c", "gp_d"]
    )
    recommended = percorso["recommended_slug"]
    assert recommended in ("uno", "due")  # phase 1 only


def test_fully_covered_scenario_has_no_advance_badge(curriculum):
    gps, cfs, scenarios = curriculum
    profile = _profile(
        mastery={"gp_a": 0.9, "gp_b": 0.9},
        fn_counts={"cf_1": 3, "cf_2": 3},
        introduced=["gp_a", "gp_b"],
        scenario_progress={"uno": ScenarioProgress(depth=3, lesson_count=4)},
    )
    percorso = _build(profile, gps, cfs, scenarios, mastered=["gp_a", "gp_b"])

    phase1 = percorso["phases"][0]
    uno = next(i for i in phase1["scenarios"] if i["scenario"].slug == "uno")
    assert uno["advances_gp"] == 0
    assert uno["advances_cf"] == 0
    # And the recommendation moves to the scenario that still advances gates
    assert percorso["recommended_slug"] == "due"


def test_profile_page_renders_gates_and_start_buttons(
    test_app, student, db, monkeypatch
):
    """End-to-end: the profile page shows the gates panel and start forms."""
    import asyncio

    from maestro.learning import grammar_cache
    from maestro.models import CurriculumScenario, GrammarPoint, CommunicativeFunction

    async def _seed():
        for code in ("gp_a", "gp_b"):
            await GrammarPoint(
                code=code, label=code, cefr_level="A1", category="t", language="it"
            ).insert()
        for code in ("cf_1", "cf_2"):
            await CommunicativeFunction(
                code=code, label=code, category="t", cefr_level="A1", language="it"
            ).insert()
        await CurriculumScenario(
            slug="al-bar-test",
            label="Al bar test",
            description="d",
            cefr_level="A1",
            phase=1,
            gp_codes=["gp_a", "gp_b"],
            cf_codes=["cf_1", "cf_2"],
            depths=["d1", "d2", "d3"],
            language="it",
        ).insert()
        await LearningProfile(
            student_id=student.id,
            target_language="it",
            progress={"it": LanguageProgress(cefr_level_override="A1")},
        ).insert()

    asyncio.get_event_loop().run_until_complete(_seed())
    grammar_cache.invalidate()

    response = test_app.get("/profile")
    assert response.status_code == 200
    html = response.text
    assert "gates-panel" in html
    assert "btn-scenario-start" in html
    assert 'name="scenario_slug" value="al-bar-test"' in html
