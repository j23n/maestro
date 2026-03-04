"""Integration tests for learning/profile.py using mongomock DB."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from maestro.models import GrammarPoint, CommunicativeFunction, LearningProfile, LearningEvent


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
                macro_category="test",
                cefr_level=level,
            )
            await cf.insert()


@pytest.mark.integration
async def test_update_profile_increments_correct_counts(db):
    from maestro.learning.profile import update_profile

    event = LearningEvent(grammar_correct=["GP_001"], grammar_errors=[], functions_performed=[])
    await event.insert()

    with patch("maestro.learning.profile._generate_description", new_callable=AsyncMock, return_value="desc"):
        await update_profile(event)

    profile = await LearningProfile.find_one()
    assert profile is not None
    assert profile.grammar_correct_counts.get("GP_001", 0) == 1


@pytest.mark.integration
async def test_update_profile_increments_error_counts(db):
    from maestro.learning.profile import update_profile

    event = LearningEvent(grammar_correct=[], grammar_errors=["GP_002"], functions_performed=[])
    await event.insert()

    with patch("maestro.learning.profile._generate_description", new_callable=AsyncMock, return_value="desc"):
        await update_profile(event)

    profile = await LearningProfile.find_one()
    assert profile.grammar_error_counts.get("GP_002", 0) == 1


@pytest.mark.integration
async def test_update_profile_recent_outcomes_capped_at_10(db):
    from maestro.learning.profile import update_profile

    profile = LearningProfile(
        grammar_recent_outcomes={"GP_001": [True] * 10}
    )
    await profile.insert()

    # Add one more True outcome
    event = LearningEvent(grammar_correct=["GP_001"], grammar_errors=[], functions_performed=[])
    await event.insert()

    with patch("maestro.learning.profile._generate_description", new_callable=AsyncMock, return_value="desc"):
        await update_profile(event)

    profile = await LearningProfile.find_one()
    assert len(profile.grammar_recent_outcomes["GP_001"]) == 10


@pytest.mark.integration
async def test_update_profile_creates_profile_if_none(db):
    from maestro.learning.profile import update_profile

    event = LearningEvent(grammar_correct=["GP_001"], grammar_errors=[], functions_performed=[])
    await event.insert()

    with patch("maestro.learning.profile._generate_description", new_callable=AsyncMock, return_value="desc"):
        await update_profile(event)

    profile = await LearningProfile.find_one()
    assert profile is not None


@pytest.mark.integration
async def test_compute_cefr_no_mastered_stays_a1(db):
    """When all levels have GPs and none are mastered, result stays A1."""
    from maestro.learning.profile import _compute_cefr

    # Seed GPs at ALL levels so vacuous-OK doesn't advance past A1
    await _seed_grammar_points(db, {
        "A1": ["GP_001", "GP_002"],
        "A2": ["GP_003"],
        "B1": ["GP_004"],
        "B2": ["GP_005"],
    })
    await _seed_comm_functions(db, {
        "A1": ["CF_001"],
        "A2": ["CF_002"],
        "B1": ["CF_003"],
        "B2": ["CF_004"],
    })

    profile = LearningProfile()  # no outcomes → 0% mastered at every level
    result = await _compute_cefr(profile)
    assert result == "A1"


@pytest.mark.integration
async def test_compute_cefr_a1_mastered_returns_a1(db):
    """A1 mastered but A2 not mastered → result is A1."""
    from maestro.learning.profile import _compute_cefr

    await _seed_grammar_points(db, {
        "A1": ["GP_001"],
        "A2": ["GP_002"],
        "B1": ["GP_003"],
        "B2": ["GP_004"],
    })
    await _seed_comm_functions(db, {
        "A1": ["CF_001"],
        "A2": ["CF_002"],
        "B1": ["CF_003"],
        "B2": ["CF_004"],
    })

    # A1 mastered; A2 not mastered → best = A1
    profile = LearningProfile(
        grammar_recent_outcomes={"GP_001": [True] * 5},
        functions_counts={"CF_001": 3},
    )
    result = await _compute_cefr(profile)
    assert result == "A1"


@pytest.mark.integration
async def test_compute_cefr_both_a1_a2_mastered(db):
    """Both A1 and A2 mastered but B1 not → result is A2."""
    from maestro.learning.profile import _compute_cefr

    await _seed_grammar_points(db, {
        "A1": ["GP_001"],
        "A2": ["GP_002"],
        "B1": ["GP_003"],
        "B2": ["GP_004"],
    })
    await _seed_comm_functions(db, {
        "A1": ["CF_001"],
        "A2": ["CF_002"],
        "B1": ["CF_003"],
        "B2": ["CF_004"],
    })

    profile = LearningProfile(
        grammar_recent_outcomes={
            "GP_001": [True] * 5,
            "GP_002": [True] * 5,
        },
        functions_counts={"CF_001": 5, "CF_002": 5},
    )
    result = await _compute_cefr(profile)
    assert result == "A2"


@pytest.mark.integration
async def test_compute_cefr_no_gp_at_level_ok(db):
    """A level with no grammar points is considered OK for gp_ok."""
    from maestro.learning.profile import _compute_cefr

    # A1 has GP; A2 has no GPs but has CF; B1/B2 have GPs (not mastered)
    await _seed_grammar_points(db, {
        "A1": ["GP_001"],
        "B1": ["GP_003"],
        "B2": ["GP_004"],
    })
    await _seed_comm_functions(db, {
        "A1": ["CF_001"],
        "A2": ["CF_002"],
        "B1": ["CF_003"],
        "B2": ["CF_004"],
    })

    profile = LearningProfile(
        grammar_recent_outcomes={"GP_001": [True] * 5},
        functions_counts={"CF_001": 5, "CF_002": 5},
    )
    result = await _compute_cefr(profile)
    # A1 mastered, A2 has no GPs (OK) and CF mastered → A2
    assert result == "A2"
