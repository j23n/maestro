"""Integration tests for learning/profile.py — _generate_description()."""

import pytest

from maestro.models import (
    GrammarPoint,
    CommunicativeFunction,
    LearningProfile,
)


@pytest.mark.integration
async def test_generate_description_empty_profile(db):
    """An empty profile should produce a valid description string."""
    from maestro.learning.profile import _generate_description

    gp = GrammarPoint(
        code="GP_001",
        label="Presente",
        cefr_level="A1",
        category="test",
        description="test",
    )
    await gp.insert()
    cf = CommunicativeFunction(
        code="CF_001",
        label="Salutare",
        macro_category="interagire_rituali_sociali",
        cefr_level="A1",
    )
    await cf.insert()

    profile = LearningProfile(cefr_estimate="A1")
    desc = await _generate_description(profile)

    assert isinstance(desc, str)
    assert "A1" in desc
    assert len(desc) > 20


@pytest.mark.integration
async def test_generate_description_with_struggles(db):
    """Profile with error-heavy grammar points should mention difficulties."""
    from maestro.learning.profile import _generate_description

    gp = GrammarPoint(
        code="GP_001",
        label="Passato prossimo",
        cefr_level="A1",
        category="test",
        description="test",
    )
    await gp.insert()

    profile = LearningProfile(
        cefr_estimate="A1",
        grammar_correct_counts={"GP_001": 1},
        grammar_error_counts={"GP_001": 5},  # 5/6 ≈ 83% error rate > 40%
    )
    desc = await _generate_description(profile)

    assert "Passato prossimo" in desc
    assert "difficult" in desc.lower() or "persistent" in desc.lower()


@pytest.mark.integration
async def test_generate_description_with_functions(db):
    """Profile with demonstrated CFs should mention communicative repertoire."""
    from maestro.learning.profile import _generate_description

    cf = CommunicativeFunction(
        code="CF_001",
        label="Salutare",
        macro_category="interagire_rituali_sociali",
        cefr_level="A1",
    )
    await cf.insert()

    profile = LearningProfile(
        cefr_estimate="A1",
        functions_counts={"CF_001": 10},
    )
    desc = await _generate_description(profile)

    assert "Salutare" in desc
