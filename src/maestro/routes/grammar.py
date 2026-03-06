from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from maestro.models import GrammarPoint, GrammarPointExplanation, ItalianChunk
from maestro.profile import get_cefr_level
from maestro.templates import templates
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
    level = await get_cefr_level()
    explanation = await GrammarPointExplanation.find_one(
        {"grammar_point.$id": gp.id, "student_level": level}
    )
    if not explanation:
        explanation = await GrammarPointExplanation.find_one(
            {"grammar_point.$id": gp.id}
        )
    annotated_explanation = await discover_markdown(explanation.explanation) if explanation else None
    annotated_translation = await discover_markdown(explanation.translation) if explanation and explanation.translation else None
    display_title = (explanation.title if explanation else "") or gp.label
    return templates.TemplateResponse(
        request=request,
        name="grammar-detail.html",
        context={
            "gp": gp,
            "explanation": explanation,
            "annotated_explanation": annotated_explanation,
            "annotated_translation": annotated_translation,
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
