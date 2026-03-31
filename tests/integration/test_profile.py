"""Integration tests for learning/profile.py using mongomock DB."""

import pytest
from unittest.mock import patch, AsyncMock

from beanie import PydanticObjectId
from maestro.models import (
    GrammarPoint,
    CommunicativeFunction,
    LanguageProgress,
    LearningProfile,
    LearningEvent,
)


_FAKE_STUDENT_ID = PydanticObjectId()


async def _seed_grammar_points(db, codes_by_level: dict):
    """Insert GrammarPoints. codes_by_level: {"A1": ["GP_001", "GP_002"], ...}"""
    for level, codes in codes_by_level.items():
        for code in codes:
            gp = GrammarPoint(
                code=code,
                label=code,
                cefr_level=level,
                category="test",
                description=code,
            )
            await gp.insert()


async def _seed_comm_functions(db, codes_by_level: dict):
    for level, codes in codes_by_level.items():
        for code in codes:
            cf = CommunicativeFunction(
                code=code,
                label=code,
                category="test",
                cefr_level=level,
            )
            await cf.insert()


@pytest.mark.integration
async def test_update_profile_increments_correct_counts(db):
    from maestro.learning.profile import update_profile

    event = LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        grammar_correct=["GP_001"],
        grammar_errors=[],
        functions_performed=[],
    )
    await event.insert()

    with patch(
        "maestro.learning.profile._generate_description",
        new_callable=AsyncMock,
        return_value="desc",
    ):
        await update_profile(event)

    profile = await LearningProfile.find_one()
    assert profile is not None
    assert profile.active_progress.grammar_correct_counts.get("GP_001", 0) == 1


@pytest.mark.integration
async def test_update_profile_increments_error_counts(db):
    from maestro.learning.profile import update_profile

    event = LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        grammar_correct=[],
        grammar_errors=["GP_002"],
        functions_performed=[],
    )
    await event.insert()

    with patch(
        "maestro.learning.profile._generate_description",
        new_callable=AsyncMock,
        return_value="desc",
    ):
        await update_profile(event)

    profile = await LearningProfile.find_one()
    assert profile.active_progress.grammar_error_counts.get("GP_002", 0) == 1


@pytest.mark.integration
async def test_update_profile_recent_outcomes_capped_at_10(db):
    from maestro.learning.profile import update_profile

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={
            "it": LanguageProgress(grammar_recent_outcomes={"GP_001": [True] * 10})
        },
    )
    await profile.insert()

    # Add one more True outcome
    event = LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        grammar_correct=["GP_001"],
        grammar_errors=[],
        functions_performed=[],
    )
    await event.insert()

    with patch(
        "maestro.learning.profile._generate_description",
        new_callable=AsyncMock,
        return_value="desc",
    ):
        await update_profile(event)

    profile = await LearningProfile.find_one()
    assert len(profile.active_progress.grammar_recent_outcomes["GP_001"]) == 10


@pytest.mark.integration
async def test_update_profile_creates_profile_if_none(db):
    from maestro.learning.profile import update_profile

    event = LearningEvent(
        student_id=_FAKE_STUDENT_ID,
        grammar_correct=["GP_001"],
        grammar_errors=[],
        functions_performed=[],
    )
    await event.insert()

    with patch(
        "maestro.learning.profile._generate_description",
        new_callable=AsyncMock,
        return_value="desc",
    ):
        await update_profile(event)

    profile = await LearningProfile.find_one()
    assert profile is not None


@pytest.mark.integration
async def test_compute_cefr_no_mastered_stays_a1(db):
    """When all levels have GPs and none are mastered, result stays A1."""
    from maestro.learning.profile import _compute_cefr

    # Seed GPs at ALL levels so vacuous-OK doesn't advance past A1
    await _seed_grammar_points(
        db,
        {
            "A1": ["GP_001", "GP_002"],
            "A2": ["GP_003"],
            "B1": ["GP_004"],
            "B2": ["GP_005"],
        },
    )
    await _seed_comm_functions(
        db,
        {
            "A1": ["CF_001"],
            "A2": ["CF_002"],
            "B1": ["CF_003"],
            "B2": ["CF_004"],
        },
    )

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID
    )  # no outcomes → 0% mastered at every level
    result = await _compute_cefr(profile)
    assert result == "A1"


@pytest.mark.integration
async def test_compute_cefr_a1_mastered_returns_a1(db):
    """A1 mastered but A2 not mastered → result is A1."""
    from maestro.learning.profile import _compute_cefr

    await _seed_grammar_points(
        db,
        {
            "A1": ["GP_001"],
            "A2": ["GP_002"],
            "B1": ["GP_003"],
            "B2": ["GP_004"],
        },
    )
    await _seed_comm_functions(
        db,
        {
            "A1": ["CF_001"],
            "A2": ["CF_002"],
            "B1": ["CF_003"],
            "B2": ["CF_004"],
        },
    )

    # A1 mastered; A2 not mastered → best = A1
    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={
            "it": LanguageProgress(
                grammar_recent_outcomes={"GP_001": [True] * 5},
                grammar_mastery_scores={"GP_001": 1.0},
                functions_counts={"CF_001": 3},
            )
        },
    )
    result = await _compute_cefr(profile)
    assert result == "A1"


@pytest.mark.integration
async def test_compute_cefr_both_a1_a2_mastered(db):
    """Both A1 and A2 mastered but B1 not → result is A2."""
    from maestro.learning.profile import _compute_cefr

    await _seed_grammar_points(
        db,
        {
            "A1": ["GP_001"],
            "A2": ["GP_002"],
            "B1": ["GP_003"],
            "B2": ["GP_004"],
        },
    )
    await _seed_comm_functions(
        db,
        {
            "A1": ["CF_001"],
            "A2": ["CF_002"],
            "B1": ["CF_003"],
            "B2": ["CF_004"],
        },
    )

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={
            "it": LanguageProgress(
                grammar_recent_outcomes={
                    "GP_001": [True] * 5,
                    "GP_002": [True] * 5,
                },
                grammar_mastery_scores={"GP_001": 1.0, "GP_002": 1.0},
                functions_counts={"CF_001": 5, "CF_002": 5},
            )
        },
    )
    result = await _compute_cefr(profile)
    assert result == "A2"


@pytest.mark.integration
async def test_compute_cefr_empty_level_blocks_advancement(db):
    """A level with no grammar points blocks advancement (can't pass with no data)."""
    from maestro.learning.profile import _compute_cefr

    # A1 has GP; A2 has no GPs but has CF; B1/B2 have GPs (not mastered)
    await _seed_grammar_points(
        db,
        {
            "A1": ["GP_001"],
            "B1": ["GP_003"],
            "B2": ["GP_004"],
        },
    )
    await _seed_comm_functions(
        db,
        {
            "A1": ["CF_001"],
            "A2": ["CF_002"],
            "B1": ["CF_003"],
            "B2": ["CF_004"],
        },
    )

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={
            "it": LanguageProgress(
                grammar_recent_outcomes={"GP_001": [True] * 5},
                grammar_mastery_scores={"GP_001": 1.0},
                functions_counts={"CF_001": 5, "CF_002": 5},
            )
        },
    )
    result = await _compute_cefr(profile)
    # A1 mastered, but A2 has no GPs → can't pass A2, stays at A1
    assert result == "A1"


@pytest.mark.integration
async def test_compute_cefr_no_skip_levels(db):
    """Can't skip a level — failing A2 blocks advancement even if B1 would pass."""
    from maestro.learning.profile import _compute_cefr

    await _seed_grammar_points(
        db,
        {
            "A1": ["GP_001"],
            "A2": ["GP_002"],
            "B1": ["GP_003"],
            "B2": ["GP_004"],
        },
    )
    await _seed_comm_functions(
        db,
        {
            "A1": ["CF_001"],
            "A2": ["CF_002"],
            "B1": ["CF_003"],
            "B2": ["CF_004"],
        },
    )

    # A1 mastered, A2 NOT mastered, B1 mastered
    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={
            "it": LanguageProgress(
                grammar_recent_outcomes={
                    "GP_001": [True] * 5,
                    "GP_003": [True] * 5,
                },
                grammar_mastery_scores={"GP_001": 1.0, "GP_003": 1.0},
                functions_counts={"CF_001": 5, "CF_003": 5},
            )
        },
    )
    result = await _compute_cefr(profile)
    # Can't skip A2, so stays at A1
    assert result == "A1"
