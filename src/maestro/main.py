from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Annotated, Union, Optional

import asyncio
import json
import logging
import markdown
import random
import re

logger = logging.getLogger(__name__)

from beanie import PydanticObjectId
from fastapi import FastAPI, Request, HTTPException, Header, Form
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from fastapi.templating import Jinja2Templates

import anthropic

from maestro.db import init_db
from maestro.drills.scoring import score_attempt
from maestro.settings import Settings
from maestro.learning.profile import update_profile
from maestro.models import (
    Message,
    Chat,
    VocabularyWord,
    VocabularyWordDefinition,
    UserVocabularyCard,
    DrillTemplate,
    GeneratedDrill,
    DrillAttempt,
    LearningEvent,
    LearningProfile,
    GrammarPoint,
    GrammarPointExplanation,
    Lesson,
    LessonActivity,
)
from maestro.rag.retrieve import get_model
from maestro.services import get_response as get_llm_response
from maestro.utils import CEFR_ORDER
from maestro.vocab.discover import discover, load_vocab
from maestro.vocab.nlp import get_nlp
from maestro.vocab.srs import review


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    get_model()  # warm up sentence-transformers
    get_nlp()    # warm up spaCy Italian model
    await load_vocab()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
_settings = Settings()
templates.env.filters["markdown"] = lambda x: markdown.markdown(
    x, extensions=["extra", "nl2br", "sane_lists"]
)
templates.env.filters["shuffle"] = lambda lst: random.sample(lst, len(lst))

_PASS_THRESHOLD = 0.7


@app.get("/chat/", response_class=HTMLResponse)
async def home(request: Request):
    chat = await Chat.find_one()
    if not chat:
        chat = Chat()
        await chat.insert()
    return templates.TemplateResponse(
        request=request, name="chat.html", context={"chat": chat}
    )


@app.get("/chat/{chat_id}/messages", response_class=HTMLResponse)
async def list_messages(
    chat_id: PydanticObjectId,
    request: Request,
    hx_request: Annotated[Union[str, None], Header()] = None,
):
    chat = await Chat.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    messages = await Message.find({"chat.$id": chat.id}).to_list()
    if hx_request:
        return templates.TemplateResponse(
            request=request, name="messages.html", context={"messages": messages}
        )
    return JSONResponse(content=jsonable_encoder(messages))


@app.post("/chat/{chat_id}/messages", response_class=HTMLResponse)
async def create_message(
    chat_id: PydanticObjectId, request: Request, message: Annotated[str, Form()]
):
    chat = await Chat.get(chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    m = Message(chat=chat, text=message, sender="user")
    await m.insert()

    return templates.TemplateResponse(
        request=request, name="user-message.html", context={"message": m}
    )


@app.get("/chat/{chat_id}/messages/{message_id}/reply")
async def get_response(
    chat_id: PydanticObjectId,
    message_id: PydanticObjectId,
    request: Request,
    hx_request: Annotated[Union[str, None], Header()] = None,
):
    chat = await Chat.get(chat_id)
    user_msg = await Message.get(message_id)
    if chat is None or user_msg is None:
        raise HTTPException(404)
    context = await Message.find({"chat.$id": chat.id}).to_list()

    reply = await get_llm_response(user_msg, context)
    await reply.insert()

    return templates.TemplateResponse(
        request=request, name="message.html", context={"message": reply}
    )


@app.get("/vocab", response_class=HTMLResponse)
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


@app.get("/vocab/word/{entry_id}", response_class=HTMLResponse)
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


QUIZ_MODES = ("word", "definition", "translation")


async def _get_word_def(word: VocabularyWord) -> VocabularyWordDefinition | None:
    """Load the student-level VocabularyWordDefinition for a word."""
    profile = await LearningProfile.find_one()
    level = profile.cefr_estimate if profile else "A1"
    return await VocabularyWordDefinition.find_one(
        {"word.$id": word.id, "student_level": level}
    )


@app.get("/vocab/practice", response_class=HTMLResponse)
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


@app.get("/vocab/practice/{card_id}/reveal", response_class=HTMLResponse)
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


@app.post("/vocab/practice/{card_id}/review", response_class=HTMLResponse)
async def vocab_review(
    card_id: PydanticObjectId, request: Request, rating: Annotated[int, Form()],
    mode: Annotated[str, Form()] = "random",
):
    card = await UserVocabularyCard.get(card_id)
    card = review(card, rating)
    await card.save()
    return Response(status_code=204, headers={"HX-Redirect": f"/vocab/practice?mode={mode}"})


# --- Profilo routes ---


def _build_grammar_by_level(grammar_points, profile):
    grammar_by_level = {}
    for level in CEFR_ORDER:
        points = [p for p in grammar_points if p.cefr_level == level]
        skills = []
        for p in points:
            correct = profile.grammar_correct_counts.get(p.code, 0) if profile else 0
            errors = profile.grammar_error_counts.get(p.code, 0) if profile else 0
            skills.append({"point": p, "correct": correct, "errors": errors, "mastered": correct >= 3})
        grammar_by_level[level] = skills
    return grammar_by_level


@app.get("/profilo", response_class=HTMLResponse)
async def profilo_page(request: Request):
    profile = await LearningProfile.find_one()
    grammar_points = await GrammarPoint.find_all().to_list()
    grammar_by_level = _build_grammar_by_level(grammar_points, profile)
    return templates.TemplateResponse(
        request=request,
        name="profilo.html",
        context={"profile": profile, "grammar_by_level": grammar_by_level, "cefr_order": CEFR_ORDER},
    )


@app.post("/profilo/interests", response_class=HTMLResponse)
async def save_profilo_interests(
    request: Request,
    interests: Annotated[str, Form()],
):
    profile = await LearningProfile.find_one()
    if profile is None:
        profile = LearningProfile()
        await profile.insert()
    profile.student_interests = [i.strip() for i in interests.split(",") if i.strip()]
    await profile.save()
    grammar_points = await GrammarPoint.find_all().to_list()
    grammar_by_level = _build_grammar_by_level(grammar_points, profile)
    return templates.TemplateResponse(
        request=request,
        name="profilo.html",
        context={"profile": profile, "grammar_by_level": grammar_by_level, "cefr_order": CEFR_ORDER, "saved": True},
    )


# --- Grammar point routes ---

@app.get("/grammar/{code}", response_class=HTMLResponse)
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
    return templates.TemplateResponse(
        request=request,
        name="grammar-detail.html",
        context={"gp": gp, "explanation": explanation},
    )


# --- Lezione routes ---

def _activity_url(lesson_id, idx: int) -> str:
    return f"/lezione/{lesson_id}/activity/{idx}"


async def _advance_lesson(lesson: Lesson, current_idx: int, skip: bool = False) -> str:
    """Mark activity done/skipped, advance index, return redirect URL."""
    if not skip:
        lesson.activities[current_idx].status = "completed"
    # Find next pending activity
    next_idx = current_idx + 1
    while next_idx < len(lesson.activities):
        if lesson.activities[next_idx].status == "pending":
            lesson.current_index = next_idx
            lesson.activities[next_idx].status = "active"
            await lesson.save()
            return _activity_url(lesson.id, next_idx)
        next_idx += 1
    # All done
    lesson.status = "completed"
    lesson.completed_at = datetime.utcnow()
    await lesson.save()
    return f"/lezione/{lesson.id}/complete"


@app.get("/lezione/", response_class=HTMLResponse)
async def lezione_index(request: Request):
    # Redirect to active lesson or new form
    active = await Lesson.find_one({"status": "active"})
    if active:
        return RedirectResponse(url=_activity_url(active.id, active.current_index))
    return RedirectResponse(url="/lezione/new")


@app.get("/lezione/new", response_class=HTMLResponse)
async def lezione_new(request: Request):
    from maestro.lezione.planner import _pick_grammar_points
    profile = await LearningProfile.find_one()
    cefr = profile.cefr_estimate if profile else "A1"
    cefr_idx = CEFR_ORDER.index(cefr) if cefr in CEFR_ORDER else 0
    target_levels = CEFR_ORDER[max(0, cefr_idx - 1): cefr_idx + 1]
    candidate_gps = await GrammarPoint.find(
        {"cefr_level": {"$in": target_levels}}
    ).to_list()
    suggested = await _pick_grammar_points(profile, cefr, min(5, len(candidate_gps)))
    suggested_codes = {gp.code for gp in suggested}
    return templates.TemplateResponse(
        request=request, name="lezione-new.html",
        context={"candidate_gps": candidate_gps, "suggested_codes": suggested_codes},
    )


@app.post("/lezione/", response_class=HTMLResponse)
async def lezione_create(
    request: Request,
    duration: Annotated[int, Form()] = 20,
    topic: Annotated[str, Form()] = "",
    grammar_codes: Annotated[list[str], Form()] = [],
):
    from maestro.lezione.planner import generate_lesson_plan
    profile = await LearningProfile.find_one()
    cefr = profile.cefr_estimate if profile else "A1"

    activities, overview = await generate_lesson_plan(duration, topic, grammar_codes)

    lesson = Lesson(
        duration_minutes=duration,
        focus_hint=topic,
        activities=activities,
        cefr_at_start=cefr,
        status="planning",
        overview=overview,
    )
    await lesson.insert()
    return RedirectResponse(url=f"/lezione/{lesson.id}", status_code=303)


@app.get("/lezione/{lesson_id}", response_class=HTMLResponse)
async def lezione_overview(lesson_id: PydanticObjectId, request: Request):
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        raise HTTPException(404)
    if lesson.status == "active":
        return RedirectResponse(url=_activity_url(lesson_id, lesson.current_index))
    if lesson.status == "completed":
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete")
    return templates.TemplateResponse(
        request=request, name="lezione.html", context={"lesson": lesson}
    )


@app.post("/lezione/{lesson_id}/start", response_class=HTMLResponse)
async def lezione_start(lesson_id: PydanticObjectId, request: Request):
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        raise HTTPException(404)
    if not lesson.activities:
        raise HTTPException(400, "Lesson has no activities")
    lesson.status = "active"
    lesson.started_at = datetime.utcnow()
    lesson.current_index = 0
    lesson.activities[0].status = "active"
    await lesson.save()
    return RedirectResponse(url=_activity_url(lesson_id, 0), status_code=303)


@app.get("/lezione/{lesson_id}/activity/{idx}", response_class=HTMLResponse)
async def lezione_activity(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    card_idx: int = 0,
):
    lesson = await Lesson.get(lesson_id)
    if lesson is None or idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    total = len(lesson.activities)

    ctx = {
        "lesson": lesson,
        "activity": activity,
        "idx": idx,
        "total": total,
        "card_idx": card_idx,
    }

    if activity.type == "drill":
        if activity.drill_id is None:
            raise HTTPException(400, "No drill attached to this activity")
        drill = await GeneratedDrill.get(activity.drill_id)
        if drill is None:
            raise HTTPException(404)
        annotated = await discover(drill.prompt)
        ctx["drill"] = drill
        ctx["annotated_prompt"] = annotated
        return templates.TemplateResponse(
            request=request, name="lezione-activity-drill.html", context=ctx
        )

    if activity.type == "vocab_review":
        card_ids = activity.card_ids
        if card_idx >= len(card_ids):
            # All cards done — advance
            redirect_url = await _advance_lesson(lesson, idx)
            return RedirectResponse(url=redirect_url, status_code=303)
        card = await UserVocabularyCard.get(card_ids[card_idx])
        if card is None:
            raise HTTPException(404)
        await card.fetch_all_links()
        profile = await LearningProfile.find_one()
        level = profile.cefr_estimate if profile else "A1"
        word_def = await VocabularyWordDefinition.find_one(
            {"word.$id": card.word.id, "student_level": level}
        )
        ctx["card"] = card
        ctx["word_def"] = word_def
        ctx["mode"] = "word"
        return templates.TemplateResponse(
            request=request, name="lezione-activity-vocab.html", context=ctx
        )

    if activity.type == "reading":
        ctx["annotated_content"] = await discover(activity.content)
        return templates.TemplateResponse(
            request=request, name="lezione-activity-reading.html", context=ctx
        )

    if activity.type == "writing":
        ctx["annotated_content"] = await discover(activity.content)
        return templates.TemplateResponse(
            request=request, name="lezione-activity-writing.html", context=ctx
        )

    if activity.type == "grammar":
        return templates.TemplateResponse(
            request=request, name="lezione-activity-grammar.html", context=ctx
        )

    if activity.type == "speaking":
        return templates.TemplateResponse(
            request=request, name="lezione-activity-speaking.html", context=ctx
        )

    raise HTTPException(400, f"Unknown activity type: {activity.type}")


@app.post("/lezione/{lesson_id}/activity/{idx}/skip")
async def lezione_activity_skip(lesson_id: PydanticObjectId, idx: int):
    lesson = await Lesson.get(lesson_id)
    if lesson is None or idx >= len(lesson.activities):
        raise HTTPException(404)
    lesson.activities[idx].status = "skipped"
    redirect_url = await _advance_lesson(lesson, idx, skip=True)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@app.post("/lezione/{lesson_id}/activity/{idx}/complete")
async def lezione_activity_complete(lesson_id: PydanticObjectId, idx: int):
    lesson = await Lesson.get(lesson_id)
    if lesson is None or idx >= len(lesson.activities):
        raise HTTPException(404)
    redirect_url = await _advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


# --- Drill within lesson ---

@app.post("/lezione/{lesson_id}/activity/{idx}/drill-submit", response_class=HTMLResponse)
async def lezione_drill_submit(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
):
    lesson = await Lesson.get(lesson_id)
    if lesson is None or idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    if activity.drill_id is None:
        raise HTTPException(400)

    drill = await GeneratedDrill.get(activity.drill_id)
    if drill is None:
        raise HTTPException(404)

    form = await request.form()
    answers = list(form.getlist("answers"))

    # Multi-item drills pass a list; free_form passes a single string
    student_input: list[str] | str = answers if drill.items else (answers[0] if answers else "")

    correct, event, feedback, rule_refs = await score_attempt(drill, student_input)
    if event is not None:
        await event.insert()
        await update_profile(event)

    stored_answer = json.dumps(answers) if len(answers) > 1 else (answers[0] if answers else "")
    attempt = DrillAttempt(
        generated_drill=drill,
        student_answer=stored_answer,
        correct=correct,
        learning_event=event,
    )
    await attempt.insert()
    drill.used = True
    await drill.save()

    lesson.activities[idx].result = {"correct": correct, "student_answer": stored_answer}

    feedback = feedback or None
    next_url = await _advance_lesson(lesson, idx)

    return templates.TemplateResponse(
        request=request,
        name="lezione-drill-result.html",
        context={
            "lesson": lesson,
            "activity": activity,
            "drill": drill,
            "attempt": attempt,
            "correct": correct,
            "feedback": feedback,
            "rule_refs": rule_refs,
            "next_url": next_url,
            "idx": idx,
            "total": len(lesson.activities),
        },
    )


# --- Vocab within lesson ---

@app.get("/lezione/{lesson_id}/activity/{idx}/vocab-reveal", response_class=HTMLResponse)
async def lezione_vocab_reveal(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    card_idx: int = 0,
):
    lesson = await Lesson.get(lesson_id)
    if lesson is None or idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    card_ids = activity.card_ids
    if card_idx >= len(card_ids):
        raise HTTPException(404)
    card = await UserVocabularyCard.get(card_ids[card_idx])
    if card is None:
        raise HTTPException(404)
    await card.fetch_all_links()
    profile = await LearningProfile.find_one()
    level = profile.cefr_estimate if profile else "A1"
    word_def = await VocabularyWordDefinition.find_one(
        {"word.$id": card.word.id, "student_level": level}
    )
    return templates.TemplateResponse(
        request=request,
        name="vocab-card-back.html",
        context={
            "card": card,
            "word_def": word_def,
            "mode": "word",
            "card_idx": card_idx,
            "total_cards": len(card_ids),
            "review_url": f"/lezione/{lesson_id}/activity/{idx}/vocab-rate",
            "review_extra_name": "card_idx",
            "review_extra_value": card_idx,
        },
    )


@app.post("/lezione/{lesson_id}/activity/{idx}/vocab-rate")
async def lezione_vocab_rate(
    lesson_id: PydanticObjectId,
    idx: int,
    rating: Annotated[int, Form()],
    card_idx: Annotated[int, Form()],
):
    lesson = await Lesson.get(lesson_id)
    if lesson is None or idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    card_ids = activity.card_ids
    if card_idx >= len(card_ids):
        raise HTTPException(404)

    card = await UserVocabularyCard.get(card_ids[card_idx])
    if card is None:
        raise HTTPException(404)
    card = review(card, rating)
    await card.save()

    next_card_idx = card_idx + 1
    if next_card_idx < len(card_ids):
        return Response(
            status_code=204,
            headers={"HX-Redirect": f"/lezione/{lesson_id}/activity/{idx}?card_idx={next_card_idx}"},
        )
    # All vocab cards done
    redirect_url = await _advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


# --- Writing/Reading submit within lesson ---

@app.post("/lezione/{lesson_id}/activity/{idx}/writing-submit", response_class=HTMLResponse)
async def lezione_writing_submit(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    answer: Annotated[str, Form()],
):
    lesson = await Lesson.get(lesson_id)
    if lesson is None or idx >= len(lesson.activities):
        raise HTTPException(404)

    asyncio.create_task(_analyze_lesson_text(answer))
    lesson.activities[idx].result = {"student_answer": answer}
    redirect_url = await _advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@app.post("/lezione/{lesson_id}/activity/{idx}/reading-submit", response_class=HTMLResponse)
async def lezione_reading_submit(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
):
    lesson = await Lesson.get(lesson_id)
    if lesson is None or idx >= len(lesson.activities):
        raise HTTPException(404)

    activity = lesson.activities[idx]
    form = await request.form()
    answers = list(form.getlist("answers"))
    combined = " | ".join(a for a in answers if a)
    asyncio.create_task(_analyze_lesson_text(combined))

    # Score reading comprehension answers
    from maestro.learning.analyzer import score_reading_answers
    questions = activity.questions or []
    correct_answers = activity.correct_answers or []
    raw_results = await score_reading_answers(questions, correct_answers, answers)

    n = min(len(questions), len(answers), len(raw_results))
    enriched = [
        {
            "prompt": questions[j] if j < len(questions) else "",
            "correct_answer": correct_answers[j] if j < len(correct_answers) else "",
            "student_answer": answers[j] if j < len(answers) else "",
            "objective_correct": raw_results[j].get("objective_correct", False),
            "objective_note": raw_results[j].get("objective_note", ""),
            "grammar_errors": raw_results[j].get("grammar_errors", []),
            "tips": raw_results[j].get("tips", []),
        }
        for j in range(n)
    ]
    correct_count = sum(1 for r in enriched if r["objective_correct"])
    overall_correct = correct_count / max(n, 1) >= _PASS_THRESHOLD if n > 0 else True
    feedback = {"items": enriched, "correct_count": correct_count, "total": n}

    lesson.activities[idx].result = {"student_answers": answers, "correct": overall_correct}
    next_url = await _advance_lesson(lesson, idx)

    return templates.TemplateResponse(
        request=request,
        name="lezione-drill-result.html",
        context={
            "lesson": lesson,
            "activity": activity,
            "drill": None,
            "attempt": None,
            "correct": overall_correct,
            "feedback": feedback,
            "rule_refs": [],
            "next_url": next_url,
            "idx": idx,
            "total": len(lesson.activities),
        },
    )


async def _analyze_lesson_text(text: str) -> None:
    try:
        from maestro.learning.analyzer import analyze_message
        event = await analyze_message(text)
        if event:
            await event.insert()
            await update_profile(event)
    except Exception as exc:
        logger.warning(f"[lezione] analyze error: {exc}")


def _generate_lesson_feedback(lesson: Lesson, weak_grammar_points: list) -> str:
    """Sync Haiku call: brief English feedback on the completed lesson."""
    lines = []
    for a in lesson.activities:
        if a.type == "drill" and a.result:
            correct = a.result.get("correct")
            status = "correct" if correct else "incorrect" if correct is not None else "completed"
            lines.append(f"- Drill ({a.title}): {status}")
        elif a.status == "completed":
            lines.append(f"- {a.title}: completed")
        elif a.status == "skipped":
            lines.append(f"- {a.title}: skipped")

    activity_summary = "\n".join(lines) if lines else "No activities recorded."
    weak_note = ""
    if weak_grammar_points:
        labels = ", ".join(gp.label for gp in weak_grammar_points)
        weak_note = f"\nThe student specifically struggled with: {labels}. Reference these by name."

    prompt = (
        f"A student just completed an Italian lesson. Summary:\n{activity_summary}{weak_note}\n\n"
        "Write 2-3 sentences of feedback in English that: mentions what was practiced, "
        "notes any areas of difficulty, and ends with one specific encouragement."
    )
    client = anthropic.Anthropic(api_key=_settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=_settings.DRILL_MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    text = re.sub(r'^#+\s+\S+\s*\n', '', text).strip()
    return text


async def _get_weak_grammar_points(lesson: Lesson) -> list[GrammarPoint]:
    """Load grammar points for drills the student answered incorrectly."""
    result = []
    seen_codes: set[str] = set()
    for a in lesson.activities:
        if a.type != "drill" or not a.drill_id or not a.result:
            continue
        if a.result.get("correct") is not False:
            continue
        drill = await GeneratedDrill.get(a.drill_id)
        if drill is None or drill.grammar_point_code in seen_codes:
            continue
        gp = await GrammarPoint.find_one(GrammarPoint.code == drill.grammar_point_code)
        if gp:
            result.append(gp)
            seen_codes.add(gp.code)
    return result


@app.get("/lezione/{lesson_id}/complete", response_class=HTMLResponse)
async def lezione_complete(lesson_id: PydanticObjectId, request: Request):
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        raise HTTPException(404)
    completed_count = sum(1 for a in lesson.activities if a.status == "completed")
    skipped_count = sum(1 for a in lesson.activities if a.status == "skipped")
    weak_grammar_points = await _get_weak_grammar_points(lesson)
    if not lesson.feedback_summary:
        try:
            lesson.feedback_summary = _generate_lesson_feedback(lesson, weak_grammar_points)
            await lesson.save()
        except Exception as exc:
            logger.warning(f"[lezione] feedback generation error: {exc}")
    return templates.TemplateResponse(
        request=request,
        name="lezione-complete.html",
        context={
            "lesson": lesson,
            "completed_count": completed_count,
            "skipped_count": skipped_count,
            "weak_grammar_points": weak_grammar_points,
        },
    )
