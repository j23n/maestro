"""Prompt assembly for lesson content generation.

Thin orchestrator: stochastic decisions live here (persona-field sampling),
while pure section formatting is delegated to `sections.py` and the JSON
output shape to `output_schema.py`. Universal instructions (lesson principles,
drill rules, output format) live in the YAML system prompt.
"""

from __future__ import annotations

import random
from typing import Optional

from maestro.language import get_language_config
from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    LearningProfile,
    Lesson,
)
from maestro.prompts import (
    planner as _prompts,
    span_tagging_block as _stb,
    json_output_block as _job,
)
from maestro.lessons.output_schema import build_output_schema
from maestro.lessons.sections import (
    pick_persona_lines,
    section_drills,
    section_grammar_targets,
    section_lesson_shape,
    section_output_schema,
    section_recent_lessons,
    section_scenario,
    section_speaking,
    section_student,
)


def build_lesson_content_system(language: str) -> str:
    """Return the system prompt for lesson content generation."""
    lang_cfg = get_language_config(language)
    return _prompts.lesson_content_system.render_system(
        target_language=lang_cfg.name,
        json_output=_job(),
        span_tagging=_stb(lang_cfg.name, lang_cfg.code),
    )


_ARCHETYPE_TEMPLATES = {
    "introduction": _prompts.archetype_introduction,
    "consolidation": _prompts.archetype_consolidation,
    "application": _prompts.archetype_application,
}


def build_lesson_content_prompt(
    cefr_level: str,
    scenario: CurriculumScenario,
    depth: int,
    profile: Optional[LearningProfile],
    grammar_gps: list[GrammarPoint],
    drill_specs: list[dict],
    listening_count: int,
    reading_count: int,
    include_writing: bool,
    speaking_cfs: list[CommunicativeFunction],
    lesson_context: str = "",
    archetype: str = "",
    recent_lessons: list[Lesson] | None = None,
    *,
    language: str,
) -> str:
    """Assemble the XML-tagged user prompt for lesson content generation."""
    lang_cfg = get_language_config(language)
    persona_lines = pick_persona_lines(profile.persona if profile else None, rng=random)
    archetype_block = (
        _ARCHETYPE_TEMPLATES[archetype].render()
        if archetype in _ARCHETYPE_TEMPLATES
        else ""
    )

    schema = build_output_schema(
        language_name=lang_cfg.name,
        cefr_level=cefr_level,
        drill_specs=drill_specs,
        listening_count=listening_count,
        reading_count=reading_count,
        include_writing=include_writing,
        speaking_cfs=speaking_cfs,
    )

    sections = [
        section_student(
            cefr_level=cefr_level,
            persona_lines=persona_lines,
            lesson_context=lesson_context,
            profile=profile,
        ),
        section_recent_lessons(recent_lessons or []),
        section_scenario(scenario, depth),
        section_lesson_shape(
            archetype_block=archetype_block,
            listening_count=listening_count,
            reading_count=reading_count,
            drill_count=len(drill_specs),
            speaking_count=len(speaking_cfs),
            include_writing=include_writing,
        ),
        section_grammar_targets(grammar_gps, profile),
        section_drills(drill_specs),
        section_speaking(speaking_cfs),
        section_output_schema(schema),
    ]
    return "\n\n".join(s for s in sections if s)
