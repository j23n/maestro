import re
from datetime import date
from typing import Annotated
import logging
import random

from beanie import PydanticObjectId
from bson import DBRef
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, Response

from maestro.auth import get_current_student
from maestro.models import (
    Student,
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
)
from maestro.profile import get_cefr_level
from maestro.utils import cefr_levels_up_to, CEFR_ORDER
from maestro.vocab.generate_definitions import generate_definitions_for_word
from maestro.tts import generate_word_audio
from maestro.vocab.query import get_word_definition
from maestro.templates import templates, render_with_discover
from maestro.vocab.srs import review

logger = logging.getLogger(__name__)
router = APIRouter()

QUIZ_MODES = ("word", "definition", "translation")


@router.get("/vocab", response_class=HTMLResponse)
async def vocab_list(request: Request, student: Student = Depends(get_current_student)):
    student_level = await get_cefr_level(student.id)
    visible_levels = cefr_levels_up_to(student_level)

    cards = await UserVocabularyCard.find({"student_id": student.id}).to_list()
    if cards:
        word_ids = [c.word.ref.id for c in cards]
        words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
        word_map = {w.id: w for w in words}
        for card in cards:
            card.word = word_map.get(card.word.ref.id)
    cards = [
        c for c in cards if c.word is not None and c.word.cefr_level in visible_levels
    ]

    today = date.today()
    due = sorted(
        [c for c in cards if c.next_review <= today], key=lambda c: c.word.word
    )
    learning = sorted(
        [c for c in cards if c.next_review > today and c.interval < 14],
        key=lambda c: c.word.word,
    )
    known = sorted(
        [c for c in cards if c.interval >= 14 and c.next_review > today],
        key=lambda c: c.word.word,
    )

    stats = {
        "total": len(cards),
        "due": len(due),
        "learning": len(learning),
        "known": len(known),
        "difficult": sum(1 for c in cards if c.ease_factor < 2.0),
        "cefr": {
            level: sum(1 for c in cards if c.word.cefr_level == level)
            for level in CEFR_ORDER
        },
    }

    return await render_with_discover(
        request,
        "vocab.html",
        {
            "due": due,
            "learning": learning,
            "known": known,
            "today": today,
            "stats": stats,
            "visible_levels": visible_levels,
        },
        student_id=student.id,
    )


@router.get("/vocab/word/{entry_id}", response_class=HTMLResponse)
async def vocab_entry(
    request: Request, entry_id: str, student: Student = Depends(get_current_student)
):
    word = await VocabularyWord.find_one(VocabularyWord.entry_id == entry_id)
    if word is None:
        raise HTTPException(status_code=404, detail="Word not found")
    logger.info("vocab entry page", extra={"word": word.word, "entry_id": entry_id})
    word_ref = DBRef(VocabularyWord.Settings.name, word.id)
    definitions = await VocabularyWordDefinition.find({"word": word_ref}).to_list()
    logger.debug(
        "found definitions",
        extra={"word": word.word, "n_definitions": len(definitions)},
    )
    if not definitions and word.senses:
        logger.info(
            "no definitions found, generating on-demand",
            extra={"word": word.word},
        )
        await generate_definitions_for_word(word)
        definitions = await VocabularyWordDefinition.find({"word": word_ref}).to_list()
        logger.info(
            "generated definitions on-demand",
            extra={"word": word.word, "n_definitions": len(definitions)},
        )
    # Generate audio on demand if file is missing
    if word.audio_url is None:
        await generate_word_audio(word.word)
    has_card = (
        await UserVocabularyCard.find_one({"student_id": student.id, "word": word_ref})
        is not None
    )
    student_level = await get_cefr_level(student.id)
    logger.debug(
        "vocab entry context",
        extra={"student_level": student_level, "has_card": has_card},
    )
    return templates.TemplateResponse(
        request=request,
        name="vocab-entry.html",
        context={
            "word": word,
            "definitions": definitions,
            "has_card": has_card,
            "student_level": student_level,
            "audio_url": word.audio_url,
        },
    )


@router.post("/vocab/word/{entry_id}/add", response_class=HTMLResponse)
async def vocab_add(
    request: Request, entry_id: str, student: Student = Depends(get_current_student)
):
    word = await VocabularyWord.find_one(VocabularyWord.entry_id == entry_id)
    if word is None:
        raise HTTPException(status_code=404)
    word_ref = DBRef(VocabularyWord.Settings.name, word.id)
    existing = await UserVocabularyCard.find_one(
        {"student_id": student.id, "word": word_ref}
    )
    if existing is None:
        card = UserVocabularyCard(student_id=student.id, word=word)
        await card.insert()
        logger.info("added word to vocabulary", extra={"word": word.word})
    else:
        logger.debug("word already in vocabulary", extra={"word": word.word})
    has_defs = await VocabularyWordDefinition.find_one({"word": word_ref}) is not None
    if not has_defs and word.senses:
        logger.info(
            "no definitions for word, generating on add", extra={"word": word.word}
        )
        await generate_definitions_for_word(word)
    return HTMLResponse('<span class="added-badge">In your vocabulary</span>')


@router.get("/vocab/search", response_class=HTMLResponse)
async def vocab_search(
    request: Request, student: Student = Depends(get_current_student), q: str = ""
):
    if len(q) < 2:
        return HTMLResponse("")
    words = (
        await VocabularyWord.find(
            {"word": {"$regex": f"^{re.escape(q)}", "$options": "i"}}
        )
        .limit(10)
        .to_list()
    )
    return templates.TemplateResponse(
        request=request, name="vocab-search-results.html", context={"words": words}
    )


@router.get("/vocab/practice", response_class=HTMLResponse)
async def vocab_practice(
    request: Request,
    student: Student = Depends(get_current_student),
    mode: str = "random",
):
    student_level = await get_cefr_level(student.id)
    visible_levels = cefr_levels_up_to(student_level)

    due_cards = await UserVocabularyCard.find(
        {"student_id": student.id, "next_review": {"$lte": date.today()}}
    ).to_list()
    if due_cards:
        word_ids = [c.word.ref.id for c in due_cards]
        words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
        word_map = {w.id: w for w in words}
        for c in due_cards:
            c.word = word_map.get(c.word.ref.id)
    card = None
    for c in due_cards:
        if c.word is not None and c.word.cefr_level in visible_levels:
            card = c
            break
    if card is None:
        return templates.TemplateResponse(
            request=request,
            name="vocab-practice.html",
            context={"card": None, "mode": mode},
        )
    resolved_mode = random.choice(QUIZ_MODES) if mode == "random" else mode
    word_def = await get_word_definition(card.word, student_level)
    return templates.TemplateResponse(
        request=request,
        name="vocab-practice.html",
        context={
            "card": card,
            "mode": resolved_mode,
            "selected_mode": mode,
            "word_def": word_def,
        },
    )


@router.get("/vocab/practice/{card_id}/reveal", response_class=HTMLResponse)
async def vocab_reveal(
    card_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
    mode: str = "word",
):
    card = await UserVocabularyCard.get(card_id)
    if card is None or card.student_id != student.id:
        raise HTTPException(403)
    await card.fetch_all_links()
    level = await get_cefr_level(student.id)
    word_def = await get_word_definition(card.word, level)
    return templates.TemplateResponse(
        request=request,
        name="vocab-card-back.html",
        context={
            "card": card,
            "mode": mode,
            "word_def": word_def,
            "review_url": f"/vocab/practice/{card.id}/review",
            "review_extra_name": "mode",
            "review_extra_value": mode,
        },
    )


@router.post("/vocab/practice/{card_id}/review", response_class=HTMLResponse)
async def vocab_review(
    card_id: PydanticObjectId,
    request: Request,
    rating: Annotated[int, Form()],
    student: Student = Depends(get_current_student),
    mode: Annotated[str, Form()] = "random",
):
    card = await UserVocabularyCard.get(card_id)
    if card is None or card.student_id != student.id:
        raise HTTPException(403)
    card = review(card, rating)
    await card.save()
    return Response(
        status_code=204, headers={"HX-Redirect": f"/vocab/practice?mode={mode}"}
    )
