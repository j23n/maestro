"""Materialize validated LessonContentResponse into LessonActivity objects."""

from __future__ import annotations

import logging
from typing import Optional

from maestro.models import (
    LessonActivity,
    GrammarPoint,
    GrammarExplanation,
    GeneratedDrill,
    DrillItem,
    CommunicativeFunction,
    GrammarChunk,
    ActivityType,
    ExerciseType,
)
from maestro.config import settings as _settings
from maestro.lezione.schemas import LessonContentResponse
from maestro.strings import t
from maestro.vocab.discover import lang_wrap

logger = logging.getLogger(__name__)


async def materialize_activities(
    content: LessonContentResponse,
    grammar_gps: list[GrammarPoint],
    grammar_explanations: list[Optional[GrammarExplanation]],
    drill_specs: list[dict],
    speaking_cfs: list[CommunicativeFunction],
    include_writing: bool,
    reading_count: int,
    topic_title: str,
    scenario_slug: str,
    cefr_level: str,
    student_id,
    listening_count: int = 0,
) -> list[LessonActivity]:
    """Convert raw LLM content dict into ordered LessonActivity list.

    Creates GeneratedDrill documents for drill activities.
    Returns activities in pedagogical order:
    grammar -> reading -> drill -> speaking -> writing.
    """

    # --- Grammar activities ---
    grammar_activities: list[LessonActivity] = []
    for i, gp in enumerate(grammar_gps):
        exp = grammar_explanations[i] if i < len(grammar_explanations) else None
        if exp:
            explanation_content = exp.explanation
            grammar_title = exp.title or gp.label
        else:
            # Fallback: load chunk content directly
            if gp.chunk_ref:
                chunk = await GrammarChunk.find_one({"ref": gp.chunk_ref})
                explanation_content = (
                    lang_wrap(chunk.content, _settings.TARGET_LANGUAGE)
                    if chunk
                    else gp.label
                )
            else:
                explanation_content = gp.label
            grammar_title = gp.label
        grammar_activities.append(
            LessonActivity(
                type=ActivityType.GRAMMAR,
                title=t("grammar_title", label=grammar_title),
                description=t("grammar_desc", label=gp.label),
                duration_minutes=3,
                content=explanation_content,
                grammar_point_code=gp.code,
            )
        )

    # --- Listening activities (audio comprehension) ---
    listening_activities: list[LessonActivity] = []
    for i, reading in enumerate(content.readings[:listening_count]):
        title = (
            t("listening_title_n", n=i + 1)
            if listening_count > 1
            else t("listening_title")
        )
        listening_activities.append(
            LessonActivity(
                type=ActivityType.LISTENING,
                title=title,
                description=t("listening_desc", topic=topic_title),
                duration_minutes=5,
                content=reading.text,
                questions=reading.questions,
                correct_answers=reading.answers,
            )
        )

    # --- Reading activities (text comprehension) ---
    reading_activities: list[LessonActivity] = []
    for i, reading in enumerate(
        content.readings[listening_count : listening_count + reading_count]
    ):
        title = (
            t("reading_title_n", n=i + 1) if reading_count > 1 else t("reading_title")
        )
        reading_activities.append(
            LessonActivity(
                type=ActivityType.READING,
                title=title,
                description=t("reading_desc", topic=topic_title),
                duration_minutes=5,
                content=reading.text,
                questions=reading.questions,
                correct_answers=reading.answers,
            )
        )

    # --- Drill activities ---
    drill_activities: list[LessonActivity] = []
    llm_drills = content.drills
    logger.info(
        "materialising drills",
        extra={"n_specs": len(drill_specs), "n_llm_drills": len(llm_drills)},
    )
    for i, spec in enumerate(drill_specs):
        drill_data = llm_drills[i] if i < len(llm_drills) else None
        if not drill_data:
            logger.warning(
                "missing drill data",
                extra={"index": i, "grammar_point_code": spec["grammar_point_code"]},
            )
            continue
        exercise_type = spec["exercise_type"]
        if exercise_type in (ExerciseType.FILL_BLANK, ExerciseType.ERROR_CORRECTION):
            items = [
                DrillItem(prompt=item.prompt, correct_answer=item.correct_answer)
                for item in drill_data.items
                if item.prompt
            ]
            drill = GeneratedDrill(
                student_id=student_id,
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
        else:
            logger.warning(
                "skipping drill with unknown exercise_type",
                extra={
                    "exercise_type": exercise_type,
                    "grammar_point_code": spec["grammar_point_code"],
                },
            )
            continue
        await drill.insert()
        logger.debug(
            "drill inserted",
            extra={
                "drill_id": str(drill.id),
                "exercise_type": exercise_type,
                "grammar_point_code": spec["grammar_point_code"],
            },
        )
        drill_activities.append(
            LessonActivity(
                type=ActivityType.DRILL,
                title=t("drill_title", label=spec["gp_label"]),
                description=f"{exercise_type.replace('_', ' ').title()} · {spec['gp_label']}",
                duration_minutes=3,
                drill_id=drill.id,
            )
        )

    # --- Speaking activities ---
    speaking_activities: list[LessonActivity] = []
    for i, cf in enumerate(speaking_cfs):
        speaking_data = content.speakings[i] if i < len(content.speakings) else None
        prompt_text = speaking_data.prompt if speaking_data else ""
        speaking_activities.append(
            LessonActivity(
                type=ActivityType.SPEAKING,
                title=t("speaking_title", label=cf.label),
                description=t("speaking_desc", label=cf.label),
                duration_minutes=3,
                content=prompt_text,
            )
        )

    # --- Writing activities ---
    writing_activities: list[LessonActivity] = []
    if include_writing and content.writing:
        writing_activities.append(
            LessonActivity(
                type=ActivityType.WRITING,
                title=t("writing_title"),
                description=t("writing_desc", topic=topic_title),
                duration_minutes=8,
                content=content.writing.prompt,
            )
        )

    # Pedagogical order: grammar → listening → reading → drill → speaking → writing
    return (
        grammar_activities
        + listening_activities
        + reading_activities
        + drill_activities
        + speaking_activities
        + writing_activities
    )
