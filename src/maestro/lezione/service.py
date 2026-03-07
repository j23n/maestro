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

from maestro.models import (
    GeneratedDrill, GrammarPoint, Lesson, ScenarioProgress,
    ActivityType, ActivityStatus, LessonStatus,
)
from maestro.learning.scorer import score_reading_answers
from maestro.learning.lesson_analyzer import analyze_lesson
from maestro.llm import get_async_client
from maestro.config import settings
from maestro.profile import get_or_create_profile
from maestro.utils import utcnow, create_background_task

logger = logging.getLogger(__name__)

_PASS_THRESHOLD = 0.7


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


async def generate_lesson_feedback(lesson: Lesson, weak_grammar_points: list) -> str:
    """Async Haiku call: brief English feedback on the completed lesson."""
    lines = []
    for a in lesson.activities:
        if a.type == ActivityType.DRILL and a.result:
            correct = a.result.get("correct")
            status = "correct" if correct else "incorrect" if correct is not None else "completed"
            lines.append(f"- Drill ({a.title}): {status}")
        elif a.status == ActivityStatus.COMPLETED:
            lines.append(f"- {a.title}: completed")
        elif a.status == ActivityStatus.SKIPPED:
            lines.append(f"- {a.title}: skipped")

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
    client = get_async_client()
    response = await client.messages.create(
        model=settings.DRILL_MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    text = re.sub(r'^#+\s+\S+\s*\n', '', text).strip()
    return text


async def get_weak_grammar_points(lesson: Lesson) -> list[GrammarPoint]:
    """Load grammar points for drills the student answered incorrectly."""
    result = []
    seen_codes: set[str] = set()
    for a in lesson.activities:
        if a.type != ActivityType.DRILL or not a.drill_id or not a.result:
            continue
        if a.result.get("correct") is not False:
            continue
        drill = await GeneratedDrill.get(a.drill_id)
        if drill is None or drill.grammar_point_code in seen_codes:
            continue
        gp = await GrammarPoint.find_one(GrammarPoint.code == drill.grammar_point_code)
        if gp:
            result.append(gp)
            seen_codes.add(gp.code)
    return result


async def score_reading_activity(
    questions: list[str],
    correct_answers: list[str],
    student_answers: list[str],
    cefr_level: str = "A1",
) -> tuple[bool, dict]:
    """Score reading answers and build enriched feedback.

    Returns (overall_correct, feedback_dict) where feedback_dict has
    keys: items, correct_count, total.
    """
    raw_results = await score_reading_answers(questions, correct_answers, student_answers, cefr_level=cefr_level)

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

    return overall_correct, feedback


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
    for code in (scenario.gp_codes or []):
        profile.grammar_correct_counts[code] = max(profile.grammar_correct_counts.get(code, 0), 5)
        profile.grammar_recent_outcomes[code] = [True] * 5

    # Credit CFs: set count to 3 (demonstration threshold)
    for code in (scenario.cf_codes or []):
        profile.functions_counts[code] = max(profile.functions_counts.get(code, 0), 3)

    # Recompute CEFR (may trigger A0->A1 graduation if all scenarios done)
    profile.cefr_estimate = await _compute_cefr(profile)
    profile.updated_at = utcnow()
    await profile.save()


async def ensure_lesson_feedback(lesson: Lesson, weak_grammar_points: list) -> str | None:
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
            feedback = await generate_lesson_feedback(lesson, weak_grammar_points)
            lesson.feedback_summary = feedback
            await lesson.update({"$set": {"feedback_summary": feedback}})
        except Exception as exc:
            logger.warning(f"[lezione] feedback generation error: {exc}")

    return lesson.feedback_summary
