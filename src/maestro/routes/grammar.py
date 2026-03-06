from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from maestro.models import GrammarPoint, GrammarPointExplanation, ItalianChunk
from maestro.profile import get_cefr_level
from maestro.templates import templates
from maestro.utils import CEFR_ORDER
from maestro.vocab.discover import discover_markdown

router = APIRouter()


@router.get("/grammar", response_class=HTMLResponse)
async def grammar_index(request: Request):
    gps = await GrammarPoint.find_all().to_list()
    student_level = await get_cefr_level()

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
    for level in ("A1", "A2", "B1", "B2"):
        grouped[level] = {}
    for gp in gps:
        grouped.setdefault(gp.cefr_level, {}).setdefault(gp.category, []).append(gp)
    for level in grouped:
        for cat in grouped[level]:
            grouped[level][cat].sort(key=lambda g: titles.get(str(g.id)) or g.label)

    return templates.TemplateResponse(
        request=request,
        name="grammar-index.html",
        context={"grouped": grouped, "titles": titles},
    )


@router.get("/grammar/{code}", response_class=HTMLResponse)
async def grammar_detail(code: str, request: Request):
    gp = await GrammarPoint.find_one(GrammarPoint.code == code)
    if gp is None:
        raise HTTPException(404)
    student_level = await get_cefr_level()
    all_expls = await GrammarPointExplanation.find(
        {"grammar_point.$id": gp.id}
    ).to_list()
    by_level = {e.student_level: e for e in all_expls}
    available_levels = sorted(by_level.keys(), key=lambda l: CEFR_ORDER.index(l))
    active_level = student_level if student_level in by_level else (available_levels[0] if available_levels else student_level)

    # Pre-render annotated markdown for each level
    panels: dict[str, dict] = {}
    for lvl, expl in by_level.items():
        panels[lvl] = {
            "title": expl.title or gp.label,
            "content": await discover_markdown(expl.explanation),
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
async def grammar_chunk_detail(ref: str, request: Request):
    chunk = await ItalianChunk.find_one({"ref": ref})
    if chunk is None:
        raise HTTPException(404)
    annotated_content = await discover_markdown(chunk.content)
    heading = chunk.chunk_metadata.get("heading", ref)
    return templates.TemplateResponse(
        request=request,
        name="grammar-chunk.html",
        context={"chunk": chunk, "heading": heading, "annotated_content": annotated_content},
    )
