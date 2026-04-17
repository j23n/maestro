"""
Lesson lifecycle helpers.

- advance_lesson: state machine for moving between activities
- get_weak_grammar_points: identify grammar areas needing work
- score_reading_activity: score reading comprehension answers
"""

from __future__ import annotations

import logging

from beanie import PydanticObjectId
from maestro.models import (
    GrammarPoint,
    LearningEvent,
    Lesson,
    LessonActivity,
    ScenarioProgress,
    UserVocabularyCard,
    VocabularyWord,
    ActivityType,
    ActivityStatus,
    LessonStatus,
)
from maestro.learning.scorer import score_reading_answers
from maestro.learning.profile import get_or_create_profile
from maestro.utils import utcnow

logger = logging.getLogger(__name__)

_PASS_THRESHOLD = 0.7


async def count_paid_lessons(student_id: PydanticObjectId) -> int:
    """Count all non-A0 lessons ever created for a student (lifetime cap).

    Non-A0 lessons count toward the free-tier cap. Counts ALL statuses to
    prevent gaming the limit by abandoning lessons.
    """
    return await Lesson.find(
        {
            "student_id": student_id,
            "cefr_at_start": {"$ne": "A0"},
        }
    ).count()


def activity_url(lesson_id, idx: int) -> str:
    return f"/lessons/{lesson_id}/activity/{idx}"


def inject_discovered_reviews(activities: list[LessonActivity]) -> None:
    """Insert mid-lesson and end-of-lesson discovered-word review placeholders.

    Modifies the list in place.  The mid-lesson review is placed after the
    first reading or listening activity; the end-of-lesson review is appended
    last.  Card IDs are left empty — populated at serve time from words
    discovered so far.
    """
    from maestro.i18n import strings_t as st

    def _make_placeholder() -> LessonActivity:
        return LessonActivity(
            type=ActivityType.VOCAB_REVIEW,
            title=st("vocab_discovered_title", count=0),
            description=st("vocab_discovered_desc"),
            review_scope="discovered",
        )

    # Mid-lesson: after the first reading/listening activity
    mid_idx = None
    for i, act in enumerate(activities):
        if act.type in (ActivityType.READING, ActivityType.LISTENING):
            mid_idx = i + 1
            break

    if mid_idx is not None:
        activities.insert(mid_idx, _make_placeholder())

    # End-of-lesson: always last
    activities.append(_make_placeholder())


async def advance_lesson(
    lesson: Lesson,
    current_idx: int,
    skip: bool = False,
    result: dict | None = None,
) -> str:
    """Mark activity done/skipped, advance index, return redirect URL.

    Uses atomic MongoDB ``$set`` operations to avoid lost updates when
    concurrent requests hit the same lesson (e.g. double-click).

    ``result`` — if provided, is persisted on the current activity alongside
    the status change so callers don't need a separate save.
    """
    # Determine the status to set on the current activity
    current_status = ActivityStatus.SKIPPED if skip else ActivityStatus.COMPLETED

    # Keep the in-memory object consistent for callers that inspect it later
    lesson.activities[current_idx].status = current_status
    if result is not None:
        lesson.activities[current_idx].result = result

    next_idx = current_idx + 1
    while next_idx < len(lesson.activities):
        if lesson.activities[next_idx].status == ActivityStatus.PENDING:
            lesson.activities[next_idx].status = ActivityStatus.ACTIVE
            lesson.current_index = next_idx

            set_fields: dict = {
                f"activities.{current_idx}.status": current_status.value,
                f"activities.{next_idx}.status": ActivityStatus.ACTIVE.value,
                "current_index": next_idx,
            }
            if result is not None:
                set_fields[f"activities.{current_idx}.result"] = result
            await lesson.update({"$set": set_fields})

            return activity_url(lesson.id, next_idx)
        next_idx += 1

    if lesson.generating:
        lesson.current_index = next_idx

        set_fields = {
            f"activities.{current_idx}.status": current_status.value,
            "current_index": next_idx,
        }
        if result is not None:
            set_fields[f"activities.{current_idx}.result"] = result
        await lesson.update({"$set": set_fields})

        return f"/lessons/{lesson.id}/generating"

    now = utcnow()
    lesson.status = LessonStatus.COMPLETED
    lesson.completed_at = now

    set_fields = {
        f"activities.{current_idx}.status": current_status.value,
        "status": LessonStatus.COMPLETED.value,
        "completed_at": now,
    }
    if result is not None:
        set_fields[f"activities.{current_idx}.result"] = result
    _sweep_leftover_activities(lesson, set_fields)
    await lesson.update({"$set": set_fields})

    await update_scenario_progress(lesson)

    if lesson.cefr_at_start == "A0":
        await _credit_a0_mastery(lesson)

    logger.info("lesson complete: lesson=%s", lesson.id)
    return f"/lessons/{lesson.id}/complete"


def _sweep_leftover_activities(lesson: Lesson, set_fields: dict) -> None:
    """Mark any PENDING/ACTIVE activities as SKIPPED (in-memory + set_fields)."""
    for i, act in enumerate(lesson.activities):
        if act.status in (ActivityStatus.PENDING, ActivityStatus.ACTIVE):
            act.status = ActivityStatus.SKIPPED
            set_fields[f"activities.{i}.status"] = ActivityStatus.SKIPPED.value


async def update_scenario_progress(lesson: Lesson) -> None:
    """Record scenario completion on the student's learning profile."""
    if not lesson.scenario_slug or not lesson.student_id:
        return
    profile = await get_or_create_profile(lesson.student_id)
    lp = profile.active_progress
    progress = lp.scenario_progress.get(lesson.scenario_slug, ScenarioProgress())
    progress.depth = max(progress.depth, lesson.scenario_depth or 1)
    progress.last_visited = utcnow()
    progress.lesson_count += 1
    lp.scenario_progress[lesson.scenario_slug] = progress
    await profile.save()


async def get_lesson_events(lesson: Lesson) -> list[LearningEvent]:
    """Fetch all LearningEvents for a lesson."""
    return await LearningEvent.find({"lesson_id": lesson.id}).to_list()


async def get_weak_grammar_points(
    lesson: Lesson,
    events: list[LearningEvent] | None = None,
) -> list[GrammarPoint]:
    """Load grammar points that had errors in per-activity LearningEvents."""
    if events is None:
        events = await get_lesson_events(lesson)
    error_codes: list[str] = list(
        dict.fromkeys(c for ev in events for c in ev.grammar_errors)
    )
    if not error_codes:
        return []
    gps = await GrammarPoint.find({"code": {"$in": error_codes}}).to_list()
    # Preserve order from error_codes
    gp_by_code = {gp.code: gp for gp in gps}
    return [gp_by_code[c] for c in error_codes if c in gp_by_code]


async def get_lesson_discovered_words(lesson: Lesson) -> list[UserVocabularyCard]:
    """Fetch vocabulary cards discovered during this lesson."""
    if not lesson.student_id or not lesson.created_at:
        return []
    end_time = lesson.completed_at or utcnow()
    cards = await UserVocabularyCard.find(
        {
            "student_id": lesson.student_id,
            "discovered_at": {"$gte": lesson.created_at, "$lte": end_time},
        }
    ).to_list()
    # Resolve word links in batch
    word_ids = []
    for c in cards:
        ref = c.word
        word_ids.append(ref.ref.id if hasattr(ref, "ref") else ref.id)
    if word_ids:
        words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
        word_map = {w.id: w for w in words}
        for c in cards:
            ref = c.word
            wid = ref.ref.id if hasattr(ref, "ref") else ref.id
            c.word = word_map.get(wid)
    return [c for c in cards if c.word is not None]


async def score_reading_activity(
    questions: list[str],
    correct_answers: list[str],
    student_answers: list[str],
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
    language: str | None = None,
) -> tuple[bool, dict, list[str], list[str]]:
    """Score reading answers and build enriched feedback.

    Returns (overall_correct, feedback_dict, gp_correct_codes, gp_error_codes).
    """
    raw_results = await score_reading_answers(
        questions,
        correct_answers,
        student_answers,
        cefr_level=cefr_level,
        student_id=student_id,
        lesson_id=lesson_id,
        language=language,
    )

    n = min(len(questions), len(student_answers), len(raw_results))
    items = [
        {
            "correct": bool(raw_results[j].get("objective_correct", False)),
            "grammar_errors": raw_results[j].get("grammar_errors", []),
        }
        for j in range(n)
    ]
    correct_count = sum(1 for r in items if r["correct"])
    overall_correct = correct_count / max(n, 1) >= _PASS_THRESHOLD if n > 0 else True
    feedback = {"items": items, "correct_count": correct_count, "total": n}

    # Aggregate GP codes across all items
    from maestro.learning import grammar_cache

    await grammar_cache.ensure_loaded(language)
    valid_codes = {g.code for g in grammar_cache.grammar_points(language)}
    gp_correct = list(
        {
            c
            for r in raw_results[:n]
            for c in r.get("grammar_correct_codes", [])
            if c in valid_codes
        }
    )
    gp_errors = list(
        {
            c
            for r in raw_results[:n]
            for c in r.get("grammar_error_codes", [])
            if c in valid_codes
        }
    )

    return overall_correct, feedback, gp_correct, gp_errors


async def _credit_a0_mastery(lesson: Lesson) -> None:
    """Credit all GPs and CFs from the A0 scenario as mastered.

    A0 is onboarding — we mark everything as complete. Real performance
    tracking begins at A1.
    """
    from maestro.models import CurriculumScenario
    from maestro.learning.profile import _compute_cefr

    if not lesson.scenario_slug or not lesson.student_id:
        return

    scenario = await CurriculumScenario.find_one({"slug": lesson.scenario_slug})
    if not scenario:
        return

    profile = await get_or_create_profile(lesson.student_id)
    lp = profile.active_progress

    # Credit GPs: fill recent_outcomes with 5 True entries -> instant mastery
    now = utcnow().isoformat()
    for code in scenario.gp_codes or []:
        lp.grammar_correct_counts[code] = max(lp.grammar_correct_counts.get(code, 0), 5)
        lp.grammar_recent_outcomes[code] = [{"ok": True, "ts": now} for _ in range(5)]
        lp.grammar_mastery_scores[code] = 1.0

    # Credit CFs: set count to 3 (demonstration threshold)
    for code in scenario.cf_codes or []:
        lp.functions_counts[code] = max(lp.functions_counts.get(code, 0), 3)

    # Recompute CEFR (may trigger A0->A1 graduation if all scenarios done)
    lp.cefr_estimate = await _compute_cefr(profile)
    profile.updated_at = utcnow()
    await profile.save()


async def ensure_lesson_analyzed(lesson: Lesson) -> None:
    """Trigger background lesson analysis if the lesson is complete.

    Analysis updates learning profile counts from grammar/CF events.
    """
    from maestro.learning.lesson_analyzer import analyze_lesson
    from maestro.utils import create_background_task

    if lesson.status == LessonStatus.COMPLETED:
        create_background_task(
            analyze_lesson(lesson),
            name=f"lesson-analyze-{lesson.id}",
        )
