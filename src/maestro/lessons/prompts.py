"""Prompt construction for lesson content generation."""

from __future__ import annotations

import json
import random
from typing import Optional

from maestro.language import get_language_config
from maestro.learning.mastery import mastery_label
from maestro.models import (
    LearningProfile,
    GrammarPoint,
    CommunicativeFunction,
    CurriculumScenario,
    ExerciseType,
    Lesson,
)
from maestro.prompts import (
    planner as _prompts,
    span_tagging_block as _stb,
    json_output_block as _job,
)
from maestro.lessons.slots import _READING_WORD_COUNT, _READING_QUESTION_COUNT


def build_lesson_content_system(language: str) -> str:
    """Return the system prompt for lesson content generation."""
    lang_cfg = get_language_config(language)
    return _prompts.lesson_content_system.render_system(
        target_language=lang_cfg.name,
        json_output=_job(),
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
    reading_count: int,
    include_writing: bool,
    speaking_cfs: list[CommunicativeFunction],
    lesson_context: str = "",
    archetype: str = "",
    recent_lessons: list[Lesson] | None = None,
    *,
    language: str,
) -> str:
    """Build the complete prompt string for lesson content generation.

    Returns the assembled prompt text ready to send to the LLM.
    """
    reading_word_count = _READING_WORD_COUNT.get(cefr_level, 150)
    depth_description = (
        scenario.depths[depth - 1]
        if depth <= len(scenario.depths)
        else scenario.depths[-1]
    )

    lang_cfg = get_language_config(language)
    lang = lang_cfg.name
    parts: list[str] = [
        _prompts.lesson_content_header.render(target_language=lang),
        f"Student CEFR level: {cefr_level}",
        f'Curriculum scenario: "{scenario.label}" (depth {depth})',
        f"Depth focus: {depth_description}",
    ]

    if archetype and archetype in _ARCHETYPE_TEMPLATES:
        parts.append(_ARCHETYPE_TEMPLATES[archetype].render())

    # Persona — include in ~70% of lessons; when included, pick 1-2 fields
    if profile and profile.persona and random.random() < 0.7:
        field_map = {
            "background": ("Student background", profile.persona.background),
            "interests": ("Student interests", profile.persona.interests),
            "goal": ("Learning goal", profile.persona.goal),
        }
        available = [k for k, (_, v) in field_map.items() if v]
        if available:
            pick_count = min(len(available), random.randint(1, 2))
            chosen = random.sample(available, pick_count)
            persona_parts = [f"{field_map[k][0]}: {field_map[k][1]}" for k in chosen]
            parts.append("\n".join(persona_parts))

    if lesson_context:
        parts.append(f"Lesson context requested by the student: {lesson_context}")

    lp = profile.active_progress if profile else None
    if lp and lp.description:
        parts.append(f"Student profile: {lp.description}")

    if recent_lessons:
        recent_lines = []
        for lesson in recent_lessons:
            title = lesson.topic_title or "(untitled)"
            desc = (lesson.topic_description or "").strip()
            meta_bits = []
            if lesson.scenario_slug:
                meta_bits.append(f"scenario: {lesson.scenario_slug}")
            if lesson.archetype:
                meta_bits.append(lesson.archetype)
            meta = f" ({', '.join(meta_bits)})" if meta_bits else ""
            recent_lines.append(f'  - "{title}" — {desc}{meta}')
        parts.append(
            "Recent lessons (avoid repeating these exact setups; "
            "optional callbacks welcome):\n" + "\n".join(recent_lines)
        )

    if grammar_gps:
        gp_lines = []
        for gp in grammar_gps:
            score = lp.grammar_mastery_scores.get(gp.code) if lp else None
            label = mastery_label(score)
            gp_lines.append(f"  - {gp.label} ({gp.code}) — mastery: {label}")
        parts.append(
            "Grammar activity points (calibrate drill difficulty to mastery: "
            "consolidated → vary contexts; developing → familiar frames; "
            "weak → scaffold with supportive contexts; new → brief explanation first):\n"
            + "\n".join(gp_lines)
        )

    if drill_specs:
        drill_lines = []
        for spec in drill_specs:
            rag_part = (
                f"\n  RAG excerpt: {spec['rag_excerpt'][:500]}"
                if spec.get("rag_excerpt")
                else ""
            )
            drill_lines.append(
                f"- grammar_point_code: {spec['grammar_point_code']}, "
                f"exercise_type: {spec['exercise_type']}, "
                f"label: {spec['gp_label']}"
                f"{rag_part}"
            )
        parts.append("Drills to generate:\n" + "\n".join(drill_lines))

    if speaking_cfs:
        cf_lines_all = []
        for cf in speaking_cfs:
            cf_examples = cf.examples[:3]
            cf_patterns = cf.patterns[:3]
            cf_block = [
                f"Speaking activity — Communicative function: {cf.label} ({cf.code})",
                f"Category: {cf.category}",
            ]
            if cf_examples:
                cf_block.append("Examples: " + "; ".join(cf_examples))
            if cf_patterns:
                cf_block.append("Patterns: " + "; ".join(cf_patterns))
            cf_lines_all.append("\n".join(cf_block))
        parts.append("\n\n".join(cf_lines_all))

    # Build the JSON schema description
    schema: dict = {
        "topic_title": f"A creative {lang} title for this lesson (3-8 words)",
        "topic_description": "1-2 sentences describing the specific situation covered",
        "overview": f"2-3 sentences in {lang}: what this lesson covers and what the student will gain",
    }
    if drill_specs:
        example_drills = []
        for spec in drill_specs:
            if spec["exercise_type"] in (
                ExerciseType.FILL_BLANK,
                ExerciseType.ERROR_CORRECTION,
            ):
                example_drills.append(
                    {
                        "grammar_point_code": spec["grammar_point_code"],
                        "items": [
                            {"prompt": "...", "correct_answer": "..."},
                            "... 10 items total",
                        ],
                    }
                )
            else:
                example_drills.append(
                    {
                        "grammar_point_code": spec["grammar_point_code"],
                        "prompt": "...",
                        "correct_answer": None,
                        "distractors": [],
                    }
                )
        schema["drills"] = example_drills
    if reading_count > 0:
        schema["readings"] = [
            {
                "text": (
                    f"{lang} reading text (~{reading_word_count} words at {cefr_level} level) "
                    f"on the lesson topic. Must be grammatically correct and natural. "
                    f"When the scenario fits a dialogue (café, station, hotel, shop, etc.), "
                    f"prefer a two-speaker exchange and mark each speaker turn with '— ' "
                    f"(em dash + space) at the start of its line — these get rendered with "
                    f"alternating voices in the audio."
                ),
                "questions": [
                    {"text": f"question {i + 1}", "correct_answer": f"answer {i + 1}"}
                    for i in range(_READING_QUESTION_COUNT)
                ],
            }
            for _ in range(reading_count)
        ]
    if include_writing:
        schema["writing"] = {
            "prompt": f"A {lang} writing prompt appropriate for {cefr_level} level on the topic"
        }
    if speaking_cfs:
        schema["speakings"] = [
            {
                "prompt": (
                    f"2-3 sentence {lang} speaking prompt asking the student to practise {cf.label}. "
                    f"If the prompt embeds a mini-dialogue for context, mark each speaker turn with "
                    f"'— ' (em dash + space) at the start of its line."
                )
            }
            for cf in speaking_cfs
        ]

    parts.append(
        _prompts.lesson_content_footer.render(
            target_language=lang,
            target_language_code=lang_cfg.code,
            schema_json=json.dumps(schema, indent=2, ensure_ascii=False),
            reading_count=reading_count,
            speaking_count=len(speaking_cfs),
            grammar_count=len(grammar_gps),
            span_tagging=_stb(lang, lang_cfg.code),
            json_output=_job(),
        )
    )

    return "\n\n".join(parts)
