from typing import Annotated

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from maestro.models import LearningProfile, GrammarPoint, CommunicativeFunction
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
    profile = await LearningProfile.find_one()
    grammar_points = await GrammarPoint.find_all().to_list()
    comm_functions = await CommunicativeFunction.find_all().to_list()
    grammar_by_level = _build_grammar_by_level(grammar_points, profile)
    cf_by_level = _build_cf_by_level(comm_functions, profile)
    return templates.TemplateResponse(
        request=request,
        name="profilo.html",
        context={
            "profile": profile,
            "grammar_by_level": grammar_by_level,
            "cf_by_level": cf_by_level,
            "cefr_order": CEFR_ORDER,
        },
    )


@router.post("/profilo/interests", response_class=HTMLResponse)
async def save_profilo_interests(
    request: Request,
    interests: Annotated[str, Form()],
):
    profile = await LearningProfile.find_one()
    if profile is None:
        profile = LearningProfile()
        await profile.insert()
    profile.student_interests = [i.strip() for i in interests.split(",") if i.strip()]
    await profile.save()
    grammar_points = await GrammarPoint.find_all().to_list()
    comm_functions = await CommunicativeFunction.find_all().to_list()
    grammar_by_level = _build_grammar_by_level(grammar_points, profile)
    cf_by_level = _build_cf_by_level(comm_functions, profile)
    return templates.TemplateResponse(
        request=request,
        name="profilo.html",
        context={
            "profile": profile,
            "grammar_by_level": grammar_by_level,
            "cf_by_level": cf_by_level,
            "cefr_order": CEFR_ORDER,
            "saved": True,
        },
    )
