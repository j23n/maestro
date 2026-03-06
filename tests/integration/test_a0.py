"""Integration tests for A0 level — static lessons, onboarding, graduation."""
import pytest
from unittest.mock import patch

from beanie import PydanticObjectId

from maestro.models import (
    CurriculumScenario,
    DrillTemplate,
    GeneratedDrill,
    LearningProfile,
    Lesson,
    LessonActivity,
    ScenarioProgress,
    Student,
    StudentPersona,
    ActivityType,
    ActivityStatus,
    LessonStatus,
)

_FAKE_STUDENT_ID = PydanticObjectId()


# ---------------------------------------------------------------------------
# _pick_a0_scenario
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_pick_a0_scenario_returns_first_incomplete(db):
    """Should return the first A0 scenario not yet completed."""
    from maestro.lezione.selection import _pick_a0_scenario

    s1 = CurriculumScenario(
        slug="a0-01-benvenuto", label="Benvenuto", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02-saluti", label="Saluti", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=2,
    )
    await s1.insert()
    await s2.insert()

    # s1 completed, s2 not
    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        scenario_progress={"a0-01-benvenuto": ScenarioProgress(depth=1, lesson_count=1)},
    )
    scenario, depth = await _pick_a0_scenario(profile)
    assert scenario.slug == "a0-02-saluti"
    assert depth == 1


@pytest.mark.integration
async def test_pick_a0_scenario_returns_first_when_none_completed(db):
    """With no progress, should return the very first scenario."""
    from maestro.lezione.selection import _pick_a0_scenario

    s1 = CurriculumScenario(
        slug="a0-01-benvenuto", label="Benvenuto", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02-saluti", label="Saluti", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=2,
    )
    await s1.insert()
    await s2.insert()

    profile = LearningProfile(student_id=_FAKE_STUDENT_ID)
    scenario, depth = await _pick_a0_scenario(profile)
    assert scenario.slug == "a0-01-benvenuto"


@pytest.mark.integration
async def test_pick_scenario_a0_delegates(db):
    """pick_scenario with cefr_level='A0' should delegate to _pick_a0_scenario."""
    from maestro.lezione.selection import pick_scenario

    s1 = CurriculumScenario(
        slug="a0-01-benvenuto", label="Benvenuto", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=1,
    )
    await s1.insert()

    profile = LearningProfile(student_id=_FAKE_STUDENT_ID)
    scenario, depth = await pick_scenario(profile, "A0")
    assert scenario.slug == "a0-01-benvenuto"
    assert depth == 1


# ---------------------------------------------------------------------------
# A0 lesson generation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a0_lesson_generates_static_content(db):
    """A0 lesson background should load static content from YAML — no LLM calls."""
    from maestro.lezione.planner import generate_lesson_background

    profile = LearningProfile(student_id=_FAKE_STUDENT_ID, cefr_estimate="A0")
    await profile.insert()

    s1 = CurriculumScenario(
        slug="a0-01-benvenuto", label="Benvenuto", description="Welcome", cefr_level="A0",
        cf_codes=[], gp_codes=["a0_saluti"], depths=["Onboarding"], sequence=1,
    )
    await s1.insert()

    lesson = Lesson(student_id=_FAKE_STUDENT_ID, status=LessonStatus.ACTIVE, duration_minutes=10, generating=True)
    await lesson.insert()

    await generate_lesson_background(lesson.id, 10)

    lesson = await Lesson.get(lesson.id)
    assert lesson.generating is False
    assert lesson.scenario_slug == "a0-01-benvenuto"
    assert lesson.topic_title == "Benvenuto!"
    assert len(lesson.activities) > 0

    # Check activity types include onboarding and grammar
    types = [a.type for a in lesson.activities]
    assert ActivityType.GRAMMAR in types
    assert ActivityType.ONBOARDING in types
    assert ActivityType.DRILL in types


@pytest.mark.integration
async def test_a0_drill_creates_generated_drill_doc(db):
    """A0 drill activities should create GeneratedDrill documents."""
    from maestro.lezione.planner import generate_lesson_background

    profile = LearningProfile(student_id=_FAKE_STUDENT_ID, cefr_estimate="A0")
    await profile.insert()

    s = CurriculumScenario(
        slug="a0-02-saluti", label="Saluti", description="Greetings", cefr_level="A0",
        cf_codes=[], gp_codes=["a0_saluti"], depths=["Greetings"], sequence=2,
    )
    await s.insert()
    # Mark lesson 1 as done so lesson 2 is picked
    profile.scenario_progress["a0-01-benvenuto"] = ScenarioProgress(depth=1, lesson_count=1)
    await profile.save()

    # Also need scenario 1 to exist for the query
    s1 = CurriculumScenario(
        slug="a0-01-benvenuto", label="Benvenuto", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=1,
    )
    await s1.insert()

    lesson = Lesson(student_id=_FAKE_STUDENT_ID, status=LessonStatus.ACTIVE, duration_minutes=10, generating=True)
    await lesson.insert()

    await generate_lesson_background(lesson.id, 10)

    lesson = await Lesson.get(lesson.id)
    drill_activities = [a for a in lesson.activities if a.type == ActivityType.DRILL]
    assert len(drill_activities) > 0

    # Verify GeneratedDrill was created
    drill_id = drill_activities[0].drill_id
    drill = await GeneratedDrill.get(drill_id)
    assert drill is not None
    assert len(drill.items) > 0


# ---------------------------------------------------------------------------
# A0 graduation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_compute_cefr_stays_a0_when_incomplete(db):
    """Profile stays A0 when not all A0 scenarios are completed."""
    from maestro.learning.profile import _compute_cefr

    s1 = CurriculumScenario(
        slug="a0-01", label="1", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02", label="2", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=2,
    )
    await s1.insert()
    await s2.insert()

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        scenario_progress={"a0-01": ScenarioProgress(depth=1, lesson_count=1)},
    )
    result = await _compute_cefr(profile)
    assert result == "A0"


@pytest.mark.integration
async def test_compute_cefr_graduates_to_a1(db):
    """Profile graduates to A1 when all A0 scenarios are completed."""
    from maestro.learning.profile import _compute_cefr
    from maestro.models import GrammarPoint, CommunicativeFunction

    s1 = CurriculumScenario(
        slug="a0-01", label="1", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02", label="2", description="", cefr_level="A0",
        cf_codes=[], gp_codes=[], depths=["d1"], sequence=2,
    )
    await s1.insert()
    await s2.insert()

    # Seed GPs and CFs at all levels so vacuous-OK doesn't advance past A1
    for lvl in ("A1", "A2", "B1", "B2"):
        await GrammarPoint(code=f"GP_{lvl}", label=lvl, cefr_level=lvl, category="test", description="").insert()
        await CommunicativeFunction(code=f"CF_{lvl}", label=lvl, macro_category="test", cefr_level=lvl).insert()

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        scenario_progress={
            "a0-01": ScenarioProgress(depth=1, lesson_count=1),
            "a0-02": ScenarioProgress(depth=1, lesson_count=1),
        },
    )
    result = await _compute_cefr(profile)
    assert result == "A1"


# ---------------------------------------------------------------------------
# Onboarding route
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_onboarding_submit_saves_name(test_app, student, db):
    """POST onboarding-submit with profile_field=name should update Student.name."""
    import asyncio
    from maestro.utils import utcnow

    async def _setup():
        lesson = Lesson(
            student_id=student.id,
            status=LessonStatus.ACTIVE,
            duration_minutes=10,
            started_at=utcnow(),
            generating=False,
            activities=[
                LessonActivity(
                    type=ActivityType.ONBOARDING,
                    title="Come ti chiami?",
                    description="Tell us your name",
                    content="What's your name?",
                    profile_field="name",
                    response_template="Nice! Mi chiamo {answer}!",
                    status=ActivityStatus.ACTIVE,
                ),
            ],
            current_index=0,
        )
        await lesson.insert()
        return lesson

    lesson = asyncio.get_event_loop().run_until_complete(_setup())

    resp = test_app.post(
        f"/lezione/{lesson.id}/activity/0/onboarding-submit",
        data={"answer": "Giovanni"},
    )
    assert resp.status_code == 200
    assert "Mi chiamo Giovanni" in resp.text

    # Verify student name was updated
    async def _check():
        s = await Student.get(student.id)
        return s.name
    name = asyncio.get_event_loop().run_until_complete(_check())
    assert name == "Giovanni"


@pytest.mark.integration
def test_onboarding_submit_saves_persona_tags(test_app, student, db):
    """POST onboarding-submit with profile_field=persona_tags should update persona."""
    import asyncio
    from maestro.utils import utcnow

    async def _setup():
        # Create a profile first
        from maestro.profile import get_or_create_profile
        await get_or_create_profile(student.id)

        lesson = Lesson(
            student_id=student.id,
            status=LessonStatus.ACTIVE,
            duration_minutes=10,
            started_at=utcnow(),
            generating=False,
            activities=[
                LessonActivity(
                    type=ActivityType.ONBOARDING,
                    title="Cosa ti piace?",
                    description="Your interests",
                    content="What are your interests?",
                    profile_field="persona_tags",
                    response_template="Mi piace {answer}!",
                    status=ActivityStatus.ACTIVE,
                ),
            ],
            current_index=0,
        )
        await lesson.insert()
        return lesson

    lesson = asyncio.get_event_loop().run_until_complete(_setup())

    resp = test_app.post(
        f"/lezione/{lesson.id}/activity/0/onboarding-submit",
        data={"answer": "cooking, travel"},
    )
    assert resp.status_code == 200

    # Verify persona tags were updated
    async def _check():
        profile = await LearningProfile.find_one({"student_id": student.id})
        return profile.persona.tags
    tags = asyncio.get_event_loop().run_until_complete(_check())
    assert "cooking" in tags
    assert "travel" in tags
