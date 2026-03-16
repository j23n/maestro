"""Skip-onboarding logic: credit A0 mastery and graduate to A1."""

from beanie import PydanticObjectId

from maestro.models import (
    CurriculumScenario,
    Lesson,
    LessonStatus,
    ScenarioProgress,
)
from maestro.profile import get_or_create_profile
from maestro.utils import utcnow


async def skip_onboarding(student_id: PydanticObjectId) -> bool:
    """Skip all A0 onboarding, credit mastery, and graduate to A1.

    Returns True if onboarding was skipped, False if already past A0.
    """
    profile = await get_or_create_profile(student_id)
    if profile.cefr_estimate != "A0":
        return False

    a0_scenarios = await CurriculumScenario.find({"cefr_level": "A0"}).to_list()
    for scenario in a0_scenarios:
        # Mark scenario as completed (lesson_count=0: student didn't do lessons)
        profile.scenario_progress[scenario.slug] = ScenarioProgress(
            depth=1, last_visited=utcnow(), lesson_count=0
        )
        # Credit GPs: fill recent_outcomes with 5 True entries -> instant mastery
        now = utcnow().isoformat()
        for code in scenario.gp_codes or []:
            profile.grammar_correct_counts[code] = max(
                profile.grammar_correct_counts.get(code, 0), 5
            )
            profile.grammar_recent_outcomes[code] = [
                {"ok": True, "ts": now} for _ in range(5)
            ]
        # Credit CFs: set count to 3 (demonstration threshold)
        for code in scenario.cf_codes or []:
            profile.functions_counts[code] = max(
                profile.functions_counts.get(code, 0), 3
            )

    profile.onboarding_skipped = True
    profile.onboarding_completed = True
    profile.cefr_estimate = "A1"
    profile.updated_at = utcnow()
    await profile.save()

    # Abandon any active A0 lesson
    active = await Lesson.find_one(
        {"student_id": student_id, "status": LessonStatus.ACTIVE}
    )
    if active and active.cefr_at_start == "A0":
        active.status = LessonStatus.ABANDONED
        await active.save()

    return True
