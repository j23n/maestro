from typing import Annotated

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from maestro.auth import get_current_student
from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    Lesson,
    LessonStatus,
    ScenarioProgress,
    Student,
    UserVocabularyCard,
)
from maestro.profile import get_profile, get_or_create_profile
from maestro.templates import render_with_discover
from maestro.utils import CEFR_ORDER
from maestro.learning.weakness import (
    build_gp_titles,
    build_grammar_by_level,
    top_weaknesses,
)

router = APIRouter()


def _build_cf_by_level(comm_functions, profile):
    cf_by_level = {}
    for level in CEFR_ORDER:
        cfs = [cf for cf in comm_functions if cf.cefr_level == level]
        items = []
        for cf in cfs:
            count = profile.functions_counts.get(cf.code, 0) if profile else 0
            items.append({"cf": cf, "count": count, "demonstrated": count >= 3})
        cf_by_level[level] = items
    return cf_by_level


@router.get("/profilo", response_class=HTMLResponse)
async def profilo_page(
    request: Request, student: Student = Depends(get_current_student)
):
    profile = await get_profile(student.id)
    grammar_points = await GrammarPoint.find_all().to_list()
    comm_functions = await CommunicativeFunction.find_all().to_list()

    cefr = profile.cefr_estimate if profile else "A0"
    gp_titles = build_gp_titles(grammar_points, cefr)
    grammar_by_level = build_grammar_by_level(grammar_points, profile, gp_titles)
    cf_by_level = _build_cf_by_level(comm_functions, profile)

    # Top weaknesses for the summary
    weaknesses = top_weaknesses(grammar_by_level, cefr)

    # Profile summary stats
    total_lessons = await Lesson.find(
        {"student_id": student.id, "status": LessonStatus.COMPLETED}
    ).count()
    vocab_known = await UserVocabularyCard.find(
        {"student_id": student.id, "interval": {"$gte": 14}, "excluded": {"$ne": True}}
    ).count()

    # Top communicative functions
    top_cf_labels = []
    if profile:
        cf_by_code = {cf.code: cf for cf in comm_functions}
        top_cfs = sorted(
            profile.functions_counts.items(), key=lambda x: x[1], reverse=True
        )[:3]
        top_cf_labels = [
            cf_by_code[code].label for code, _ in top_cfs if code in cf_by_code
        ]

    scenarios = await CurriculumScenario.find({"cefr_level": cefr}).to_list()
    # Sort A0 by sequence, others by label
    if cefr == "A0":
        scenarios.sort(key=lambda s: s.sequence or 0)
    else:
        scenarios.sort(key=lambda s: s.label)
    progress = profile.scenario_progress if profile else {}
    _no_progress = ScenarioProgress()
    scenario_map = [
        {
            "scenario": s,
            "depth_completed": progress.get(s.slug, _no_progress).depth,
            "lesson_count": progress.get(s.slug, _no_progress).lesson_count,
            "last_visited": progress.get(s.slug, _no_progress).last_visited,
        }
        for s in scenarios
    ]

    # Build scenario maps for completed levels
    current_idx = CEFR_ORDER.index(cefr) if cefr in CEFR_ORDER else 0
    completed_levels = CEFR_ORDER[:current_idx]
    completed_scenario_maps = []
    for level in completed_levels:
        level_scenarios = await CurriculumScenario.find({"cefr_level": level}).to_list()
        if level == "A0":
            level_scenarios.sort(key=lambda s: s.sequence or 0)
        else:
            level_scenarios.sort(key=lambda s: s.label)
        level_map = [
            {
                "scenario": s,
                "depth_completed": progress.get(s.slug, _no_progress).depth,
                "lesson_count": progress.get(s.slug, _no_progress).lesson_count,
            }
            for s in level_scenarios
        ]
        if level_map:
            completed_scenario_maps.append((level, level_map))

    # Lesson history
    recent_lessons = (
        await Lesson.find({"student_id": student.id, "status": LessonStatus.COMPLETED})
        .sort(-Lesson.completed_at)
        .limit(20)
        .to_list()
    )

    scenario_slugs = {
        lesson.scenario_slug for lesson in recent_lessons if lesson.scenario_slug
    }
    scenarios_list = (
        await CurriculumScenario.find({"slug": {"$in": list(scenario_slugs)}}).to_list()
        if scenario_slugs
        else []
    )
    scenario_labels = {s.slug: s.label for s in scenarios_list}

    lesson_history = [
        {
            "lesson": lesson,
            "scenario_label": scenario_labels.get(lesson.scenario_slug, ""),
        }
        for lesson in recent_lessons
    ]

    return await render_with_discover(
        request,
        "profilo.html",
        {
            "profile": profile,
            "grammar_by_level": grammar_by_level,
            "cf_by_level": cf_by_level,
            "cefr_order": CEFR_ORDER,
            "scenario_map": scenario_map,
            "completed_scenario_maps": completed_scenario_maps,
            "lesson_history": lesson_history,
            "weaknesses": weaknesses,
            "total_lessons": total_lessons,
            "vocab_known": vocab_known,
            "top_cf_labels": top_cf_labels,
        },
        student_id=student.id,
        create_cards=False,
    )


@router.post("/profilo/persona")
async def save_profilo_persona(
    request: Request,
    student: Student = Depends(get_current_student),
    background: Annotated[str, Form()] = "",
    interests: Annotated[str, Form()] = "",
    goal: Annotated[str, Form()] = "",
):
    profile = await get_or_create_profile(student.id)
    profile.persona.background = background.strip()
    profile.persona.interests = interests.strip()
    profile.persona.goal = goal.strip()
    await profile.save()
    return RedirectResponse(url="/profilo?saved=1", status_code=303)
