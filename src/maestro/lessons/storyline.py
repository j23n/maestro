"""
Storyline evolution: keeps each student's evolving 3-5 sentence "story so far"
coherent across lessons.

Two triggers update the storyline:
  1. Auto: every STORYLINE_EVOLVE_EVERY_N_LESSONS completed lessons, from the
     completion hook in lessons.lifecycle.
  2. Manual: the /profile/storyline/regenerate route.

The evolver reads raw Lesson metadata (title, description, scenario, archetype)
directly — no separate recap storage is needed because the planner already has
access to the last N completed lessons via _fetch_recent_lessons in planner.py.
"""

from __future__ import annotations

import logging
import re

from maestro.config import settings
from maestro.language import get_language_config
from maestro.llm import llm_messages_create
from maestro.models import (
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
    """Strip markdown, collapse whitespace, hard-trim to _STORYLINE_MAX_CHARS."""
    text = raw.strip()
    # Strip surrounding code fences and quotes
    text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    text = text.strip('"“”‘’')
    # Remove markdown headings/bullets at line starts
    text = re.sub(r"(?m)^[#>\-\*]\s+", "", text)
    # Strip bold/italic markers
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _STORYLINE_MAX_CHARS:
        text = text[:_STORYLINE_MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return text


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
    """Completion-hook entry point. Increments the counter and, if the threshold
    is reached, evolves the storyline and resets the counter atomically.

    Fire-and-forget: all exceptions are logged but never raised. Skips A0 and
    anonymous lessons at the caller in lifecycle.py, but also defensive here.
    """
    try:
        if lesson.cefr_at_start == "A0" or lesson.student_id is None:
            return

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
