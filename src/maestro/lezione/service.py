"""
Lesson lifecycle helpers.

- advance_lesson: state machine for moving between activities
- generate_lesson_feedback: end-of-lesson AI feedback
- get_weak_grammar_points: identify grammar areas needing work
- score_reading_activity: score reading comprehension answers
- ensure_lesson_feedback: ensure lesson has feedback (analyse + generate)
"""

from __future__ import annotations

import logging
import re

from beanie import PydanticObjectId
from maestro.models import (
    GrammarPoint,
    LearningEvent,
    Lesson,
    ScenarioProgress,
    ActivityType,
    ActivityStatus,
    LessonStatus,
)
from maestro.learning.scorer import score_reading_answers
from maestro.learning.lesson_analyzer import analyze_lesson
from maestro.llm import llm_messages_create
from maestro.models import CallType
from maestro.prompts import planner as _planner_prompts
from maestro.config import settings
from maestro.profile import get_or_create_profile
from maestro.utils import utcnow, create_background_task

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
    return f"/lezione/{lesson_id}/activity/{idx}"


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

        return f"/lezione/{lesson.id}/generating"

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
    return f"/lezione/{lesson.id}/complete"


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
    progress = profile.scenario_progress.get(lesson.scenario_slug, ScenarioProgress())
    progress.depth = max(progress.depth, lesson.scenario_depth or 1)
    progress.last_visited = utcnow()
    progress.lesson_count += 1
    profile.scenario_progress[lesson.scenario_slug] = progress
    await profile.save()


async def get_lesson_events(lesson: Lesson) -> list[LearningEvent]:
    """Fetch all LearningEvents for a lesson."""
    return await LearningEvent.find({"lesson_id": lesson.id}).to_list()


async def generate_lesson_feedback(
    lesson: Lesson,
    weak_grammar_points: list,
    events: list[LearningEvent] | None = None,
) -> str:
    """Async Haiku call: brief English feedback on the completed lesson."""
    if events is None:
        events = await get_lesson_events(lesson)
    event_by_idx: dict[int, list[LearningEvent]] = {}
    for ev in events:
        if ev.activity_index is not None:
            event_by_idx.setdefault(ev.activity_index, []).append(ev)

    lines = []
    for i, a in enumerate(lesson.activities):
        if a.type in (ActivityType.ONBOARDING, ActivityType.INFO):
            continue
        if a.status == ActivityStatus.SKIPPED:
            lines.append(f"- {a.title}: skipped")
        elif a.status == ActivityStatus.COMPLETED:
            idx_events = event_by_idx.get(i, [])
            if a.type == ActivityType.DRILL and a.result:
                correct = a.result.get("correct")
                status = (
                    "correct"
                    if correct
                    else "incorrect"
                    if correct is not None
                    else "completed"
                )
                lines.append(f"- Drill ({a.title}): {status}")
            elif idx_events:
                n_errors = sum(len(ev.grammar_errors) for ev in idx_events)
                lines.append(
                    f"- {a.title}: completed"
                    + (f" ({n_errors} grammar issues)" if n_errors else "")
                )
            else:
                lines.append(f"- {a.title}: completed")

    activity_summary = "\n".join(lines) if lines else "No activities recorded."
    weak_note = ""
    if weak_grammar_points:
        labels = ", ".join(gp.label for gp in weak_grammar_points)
        weak_note = f"\nThe student specifically struggled with: {labels}. Reference these by name."

    prompt = (
        f"A student just completed a {settings.TARGET_LANGUAGE_NAME} lesson. Summary:\n{activity_summary}{weak_note}\n\n"
        "Write 2-3 sentences of feedback in English that: mentions what was practiced, "
        "notes any areas of difficulty, and ends with one specific encouragement."
    )
    response = await llm_messages_create(
        model=settings.DRILL_MODEL,
        max_tokens=200,
        system=_planner_prompts.lesson_feedback.render_system(),
        messages=[{"role": "user", "content": prompt}],
        entity_id=lesson.id,
        call_type=CallType.LESSON_FEEDBACK,
        student_id=lesson.student_id,
    )
    text = response.content[0].text.strip()
    text = re.sub(r"^#+\s+.+\s*\n", "", text).strip()
    return text


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


async def score_reading_activity(
    questions: list[str],
    correct_answers: list[str],
    student_answers: list[str],
    cefr_level: str = "A1",
    student_id=None,
    lesson_id=None,
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
    )

    n = min(len(questions), len(student_answers), len(raw_results))
    enriched = [
        {
            "prompt": questions[j] if j < len(questions) else "",
            "correct_answer": correct_answers[j] if j < len(correct_answers) else "",
            "student_answer": student_answers[j] if j < len(student_answers) else "",
            "objective_correct": raw_results[j].get("objective_correct", False),
            "objective_note": raw_results[j].get("objective_note", ""),
            "grammar_errors": raw_results[j].get("grammar_errors", []),
            "tips": raw_results[j].get("tips", []),
        }
        for j in range(n)
    ]
    correct_count = sum(1 for r in enriched if r["objective_correct"])
    overall_correct = correct_count / max(n, 1) >= _PASS_THRESHOLD if n > 0 else True
    feedback = {"items": enriched, "correct_count": correct_count, "total": n}

    # Aggregate GP codes across all items
    from maestro import taxonomy

    await taxonomy.ensure_loaded()
    valid_codes = {g.code for g in taxonomy.grammar_points()}
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
        profile.functions_counts[code] = max(profile.functions_counts.get(code, 0), 3)

    # Recompute CEFR (may trigger A0->A1 graduation if all scenarios done)
    profile.cefr_estimate = await _compute_cefr(profile)
    profile.updated_at = utcnow()
    await profile.save()


async def ensure_lesson_feedback(
    lesson: Lesson,
    weak_grammar_points: list,
    events: list[LearningEvent] | None = None,
) -> str | None:
    """Ensure lesson has feedback. Triggers analysis if needed, generates feedback if missing.

    Returns the feedback_summary (may be None if generation fails).
    """
    if lesson.status == LessonStatus.COMPLETED and not lesson.feedback_summary:
        create_background_task(
            analyze_lesson(lesson),
            name=f"lesson-analyze-{lesson.id}",
        )

    if not lesson.feedback_summary:
        try:
            feedback = await generate_lesson_feedback(
                lesson, weak_grammar_points, events
            )
            lesson.feedback_summary = feedback
            await lesson.update({"$set": {"feedback_summary": feedback}})
        except Exception:
            logger.exception("lesson feedback generation failed: lesson=%s", lesson.id)

    return lesson.feedback_summary
