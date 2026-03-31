from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse

from maestro.auth import get_current_student
from maestro.models import CommunicativeFunction, Student
from maestro.learning.profile import get_cefr_level
from maestro.learning.weakness import build_titles
from maestro.templates import render_with_discover
from maestro.utils import CEFR_ORDER, explanation_lang_for_level, strip_lang_spans

router = APIRouter()


@router.get("/cf", response_class=HTMLResponse)
async def cf_index(request: Request, student: Student = Depends(get_current_student)):
    student_level = await get_cefr_level(student.id)
    visible_levels = (
        CEFR_ORDER[: CEFR_ORDER.index(student_level) + 1]
        if student_level in CEFR_ORDER
        else CEFR_ORDER
    )

    lang = request.state.lang_ctx.code
    cfs = await CommunicativeFunction.find(
        {"cefr_level": {"$in": visible_levels}, "language": lang}
    ).to_list()

    titles = build_titles(cfs, student_level, lang)

    # Build nested dict: level → category → [cf, ...]
    grouped: dict[str, dict[str, list]] = {}
    for cf in cfs:
        grouped.setdefault(cf.cefr_level, {}).setdefault(cf.category, []).append(cf)
    for level in grouped:
        for cat in grouped[level]:
            grouped[level][cat].sort(key=lambda c: titles.get(c.code) or c.label)

    return await render_with_discover(
        request,
        "cf-index.html",
        {"grouped": grouped, "titles": titles, "student_level": student_level},
        student_id=student.id,
        create_cards=False,
    )


@router.get("/cf/{code}", response_class=HTMLResponse)
async def cf_detail(
    code: str, request: Request, student: Student = Depends(get_current_student)
):
    cf = await CommunicativeFunction.find_one(CommunicativeFunction.code == code)
    if cf is None:
        raise HTTPException(404)
    student_level = await get_cefr_level(student.id)

    target_lang = request.state.lang_ctx.code
    expl_lang = explanation_lang_for_level(student_level, target_lang)
    expl = cf.explanations.get(expl_lang) or next(
        (cf.explanations[k] for k in ("en", target_lang) if k in cf.explanations),
        None,
    )

    ctx: dict = {"cf": cf}
    if expl:
        ctx["content"] = expl.explanation
        ctx["why_this_matters"] = expl.why_this_matters

    display_title = strip_lang_spans(expl.title) if expl and expl.title else cf.label
    ctx["display_title"] = display_title
    return await render_with_discover(
        request,
        "cf-detail.html",
        ctx,
        student_id=student.id,
        create_cards=False,
    )
