"""
Per-lesson summary + storyline evolution. Together these keep each student's
narrative arc coherent across lessons.

After a non-A0 lesson completes, ``maybe_evolve_storyline`` runs as a
background task and:

  1. Distills a 1-2 sentence student-specific summary (lesson_context +
     writing/speaking responses + scenario) via Haiku and persists it on the
     Lesson. The render code in <recent_lessons> prefers this over the
     planner-supplied title/description, so personalisation reaches every
     subsequent lesson — not just the one in 5 that triggers a storyline
     evolve.
  2. Increments the per-language evolve counter; when it crosses
     ``STORYLINE_EVOLVE_EVERY_N_LESSONS`` (atomically guarded against
     concurrent completions) it generates a fresh long-arc storyline
     paragraph from the persona, prior storyline, and recent lessons.

Manual storyline regeneration is also exposed via /profile/storyline/regenerate.
"""

from __future__ import annotations

import logging
from typing import Iterable

from maestro.config import settings
from maestro.language import get_language_config
from maestro.llm import llm_messages_create
from maestro.models import (
    ActivityStatus,
    ActivityType,
    CallType,
    LearningProfile,
    Lesson,
    LessonStatus,
    StudentPersona,
)
from maestro.prompts import planner as _prompts
from maestro.utils import utcnow
from pymongo import ReturnDocument

logger = logging.getLogger(__name__)

_STORYLINE_MAX_CHARS = 800
_SUMMARY_MAX_CHARS = 280


def _render_persona_block(persona: StudentPersona | None) -> str:
    if not persona:
        return "Student persona: (none recorded)"
    bits: list[str] = []
    if persona.background:
        bits.append(f"Background: {persona.background}")
    if persona.interests:
        bits.append(f"Interests: {persona.interests}")
    if persona.goal:
        bits.append(f"Goal: {persona.goal}")
    if not bits:
        return "Student persona: (none recorded)"
    return "Student persona:\n" + "\n".join(f"  - {b}" for b in bits)


def _render_recent_lessons_block(recent_lessons: list[Lesson]) -> str:
    if not recent_lessons:
        return "  (no completed lessons yet)"
    # Oldest first so the LLM reads chronologically
    lines: list[str] = []
    for lesson in reversed(recent_lessons):
        summary = (getattr(lesson, "summary", "") or "").strip()
        if summary:
            lines.append(f"  - {summary}")
            continue
        title = (lesson.topic_title or "(untitled)").strip()
        desc = (lesson.topic_description or "").strip()
        meta_bits: list[str] = []
        if lesson.scenario_slug:
            meta_bits.append(f"scenario: {lesson.scenario_slug}")
        if lesson.archetype:
            meta_bits.append(lesson.archetype)
        meta = f" ({', '.join(meta_bits)})" if meta_bits else ""
        lines.append(f'  - "{title}" — {desc}{meta}')
    return "\n".join(lines)


def _clean_storyline_text(raw: str) -> str:
    """Trim whitespace + surrounding quotes, hard-cap to _STORYLINE_MAX_CHARS.

    The system prompt forbids markdown; if the model emits any anyway, the
    storyline is user-visible and editable, so we trust the prompt and let
    the user regenerate or fix on the profile page.
    """
    text = raw.strip().strip("\"“”‘’'")
    if len(text) > _STORYLINE_MAX_CHARS:
        text = text[:_STORYLINE_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return text


def _clean_summary_text(raw: str) -> str:
    text = raw.strip().strip("\"“”‘’'")
    if len(text) > _SUMMARY_MAX_CHARS:
        text = text[:_SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return text


def _collect_student_signals(lesson: Lesson) -> list[tuple[str, str]]:
    """Pull free-form student input out of completed activities.

    Returns a list of ``(label, text)`` pairs. Empty/skipped activities are
    ignored. When this is empty AND lesson_context is empty, the summarizer
    has nothing student-specific to distil and short-circuits to "" so the
    renderer falls back to scenario metadata.
    """
    signals: list[tuple[str, str]] = []
    if lesson.lesson_context:
        signals.append(
            ("Student's note at lesson start", lesson.lesson_context.strip())
        )

    activities: Iterable = lesson.activities or []
    for act in activities:
        if act.status != ActivityStatus.COMPLETED:
            continue
        result = act.result or {}
        if act.type == ActivityType.WRITING:
            answer = (result.get("student_answer") or "").strip()
            if answer:
                prompt = (act.content or "").strip()
                label = f"Writing (prompt: {prompt})" if prompt else "Writing"
                signals.append((label, answer))
        elif act.type == ActivityType.SPEAKING:
            transcript = (
                result.get("recognized_text") or result.get("student_answer") or ""
            ).strip()
            if transcript:
                prompt = (act.content or "").strip()
                label = f"Speaking (prompt: {prompt})" if prompt else "Speaking"
                signals.append((label, transcript))
    return signals


def _render_signals_block(signals: list[tuple[str, str]]) -> str:
    if not signals:
        return "  (no student-written or spoken responses)"
    return "\n".join(f"  - {label}:\n      {text}" for label, text in signals)


async def summarize_lesson(lesson: Lesson) -> str:
    """Distill a 1-2 sentence student-specific recap of this lesson via Haiku.

    Inputs are the student's own contributions (lesson_context, writing,
    speaking) plus scenario metadata. Returns "" if there are no
    student-specific signals (the renderer falls back to title/description),
    or on LLM failure.
    """
    signals = _collect_student_signals(lesson)
    if not signals:
        return ""

    lang_cfg = get_language_config(lesson.language)
    scenario_lines = []
    if lesson.topic_title:
        scenario_lines.append(f"Title: {lesson.topic_title}")
    if lesson.topic_description:
        scenario_lines.append(f"Description: {lesson.topic_description}")
    if lesson.scenario_slug:
        scenario_lines.append(f"Scenario: {lesson.scenario_slug}")
    if lesson.archetype:
        scenario_lines.append(f"Archetype: {lesson.archetype}")
    scenario_block = "\n".join(scenario_lines) if scenario_lines else "(none)"

    system = _prompts.lesson_summary.render_system() or ""
    user = _prompts.lesson_summary.render(
        target_language=lang_cfg.name,
        scenario_block=scenario_block,
        signals_block=_render_signals_block(signals),
    )

    try:
        response = await llm_messages_create(
            model=settings.STORYLINE_MODEL,
            max_tokens=200,
            system=system,
            messages=[{"role": "user", "content": user}],
            entity_id=lesson.id,
            call_type=CallType.LESSON_SUMMARY,
            student_id=lesson.student_id,
        )
    except Exception:
        logger.warning("lesson summary: LLM call failed", exc_info=True)
        return ""

    try:
        raw = response.content[0].text if response.content else ""
    except Exception:
        logger.warning("lesson summary: unexpected response shape", exc_info=True)
        return ""

    return _clean_summary_text(raw)


async def evolve_storyline(
    *,
    old_storyline: str,
    persona: StudentPersona | None,
    recent_lessons: list[Lesson],
    language: str,
    student_id,
    profile_id,
) -> str:
    """Produce a fresh 3-5 sentence storyline paragraph via Haiku.

    Returns ``old_storyline`` unchanged if the LLM call fails. If there is
    neither an old storyline nor any recent lessons, returns "" (no call).
    """
    if not old_storyline.strip() and not recent_lessons:
        return ""

    lang_cfg = get_language_config(language)
    system = _prompts.storyline_evolve.render_system() or ""
    user = _prompts.storyline_evolve.render(
        target_language=lang_cfg.name,
        persona_block=_render_persona_block(persona),
        prior_storyline=old_storyline.strip() or "(none yet)",
        recent_lessons_block=_render_recent_lessons_block(recent_lessons),
    )

    try:
        response = await llm_messages_create(
            model=settings.STORYLINE_MODEL,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
            entity_id=profile_id,
            call_type=CallType.STORYLINE_EVOLVE,
            student_id=student_id,
        )
    except Exception:
        logger.warning("storyline evolve: LLM call failed", exc_info=True)
        return old_storyline

    try:
        raw = response.content[0].text if response.content else ""
    except Exception:
        logger.warning("storyline evolve: unexpected response shape", exc_info=True)
        return old_storyline

    cleaned = _clean_storyline_text(raw)
    if not cleaned:
        return old_storyline
    return cleaned


async def _fetch_recent_completed(
    student_id, language: str, limit: int = 5
) -> list[Lesson]:
    """Return the student's most recent completed lessons in this language."""
    if student_id is None:
        return []
    return await Lesson.find(
        {
            "student_id": student_id,
            "language": language,
            "status": LessonStatus.COMPLETED.value,
        },
        sort=[("created_at", -1)],
        limit=limit,
    ).to_list()


async def maybe_evolve_storyline(lesson: Lesson) -> None:
    """Post-completion background hook. Two responsibilities:

      1. Distill a per-lesson summary and persist it on the Lesson, so
         subsequent <recent_lessons> blocks reflect what the student
         actually did rather than the planner's title/description.
      2. Increment the per-language evolve counter; when the threshold is
         crossed (atomically guarded), generate a fresh long-arc storyline.

    Fire-and-forget: all exceptions are logged but never raised. Skips A0 and
    anonymous lessons at the caller in lifecycle.py, but also defensive here.
    """
    try:
        if lesson.cefr_at_start == "A0" or lesson.student_id is None:
            return

        # --- Per-lesson summary (independent of storyline cadence) ---
        try:
            summary = await summarize_lesson(lesson)
        except Exception:
            logger.exception(
                "lesson summary failed",
                extra={"lesson_id": str(lesson.id)},
            )
            summary = ""
        if summary:
            try:
                await Lesson.find_one(Lesson.id == lesson.id).update(
                    {"$set": {"summary": summary}}
                )
                lesson.summary = summary  # so the evolver below reads it
            except Exception:
                logger.exception(
                    "lesson summary persist failed",
                    extra={"lesson_id": str(lesson.id)},
                )

        lang = lesson.language
        profile = await LearningProfile.find_one(
            LearningProfile.student_id == lesson.student_id
        )
        if profile is None:
            return

        coll = LearningProfile.get_pymongo_collection()

        # Atomic counter increment; return updated doc so we can read the counter.
        updated = await coll.find_one_and_update(
            {"_id": profile.id},
            {"$inc": {f"progress.{lang}.storyline_lessons_since_evolve": 1}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return

        counter = (
            updated.get("progress", {})
            .get(lang, {})
            .get("storyline_lessons_since_evolve", 0)
        )
        threshold = settings.STORYLINE_EVOLVE_EVERY_N_LESSONS
        if counter < threshold:
            return

        # Guard against concurrent triggers: only one writer will succeed.
        guarded = await coll.find_one_and_update(
            {
                "_id": profile.id,
                f"progress.{lang}.storyline_lessons_since_evolve": {"$gte": threshold},
            },
            {"$set": {f"progress.{lang}.storyline_lessons_since_evolve": 0}},
            return_document=ReturnDocument.AFTER,
        )
        if guarded is None:
            # Another completion already took the slot.
            return

        recent = await _fetch_recent_completed(lesson.student_id, lang, limit=5)
        lp = profile.progress.get(lang) if profile.progress else None
        old = lp.storyline if lp else ""

        new_text = await evolve_storyline(
            old_storyline=old,
            persona=profile.persona,
            recent_lessons=recent,
            language=lang,
            student_id=lesson.student_id,
            profile_id=profile.id,
        )
        if not new_text or new_text == old:
            return

        await coll.update_one(
            {"_id": profile.id},
            {
                "$set": {
                    f"progress.{lang}.storyline": new_text,
                    f"progress.{lang}.storyline_updated_at": utcnow(),
                }
            },
        )
        logger.info(
            "storyline auto-evolved",
            extra={
                "student_id": str(lesson.student_id),
                "language": lang,
                "lesson_id": str(lesson.id),
            },
        )
    except Exception:
        logger.exception(
            "storyline auto-evolve hook failed",
            extra={"lesson_id": str(getattr(lesson, "id", None))},
        )
