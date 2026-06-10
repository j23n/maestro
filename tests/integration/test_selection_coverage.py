"""Unit tests for coverage-driven scenario/CF selection (graduation gates)."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from maestro.lessons import selection
from maestro.lessons.selection import pick_scenario
from maestro.models import LanguageProgress, LearningProfile, ScenarioProgress

pytestmark = pytest.mark.integration


def _scenario(slug, gp_codes=(), cf_codes=(), phase=1):
    return SimpleNamespace(
        slug=slug,
        label=slug,
        description=slug,
        depths=["d1", "d2", "d3"],
        gp_codes=list(gp_codes),
        cf_codes=list(cf_codes),
        phase=phase,
    )


def _profile(
    mastery=None,
    fn_counts=None,
    introduced=None,
    scenario_progress=None,
):
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


@pytest.fixture(autouse=True)
def deterministic(monkeypatch):
    monkeypatch.setattr(selection, "get_available_scenarios", lambda p, s: s)
    monkeypatch.setattr(selection, "get_max_available_depth", lambda *a, **k: 3)
    random.seed(0)


async def test_pick_scenario_prefers_unmastered_gps(db):
    """A scenario whose GPs are already mastered loses to one advancing the gate."""
    mastered = _scenario("mastered", gp_codes=["GP1", "GP2"], cf_codes=["CF1"])
    open_gate = _scenario("open-gate", gp_codes=["GP3", "GP4"], cf_codes=["CF2"])
    # Both visited equally so unvisited/depth bonuses don't differ
    progress = {
        "mastered": ScenarioProgress(depth=1),
        "open-gate": ScenarioProgress(depth=1),
    }
    profile = _profile(
        mastery={"GP1": 0.9, "GP2": 0.95},
        fn_counts={"CF1": 5},
        introduced=["GP1", "GP2", "GP3", "GP4"],
        scenario_progress=progress,
    )
    picked, _ = await pick_scenario(
        profile, "A1", scenarios=[mastered, open_gate], language="it"
    )
    assert picked.slug == "open-gate"


async def test_pick_scenario_prefers_undemonstrated_cfs(db):
    done = _scenario("done", cf_codes=["CF1", "CF2"])
    pending = _scenario("pending", cf_codes=["CF3", "CF4"])
    progress = {
        "done": ScenarioProgress(depth=1),
        "pending": ScenarioProgress(depth=1),
    }
    profile = _profile(
        fn_counts={"CF1": 4, "CF2": 3, "CF3": 1},
        scenario_progress=progress,
    )
    picked, _ = await pick_scenario(
        profile, "A1", scenarios=[done, pending], language="it"
    )
    assert picked.slug == "pending"


async def test_pick_scenario_introduction_pressure_respects_unlocked(db):
    """Unintroduced GPs only add pressure when their prerequisites are met."""
    locked = _scenario("locked", gp_codes=["GP_LOCKED1", "GP_LOCKED2"])
    unlocked = _scenario("unlocked", gp_codes=["GP_NEW1", "GP_NEW2"])
    progress = {
        "locked": ScenarioProgress(depth=1),
        "unlocked": ScenarioProgress(depth=1),
    }
    profile = _profile(scenario_progress=progress)
    picked, _ = await pick_scenario(
        profile,
        "A1",
        scenarios=[locked, unlocked],
        language="it",
        unlocked_codes={"GP_NEW1", "GP_NEW2"},
    )
    assert picked.slug == "unlocked"


async def test_pick_comm_functions_prefers_undemonstrated(db):
    from maestro.lessons.selection import pick_comm_functions
    from maestro.models import CommunicativeFunction

    # CF_A practised most but still short of the demonstration threshold;
    # CF_B/CF_C already demonstrated with low counts.
    for code, _count in (("CF_A", 2), ("CF_B", 3), ("CF_C", 4)):
        await CommunicativeFunction(
            code=code, label=code, category="test", cefr_level="A1", language="it"
        ).insert()
    profile = _profile(fn_counts={"CF_A": 2, "CF_B": 3, "CF_C": 4})

    picked = await pick_comm_functions(profile, "A1", 1, language="it")
    assert picked[0].code == "CF_A"


async def test_pick_grammar_points_new_material_first_for_introduction(db):
    from maestro.lessons.selection import pick_grammar_points
    from maestro.models import GrammarPoint

    for code in ("GP_NEW", "GP_WEAK"):
        await GrammarPoint(
            code=code, label=code, cefr_level="A1", category="test", language="it"
        ).insert()
    profile = _profile(introduced=["GP_WEAK"])
    profile.active_progress.grammar_error_counts = {"GP_WEAK": 5}
    profile.active_progress.grammar_correct_counts = {"GP_WEAK": 1}

    random.seed(0)
    picked = await pick_grammar_points(
        profile, "A1", 1, language="it", archetype="introduction"
    )
    assert picked[0].code == "GP_NEW"

    # Consolidation flips the priority: the weak GP wins over new material
    random.seed(0)
    picked = await pick_grammar_points(
        profile, "A1", 1, language="it", archetype="consolidation"
    )
    assert picked[0].code == "GP_WEAK"


async def test_pick_grammar_points_mastered_sort_last(db):
    from maestro.lessons.selection import pick_grammar_points
    from maestro.models import GrammarPoint

    for code in ("GP_DONE", "GP_TODO"):
        await GrammarPoint(
            code=code, label=code, cefr_level="A1", category="test", language="it"
        ).insert()
    profile = _profile(
        mastery={"GP_DONE": 0.95},
        introduced=["GP_DONE", "GP_TODO"],
    )
    profile.active_progress.grammar_correct_counts = {"GP_DONE": 10, "GP_TODO": 1}

    picked = await pick_grammar_points(profile, "A1", 1, language="it")
    assert picked[0].code == "GP_TODO"
