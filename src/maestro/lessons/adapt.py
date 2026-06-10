"""Lesson framing adaptation for bank-assembled lessons.

One small LLM call that personalizes the *framing* of a bank-assembled
lesson — title, description, overview/intro narrative — using the student's
persona, storyline, and recent lessons. It receives only metadata about the
selected content (scenario, grammar labels, CF labels), never the exercise
texts themselves, so it is structurally unable to alter bank material or
answer keys.

Failure is always graceful: callers fall back to scenario label/description.
"""

from __future__ import annotations

import logging
from typing import Optional

from maestro.config import settings
from maestro.lessons.sections import (
    section_recent_lessons,
    section_scenario,
    section_storyline,
    section_student,
    pick_persona_lines,
)
from maestro.llm import llm_messages_create
from maestro.language import get_language_config
from maestro.models import (
    CallType,
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    LearningProfile,
    Lesson,
)
from maestro.utils import parse_llm_json

logger = logging.getLogger(__name__)

_ADAPT_SYSTEM = """\
You write the framing for a {language_name} lesson whose exercise content is \
already fixed. You are given the student's context and the lesson's scenario, \
grammar points, and communicative functions.

Return ONLY a JSON object:
{{
  "topic_title": "A creative {language_name} title for this lesson (3-8 words)",
  "topic_description": "1-2 sentences in English describing the specific situation covered, personalised to the student where natural",
  "overview": "2-3 sentences in {language_name} ({cefr_level} level): what this lesson covers and what the student will gain. Thread in the storyline/recent lessons where natural — never contradict them."
}}

Do not invent exercise content, vocabulary lists, or grammar explanations — \
framing only."""


def build_adapt_prompt(
    *,
    cefr_level: str,
    scenario: CurriculumScenario,
    depth: int,
    profile: Optional[LearningProfile],
    grammar_gps: list[GrammarPoint],
    speaking_cfs: list[CommunicativeFunction],
    lesson_context: str = "",
    archetype: str = "",
    recent_lessons: list[Lesson] | None = None,
    storyline: str = "",
    stale: bool = False,
    rng=None,
) -> str:
    """Assemble the user prompt — reuses the planner's section builders."""
    import random as _random

    persona_lines = pick_persona_lines(
        profile.persona if profile else None, rng=rng or _random
    )
    lines = []
    if archetype:
        lines.append(f"<archetype>{archetype}</archetype>")
    if grammar_gps:
        gp_lines = "\n".join(f"  - {gp.label}" for gp in grammar_gps)
        lines.append(f"<grammar_targets>\n{gp_lines}\n</grammar_targets>")
    if speaking_cfs:
        cf_lines = "\n".join(f"  - {cf.label}" for cf in speaking_cfs)
        lines.append(f"<speaking_functions>\n{cf_lines}\n</speaking_functions>")

    sections = [
        section_student(
            cefr_level=cefr_level,
            persona_lines=persona_lines,
            lesson_context=lesson_context,
            profile=profile,
        ),
        section_storyline(storyline, stale=stale),
        section_recent_lessons(recent_lessons or []),
        section_scenario(scenario, depth),
        *lines,
    ]
    return "\n\n".join(s for s in sections if s)


async def adapt_lesson_framing(
    *,
    language: str,
    cefr_level: str,
    scenario: CurriculumScenario,
    depth: int,
    profile: Optional[LearningProfile],
    grammar_gps: list[GrammarPoint],
    speaking_cfs: list[CommunicativeFunction],
    lesson_context: str = "",
    archetype: str = "",
    recent_lessons: list[Lesson] | None = None,
    storyline: str = "",
    stale: bool = False,
    lesson_id=None,
    student_id=None,
) -> dict | None:
    """Return {"topic_title", "topic_description", "overview"} or None on failure."""
    lang_cfg = get_language_config(language)
    prompt = build_adapt_prompt(
        cefr_level=cefr_level,
        scenario=scenario,
        depth=depth,
        profile=profile,
        grammar_gps=grammar_gps,
        speaking_cfs=speaking_cfs,
        lesson_context=lesson_context,
        archetype=archetype,
        recent_lessons=recent_lessons,
        storyline=storyline,
        stale=stale,
    )
    try:
        response = await llm_messages_create(
            model=settings.ADAPTATION_MODEL,
            max_tokens=1000,
            system=_ADAPT_SYSTEM.format(
                language_name=lang_cfg.name, cefr_level=cefr_level
            ),
            messages=[{"role": "user", "content": prompt}],
            entity_id=lesson_id,
            call_type=CallType.LESSON_ADAPT,
            student_id=student_id,
        )
        result = parse_llm_json(response.content[0].text)
    except Exception:
        logger.exception("lesson adaptation failed", extra={"lesson_id": str(lesson_id)})
        return None

    if not isinstance(result, dict):
        logger.warning("lesson adaptation: unparseable response")
        return None
    framing = {
        key: str(result.get(key) or "").strip()
        for key in ("topic_title", "topic_description", "overview")
    }
    if not any(framing.values()):
        return None
    return framing
