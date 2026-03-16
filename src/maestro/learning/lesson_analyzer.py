"""End-of-lesson learning signal extraction.

Called once when a lesson is marked completed. Aggregates per-activity
LearningEvents (saved during the lesson) and collects CFs declared on
completed productive activities.

Phases:
  1 — Aggregate per-activity LearningEvents (GP codes + student text)
  2 — Collect CFs from completed speaking/writing activities
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from maestro.models import (
    ActivityStatus,
    ActivityType,
    LearningEvent,
)
from maestro.learning.profile import update_profile
from maestro import taxonomy

if TYPE_CHECKING:
    from maestro.models import Lesson

logger = logging.getLogger(__name__)


async def _collect_activity_events(
    lesson: "Lesson",
) -> tuple[list[str], list[str], str]:
    """Query per-activity LearningEvents for this lesson.

    Returns (gp_correct, gp_errors, combined_text).
    """
    events = await LearningEvent.find(
        {"lesson_id": lesson.id, "activity_type": {"$ne": None}}
    ).to_list()

    correct_set: set[str] = set()
    error_set: set[str] = set()
    texts: list[str] = []

    for ev in events:
        correct_set.update(ev.grammar_correct)
        error_set.update(ev.grammar_errors)
        if ev.student_text:
            texts.append(ev.student_text)
        logger.debug(
            "activity event",
            extra={
                "lesson_id": str(lesson.id),
                "activity_type": ev.activity_type,
                "grammar_correct": ev.grammar_correct,
                "grammar_errors": ev.grammar_errors,
            },
        )

    logger.info(
        "collected activity events",
        extra={
            "lesson_id": str(lesson.id),
            "n_events": len(events),
            "n_correct_codes": len(correct_set),
            "n_error_codes": len(error_set),
        },
    )
    return list(correct_set), list(error_set), "\n---\n".join(texts)


async def analyze_lesson(lesson: "Lesson") -> None:
    """Run end-of-lesson analysis and update the learning profile.

    Aggregates per-activity LearningEvents (already saved during the lesson),
    collects CFs from completed productive activities, then updates the profile.
    """
    try:
        logger.info(
            "analyze_lesson start",
            extra={"lesson_id": str(lesson.id), "student_id": str(lesson.student_id)},
        )
        await taxonomy.ensure_loaded()

        # Phase 1: aggregate per-activity events
        gp_correct, gp_errors, combined = await _collect_activity_events(lesson)

        # Phase 2: Collect CFs declared on completed productive activities
        _productive = {ActivityType.SPEAKING.value, ActivityType.WRITING.value}
        cf_codes = list(
            dict.fromkeys(
                code
                for act in lesson.activities
                if act.status == ActivityStatus.COMPLETED
                and act.type.value in _productive
                for code in act.cf_codes
            )
        )
        if cf_codes:
            logger.info(
                "collected %d CF codes from productive activities",
                len(cf_codes),
                extra={"lesson_id": str(lesson.id), "cf_codes": cf_codes},
            )

        # Create a summary event for profile update
        event = LearningEvent(
            student_id=lesson.student_id,
            lesson_id=lesson.id,
            grammar_correct=gp_correct,
            grammar_errors=gp_errors,
            functions_performed=cf_codes,
        )
        await event.insert()
        await update_profile(event)

        logger.info(
            "lesson analysis complete",
            extra={
                "lesson_id": str(lesson.id),
                "n_correct": len(gp_correct),
                "n_errors": len(gp_errors),
                "n_cfs": len(cf_codes),
            },
        )
    except Exception:
        logger.error("analyze_lesson error", exc_info=True)
