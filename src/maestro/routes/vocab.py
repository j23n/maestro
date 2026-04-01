import re
from datetime import date
from typing import Annotated
import logging
import random

from beanie import PydanticObjectId
from bson import DBRef
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, Response

from maestro.auth import get_current_student
from maestro.models import (
    Student,
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
)
from maestro.learning.profile import get_cefr_level
from maestro.utils import CEFR_ORDER
from maestro.vocab.generate_definitions import generate_definitions_for_word
from maestro.tts import generate_word_audio
from maestro.vocab.query import get_word_definition
from maestro.i18n import t
from maestro.templates import render, render_with_discover
from maestro.vocab.srs import review

logger = logging.getLogger(__name__)
router = APIRouter()

QUIZ_MODES = ("word", "translation")


@router.get("/vocab", response_class=HTMLResponse)
async def vocab_list(request: Request, student: Student = Depends(get_current_student)):
    profile = request.state.profile
    language = profile.target_language
    cards = await UserVocabularyCard.find(
        {"student_id": student.id, "language": language, "excluded": {"$ne": True}}
    ).to_list()
    if cards:
        word_ids = [c.word.ref.id for c in cards]
        words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
        word_map = {w.id: w for w in words}
        for card in cards:
            card.word = word_map.get(card.word.ref.id)
    cards = [c for c in cards if c.word is not None]

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

    return render(
        request,
        "vocab.html",
        {
            "due": due,
            "learning": learning,
            "known": known,
            "today": today,
            "stats": stats,
            "visible_levels": [lv for lv in CEFR_ORDER if stats["cefr"].get(lv)],
        },
    )


@router.get("/vocab/word/{word_id}", response_class=HTMLResponse)
async def vocab_entry(
    request: Request, word_id: str, student: Student = Depends(get_current_student)
):
    try:
        word = await VocabularyWord.get(PydanticObjectId(word_id))
    except InvalidId:
        raise HTTPException(status_code=404, detail="Word not found")
    if word is None:
        raise HTTPException(status_code=404, detail="Word not found")
    logger.info("vocab entry page", extra={"word": word.word, "word_id": word_id})
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
        await generate_word_audio(word.word, language=word.language)
    has_card = (
        await UserVocabularyCard.find_one(
            {"student_id": student.id, "word": word_ref, "excluded": {"$ne": True}}
        )
        is not None
    )
    student_level = await get_cefr_level(student.id)
    logger.debug(
        "vocab entry context",
        extra={"student_level": student_level, "has_card": has_card},
    )
    return await render_with_discover(
        request,
        "vocab-entry.html",
        {
            "word": word,
            "definitions": definitions,
            "has_card": has_card,
            "student_level": student_level,
            "audio_url": word.audio_url,
        },
        student_id=student.id,
        create_cards=False,
    )


@router.post("/vocab/word/{word_id}/add", response_class=HTMLResponse)
async def vocab_add(
    request: Request, word_id: str, student: Student = Depends(get_current_student)
):
    try:
        word = await VocabularyWord.get(PydanticObjectId(word_id))
    except InvalidId:
        raise HTTPException(status_code=404)
    if word is None:
        raise HTTPException(status_code=404)
    word_ref = DBRef(VocabularyWord.Settings.name, word.id)
    # word_ref is a DBRef with a unique ObjectId — already language-specific
    existing = await UserVocabularyCard.find_one(
        {"student_id": student.id, "word": word_ref}
    )
    if existing is None:
        card = UserVocabularyCard(
            student_id=student.id, word=word, language=word.language
        )
        await card.insert()
        logger.info("added word to vocabulary", extra={"word": word.word})
    elif existing.excluded:
        existing.excluded = False
        await existing.save()
        logger.info("un-excluded word from vocabulary", extra={"word": word.word})
    else:
        logger.debug("word already in vocabulary", extra={"word": word.word})
    has_defs = await VocabularyWordDefinition.find_one({"word": word_ref}) is not None
    if not has_defs and word.senses:
        logger.info(
            "no definitions for word, generating on add", extra={"word": word.word}
        )
        await generate_definitions_for_word(word)
    return HTMLResponse(f'<span class="added-badge">{t("vocab_in_your_vocab")}</span>')


@router.post("/vocab/word/{word_id}/exclude", response_class=HTMLResponse)
async def vocab_exclude(
    request: Request, word_id: str, student: Student = Depends(get_current_student)
):
    try:
        word = await VocabularyWord.get(PydanticObjectId(word_id))
    except InvalidId:
        raise HTTPException(status_code=404)
    if word is None:
        raise HTTPException(status_code=404)
    word_ref = DBRef(VocabularyWord.Settings.name, word.id)
    card = await UserVocabularyCard.find_one(
        {"student_id": student.id, "word": word_ref}
    )
    if card is None:
        raise HTTPException(status_code=404)
    card.excluded = True
    await card.save()
    logger.info("excluded word from vocabulary", extra={"word": word.word})
    return HTMLResponse("")


@router.post("/vocab/bulk-exclude", response_class=HTMLResponse)
async def vocab_bulk_exclude(
    request: Request, student: Student = Depends(get_current_student)
):
    form = await request.form()
    word_ids_raw = form.getlist("word_ids")
    oids = []
    for raw_id in word_ids_raw:
        try:
            oids.append(PydanticObjectId(raw_id))
        except InvalidId:
            continue
    if not oids:
        return Response(status_code=204, headers={"HX-Redirect": "/vocab"})
    word_refs = [DBRef(VocabularyWord.Settings.name, oid) for oid in oids]
    result = await UserVocabularyCard.find(
        {
            "student_id": student.id,
            "word": {"$in": word_refs},
            "excluded": {"$ne": True},
        }
    ).update_many({"$set": {"excluded": True}})
    excluded = result.modified_count if result else 0
    logger.info("bulk excluded words", extra={"count": excluded})
    return Response(status_code=204, headers={"HX-Redirect": "/vocab"})


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
    return await render_with_discover(
        request,
        "vocab-search-results.html",
        {"words": words},
        student_id=student.id,
        create_cards=False,
    )


@router.get("/vocab/practice", response_class=HTMLResponse)
async def vocab_practice(
    request: Request,
    student: Student = Depends(get_current_student),
    mode: str = "random",
    correct: int = 0,
    incorrect: int = 0,
):
    if mode not in ("word", "translation", "random"):
        mode = "random"
    correct = max(0, correct)
    incorrect = max(0, incorrect)
    student_level = await get_cefr_level(student.id)

    profile = request.state.profile
    language = profile.target_language
    due_cards = await UserVocabularyCard.find(
        {
            "student_id": student.id,
            "language": language,
            "next_review": {"$lte": date.today()},
            "excluded": {"$ne": True},
        }
    ).to_list()
    if due_cards:
        word_ids = [c.word.ref.id for c in due_cards]
        words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
        word_map = {w.id: w for w in words}
        for c in due_cards:
            c.word = word_map.get(c.word.ref.id)
    card = next((c for c in due_cards if c.word is not None), None)
    if card is None:
        is_complete = (correct + incorrect) > 0
        return await render_with_discover(
            request,
            "vocab-practice.html",
            {
                "card": None,
                "mode": mode,
                "selected_mode": mode,
                "is_complete": is_complete,
                "correct": correct,
                "incorrect": incorrect,
                "mode_url_prefix": "/vocab/practice?correct=0&incorrect=0&mode=",
            },
            student_id=student.id,
            create_cards=False,
        )
    resolved_mode = random.choice(QUIZ_MODES) if mode == "random" else mode
    word_def = await get_word_definition(card.word, student_level)
    return await render_with_discover(
        request,
        "vocab-practice.html",
        {
            "card": card,
            "mode": resolved_mode,
            "selected_mode": mode,
            "word_def": word_def,
            "student_level": student_level,
            "correct": correct,
            "incorrect": incorrect,
            "reveal_url": (
                f"/vocab/practice/{card.id}/reveal"
                f"?mode={resolved_mode}&correct={correct}&incorrect={incorrect}"
            ),
            "mode_url_prefix": (
                f"/vocab/practice?correct={correct}&incorrect={incorrect}&mode="
            ),
        },
        student_id=student.id,
        create_cards=False,
    )


@router.get("/vocab/practice/{card_id}/reveal", response_class=HTMLResponse)
async def vocab_reveal(
    card_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
    mode: str = "word",
    correct: int = 0,
    incorrect: int = 0,
):
    card = await UserVocabularyCard.get(card_id)
    if card is None or card.student_id != student.id:
        raise HTTPException(403)
    await card.fetch_all_links()
    level = await get_cefr_level(student.id)
    word_def = await get_word_definition(card.word, level)
    if word_def is None and card.word.senses:
        try:
            await generate_definitions_for_word(card.word)
            word_def = await get_word_definition(card.word, level)
        except Exception:
            logger.warning(
                "on-demand definition generation failed", extra={"word": card.word.word}
            )
    return await render_with_discover(
        request,
        "vocab-card-back.html",
        {
            "card": card,
            "mode": mode,
            "word_def": word_def,
            "student_level": level,
            "review_url": f"/vocab/practice/{card.id}/review",
            "review_extra_name": "mode",
            "review_extra_value": mode,
            "correct": correct,
            "incorrect": incorrect,
        },
        student_id=student.id,
        create_cards=False,
    )


@router.post("/vocab/practice/{card_id}/review", response_class=HTMLResponse)
async def vocab_review(
    card_id: PydanticObjectId,
    request: Request,
    rating: Annotated[int, Form()],
    student: Student = Depends(get_current_student),
    mode: Annotated[str, Form()] = "random",
    correct: Annotated[int, Form()] = 0,
    incorrect: Annotated[int, Form()] = 0,
):
    if mode not in ("word", "translation", "random"):
        mode = "random"
    correct = max(0, correct)
    incorrect = max(0, incorrect)
    card = await UserVocabularyCard.get(card_id)
    if card is None or card.student_id != student.id:
        raise HTTPException(403)
    card = review(card, rating)
    await card.save()
    new_correct = correct + (1 if rating >= 3 else 0)
    new_incorrect = incorrect + (1 if rating < 3 else 0)
    redirect_url = (
        f"/vocab/practice?mode={mode}&correct={new_correct}&incorrect={new_incorrect}"
    )
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})
