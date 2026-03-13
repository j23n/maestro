"""Integration tests for A0 level — static lessons, onboarding, graduation."""

import pytest

from beanie import PydanticObjectId

from maestro.models import (
    Account,
    CurriculumScenario,
    GeneratedDrill,
    LearningProfile,
    Lesson,
    LessonActivity,
    ScenarioProgress,
    Student,
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
        slug="a0-01-benvenuto",
        label="Benvenuto",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02-saluti",
        label="Saluti",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=2,
    )
    await s1.insert()
    await s2.insert()

    # s1 completed, s2 not
    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        scenario_progress={
            "a0-01-benvenuto": ScenarioProgress(depth=1, lesson_count=1)
        },
    )
    scenario, depth = await _pick_a0_scenario(profile)
    assert scenario.slug == "a0-02-saluti"
    assert depth == 1


@pytest.mark.integration
async def test_pick_a0_scenario_returns_first_when_none_completed(db):
    """With no progress, should return the very first scenario."""
    from maestro.lezione.selection import _pick_a0_scenario

    s1 = CurriculumScenario(
        slug="a0-01-benvenuto",
        label="Benvenuto",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02-saluti",
        label="Saluti",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=2,
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
        slug="a0-01-benvenuto",
        label="Benvenuto",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
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
        slug="a0-01-benvenuto",
        label="Benvenuto",
        description="Welcome",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=["a0_saluti"],
        depths=["Onboarding"],
        sequence=1,
    )
    await s1.insert()

    lesson = Lesson(
        student_id=_FAKE_STUDENT_ID,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        generating=True,
    )
    await lesson.insert()

    await generate_lesson_background(lesson.id, 10)

    lesson = await Lesson.get(lesson.id)
    assert lesson.generating is False
    assert lesson.scenario_slug == "a0-01-benvenuto"
    assert lesson.topic_title == '<span lang="it">Benvenuto!</span>'
    assert len(lesson.activities) > 0

    # Check activity types include onboarding and grammar
    types = [a.type for a in lesson.activities]
    assert ActivityType.GRAMMAR in types
    assert ActivityType.ONBOARDING in types
    assert ActivityType.DRILL in types

    # After lang flip: EN content is NOT wrapped (base lang is EN), only IT content is
    assert not lesson.overview.startswith("<span")
    assert not lesson.topic_description.startswith("<span")

    # Grammar: title/description plain text, content unchanged (has inline spans)
    grammar = next(a for a in lesson.activities if a.type == ActivityType.GRAMMAR)
    assert not grammar.title.startswith("<span")
    assert not grammar.description.startswith("<span")
    assert not grammar.content.startswith("<span")  # mixed lang, not outer-wrapped

    # Onboarding: title/content are plain text (no longer wrapped)
    onboarding = next(a for a in lesson.activities if a.type == ActivityType.ONBOARDING)
    assert not onboarding.title.startswith("<span")
    assert not onboarding.content.startswith("<span")


@pytest.mark.integration
async def test_a0_drill_creates_generated_drill_doc(db):
    """A0 drill activities should create GeneratedDrill documents."""
    from maestro.lezione.planner import generate_lesson_background

    profile = LearningProfile(student_id=_FAKE_STUDENT_ID, cefr_estimate="A0")
    await profile.insert()

    s = CurriculumScenario(
        slug="a0-02-saluti",
        label="Saluti",
        description="Greetings",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=["a0_saluti"],
        depths=["Greetings"],
        sequence=2,
    )
    await s.insert()
    # Mark lesson 1 as done so lesson 2 is picked
    profile.scenario_progress["a0-01-benvenuto"] = ScenarioProgress(
        depth=1, lesson_count=1
    )
    await profile.save()

    # Also need scenario 1 to exist for the query
    s1 = CurriculumScenario(
        slug="a0-01-benvenuto",
        label="Benvenuto",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
    )
    await s1.insert()

    lesson = Lesson(
        student_id=_FAKE_STUDENT_ID,
        status=LessonStatus.ACTIVE,
        duration_minutes=10,
        generating=True,
    )
    await lesson.insert()

    await generate_lesson_background(lesson.id, 10)

    lesson = await Lesson.get(lesson.id)
    drill_activities = [a for a in lesson.activities if a.type == ActivityType.DRILL]
    assert len(drill_activities) > 0

    # Verify GeneratedDrill was created — prompts/answers are plain text (no lang wrapping)
    drill_id = drill_activities[0].drill_id
    drill = await GeneratedDrill.get(drill_id)
    assert drill is not None
    assert len(drill.items) > 0
    assert not drill.items[0].prompt.startswith("<span")
    assert not drill.items[0].correct_answer.startswith("<span")


# ---------------------------------------------------------------------------
# A0 graduation
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_compute_cefr_stays_a0_when_incomplete(db):
    """Profile stays A0 when not all A0 scenarios are completed."""
    from maestro.learning.profile import _compute_cefr

    s1 = CurriculumScenario(
        slug="a0-01",
        label="1",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02",
        label="2",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=2,
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
        slug="a0-01",
        label="1",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02",
        label="2",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=2,
    )
    await s1.insert()
    await s2.insert()

    # Seed GPs and CFs at all levels so vacuous-OK doesn't advance past A1
    for lvl in ("A1", "A2", "B1", "B2"):
        await GrammarPoint(
            code=f"GP_{lvl}", label=lvl, cefr_level=lvl, category="test", description=""
        ).insert()
        await CommunicativeFunction(
            code=f"CF_{lvl}", label=lvl, macro_category="test", cefr_level=lvl
        ).insert()

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
def test_onboarding_submit_saves_background(test_app, student, db):
    """POST onboarding-submit with profile_field=background should update persona."""
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
                    title="Chi sei?",
                    description="Tell us about yourself",
                    content="What describes you?",
                    profile_field="background",
                    response_template="Sono {answer}!",
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
        data={"answer": "university student"},
    )
    assert resp.status_code == 200

    # Verify background was updated
    async def _check():
        profile = await LearningProfile.find_one({"student_id": student.id})
        return profile.persona.background

    background = asyncio.get_event_loop().run_until_complete(_check())
    assert "university student" in background


# ---------------------------------------------------------------------------
# End-to-end: signup → onboarding (#25)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_signup_then_onboarding_saves_name(auth_app, db):
    """Full flow: signup creates Account+Student, then onboarding saves name."""
    import asyncio
    from maestro.utils import utcnow

    # 1. Signup — creates Account + Student with empty name
    resp = auth_app.post(
        "/auth/signup",
        data={
            "email": "e2e@example.com",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Resolve the student created by signup
    async def _get_student():
        account = await Account.find_one({"email": "e2e@example.com"})
        student = await Student.get(account.student_id)
        assert student.name == ""  # empty before onboarding
        return student

    student = asyncio.get_event_loop().run_until_complete(_get_student())

    # 2. Create an onboarding lesson for this student
    async def _create_lesson():
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
                    response_template="Piacere, {answer}!",
                    status=ActivityStatus.ACTIVE,
                ),
            ],
            current_index=0,
        )
        await lesson.insert()
        return lesson

    lesson = asyncio.get_event_loop().run_until_complete(_create_lesson())

    # 3. Submit onboarding — should save name on the Student
    resp = auth_app.post(
        f"/lezione/{lesson.id}/activity/0/onboarding-submit",
        data={"answer": "Maria"},
    )
    assert resp.status_code == 200
    assert "Maria" in resp.text

    # 4. Verify Student.name was persisted
    async def _check():
        s = await Student.get(student.id)
        return s.name

    name = asyncio.get_event_loop().run_until_complete(_check())
    assert name == "Maria"


# ---------------------------------------------------------------------------
# Skip onboarding
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_skip_onboarding_sets_flags_and_graduates(db):
    """_skip_onboarding should set flags, credit mastery, and graduate to A1."""
    from maestro.learning.onboarding import skip_onboarding as _skip_onboarding
    from maestro.profile import get_or_create_profile

    student = Student(name="")
    await student.insert()

    s1 = CurriculumScenario(
        slug="a0-01",
        label="1",
        description="",
        cefr_level="A0",
        cf_codes=["cf_greet"],
        gp_codes=["gp_saluti"],
        depths=["d1"],
        sequence=1,
    )
    s2 = CurriculumScenario(
        slug="a0-02",
        label="2",
        description="",
        cefr_level="A0",
        cf_codes=["cf_bye"],
        gp_codes=["gp_addio"],
        depths=["d1"],
        sequence=2,
    )
    await s1.insert()
    await s2.insert()

    profile = await get_or_create_profile(student.id)
    assert profile.cefr_estimate == "A0"

    result = await _skip_onboarding(student.id)
    assert result is True

    profile = await LearningProfile.find_one({"student_id": student.id})
    assert profile.onboarding_skipped is True
    assert profile.onboarding_completed is True
    assert profile.cefr_estimate == "A1"

    # Scenario progress filled
    assert profile.scenario_progress["a0-01"].depth == 1
    assert profile.scenario_progress["a0-02"].depth == 1

    # GP mastery credited
    assert profile.grammar_correct_counts.get("gp_saluti", 0) >= 5
    assert profile.grammar_recent_outcomes.get("gp_saluti") == [True] * 5
    assert profile.grammar_correct_counts.get("gp_addio", 0) >= 5

    # CF mastery credited
    assert profile.functions_counts.get("cf_greet", 0) >= 3
    assert profile.functions_counts.get("cf_bye", 0) >= 3


@pytest.mark.integration
async def test_skip_onboarding_already_past_a0(db):
    """_skip_onboarding should return False if already past A0."""
    from maestro.learning.onboarding import skip_onboarding as _skip_onboarding
    from maestro.profile import get_or_create_profile

    student = Student(name="")
    await student.insert()

    profile = await get_or_create_profile(student.id)
    profile.cefr_estimate = "A1"
    await profile.save()

    result = await _skip_onboarding(student.id)
    assert result is False


@pytest.mark.integration
async def test_skip_onboarding_abandons_active_lesson(db):
    """_skip_onboarding should abandon any active A0 lesson."""
    from maestro.learning.onboarding import skip_onboarding as _skip_onboarding
    from maestro.profile import get_or_create_profile
    from maestro.utils import utcnow

    student = Student(name="")
    await student.insert()
    await get_or_create_profile(student.id)

    s1 = CurriculumScenario(
        slug="a0-01",
        label="1",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
    )
    await s1.insert()

    lesson = Lesson(
        student_id=student.id,
        status=LessonStatus.ACTIVE,
        cefr_at_start="A0",
        duration_minutes=10,
        started_at=utcnow(),
        generating=False,
    )
    await lesson.insert()

    await _skip_onboarding(student.id)

    lesson = await Lesson.get(lesson.id)
    assert lesson.status == LessonStatus.ABANDONED


@pytest.mark.integration
async def test_compute_cefr_respects_skip_flag(db):
    """Profile with onboarding_skipped=True should skip A0 check."""
    from maestro.learning.profile import _compute_cefr
    from maestro.models import GrammarPoint, CommunicativeFunction

    # Create A0 scenarios that are NOT completed — normally this would return A0
    s1 = CurriculumScenario(
        slug="a0-01",
        label="1",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
    )
    await s1.insert()

    # Seed A1+ GPs/CFs so we don't vacuously advance
    for lvl in ("A1", "A2", "B1", "B2"):
        await GrammarPoint(
            code=f"GP_{lvl}", label=lvl, cefr_level=lvl, category="test", description=""
        ).insert()
        await CommunicativeFunction(
            code=f"CF_{lvl}", label=lvl, macro_category="test", cefr_level=lvl
        ).insert()

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        onboarding_skipped=True,
    )
    result = await _compute_cefr(profile)
    assert result == "A1"  # Not A0, because skip flag bypasses A0 check


@pytest.mark.integration
async def test_compute_cefr_sets_onboarding_completed_on_natural_graduation(db):
    """When all A0 scenarios are done, _compute_cefr should set onboarding_completed."""
    from maestro.learning.profile import _compute_cefr
    from maestro.models import GrammarPoint, CommunicativeFunction

    s1 = CurriculumScenario(
        slug="a0-01",
        label="1",
        description="",
        cefr_level="A0",
        cf_codes=[],
        gp_codes=[],
        depths=["d1"],
        sequence=1,
    )
    await s1.insert()

    for lvl in ("A1", "A2", "B1", "B2"):
        await GrammarPoint(
            code=f"GP_{lvl}", label=lvl, cefr_level=lvl, category="test", description=""
        ).insert()
        await CommunicativeFunction(
            code=f"CF_{lvl}", label=lvl, macro_category="test", cefr_level=lvl
        ).insert()

    profile = LearningProfile(
        student_id=_FAKE_STUDENT_ID,
        scenario_progress={"a0-01": ScenarioProgress(depth=1, lesson_count=1)},
    )
    assert profile.onboarding_completed is False

    result = await _compute_cefr(profile)
    assert result == "A1"
    assert profile.onboarding_completed is True


@pytest.mark.integration
def test_skip_onboarding_route(test_app, student, db):
    """POST /onboarding/skip should redirect to /lezione/."""
    import asyncio

    async def _setup():
        from maestro.profile import get_or_create_profile

        await get_or_create_profile(student.id)
        s1 = CurriculumScenario(
            slug="a0-01",
            label="1",
            description="",
            cefr_level="A0",
            cf_codes=[],
            gp_codes=[],
            depths=["d1"],
            sequence=1,
        )
        await s1.insert()

    asyncio.get_event_loop().run_until_complete(_setup())

    resp = test_app.post("/onboarding/skip", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/lezione/"

    async def _check():
        profile = await LearningProfile.find_one({"student_id": student.id})
        return profile

    profile = asyncio.get_event_loop().run_until_complete(_check())
    assert profile.onboarding_skipped is True
    assert profile.cefr_estimate == "A1"
