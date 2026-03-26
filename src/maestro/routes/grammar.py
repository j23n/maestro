import json

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse

from maestro.auth import get_current_student
from maestro.drills.scoring import score_attempt
from maestro.models import (
    ActivityType,
    DrillAttempt,
    GeneratedDrill,
    GrammarChunk,
    GrammarPoint,
    Student,
)
from maestro.learning.profile import update_profile
from maestro.profile import get_cefr_level
from maestro.templates import render_with_discover
from maestro.utils import CEFR_ORDER, explanation_lang_for_level, strip_lang_spans

router = APIRouter()


@router.get("/grammar", response_class=HTMLResponse)
async def grammar_index(
    request: Request, student: Student = Depends(get_current_student)
):
    student_level = await get_cefr_level(student.id)
    visible_levels = (
        CEFR_ORDER[: CEFR_ORDER.index(student_level) + 1]
        if student_level in CEFR_ORDER
        else CEFR_ORDER
    )

    gps = await GrammarPoint.find({"cefr_level": {"$in": visible_levels}}).to_list()

    # Build titles from inline explanations, keyed by gp id
    student_lang = explanation_lang_for_level(student_level)
    fallback_lang = "it" if student_lang == "en" else "en"
    titles: dict = {}
    for gp in gps:
        expl = gp.explanations.get(student_lang) or gp.explanations.get(fallback_lang)
        if expl and expl.title:
            titles[str(gp.id)] = strip_lang_spans(expl.title)

    # Build nested dict: level → category → [gp, ...]
    grouped: dict[str, dict[str, list]] = {}
    for gp in gps:
        grouped.setdefault(gp.cefr_level, {}).setdefault(gp.category, []).append(gp)
    for level in grouped:
        for cat in grouped[level]:
            grouped[level][cat].sort(key=lambda g: titles.get(str(g.id)) or g.label)

    return await render_with_discover(
        request,
        "grammar-index.html",
        {"grouped": grouped, "titles": titles, "student_level": student_level},
        student_id=student.id,
        create_cards=False,
    )


@router.get("/grammar/{code}", response_class=HTMLResponse)
async def grammar_detail(
    code: str, request: Request, student: Student = Depends(get_current_student)
):
    gp = await GrammarPoint.find_one(GrammarPoint.code == code)
    if gp is None:
        raise HTTPException(404)
    student_level = await get_cefr_level(student.id)

    # Pick the explanation at the student's language (en for A0-A2, it for B1-B2)
    expl_lang = explanation_lang_for_level(student_level)
    expl = gp.explanations.get(expl_lang) or next(
        (gp.explanations[k] for k in ("en", "it") if k in gp.explanations),
        None,
    )

    ctx: dict = {"gp": gp}
    if expl:
        ctx["content"] = expl.explanation
        ctx["why_this_matters"] = expl.why_this_matters

    display_title = strip_lang_spans(expl.title) if expl and expl.title else gp.label
    ctx["display_title"] = display_title
    return await render_with_discover(
        request,
        "grammar-detail.html",
        ctx,
        student_id=student.id,
        create_cards=False,
    )


@router.get("/grammar/{code}/practice", response_class=HTMLResponse)
async def grammar_practice(
    code: str, request: Request, student: Student = Depends(get_current_student)
):
    gp = await GrammarPoint.find_one(GrammarPoint.code == code)
    if gp is None:
        raise HTTPException(404)

    drill = await GeneratedDrill.find_one(
        {
            "grammar_point_code": code,
            "student_id": student.id,
            "used": False,
        }
    )

    student_level = await get_cefr_level(student.id)
    expl_lang = explanation_lang_for_level(student_level)
    expl = gp.explanations.get(expl_lang) or next(
        (gp.explanations[k] for k in ("en", "it") if k in gp.explanations),
        None,
    )
    display_title = strip_lang_spans(expl.title) if expl and expl.title else gp.label

    return await render_with_discover(
        request,
        "grammar-practice.html",
        {"gp": gp, "drill": drill, "display_title": display_title},
        student_id=student.id,
        create_cards=False,
    )


@router.post("/grammar/{code}/practice/submit", response_class=HTMLResponse)
async def grammar_practice_submit(
    code: str, request: Request, student: Student = Depends(get_current_student)
):
    form = await request.form()
    drill_id = form.get("drill_id")
    answers = list(form.getlist("answers"))

    drill = await GeneratedDrill.get(drill_id)
    if drill is None:
        raise HTTPException(404)

    student_input: list[str] | str = (
        answers if drill.items else (answers[0] if answers else "")
    )

    correct, event, feedback, rule_refs = await score_attempt(
        drill, student_input, student_id=student.id
    )

    stored_answer = (
        json.dumps(answers) if len(answers) > 1 else (answers[0] if answers else "")
    )
    attempt = DrillAttempt(
        student_id=student.id,
        generated_drill=drill,
        student_answer=stored_answer,
        correct=correct,
    )
    await attempt.insert()
    drill.used = True
    await drill.save()

    if event:
        event.activity_type = ActivityType.DRILL.value
        event.student_text = stored_answer
        await event.insert()
        await update_profile(event)

    return await render_with_discover(
        request,
        "grammar-practice-result.html",
        {
            "gp_code": code,
            "drill": drill,
            "correct": correct,
            "feedback": feedback,
            "rule_refs": rule_refs,
        },
        student_id=student.id,
        create_cards=False,
    )


@router.get("/grammar/chunk/{ref}", response_class=HTMLResponse)
async def grammar_chunk_detail(
    ref: str, request: Request, student: Student = Depends(get_current_student)
):
    chunk = await GrammarChunk.find_one({"ref": ref})
    if chunk is None:
        raise HTTPException(404)
    heading = chunk.chunk_metadata.get("heading", ref)
    return await render_with_discover(
        request,
        "grammar-chunk.html",
        {
            "chunk": chunk,
            "heading": heading,
            "content": chunk.content,
        },
        student_id=student.id,
        create_cards=False,
    )
