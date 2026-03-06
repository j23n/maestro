"""Materialize LLM response dict into LessonActivity objects."""

from __future__ import annotations

import logging
from typing import Optional

from maestro.models import (
    LessonActivity,
    GrammarPoint,
    GrammarPointExplanation,
    GeneratedDrill,
    DrillItem,
    DrillTemplate,
    CommunicativeFunction,
    ItalianChunk,
)

logger = logging.getLogger(__name__)


async def materialize_activities(
    content: dict,
    grammar_gps: list[GrammarPoint],
    grammar_explanations: list[Optional[GrammarPointExplanation]],
    drill_specs: list[dict],
    drill_templates_used: list[DrillTemplate],
    speaking_cfs: list[CommunicativeFunction],
    include_writing: bool,
    reading_count: int,
    topic_title: str,
    scenario_slug: str,
    cefr_level: str,
    student_id,
) -> list[LessonActivity]:
    """Convert raw LLM content dict into ordered LessonActivity list.

    Creates GeneratedDrill documents for drill activities.
    Returns activities in pedagogical order:
    grammar -> reading -> drill -> speaking -> writing.
    """

    # --- Grammar activities ---
    grammar_activities: list[LessonActivity] = []
    grammar_motivations = content.get("grammar_motivations", [])
    for i, gp in enumerate(grammar_gps):
        exp = grammar_explanations[i] if i < len(grammar_explanations) else None
        if exp:
            explanation_content = exp.explanation
            grammar_title = exp.title or gp.label
        else:
            # Fallback: load chunk content directly
            if gp.chunk_ref:
                chunk = await ItalianChunk.find_one({"ref": gp.chunk_ref})
                explanation_content = chunk.content if chunk else gp.description
            else:
                explanation_content = gp.description
            grammar_title = gp.label
        motivation = grammar_motivations[i].get("text") if i < len(grammar_motivations) and isinstance(grammar_motivations[i], dict) else None
        grammar_activities.append(LessonActivity(
            type="grammar",
            title=f"Grammatica: {grammar_title}",
            description=f"Ripassa la regola grammaticale: {gp.label}",
            duration_minutes=3,
            content=explanation_content,
            why_important=motivation,
            grammar_point_code=gp.code,
        ))

    # --- Reading activities ---
    reading_activities: list[LessonActivity] = []
    llm_readings = content.get("readings", [])
    for i, reading_data in enumerate(llm_readings[:reading_count]):
        if not isinstance(reading_data, dict):
            continue
        reading_activities.append(LessonActivity(
            type="reading",
            title=f"Lettura {i + 1}" if reading_count > 1 else "Lettura",
            description=f"Leggi un testo su: {topic_title}",
            duration_minutes=5,
            content=reading_data.get("text", ""),
            questions=reading_data.get("questions", []),
            correct_answers=reading_data.get("answers", []),
        ))

    # --- Drill activities ---
    drill_activities: list[LessonActivity] = []
    llm_drills = content.get("drills", [])
    logger.info(f"[materialize] materialising {len(drill_specs)} drills ({len(llm_drills)} returned by LLM)")
    for i, (spec, template) in enumerate(zip(drill_specs, drill_templates_used)):
        drill_data = llm_drills[i] if i < len(llm_drills) else None
        if not drill_data:
            logger.warning(f"[materialize] missing drill data at index {i} for {spec['grammar_point_code']}")
            continue
        exercise_type = spec["exercise_type"]
        if exercise_type in ("fill_blank", "error_correction"):
            raw_items = drill_data.get("items") or []
            items = [
                DrillItem(prompt=it["prompt"], correct_answer=it.get("correct_answer"))
                for it in raw_items
                if isinstance(it, dict) and it.get("prompt")
            ]
            drill = GeneratedDrill(
                student_id=student_id,
                template=template,
                grammar_point_code=spec["grammar_point_code"],
                cefr_level=cefr_level,
                exercise_type=exercise_type,
                prompt="",
                correct_answer=None,
                distractors=[],
                items=items,
                scenario_slug=scenario_slug,
                chunk_ref=spec.get("chunk_ref"),
            )
        else:  # free_form
            drill = GeneratedDrill(
                student_id=student_id,
                template=template,
                grammar_point_code=spec["grammar_point_code"],
                cefr_level=cefr_level,
                exercise_type=exercise_type,
                prompt=drill_data.get("prompt", ""),
                correct_answer=None,
                distractors=[],
                scenario_slug=scenario_slug,
                chunk_ref=spec.get("chunk_ref"),
            )
        await drill.insert()
        logger.debug(f"[materialize] drill inserted: {drill.id} ({exercise_type}, {spec['grammar_point_code']})")
        drill_activities.append(LessonActivity(
            type="drill",
            title=f"Esercizio: {spec['gp_label']}",
            description=f"{exercise_type.replace('_', ' ').title()} · {spec['gp_label']}",
            duration_minutes=3,
            drill_id=drill.id,
        ))

    # --- Speaking activities ---
    speaking_activities: list[LessonActivity] = []
    llm_speakings = content.get("speakings", [])
    for i, cf in enumerate(speaking_cfs):
        speaking_data = llm_speakings[i] if i < len(llm_speakings) else None
        prompt_text = speaking_data.get("prompt", "") if isinstance(speaking_data, dict) else ""
        speaking_activities.append(LessonActivity(
            type="speaking",
            title=f"Parlare: {cf.label}",
            description=f"Pratica: {cf.label}",
            duration_minutes=3,
            content=prompt_text,
        ))

    # --- Writing activities ---
    writing_activities: list[LessonActivity] = []
    if include_writing and content.get("writing"):
        writing_data = content["writing"]
        writing_activities.append(LessonActivity(
            type="writing",
            title="Scrittura",
            description=f"Scrivi un testo su: {topic_title}",
            duration_minutes=8,
            content=writing_data.get("prompt", ""),
        ))

    # Pedagogical order: grammar x N -> readings x N -> drills x N -> speakings x N -> writing x N
    return grammar_activities + reading_activities + drill_activities + speaking_activities + writing_activities
