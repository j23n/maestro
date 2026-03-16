"""End-of-lesson learning signal extraction.

Called once when a lesson is marked completed. Aggregates per-activity
LearningEvents (saved during the lesson) and runs CF analysis on
combined student text.

Phases:
  1 — Aggregate per-activity LearningEvents (GP codes + student text)
  2 — CF analysis (two-stage: macro → per-macro parallel)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from maestro.models import (
    ActivityStatus,
    ActivityType,
    LearningEvent,
)
from maestro.learning.profile import update_profile
from maestro import taxonomy
from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import CallType
from maestro.prompts import lesson_analyzer as _prompts
from maestro.learning.constants import MACRO_CATEGORIES as _MACRO_TUPLES
from maestro.utils import parse_llm_json

if TYPE_CHECKING:
    from maestro.models import Lesson

logger = logging.getLogger(__name__)

_MACRO_CATEGORIES = {k: v[0] for k, v in _MACRO_TUPLES.items()}


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


async def _analyze_cfs_staged(
    combined: str,
    cefr_level: str,
    student_id=None,
    lesson_id=None,
) -> list[str]:
    """Two-stage CF analysis: macro identification → per-macro CF classification."""
    macro_lines = "\n".join(
        f"- {macro}: {desc}" for macro, desc in _MACRO_CATEGORIES.items()
    )
    stage1_prompt = _prompts.cf_macro_detection.render(
        combined=combined,
        macro_lines=macro_lines,
    )

    try:
        response = await llm_messages_create(
            model=settings.DRILL_MODEL,
            max_tokens=128,
            system=_prompts.cf_macro_detection.render_system(),
            messages=[{"role": "user", "content": stage1_prompt}],
            entity_id=lesson_id,
            call_type=CallType.LESSON_ANALYZER_CF1,
            student_id=student_id,
        )
        raw = response.content[0].text
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            return []
        identified_macros = [
            m for m in data.get("categories", []) if m in _MACRO_CATEGORIES
        ]
    except Exception:
        logger.error("CF stage 1 error", exc_info=True)
        return []

    if not identified_macros:
        return []

    async def _analyze_one_macro(macro: str) -> list[str]:
        cfs = [
            cf
            for cf in taxonomy.comm_functions()
            if cf.macro_category == macro and cf.cefr_level == cefr_level
        ]
        if not cfs:
            return []
        cf_lines = "\n".join(
            f"{cf.code}: {cf.label}"
            + (f" — {', '.join(cf.patterns[:2])}" if cf.patterns else "")
            for cf in cfs
        )
        prompt = _prompts.cf_function_detection.render(
            combined=combined,
            cf_lines=cf_lines,
        )
        try:
            resp = await llm_messages_create(
                model=settings.DRILL_MODEL,
                max_tokens=128,
                system=_prompts.cf_function_detection.render_system(),
                messages=[{"role": "user", "content": prompt}],
                entity_id=lesson_id,
                call_type=CallType.LESSON_ANALYZER_CF2,
                student_id=student_id,
            )
            raw = resp.content[0].text
            d = parse_llm_json(raw)
            if not isinstance(d, dict):
                return []
            valid = {cf.code for cf in cfs}
            return [c for c in d.get("functions", []) if c in valid]
        except Exception:
            logger.error("CF stage 2 error", extra={"macro": macro}, exc_info=True)
            return []

    results = await asyncio.gather(*[_analyze_one_macro(m) for m in identified_macros])
    cf_codes: list[str] = []
    for codes in results:
        cf_codes.extend(codes)
    return cf_codes


async def analyze_lesson(lesson: "Lesson") -> None:
    """Run end-of-lesson analysis and update the learning profile.

    Aggregates per-activity LearningEvents (already saved during the lesson),
    then runs CF analysis on combined student text.
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
