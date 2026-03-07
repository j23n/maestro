"""End-of-lesson learning signal extraction.

Called once when a lesson is marked completed. Analyzes all free-text
student responses in a single batch, with full lesson context available.

Phases:
  A — Drill GP outcomes (high-confidence, no LLM needed)
  B — Free-text GP analysis (current-level candidates + lesson GPs)
  C — CF analysis (two-stage: macro → per-macro parallel)
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from maestro.models import (
    GeneratedDrill,
    GrammarPoint,
    LearningEvent,
    ActivityType,
    ActivityStatus,
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

_MAX_GP_CANDIDATES = 80


def _collect_free_texts(lesson: "Lesson") -> list[str]:
    """Gather all student free-text answers from completed activities."""
    texts: list[str] = []
    for activity in lesson.activities:
        if activity.status != ActivityStatus.COMPLETED or not activity.result:
            continue
        if activity.type in (ActivityType.WRITING, ActivityType.SPEAKING):
            answer = activity.result.get("student_answer", "")
            if answer:
                texts.append(answer)
        elif activity.type == ActivityType.READING:
            answers = activity.result.get("student_answers", [])
            joined = " | ".join(a for a in answers if a)
            if joined:
                texts.append(joined)
        elif activity.type == ActivityType.DRILL:
            answer = activity.result.get("student_answer", "")
            if answer:
                texts.append(answer)
    return texts


async def _collect_drill_gp_outcomes(lesson: "Lesson") -> tuple[list[str], list[str], list[str]]:
    """Read already-scored drill activities. Returns (correct_codes, error_codes, all_gp_codes).

    Aggregates all attempts per grammar point: any error counts as an error,
    otherwise all-correct counts as correct. all_gp_codes includes every GP
    seen in the lesson (including skipped drills) for use as priority hints.
    """
    outcomes: dict[str, list[bool]] = {}  # gp_code → list of True/False outcomes
    all_gp_codes: list[str] = []
    for activity in lesson.activities:
        if activity.type != ActivityType.DRILL or not activity.drill_id:
            continue
        drill = await GeneratedDrill.get(activity.drill_id)
        if drill is None:
            continue
        code = drill.grammar_point_code
        if code not in outcomes:
            outcomes[code] = []
            all_gp_codes.append(code)
        if activity.result:
            if activity.result.get("correct") is True:
                outcomes[code].append(True)
            elif activity.result.get("correct") is False:
                outcomes[code].append(False)

    correct_codes: list[str] = []
    error_codes: list[str] = []
    for code, results in outcomes.items():
        if not results:
            continue
        if any(r is False for r in results):
            error_codes.append(code)
        else:
            correct_codes.append(code)
    return correct_codes, error_codes, all_gp_codes


async def _analyze_gps(
    combined: str,
    cefr_level: str,
    lesson_gp_codes: list[str],
    client: "anthropic.AsyncAnthropic",
) -> tuple[list[str], list[str]]:
    """Identify GP correct/error usage in combined student text."""
    candidates: dict[str, GrammarPoint] = {
        gp.code: gp
        for gp in taxonomy.grammar_points()
        if gp.cefr_level == cefr_level
    }
    for code in lesson_gp_codes:
        if code not in candidates:
            gp = next((g for g in taxonomy.grammar_points() if g.code == code), None)
            if gp:
                candidates[code] = gp
    candidate_list = list(candidates.values())[:_MAX_GP_CANDIDATES]

    gp_lines = "\n".join(f"{gp.code}: {gp.label}" for gp in candidate_list)
    lesson_priority = ""
    if lesson_gp_codes:
        lesson_priority = _prompts.gps_priority_block.render(
            lesson_gp_codes=", ".join(lesson_gp_codes)
        )

    prompt = _prompts.analyze_gps.render(
        target_language=settings.TARGET_LANGUAGE_NAME,
        cefr_level=cefr_level,
        combined=combined,
        lesson_priority=lesson_priority,
        gp_lines=gp_lines,
    )

    try:
        response = await client.messages.create(
            model=settings.DRILL_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        data = parse_llm_json(raw)
        if not isinstance(data, dict):
            logger.error(f"[lesson_analyzer] _analyze_gps bad response: {raw[:200]}")
            return [], []
        valid = {gp.code for gp in candidate_list}
        correct = [c for c in data.get("grammar_correct", []) if c in valid]
        errors = [c for c in data.get("grammar_errors", []) if c in valid]
        return correct, errors
    except Exception as exc:
        logger.error(f"[lesson_analyzer] _analyze_gps error: {exc}")
        return [], []


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
            cf for cf in taxonomy.comm_functions()
            if cf.macro_category == macro and cf.cefr_level == cefr_level
        ]
        if not cfs:
            return []
        cf_lines = "\n".join(
            f"{cf.code}: {cf.label}" + (f" — {', '.join(cf.patterns[:2])}" if cf.patterns else "")
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
    """Run full end-of-lesson analysis and update the learning profile."""
    try:
        await taxonomy.ensure_loaded()
        profile = await get_profile(lesson.student_id) if lesson.student_id else None
        cefr_level = profile.cefr_estimate if profile else "A0"
        client = get_async_client()

        # Phase A: drill outcomes (high-confidence, no LLM)
        drill_correct, drill_errors, all_drill_gp_codes = await _collect_drill_gp_outcomes(lesson)

        # Phase B: free-text GP analysis
        texts = _collect_free_texts(lesson)
        combined = "\n---\n".join(texts) if texts else ""
        lesson_gp_codes = list(dict.fromkeys(all_drill_gp_codes))

        gp_correct: list[str] = []
        gp_errors: list[str] = []
        if combined.strip():
            gp_correct, gp_errors = await _analyze_gps(
                combined, cefr_level, lesson_gp_codes, client
            )

        # Phase C: CF two-stage analysis
        cf_codes: list[str] = []
        if combined.strip():
            cf_codes = await _analyze_cfs_staged(combined, cefr_level, client)

        # Merge: drill outcomes take precedence over free-text GP findings
        all_correct = list(dict.fromkeys(
            drill_correct + [c for c in gp_correct if c not in drill_errors]
        ))
        all_errors = list(dict.fromkeys(
            drill_errors + [c for c in gp_errors if c not in drill_correct]
        ))

        event = LearningEvent(
            student_id=lesson.student_id,
            grammar_correct=all_correct,
            grammar_errors=all_errors,
            functions_performed=cf_codes,
        )
        await event.insert()
        await update_profile(event)

        logger.info(
            f"[lesson_analyzer] lesson {lesson.id}: "
            f"{len(all_correct)} correct, {len(all_errors)} errors, {len(cf_codes)} CFs"
        )
    except Exception as exc:
        logger.error(f"[lesson_analyzer] analyze_lesson error: {exc}")
