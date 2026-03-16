"""Curriculum engine: phase gating, GP unlocking, and lesson archetypes.

All functions are pure (no DB calls) for easy testing.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

from maestro.models import CurriculumScenario, LearningProfile, ScenarioProgress

logger = logging.getLogger(__name__)


class LessonArchetype(str, Enum):
    INTRODUCTION = "introduction"
    CONSOLIDATION = "consolidation"
    APPLICATION = "application"


# ---------------------------------------------------------------------------
# Phase gating
# ---------------------------------------------------------------------------

# How many scenarios at depth >= 1 to unlock the next phase
PHASE_GATE_THRESHOLD = 5


def get_current_phase(
    profile: Optional[LearningProfile],
    scenarios: list[CurriculumScenario],
) -> int:
    """Return the highest unlocked phase (1, 2, or 3) for the student.

    Phase N+1 unlocks when >= PHASE_GATE_THRESHOLD scenarios in phase N
    have been completed at depth >= 1.
    """
    if profile is None:
        return 1
    progress = profile.scenario_progress or {}
    for phase in (1, 2):
        phase_scenarios = [s for s in scenarios if (s.phase or 1) == phase]
        completed = sum(
            1
            for s in phase_scenarios
            if progress.get(s.slug, ScenarioProgress()).depth >= 1
        )
        if completed < PHASE_GATE_THRESHOLD:
            return phase
    return 3


def get_available_scenarios(
    profile: Optional[LearningProfile],
    scenarios: list[CurriculumScenario],
) -> list[CurriculumScenario]:
    """Return scenarios in unlocked phases only."""
    max_phase = get_current_phase(profile, scenarios)
    return [s for s in scenarios if (s.phase or 1) <= max_phase]


# ---------------------------------------------------------------------------
# Depth gating within a phase
# ---------------------------------------------------------------------------

# Must complete depth 1 of this many scenarios before depth 2+ unlocks
_BREADTH_BEFORE_DEPTH = 3


def get_max_available_depth(
    profile: Optional[LearningProfile],
    scenario: CurriculumScenario,
    scenarios: list[CurriculumScenario],
) -> int:
    """Determine max depth available for a scenario.

    Students must complete depth 1 of at least _BREADTH_BEFORE_DEPTH
    scenarios in the same phase before depth 2+ becomes available
    for any scenario in that phase.
    """
    if profile is None:
        return 1
    progress = profile.scenario_progress or {}
    phase = scenario.phase or 1
    phase_scenarios = [s for s in scenarios if (s.phase or 1) == phase]
    depth1_completed = sum(
        1
        for s in phase_scenarios
        if progress.get(s.slug, ScenarioProgress()).depth >= 1
    )
    if depth1_completed < _BREADTH_BEFORE_DEPTH:
        return 1
    return len(scenario.depths)


# ---------------------------------------------------------------------------
# GP unlocking
# ---------------------------------------------------------------------------


def get_unlocked_gps(
    profile: Optional[LearningProfile],
    all_gp_codes: set[str],
    prerequisites: dict[str, list[str]],
) -> set[str]:
    """Return GP codes that are unlocked (all prerequisites satisfied).

    A GP is unlocked if ALL its prerequisites have been introduced
    (i.e., appear in profile.grammar_introduced).
    GPs with no prerequisites are always unlocked.

    Args:
        prerequisites: mapping of GP code → list of prerequisite GP codes,
            built from GrammarPoint.prerequisites fields.
    """
    introduced = set(profile.grammar_introduced) if profile else set()

    unlocked = set()
    for code in all_gp_codes:
        code_prereqs = prerequisites.get(code, [])
        if all(p in introduced for p in code_prereqs):
            unlocked.add(code)
    return unlocked


# ---------------------------------------------------------------------------
# Archetype selection
# ---------------------------------------------------------------------------


def pick_archetype(
    profile: Optional[LearningProfile],
    unlocked_gps: set[str],
    scenario_gp_codes: list[str],
    focus_weak: bool = False,
) -> LessonArchetype:
    """Choose lesson archetype based on student state.

    - focus_weak -> always CONSOLIDATION
    - Has newly unlocked, never-introduced GPs among scenario's GPs -> INTRODUCTION
    - >= 70% scenario GPs mastered -> APPLICATION
    - Otherwise -> CONSOLIDATION
    """
    if focus_weak:
        return LessonArchetype.CONSOLIDATION

    if profile is None:
        return LessonArchetype.INTRODUCTION

    introduced = set(profile.grammar_introduced)
    recent = profile.grammar_recent_outcomes or {}

    # Check if any scenario GPs are unlocked but never introduced
    new_gps = [
        c for c in scenario_gp_codes if c in unlocked_gps and c not in introduced
    ]
    if new_gps:
        return LessonArchetype.INTRODUCTION

    # Check mastery of scenario GPs
    def _is_mastered(code: str) -> bool:
        outcomes = recent.get(code, [])
        return len(outcomes) >= 5 and sum(outcomes) / len(outcomes) >= 0.8

    scenario_codes = [c for c in scenario_gp_codes if c]
    if not scenario_codes:
        return LessonArchetype.CONSOLIDATION

    mastered_count = sum(1 for c in scenario_codes if _is_mastered(c))
    if mastered_count >= len(scenario_codes) * 0.7:
        return LessonArchetype.APPLICATION

    return LessonArchetype.CONSOLIDATION
