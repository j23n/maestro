from typing import Annotated

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    Lesson,
    ScenarioProgress,
    StudentPersona,
)
from maestro.profile import get_profile, get_or_create_profile
from maestro.templates import templates
from maestro.utils import CEFR_ORDER

router = APIRouter()


def _build_grammar_by_level(grammar_points, profile):
    grammar_by_level = {}
    for level in CEFR_ORDER:
        points = [p for p in grammar_points if p.cefr_level == level]
        skills = []
        for p in points:
            correct = profile.grammar_correct_counts.get(p.code, 0) if profile else 0
            errors = profile.grammar_error_counts.get(p.code, 0) if profile else 0
            recent = profile.grammar_recent_outcomes.get(p.code, []) if profile else []
            mastered = len(recent) >= 5 and sum(recent) / len(recent) >= 0.8
            skills.append({"point": p, "correct": correct, "errors": errors, "mastered": mastered, "recent": recent})
        grammar_by_level[level] = skills
    return grammar_by_level


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
async def profilo_page(request: Request):
    profile = await get_profile()
    grammar_points = await GrammarPoint.find_all().to_list()
    comm_functions = await CommunicativeFunction.find_all().to_list()
    grammar_by_level = _build_grammar_by_level(grammar_points, profile)
    cf_by_level = _build_cf_by_level(comm_functions, profile)

    # Scenario map
    cefr = profile.cefr_estimate if profile else "A1"
    scenarios = await CurriculumScenario.find({"cefr_level": cefr}).to_list()
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

    # Lesson history
    recent_lessons = await Lesson.find(
        {"status": "completed"}
    ).sort(-Lesson.completed_at).limit(20).to_list()

    scenario_slugs = {l.scenario_slug for l in recent_lessons if l.scenario_slug}
    scenarios_list = await CurriculumScenario.find(
        {"slug": {"$in": list(scenario_slugs)}}
    ).to_list() if scenario_slugs else []
    scenario_labels = {s.slug: s.label for s in scenarios_list}

    lesson_history = [
        {
            "lesson": lesson,
            "scenario_label": scenario_labels.get(lesson.scenario_slug, ""),
        }
        for lesson in recent_lessons
    ]

    return templates.TemplateResponse(
        request=request,
        name="profilo.html",
        context={
            "profile": profile,
            "grammar_by_level": grammar_by_level,
            "cf_by_level": cf_by_level,
            "cefr_order": CEFR_ORDER,
            "scenario_map": scenario_map,
            "lesson_history": lesson_history,
        },
    )


@router.post("/profilo/persona")
async def save_profilo_persona(
    request: Request,
    tags: Annotated[str, Form()] = "",
):
    profile = await get_or_create_profile()
    profile.persona = StudentPersona(
        tags=[t.strip() for t in tags.split(",") if t.strip()],
    )
    await profile.save()
    return RedirectResponse(url="/profilo?saved=1", status_code=303)
