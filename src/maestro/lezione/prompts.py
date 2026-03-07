"""Prompt construction for lesson content generation."""

from __future__ import annotations

import json
from typing import Optional

from maestro.config import settings
from maestro.models import (
    LearningProfile,
    GrammarPoint,
    CommunicativeFunction,
    CurriculumScenario,
    ExerciseType,
)
from maestro.prompts import planner as _prompts
from maestro.lezione.slots import _READING_WORD_COUNT, _READING_QUESTION_COUNT


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
) -> str:
    """Build the complete prompt string for lesson content generation.

    Returns the assembled prompt text ready to send to the LLM.
    """
    reading_word_count = _READING_WORD_COUNT.get(cefr_level, 150)
    depth_description = scenario.depths[depth - 1] if depth <= len(scenario.depths) else scenario.depths[-1]

    lang = settings.TARGET_LANGUAGE_NAME
    parts: list[str] = [
        _prompts.lesson_content_header.render(target_language=lang),
        f"Student CEFR level: {cefr_level}",
        f'Curriculum scenario: "{scenario.label}" (depth {depth})',
        f"Depth focus: {depth_description}",
    ]

    # Persona
    if profile and profile.persona:
        persona_parts = []
        if profile.persona.tags:
            persona_parts.append(f"Student description: {', '.join(profile.persona.tags)}")
        if profile.persona.interests:
            persona_parts.append(f"Student interests: {', '.join(profile.persona.interests)}")
        if profile.persona.background:
            persona_parts.append(f"Language background: {profile.persona.background}")
        if profile.persona.goal:
            persona_parts.append(f"Learning goal: {profile.persona.goal}")
        if persona_parts:
            parts.append("\n".join(persona_parts))

    if profile and profile.description:
        parts.append(f"Student profile: {profile.description}")

    if grammar_gps:
        gp_lines = []
        for gp in grammar_gps:
            gp_errors = profile.grammar_error_counts.get(gp.code, 0) if profile else 0
            gp_correct = profile.grammar_correct_counts.get(gp.code, 0) if profile else 0
            gp_lines.append(
                f"  - {gp.label} ({gp.code}) — {gp.description}\n"
                f"    Performance: {gp_correct} correct, {gp_errors} errors"
            )
        parts.append("Grammar activity points:\n" + "\n".join(gp_lines))

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
                f"label: {spec['gp_label']}, "
                f"description: {spec['gp_description']}"
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
                f"Category: {cf.macro_category}",
            ]
            if cf_examples:
                cf_block.append("Examples: " + "; ".join(cf_examples))
            if cf_patterns:
                cf_block.append("Patterns: " + "; ".join(cf_patterns))
            cf_lines_all.append("\n".join(cf_block))
        parts.append("\n\n".join(cf_lines_all))

    # Build the JSON schema description
    motivation_lang = "English" if cefr_level in ("A1", "A2") else lang
    schema: dict = {
        "topic_title": f"A creative {lang} title for this lesson (3-8 words)",
        "topic_description": "1-2 sentences describing the specific situation covered",
        "overview": f"2-3 sentences in {lang}: what this lesson covers and what the student will gain",
    }
    if grammar_gps:
        schema["grammar_motivations"] = [
            {
                "code": gp.code,
                "text": f"1-2 sentences in {motivation_lang}: why {gp.label} matters in real conversation",
            }
            for gp in grammar_gps
        ]
    if drill_specs:
        example_drills = []
        for spec in drill_specs:
            if spec["exercise_type"] in (ExerciseType.FILL_BLANK, ExerciseType.ERROR_CORRECTION):
                example_drills.append({
                    "grammar_point_code": spec["grammar_point_code"],
                    "items": [{"prompt": "...", "correct_answer": "..."}, "... 10 items total"],
                })
            else:
                example_drills.append({
                    "grammar_point_code": spec["grammar_point_code"],
                    "prompt": "...",
                    "correct_answer": None,
                    "distractors": [],
                })
        schema["drills"] = example_drills
    if reading_count > 0:
        q_labels = [f"question {i + 1}" for i in range(_READING_QUESTION_COUNT)]
        a_labels = [f"answer {i + 1}" for i in range(_READING_QUESTION_COUNT)]
        schema["readings"] = [
            {
                "text": f"{lang} reading text (~{reading_word_count} words at {cefr_level} level) on the lesson topic. Must be grammatically correct and natural.",
                "questions": q_labels,
                "answers": a_labels,
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
                "prompt": f"2-3 sentence {lang} speaking prompt asking the student to practise {cf.label}"
            }
            for cf in speaking_cfs
        ]

    parts.append(
        _prompts.lesson_content_footer.render(
            target_language=lang,
            target_language_code=settings.TARGET_LANGUAGE,
            schema_json=json.dumps(schema, indent=2, ensure_ascii=False),
            reading_count=reading_count,
            speaking_count=len(speaking_cfs),
            grammar_count=len(grammar_gps),
        )
    )

    return "\n\n".join(parts)
