from datetime import date
from typing import Annotated
import random

from beanie import PydanticObjectId
from fastapi import APIRouter, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, Response

from maestro.models import VocabularyWord, VocabularyWordDefinition, UserVocabularyCard, LearningProfile
from maestro.templates import templates
from maestro.vocab.srs import review

router = APIRouter()

QUIZ_MODES = ("word", "definition", "translation")


async def _get_word_def(word: VocabularyWord) -> VocabularyWordDefinition | None:
    """Load the student-level VocabularyWordDefinition for a word."""
    profile = await LearningProfile.find_one()
    level = profile.cefr_estimate if profile else "A1"
    return await VocabularyWordDefinition.find_one(
        {"word.$id": word.id, "student_level": level}
    )


@router.get("/vocab", response_class=HTMLResponse)
async def vocab_list(request: Request):
    cards = await UserVocabularyCard.find_all().to_list()
    for card in cards:
        await card.fetch_all_links()

    cefr_levels = ["A1", "A2", "B1", "B2"]
    stats = {
        "total": len(cards),
        "learned": sum(1 for c in cards if c.interval >= 14),
        "difficult": sum(1 for c in cards if c.ease_factor < 2.0),
        "cefr": {level: sum(1 for c in cards if c.word.cefr_level == level) for level in cefr_levels},
    }

    return templates.TemplateResponse(
        request=request,
        name="vocab.html",
        context={"cards": cards, "today": date.today(), "stats": stats},
    )


@router.get("/vocab/word/{entry_id}", response_class=HTMLResponse)
async def vocab_entry(request: Request, entry_id: str):
    word = await VocabularyWord.find_one(VocabularyWord.entry_id == entry_id)
    if word is None:
        raise HTTPException(status_code=404, detail="Word not found")
    definitions = await VocabularyWordDefinition.find(
        {"word.$id": word.id}
    ).to_list()
    return templates.TemplateResponse(
        request=request,
        name="vocab-entry.html",
        context={"word": word, "definitions": definitions},
    )


@router.get("/vocab/practice", response_class=HTMLResponse)
async def vocab_practice(request: Request, mode: str = "random"):
    card = await UserVocabularyCard.find_one(
        {"next_review": {"$lte": date.today()}}
    )
    if card is None:
        return templates.TemplateResponse(
            request=request, name="vocab-practice.html", context={"card": None, "mode": mode}
        )
    await card.fetch_all_links()
    resolved_mode = random.choice(QUIZ_MODES) if mode == "random" else mode
    word_def = await _get_word_def(card.word)
    return templates.TemplateResponse(
        request=request, name="vocab-practice.html",
        context={"card": card, "mode": resolved_mode, "selected_mode": mode, "word_def": word_def},
    )


@router.get("/vocab/practice/{card_id}/reveal", response_class=HTMLResponse)
async def vocab_reveal(card_id: PydanticObjectId, request: Request, mode: str = "word"):
    card = await UserVocabularyCard.get(card_id)
    await card.fetch_all_links()
    word_def = await _get_word_def(card.word)
    return templates.TemplateResponse(
        request=request, name="vocab-card-back.html",
        context={
            "card": card, "mode": mode, "word_def": word_def,
            "review_url": f"/vocab/practice/{card.id}/review",
            "review_extra_name": "mode",
            "review_extra_value": mode,
        },
    )


@router.post("/vocab/practice/{card_id}/review", response_class=HTMLResponse)
async def vocab_review(
    card_id: PydanticObjectId, request: Request, rating: Annotated[int, Form()],
    mode: Annotated[str, Form()] = "random",
):
    card = await UserVocabularyCard.get(card_id)
    card = review(card, rating)
    await card.save()
    return Response(status_code=204, headers={"HX-Redirect": f"/vocab/practice?mode={mode}"})
