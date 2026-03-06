"""A0 static lesson generation from pre-authored YAML content (no LLM calls)."""

from __future__ import annotations

import logging

import yaml

from maestro.models import (
    Lesson,
    LessonActivity,
    GeneratedDrill,
    DrillItem,
    DrillTemplate,
)
from maestro.profile import get_profile
from maestro.utils import DATA_DIR
from maestro.lezione.selection import pick_scenario

logger = logging.getLogger(__name__)


async def _generate_a0_lesson_background(
    lesson_id,
    duration_minutes: int,
) -> None:
    """Generate a static A0 lesson from pre-authored YAML content (no LLM calls)."""
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        logger.error(f"[planner] _generate_a0_lesson_background: lesson {lesson_id} not found")
        return

    profile = await get_profile(lesson.student_id) if lesson.student_id else None
    scenario, depth = await pick_scenario(profile, "A0")

    # Load static content
    lessons_file = DATA_DIR / "a0_lessons.yaml"
    with open(lessons_file) as f:
        all_lessons = yaml.safe_load(f)

    lesson_data = all_lessons.get(scenario.slug)
    if not lesson_data:
        logger.error(f"[planner] No static content for A0 scenario: {scenario.slug}")
        lesson.generating = False
        await lesson.save()
        return

    topic_title = lesson_data.get("topic_title", scenario.label)
    topic_description = lesson_data.get("topic_description", scenario.description)
    overview = lesson_data.get("overview", "")

    new_activities: list[LessonActivity] = []
    for act_data in lesson_data.get("activities", []):
        act_type = act_data["type"]

        if act_type == "grammar":
            new_activities.append(LessonActivity(
                type="grammar",
                title=act_data.get("title", ""),
                description=act_data.get("description", ""),
                content=act_data.get("content", ""),
                why_important=act_data.get("why_important"),
                grammar_point_code=act_data.get("grammar_point_code"),
            ))

        elif act_type == "onboarding":
            new_activities.append(LessonActivity(
                type="onboarding",
                title=act_data.get("title", ""),
                description=act_data.get("description", ""),
                content=act_data.get("content", ""),
                profile_field=act_data.get("profile_field"),
                response_template=act_data.get("response_template"),
            ))

        elif act_type == "drill":
            # Create a GeneratedDrill doc from static items
            gp_code = act_data.get("grammar_point_code", "a0_saluti")
            exercise_type = act_data.get("exercise_type", "fill_blank")
            items = [
                DrillItem(prompt=it["prompt"], correct_answer=it.get("correct_answer"))
                for it in act_data.get("items", [])
            ]
            # Find or create a template
            template = await DrillTemplate.find_one({
                "grammar_point_code": gp_code,
                "exercise_type": exercise_type,
            })
            if not template:
                template = DrillTemplate(
                    grammar_point_code=gp_code,
                    cefr_level="A0",
                    exercise_type=exercise_type,
                )
                await template.insert()

            drill = GeneratedDrill(
                student_id=lesson.student_id,
                template=template,
                grammar_point_code=gp_code,
                cefr_level="A0",
                exercise_type=exercise_type,
                prompt="",
                items=items,
                scenario_slug=scenario.slug,
            )
            await drill.insert()
            new_activities.append(LessonActivity(
                type="drill",
                title=act_data.get("title", f"Esercizio: {gp_code}"),
                description=act_data.get("description", exercise_type),
                drill_id=drill.id,
                hint=act_data.get("hint"),
            ))

        elif act_type == "reading":
            new_activities.append(LessonActivity(
                type="reading",
                title=act_data.get("title", "Lettura"),
                description=act_data.get("description", ""),
                content=act_data.get("content", ""),
                questions=act_data.get("questions", []),
                correct_answers=act_data.get("correct_answers", []),
            ))

    # Update lesson
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        return
    lesson.activities.extend(new_activities)
    lesson.overview = overview
    lesson.scenario_slug = scenario.slug
    lesson.scenario_depth = depth
    lesson.topic_title = topic_title
    lesson.topic_description = topic_description
    lesson.generating = False
    await lesson.save()

    logger.info(
        f"[planner] _generate_a0_lesson_background complete: "
        f"scenario={scenario.slug}, {len(new_activities)} activities"
    )
