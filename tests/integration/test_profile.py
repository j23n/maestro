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


# ---------------------------------------------------------------------------
# Storyline routes
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_storyline_save_persists_to_active_language(test_app, student):
    """POST /profile/storyline writes to progress.<target_language>.storyline."""
    import asyncio
    from maestro.learning.profile import get_or_create_profile

    async def _setup():
        await get_or_create_profile(student.id)

    asyncio.get_event_loop().run_until_complete(_setup())

    resp = test_app.post(
        "/profile/storyline",
        data={"storyline": "Elena arrived in Bologna last month."},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    async def _check():
        p = await LearningProfile.find_one(LearningProfile.student_id == student.id)
        return p.progress[p.target_language].storyline

    stored = asyncio.get_event_loop().run_until_complete(_check())
    assert stored == "Elena arrived in Bologna last month."


@pytest.mark.integration
def test_storyline_save_trims_and_caps_length(test_app, student):
    import asyncio
    from maestro.learning.profile import get_or_create_profile

    async def _setup():
        await get_or_create_profile(student.id)

    asyncio.get_event_loop().run_until_complete(_setup())

    long_text = "  " + "x" * 5000 + "  "
    resp = test_app.post(
        "/profile/storyline", data={"storyline": long_text}, follow_redirects=False
    )
    assert resp.status_code == 303

    async def _check():
        p = await LearningProfile.find_one(LearningProfile.student_id == student.id)
        return p.progress[p.target_language].storyline

    stored = asyncio.get_event_loop().run_until_complete(_check())
    assert len(stored) == 1500
    assert stored == "x" * 1500


@pytest.mark.integration
def test_storyline_regenerate_returns_partial_and_resets_counter(
    test_app, student, monkeypatch
):
    """POST /profile/storyline/regenerate swaps the textarea and resets the counter."""
    import asyncio
    from unittest.mock import AsyncMock
    from maestro.learning.profile import get_or_create_profile

    async def _setup():
        profile = await get_or_create_profile(student.id)
        lp = profile.active_progress  # lazily initialises progress[lang]
        lp.storyline = "old"
        lp.storyline_lessons_since_evolve = 3
        await profile.save()

    asyncio.get_event_loop().run_until_complete(_setup())

    # Patch the LLM-driven evolver to a deterministic output.
    from maestro.lessons import storyline as storyline_mod

    monkeypatch.setattr(
        storyline_mod,
        "evolve_storyline",
        AsyncMock(return_value="A brand new paragraph about Elena."),
    )

    resp = test_app.post("/profile/storyline/regenerate")
    assert resp.status_code == 200
    assert "A brand new paragraph about Elena." in resp.text
    assert "<textarea" in resp.text

    async def _check():
        p = await LearningProfile.find_one(LearningProfile.student_id == student.id)
        lang = p.target_language
        return (
            p.progress[lang].storyline,
            p.progress[lang].storyline_lessons_since_evolve,
        )

    text, counter = asyncio.get_event_loop().run_until_complete(_check())
    assert text == "A brand new paragraph about Elena."
    assert counter == 0


# ---------------------------------------------------------------------------
# CEFR level override (floor semantics)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_effective_cefr_no_override_returns_estimate():
    lp = LanguageProgress(cefr_estimate="A1")
    assert lp.effective_cefr_level == "A1"


@pytest.mark.unit
def test_effective_cefr_override_above_estimate_wins():
    lp = LanguageProgress(cefr_estimate="A0", cefr_level_override="A2")
    assert lp.effective_cefr_level == "A2"


@pytest.mark.unit
def test_effective_cefr_estimate_above_override_wins():
    """Floor semantics: override sets a minimum; estimate can rise higher."""
    lp = LanguageProgress(cefr_estimate="B1", cefr_level_override="A1")
    assert lp.effective_cefr_level == "B1"


@pytest.mark.unit
def test_effective_cefr_invalid_override_falls_back_to_estimate():
    lp = LanguageProgress(cefr_estimate="A1", cefr_level_override="C5")
    assert lp.effective_cefr_level == "A1"


@pytest.mark.integration
async def test_get_cefr_level_returns_effective_with_override(db):
    from maestro.learning.profile import get_cefr_level

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        progress={"it": LanguageProgress(cefr_estimate="A0", cefr_level_override="A2")},
    )
    await profile.insert()

    assert await get_cefr_level(_FAKE_STUDENT_ID) == "A2"


@pytest.mark.integration
def test_post_profile_level_rejects_invalid(test_app, student):
    import asyncio
    from maestro.learning.profile import get_or_create_profile

    asyncio.get_event_loop().run_until_complete(get_or_create_profile(student.id))

    resp = test_app.post("/profile/level", data={"level": "C2"}, follow_redirects=False)
    assert resp.status_code == 303

    async def _check():
        p = await LearningProfile.find_one(LearningProfile.student_id == student.id)
        lp = p.progress.get(p.target_language)
        return lp.cefr_level_override if lp else None

    assert asyncio.get_event_loop().run_until_complete(_check()) is None


@pytest.mark.integration
def test_post_profile_level_sets_override_and_marks_onboarding(test_app, student):
    import asyncio
    from maestro.learning.profile import get_or_create_profile

    async def _setup():
        await get_or_create_profile(student.id)

    asyncio.get_event_loop().run_until_complete(_setup())

    resp = test_app.post("/profile/level", data={"level": "A2"}, follow_redirects=False)
    assert resp.status_code == 303

    async def _check():
        p = await LearningProfile.find_one(LearningProfile.student_id == student.id)
        lp = p.progress[p.target_language]
        return lp.cefr_level_override, lp.onboarding_completed

    override, onboarding_done = asyncio.get_event_loop().run_until_complete(_check())
    assert override == "A2"
    assert onboarding_done is True


@pytest.mark.integration
def test_post_profile_level_a0_does_not_force_onboarding_completed(test_app, student):
    import asyncio
    from maestro.learning.profile import get_or_create_profile

    asyncio.get_event_loop().run_until_complete(get_or_create_profile(student.id))

    resp = test_app.post("/profile/level", data={"level": "A0"}, follow_redirects=False)
    assert resp.status_code == 303

    async def _check():
        p = await LearningProfile.find_one(LearningProfile.student_id == student.id)
        lp = p.progress[p.target_language]
        return lp.cefr_level_override, lp.onboarding_completed

    override, onboarding_done = asyncio.get_event_loop().run_until_complete(_check())
    assert override == "A0"
    assert onboarding_done is False


@pytest.mark.integration
def test_post_profile_level_change_abandons_active_lesson(test_app, student):
    import asyncio
    from maestro.models import Lesson, LessonStatus
    from maestro.learning.profile import get_or_create_profile

    async def _setup():
        profile = await get_or_create_profile(student.id)
        lesson = Lesson(
            student_id=student.id,
            language=profile.target_language,
            status=LessonStatus.ACTIVE,
            cefr_at_start="A0",
            generating=False,
        )
        await lesson.insert()
        return lesson.id

    lesson_id = asyncio.get_event_loop().run_until_complete(_setup())

    resp = test_app.post("/profile/level", data={"level": "A2"}, follow_redirects=False)
    assert resp.status_code == 303

    async def _check():
        return await Lesson.get(lesson_id)

    lesson = asyncio.get_event_loop().run_until_complete(_check())
    assert lesson.status == LessonStatus.ABANDONED


@pytest.mark.integration
def test_post_profile_level_no_change_keeps_lesson_active(test_app, student):
    """Setting the same effective level should not abandon in-progress lessons."""
    import asyncio
    from maestro.models import Lesson, LessonStatus
    from maestro.learning.profile import get_or_create_profile

    async def _setup():
        profile = await get_or_create_profile(student.id)
        # Pre-set override A0 (effective A0 since estimate is also A0)
        lp = profile.active_progress
        lp.cefr_level_override = "A0"
        await profile.save()
        lesson = Lesson(
            student_id=student.id,
            language=profile.target_language,
            status=LessonStatus.ACTIVE,
            cefr_at_start="A0",
            generating=False,
        )
        await lesson.insert()
        return lesson.id

    lesson_id = asyncio.get_event_loop().run_until_complete(_setup())

    resp = test_app.post("/profile/level", data={"level": "A0"}, follow_redirects=False)
    assert resp.status_code == 303

    async def _check():
        return await Lesson.get(lesson_id)

    lesson = asyncio.get_event_loop().run_until_complete(_check())
    assert lesson.status == LessonStatus.ACTIVE
