"""Unit tests for the curriculum engine (phase gating, GP unlocking, archetypes)."""

from types import SimpleNamespace

from maestro.lessons.curriculum import (
    LessonArchetype,
    PHASE_GATE_THRESHOLD,
    detect_prerequisite_cycles,
    get_available_scenarios,
    get_current_phase,
    get_max_available_depth,
    get_unlocked_gps,
    pick_archetype,
)
from maestro.models import ScenarioProgress


def _scenario(slug, phase=1, depths=None):
    return SimpleNamespace(
        slug=slug,
        phase=phase,
        gp_codes=[],
        depths=depths or ["d1", "d2", "d3"],
    )


def _profile(
    scenario_progress=None, grammar_introduced=None, grammar_recent_outcomes=None
):
    progress = SimpleNamespace(
        scenario_progress=scenario_progress or {},
        grammar_introduced=grammar_introduced or [],
        grammar_recent_outcomes=grammar_recent_outcomes or {},
    )
    return SimpleNamespace(
        active_progress=progress,
        target_language="it",
    )


# ---------------------------------------------------------------------------
# Phase gating
# ---------------------------------------------------------------------------


class TestGetCurrentPhase:
    def test_new_student_returns_phase_1(self):
        scenarios = [_scenario(f"s{i}", phase=1) for i in range(8)]
        assert get_current_phase(None, scenarios) == 1

    def test_empty_progress_returns_phase_1(self):
        scenarios = [_scenario(f"s{i}", phase=1) for i in range(8)]
        profile = _profile()
        assert get_current_phase(profile, scenarios) == 1

    def test_phase_1_incomplete_stays_1(self):
        scenarios = [_scenario(f"s{i}", phase=1) for i in range(8)]
        progress = {f"s{i}": ScenarioProgress(depth=1) for i in range(3)}
        profile = _profile(scenario_progress=progress)
        assert get_current_phase(profile, scenarios) == 1

    def test_phase_1_complete_unlocks_2(self):
        scenarios = [_scenario(f"p1-{i}", phase=1) for i in range(8)] + [
            _scenario(f"p2-{i}", phase=2) for i in range(8)
        ]
        progress = {
            f"p1-{i}": ScenarioProgress(depth=1) for i in range(PHASE_GATE_THRESHOLD)
        }
        profile = _profile(scenario_progress=progress)
        assert get_current_phase(profile, scenarios) == 2

    def test_phase_2_complete_unlocks_3(self):
        scenarios = (
            [_scenario(f"p1-{i}", phase=1) for i in range(8)]
            + [_scenario(f"p2-{i}", phase=2) for i in range(8)]
            + [_scenario(f"p3-{i}", phase=3) for i in range(8)]
        )
        progress = {}
        for i in range(PHASE_GATE_THRESHOLD):
            progress[f"p1-{i}"] = ScenarioProgress(depth=1)
            progress[f"p2-{i}"] = ScenarioProgress(depth=1)
        profile = _profile(scenario_progress=progress)
        assert get_current_phase(profile, scenarios) == 3


class TestGetAvailableScenarios:
    def test_new_student_only_sees_phase_1(self):
        scenarios = (
            [_scenario("p1", phase=1)]
            + [_scenario("p2", phase=2)]
            + [_scenario("p3", phase=3)]
        )
        result = get_available_scenarios(None, scenarios)
        assert len(result) == 1
        assert result[0].slug == "p1"

    def test_phase_2_unlocked_sees_1_and_2(self):
        scenarios = (
            [_scenario(f"p1-{i}", phase=1) for i in range(8)]
            + [_scenario("p2-0", phase=2)]
            + [_scenario("p3-0", phase=3)]
        )
        progress = {
            f"p1-{i}": ScenarioProgress(depth=1) for i in range(PHASE_GATE_THRESHOLD)
        }
        profile = _profile(scenario_progress=progress)
        result = get_available_scenarios(profile, scenarios)
        slugs = {s.slug for s in result}
        assert "p2-0" in slugs
        assert "p3-0" not in slugs


# ---------------------------------------------------------------------------
# Depth gating
# ---------------------------------------------------------------------------


class TestGetMaxAvailableDepth:
    def test_few_scenarios_completed_limits_to_1(self):
        scenarios = [_scenario(f"s{i}", phase=1) for i in range(8)]
        progress = {"s0": ScenarioProgress(depth=1)}
        profile = _profile(scenario_progress=progress)
        assert get_max_available_depth(profile, scenarios[1], scenarios) == 1

    def test_enough_scenarios_completed_unlocks_all_depths(self):
        scenarios = [_scenario(f"s{i}", phase=1) for i in range(8)]
        progress = {f"s{i}": ScenarioProgress(depth=1) for i in range(3)}
        profile = _profile(scenario_progress=progress)
        assert get_max_available_depth(profile, scenarios[4], scenarios) == 3

    def test_new_student_limited_to_depth_1(self):
        scenarios = [_scenario("s0", phase=1)]
        assert get_max_available_depth(None, scenarios[0], scenarios) == 1


# ---------------------------------------------------------------------------
# GP unlocking
# ---------------------------------------------------------------------------


class TestGetUnlockedGps:
    def test_no_prerequisites_all_unlocked(self):
        result = get_unlocked_gps(None, {"gp1", "gp2", "gp3"}, {})
        assert result == {"gp1", "gp2", "gp3"}

    def test_unmet_prerequisites_filtered(self):
        prereqs = {"gp2": ["gp1"], "gp3": ["gp1", "gp2"]}
        profile = _profile(grammar_introduced=[])
        result = get_unlocked_gps(profile, {"gp1", "gp2", "gp3"}, prereqs)
        # gp1 has no prereqs → unlocked; gp2 needs gp1 → locked; gp3 needs both → locked
        assert result == {"gp1"}

    def test_met_prerequisites_unlocked(self):
        prereqs = {"gp2": ["gp1"], "gp3": ["gp1", "gp2"]}
        profile = _profile(grammar_introduced=["gp1", "gp2"])
        result = get_unlocked_gps(profile, {"gp1", "gp2", "gp3"}, prereqs)
        assert result == {"gp1", "gp2", "gp3"}

    def test_partial_prerequisites_partially_unlocked(self):
        prereqs = {"gp2": ["gp1"], "gp3": ["gp1", "gp2"]}
        profile = _profile(grammar_introduced=["gp1"])
        result = get_unlocked_gps(profile, {"gp1", "gp2", "gp3"}, prereqs)
        # gp1 unlocked (no prereqs), gp2 unlocked (gp1 introduced), gp3 locked (needs gp2)
        assert result == {"gp1", "gp2"}

    def test_new_student_no_profile_only_no_prereqs(self):
        prereqs = {"gp2": ["gp1"]}
        result = get_unlocked_gps(None, {"gp1", "gp2"}, prereqs)
        assert result == {"gp1"}


# ---------------------------------------------------------------------------
# Archetype selection
# ---------------------------------------------------------------------------


class TestPickArchetype:
    def test_focus_weak_always_consolidation(self):
        profile = _profile(grammar_introduced=["gp1"])
        result = pick_archetype(profile, {"gp1"}, ["gp1"], focus_weak=True)
        assert result == LessonArchetype.CONSOLIDATION

    def test_new_student_returns_introduction(self):
        result = pick_archetype(None, {"gp1"}, ["gp1"])
        assert result == LessonArchetype.INTRODUCTION

    def test_unlocked_but_not_introduced_returns_introduction(self):
        profile = _profile(grammar_introduced=[])
        result = pick_archetype(profile, {"gp1", "gp2"}, ["gp1", "gp2"])
        assert result == LessonArchetype.INTRODUCTION

    def test_all_mastered_returns_application(self):
        outcomes = {
            "gp1": [True] * 10,
            "gp2": [True] * 10,
            "gp3": [True] * 10,
        }
        profile = _profile(
            grammar_introduced=["gp1", "gp2", "gp3"],
            grammar_recent_outcomes=outcomes,
        )
        result = pick_archetype(profile, {"gp1", "gp2", "gp3"}, ["gp1", "gp2", "gp3"])
        assert result == LessonArchetype.APPLICATION

    def test_introduced_but_not_mastered_returns_consolidation(self):
        outcomes = {
            "gp1": [True, False, True],  # not enough outcomes for mastery
            "gp2": [True, False],
        }
        profile = _profile(
            grammar_introduced=["gp1", "gp2"],
            grammar_recent_outcomes=outcomes,
        )
        # All scenario GPs are introduced (none are new), none are mastered
        result = pick_archetype(profile, {"gp1", "gp2"}, ["gp1", "gp2"])
        assert result == LessonArchetype.CONSOLIDATION

    def test_mostly_mastered_returns_application(self):
        """70% mastered threshold."""
        outcomes = {
            "gp1": [True] * 10,
            "gp2": [True] * 10,
            "gp3": [True, False, True],  # not mastered
        }
        profile = _profile(
            grammar_introduced=["gp1", "gp2", "gp3"],
            grammar_recent_outcomes=outcomes,
        )
        # 2/3 = 66.7% < 70% → consolidation
        result = pick_archetype(profile, {"gp1", "gp2", "gp3"}, ["gp1", "gp2", "gp3"])
        assert result == LessonArchetype.CONSOLIDATION

    def test_some_new_gps_returns_introduction(self):
        """Even if some are mastered, having new unlocked GPs triggers introduction."""
        outcomes = {"gp1": [True] * 10}
        profile = _profile(
            grammar_introduced=["gp1"],  # gp2 not introduced
            grammar_recent_outcomes=outcomes,
        )
        result = pick_archetype(profile, {"gp1", "gp2"}, ["gp1", "gp2"])
        assert result == LessonArchetype.INTRODUCTION


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------


class TestDetectPrerequisiteCycles:
    def test_no_prerequisites_no_cycles(self):
        assert detect_prerequisite_cycles({}) == []

    def test_acyclic_dag_no_cycles(self):
        prereqs = {"gp2": ["gp1"], "gp3": ["gp1", "gp2"]}
        assert detect_prerequisite_cycles(prereqs) == []

    def test_simple_cycle_detected(self):
        prereqs = {"gp1": ["gp2"], "gp2": ["gp1"]}
        cycles = detect_prerequisite_cycles(prereqs)
        assert len(cycles) > 0
        # At least one cycle should contain both nodes
        cycle_nodes = {node for cycle in cycles for node in cycle}
        assert "gp1" in cycle_nodes
        assert "gp2" in cycle_nodes

    def test_longer_cycle_detected(self):
        prereqs = {"gp1": ["gp3"], "gp2": ["gp1"], "gp3": ["gp2"]}
        cycles = detect_prerequisite_cycles(prereqs)
        assert len(cycles) > 0
        cycle_nodes = {node for cycle in cycles for node in cycle}
        assert {"gp1", "gp2", "gp3"} <= cycle_nodes

    def test_mixed_dag_and_cycle(self):
        """Cycle in one part of the graph, clean DAG in another."""
        prereqs = {
            "gp2": ["gp1"],  # clean edge
            "gp3": ["gp4"],  # cycle
            "gp4": ["gp3"],  # cycle
        }
        cycles = detect_prerequisite_cycles(prereqs)
        assert len(cycles) > 0
        cycle_nodes = {node for cycle in cycles for node in cycle}
        assert "gp3" in cycle_nodes
        assert "gp4" in cycle_nodes
        # gp1 and gp2 should NOT be in any cycle
        assert "gp1" not in cycle_nodes
        assert "gp2" not in cycle_nodes
