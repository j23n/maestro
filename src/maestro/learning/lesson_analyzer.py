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
    LearningEvent,
)
from maestro.learning.profile import update_profile
from maestro import taxonomy
from maestro.config import settings
from maestro.llm import get_async_client
from maestro.profile import get_profile
from maestro.prompts import lesson_analyzer as _prompts
from maestro.learning.constants import MACRO_CATEGORIES as _MACRO_TUPLES
from maestro.utils import parse_llm_json

if TYPE_CHECKING:
    import anthropic
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

    correct_codes: list[str] = []
    error_codes: list[str] = []
    texts: list[str] = []

    for ev in events:
        correct_codes.extend(ev.grammar_correct)
        error_codes.extend(ev.grammar_errors)
        if ev.student_text:
            texts.append(ev.student_text)

    return correct_codes, error_codes, "\n---\n".join(texts)


async def _analyze_cfs_staged(
    combined: str,
    cefr_level: str,
    client: "anthropic.AsyncAnthropic",
) -> list[str]:
    """Two-stage CF analysis: macro identification → per-macro CF classification."""
    macro_lines = "\n".join(
        f"- {macro}: {desc}" for macro, desc in _MACRO_CATEGORIES.items()
    )
    stage1_prompt = _prompts.cf_stage1.render(
        combined=combined,
        macro_lines=macro_lines,
    )

    try:
        response = await client.messages.create(
            model=settings.DRILL_MODEL,
            max_tokens=128,
            messages=[{"role": "user", "content": stage1_prompt}],
        )
        raw = response.content[0].text
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            return []
        identified_macros = [
            m for m in data.get("categories", []) if m in _MACRO_CATEGORIES
        ]
    except Exception as exc:
        logger.error(f"[lesson_analyzer] CF stage 1 error: {exc}")
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
        prompt = _prompts.cf_stage2.render(
            combined=combined,
            cf_lines=cf_lines,
        )
        try:
            resp = await client.messages.create(
                model=settings.DRILL_MODEL,
                max_tokens=128,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text
            d = parse_llm_json(raw)
            if not isinstance(d, dict):
                return []
            valid = {cf.code for cf in cfs}
            return [c for c in d.get("functions", []) if c in valid]
        except Exception as exc:
            logger.error(f"[lesson_analyzer] CF stage 2 ({macro}) error: {exc}")
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
        await taxonomy.ensure_loaded()
        profile = await get_profile(lesson.student_id) if lesson.student_id else None
        cefr_level = profile.cefr_estimate if profile else "A0"
        client = get_async_client()

        # Phase 1: aggregate per-activity events
        gp_correct, gp_errors, combined = await _collect_activity_events(lesson)

        # Phase 2: CF two-stage analysis
        cf_codes: list[str] = []
        if combined.strip():
            cf_codes = await _analyze_cfs_staged(combined, cefr_level, client)

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
            f"[lesson_analyzer] lesson {lesson.id}: "
            f"{len(gp_correct)} correct, {len(gp_errors)} errors, {len(cf_codes)} CFs"
        )
    except Exception as exc:
        logger.error(f"[lesson_analyzer] analyze_lesson error: {exc}")
