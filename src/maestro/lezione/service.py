"""
Lesson lifecycle helpers.

- advance_lesson: state machine for moving between activities
- generate_lesson_feedback: end-of-lesson AI feedback
- get_weak_grammar_points: identify grammar areas needing work
"""
from __future__ import annotations

import logging
import re

from maestro.models import GeneratedDrill, GrammarPoint, Lesson, ScenarioProgress
from maestro.llm import get_async_client
from maestro.config import settings
from maestro.profile import get_profile
from maestro.utils import utcnow

logger = logging.getLogger(__name__)


def activity_url(lesson_id, idx: int) -> str:
    return f"/lezione/{lesson_id}/activity/{idx}"


async def advance_lesson(lesson: Lesson, current_idx: int, skip: bool = False) -> str:
    """Mark activity done/skipped, advance index, return redirect URL."""
    if not skip:
        lesson.activities[current_idx].status = "completed"
    next_idx = current_idx + 1
    while next_idx < len(lesson.activities):
        if lesson.activities[next_idx].status == "pending":
            lesson.current_index = next_idx
            lesson.activities[next_idx].status = "active"
            await lesson.save()
            return activity_url(lesson.id, next_idx)
        next_idx += 1
    if lesson.generating:
        lesson.current_index = next_idx
        await lesson.save()
        return f"/lezione/{lesson.id}/generating"
    lesson.status = "completed"
    lesson.completed_at = utcnow()
    await lesson.save()

    # Update scenario progress
    if lesson.scenario_slug:
        profile = await get_profile()
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
        if a.type == "drill" and a.result:
            correct = a.result.get("correct")
            status = "correct" if correct else "incorrect" if correct is not None else "completed"
            lines.append(f"- Drill ({a.title}): {status}")
        elif a.status == "completed":
            lines.append(f"- {a.title}: completed")
        elif a.status == "skipped":
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
        if a.type != "drill" or not a.drill_id or not a.result:
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
