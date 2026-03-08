from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse

from maestro.auth import get_current_student
from maestro.models import GrammarPoint, GrammarPointExplanation, GrammarChunk, Student
from maestro.profile import get_cefr_level
from maestro.templates import templates
from maestro.utils import CEFR_ORDER
from maestro.config import settings as _settings
from maestro.vocab.discover import discover_markdown

router = APIRouter()


@router.get("/grammar", response_class=HTMLResponse)
async def grammar_index(request: Request, student: Student = Depends(get_current_student)):
    student_level = await get_cefr_level(student.id)
    visible_levels = CEFR_ORDER[:CEFR_ORDER.index(student_level) + 1] if student_level in CEFR_ORDER else CEFR_ORDER

    gps = await GrammarPoint.find({"cefr_level": {"$in": visible_levels}}).to_list()

    # Load explanations for student's level, keyed by gp id
    explanations = await GrammarPointExplanation.find(
        {"student_level": student_level}
    ).to_list()
    titles: dict = {
        str(ex.grammar_point.ref.id): ex.title or None
        for ex in explanations
    }

    # Build nested dict: level → category → [gp, ...]
    grouped: dict[str, dict[str, list]] = {}
    for gp in gps:
        grouped.setdefault(gp.cefr_level, {}).setdefault(gp.category, []).append(gp)
    for level in grouped:
        for cat in grouped[level]:
            grouped[level][cat].sort(key=lambda g: titles.get(str(g.id)) or g.label)

    return templates.TemplateResponse(
        request=request,
        name="grammar-index.html",
        context={"grouped": grouped, "titles": titles, "student_level": student_level},
    )


@router.get("/grammar/{code}", response_class=HTMLResponse)
async def grammar_detail(code: str, request: Request, student: Student = Depends(get_current_student)):
    gp = await GrammarPoint.find_one(GrammarPoint.code == code)
    if gp is None:
        raise HTTPException(404)
    student_level = await get_cefr_level(student.id)
    max_idx = CEFR_ORDER.index(student_level) if student_level in CEFR_ORDER else len(CEFR_ORDER) - 1
    all_expls = await GrammarPointExplanation.find(
        {"grammar_point.$id": gp.id}
    ).to_list()
    by_level = {e.student_level: e for e in all_expls if CEFR_ORDER.index(e.student_level) <= max_idx}
    available_levels = sorted(by_level.keys(), key=lambda lvl: CEFR_ORDER.index(lvl))
    active_level = student_level if student_level in by_level else (available_levels[-1] if available_levels else student_level)

    # Pre-render annotated markdown for each level
    # B1/B2 explanations are fully in target language — add lang fallback
    # so vocab discovery works even for old explanations without inline lang tags.
    # A1/A2 are mixed-language and need inline tags from the LLM.
    panels: dict[str, dict] = {}
    for lvl, expl in by_level.items():
        fallback_lang = _settings.TARGET_LANGUAGE if lvl in ("B1", "B2") else None
        panels[lvl] = {
            "title": expl.title or gp.label,
            "content": await discover_markdown(expl.explanation, student_id=student.id, lang=fallback_lang),
        }

    display_title = panels[active_level]["title"] if active_level in panels else gp.label
    return templates.TemplateResponse(
        request=request,
        name="grammar-detail.html",
        context={
            "gp": gp,
            "panels": panels,
            "available_levels": available_levels,
            "active_level": active_level,
            "display_title": display_title,
        },
    )


@router.get("/grammar/chunk/{ref}", response_class=HTMLResponse)
async def grammar_chunk_detail(ref: str, request: Request, student: Student = Depends(get_current_student)):
    chunk = await GrammarChunk.find_one({"ref": ref})
    if chunk is None:
        raise HTTPException(404)
    annotated_content = await discover_markdown(chunk.content, student_id=student.id, lang=_settings.TARGET_LANGUAGE)
    heading = chunk.chunk_metadata.get("heading", ref)
    return templates.TemplateResponse(
        request=request,
        name="grammar-chunk.html",
        context={"chunk": chunk, "heading": heading, "annotated_content": annotated_content},
    )
