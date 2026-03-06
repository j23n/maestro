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
from maestro.llm import get_async_client
from maestro.config import settings
from maestro.profile import get_profile
from maestro.utils import utcnow, create_background_task

logger = logging.getLogger(__name__)

_PASS_THRESHOLD = 0.7


def activity_url(lesson_id, idx: int) -> str:
    return f"/lezione/{lesson_id}/activity/{idx}"


async def advance_lesson(lesson: Lesson, current_idx: int, skip: bool = False) -> str:
    """Mark activity done/skipped, advance index, return redirect URL."""
    if not skip:
        lesson.activities[current_idx].status = ActivityStatus.COMPLETED
    next_idx = current_idx + 1
    while next_idx < len(lesson.activities):
        if lesson.activities[next_idx].status == ActivityStatus.PENDING:
            lesson.current_index = next_idx
            lesson.activities[next_idx].status = ActivityStatus.ACTIVE
            await lesson.save()
            return activity_url(lesson.id, next_idx)
        next_idx += 1
    if lesson.generating:
        lesson.current_index = next_idx
        await lesson.save()
        return f"/lezione/{lesson.id}/generating"
    lesson.status = LessonStatus.COMPLETED
    lesson.completed_at = utcnow()
    await lesson.save()

    # Update scenario progress
    if lesson.scenario_slug and lesson.student_id:
        profile = await get_profile(lesson.student_id)
        if profile:
            progress = profile.scenario_progress.get(lesson.scenario_slug, ScenarioProgress())
            progress.depth = max(progress.depth, lesson.scenario_depth or 1)
            progress.last_visited = utcnow()
            progress.lesson_count += 1
            profile.scenario_progress[lesson.scenario_slug] = progress
            await profile.save()

    return f"/lezione/{lesson.id}/complete"


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
        f"A student just completed an Italian lesson. Summary:\n{activity_summary}{weak_note}\n\n"
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
) -> tuple[bool, dict]:
    """Score reading answers and build enriched feedback.

    Returns (overall_correct, feedback_dict) where feedback_dict has
    keys: items, correct_count, total.
    """
    raw_results = await score_reading_answers(questions, correct_answers, student_answers)

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


async def ensure_lesson_feedback(lesson: Lesson, weak_grammar_points: list) -> str | None:
    """Ensure lesson has feedback. Triggers analysis if needed, generates feedback if missing.

    Returns the feedback_summary (may be None if generation fails).
    """
    if lesson.status == LessonStatus.COMPLETED and not lesson.feedback_summary:
        from maestro.learning.lesson_analyzer import analyze_lesson

        create_background_task(
            analyze_lesson(lesson),
            name=f"lesson-analyze-{lesson.id}",
        )

    if not lesson.feedback_summary:
        try:
            lesson.feedback_summary = await generate_lesson_feedback(lesson, weak_grammar_points)
            await lesson.save()
        except Exception as exc:
            logger.warning(f"[lezione] feedback generation error: {exc}")

    return lesson.feedback_summary
