"""A0 static lesson generation from pre-authored YAML content (no LLM calls)."""

from __future__ import annotations

import logging

import yaml

from maestro.models import (
    Lesson,
    LessonActivity,
    GeneratedDrill,
    DrillItem,
    QuestionItem,
    ActivityType,
    ActivityStatus,
    ExerciseType,
)
from maestro.profile import get_profile
from maestro.strings import t
from maestro.utils import data_dir
from maestro.lezione.selection import pick_scenario, get_due_vocab_cards

logger = logging.getLogger(__name__)


async def _generate_a0_lesson_background(
    lesson_id,
    duration_minutes: int,
) -> None:
    """Generate a static A0 lesson from pre-authored YAML content (no LLM calls)."""
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        logger.error("lesson not found", extra={"lesson_id": str(lesson_id)})
        return

    profile = await get_profile(lesson.student_id) if lesson.student_id else None
    scenario, depth = await pick_scenario(profile, "A0")

    # Load static content
    lessons_file = data_dir() / "a0_lessons.yaml"
    with open(lessons_file) as f:
        all_lessons = yaml.safe_load(f)

    lesson_data = all_lessons.get(scenario.slug)
    if not lesson_data:
        logger.error(
            "no static A0 content for scenario", extra={"scenario_slug": scenario.slug}
        )
        await lesson.update({"$set": {"generating": False}})
        return

    topic_title = lesson_data.get("topic_title", scenario.label)
    topic_description = lesson_data.get("topic_description", scenario.description)
    overview = lesson_data.get("overview", "")

    new_activities: list[LessonActivity] = []
    for act_data in lesson_data.get("activities", []):
        act_type = act_data["type"]

        if act_type in (ActivityType.GRAMMAR, ActivityType.INFO):
            new_activities.append(
                LessonActivity(
                    type=ActivityType(act_type),
                    title=act_data.get("title", ""),
                    description=act_data.get("description", ""),
                    content=act_data.get("content", ""),  # mixed lang; has inline spans
                    why_important=act_data.get("why_important"),
                    grammar_point_code=act_data.get("grammar_point_code"),
                )
            )

        elif act_type == ActivityType.ONBOARDING:
            new_activities.append(
                LessonActivity(
                    type=ActivityType.ONBOARDING,
                    title=act_data.get("title", ""),
                    description=act_data.get("description", ""),
                    content=act_data.get("content", ""),
                    profile_field=act_data.get("profile_field"),
                    response_template=act_data.get("response_template"),
                )
            )

        elif act_type == ActivityType.DRILL:
            # Create a GeneratedDrill doc from static items
            gp_code = act_data.get("grammar_point_code", "a0_saluti")
            exercise_type = ExerciseType(
                act_data.get("exercise_type", ExerciseType.FILL_BLANK.value)
            )
            items = [
                DrillItem(
                    prompt=it["prompt"],
                    correct_answer=it.get("correct_answer"),
                    grammar_point_code=it.get("grammar_point_code"),
                )
                for it in act_data.get("items", [])
            ]
            drill = GeneratedDrill(
                student_id=lesson.student_id,
                grammar_point_code=gp_code,
                cefr_level="A0",
                exercise_type=exercise_type,
                prompt="",
                items=items,
                scenario_slug=scenario.slug,
            )
            await drill.insert()
            new_activities.append(
                LessonActivity(
                    type=ActivityType.DRILL,
                    title=act_data.get("title", t("a0_drill_title", code=gp_code)),
                    description=act_data.get("description", exercise_type),
                    drill_id=drill.id,
                    hint=act_data.get("hint"),
                )
            )

        elif act_type == ActivityType.READING:
            q_items = [
                QuestionItem(
                    text=q["text"],
                    correct_answer=q.get("correct_answer", ""),
                    grammar_point_codes=q.get("grammar_point_codes", []),
                )
                for q in act_data.get("questions", [])
            ]
            new_activities.append(
                LessonActivity(
                    type=ActivityType.READING,
                    title=act_data.get("title", t("a0_reading_title")),
                    description=act_data.get("description", ""),
                    content=act_data.get("content", ""),
                    questions=q_items,
                )
            )

        elif act_type == ActivityType.LISTENING:
            q_items = [
                QuestionItem(
                    text=q["text"],
                    correct_answer=q.get("correct_answer", ""),
                    grammar_point_codes=q.get("grammar_point_codes", []),
                )
                for q in act_data.get("questions", [])
            ]
            new_activities.append(
                LessonActivity(
                    type=ActivityType.LISTENING,
                    title=act_data.get("title", t("listening_title")),
                    description=act_data.get("description", ""),
                    content=act_data.get("content", ""),
                    questions=q_items,
                    audio_path=act_data.get("audio_path"),
                )
            )

        elif act_type == ActivityType.WRITING:
            new_activities.append(
                LessonActivity(
                    type=ActivityType.WRITING,
                    title=act_data.get("title", t("a0_writing_title")),
                    description=act_data.get("description", ""),
                    content=act_data.get("content", ""),
                    grammar_point_codes=act_data.get("grammar_point_codes", []),
                )
            )

        elif act_type == ActivityType.SPEAKING:
            new_activities.append(
                LessonActivity(
                    type=ActivityType.SPEAKING,
                    title=act_data.get("title", t("speaking_title", label="")),
                    description=act_data.get("description", ""),
                    content=act_data.get("content", ""),
                    grammar_point_codes=act_data.get("grammar_point_codes", []),
                )
            )

        elif act_type == ActivityType.VOCAB_REVIEW:
            due_cards = await get_due_vocab_cards(5, student_id=lesson.student_id)
            if due_cards:
                new_activities.append(
                    LessonActivity(
                        type=ActivityType.VOCAB_REVIEW,
                        title=t("vocab_title", count=len(due_cards)),
                        description=t("vocab_desc"),
                        card_ids=[c.id for c in due_cards],
                    )
                )

    # Atomically update lesson
    activities_dicts = [a.model_dump() for a in new_activities]
    initial_count = len(lesson.activities)
    await Lesson.find_one(Lesson.id == lesson_id).update(
        {
            "$push": {"activities": {"$each": activities_dicts}},
            "$set": {
                "overview": overview,
                "scenario_slug": scenario.slug,
                "scenario_depth": depth,
                "topic_title": topic_title,
                "topic_description": topic_description,
                "generating": False,
            },
        }
    )
    # If the lesson had no initial activities, activate the first appended one
    if initial_count == 0 and new_activities:
        await Lesson.find_one(Lesson.id == lesson_id).update(
            {
                "$set": {
                    f"activities.{initial_count}.status": ActivityStatus.ACTIVE.value
                }
            }
        )

    logger.info(
        "A0 lesson background generation complete",
        extra={"scenario": scenario.slug, "n_activities": len(new_activities)},
    )
