from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse

from maestro.auth import get_current_student
from maestro.models import GrammarPoint, GrammarChunk, Student
from maestro.profile import get_cefr_level
from maestro.templates import render_with_discover
from maestro.utils import CEFR_ORDER, explanation_lang_for_level, strip_lang_spans
from maestro.config import settings as _settings
from maestro.vocab.discover import preprocess_grammar_markdown

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
        fallback_lang = (
            _settings.TARGET_LANGUAGE
            if expl.language == _settings.TARGET_LANGUAGE
            else None
        )
        ctx["preprocessed_content"] = preprocess_grammar_markdown(expl.explanation)
        ctx["content_lang"] = fallback_lang

    display_title = strip_lang_spans(expl.title) if expl and expl.title else gp.label
    ctx["display_title"] = display_title
    return await render_with_discover(
        request,
        "grammar-detail.html",
        ctx,
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
    preprocessed_content = preprocess_grammar_markdown(chunk.content)
    heading = chunk.chunk_metadata.get("heading", ref)
    return await render_with_discover(
        request,
        "grammar-chunk.html",
        {
            "chunk": chunk,
            "heading": heading,
            "preprocessed_content": preprocessed_content,
        },
        student_id=student.id,
        create_cards=False,
    )
