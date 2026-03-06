from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from maestro.models import GrammarPoint, GrammarPointExplanation, LearningProfile
from maestro.templates import templates
from maestro.vocab.discover import discover_markdown

router = APIRouter()


@router.get("/grammar/{code}", response_class=HTMLResponse)
async def grammar_detail(code: str, request: Request):
    gp = await GrammarPoint.find_one(GrammarPoint.code == code)
    if gp is None:
        raise HTTPException(404)
    profile = await LearningProfile.find_one()
    level = profile.cefr_estimate if profile else "A1"
    explanation = await GrammarPointExplanation.find_one(
        {"grammar_point.$id": gp.id, "student_level": level}
    )
    if not explanation:
        explanation = await GrammarPointExplanation.find_one(
            {"grammar_point.$id": gp.id}
        )
    annotated_explanation = await discover_markdown(explanation.explanation) if explanation else None
    return templates.TemplateResponse(
        request=request,
        name="grammar-detail.html",
        context={"gp": gp, "explanation": explanation, "annotated_explanation": annotated_explanation},
    )
