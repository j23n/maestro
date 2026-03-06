import json
import logging
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from maestro.auth import get_current_student
from maestro.models import (
    Student,
    VocabularyWordDefinition,
    UserVocabularyCard,
    GeneratedDrill,
    DrillAttempt,
    GrammarPoint,
    GrammarPointExplanation,
    Lesson,
)
from maestro.profile import get_profile
from maestro.drills.scoring import score_attempt
from maestro.learning.scorer import generate_writing_feedback, score_reading_answers
from maestro.templates import templates
from maestro.utils import CEFR_ORDER, utcnow, create_background_task
from maestro.vocab.discover import discover, discover_markdown, discover_list
from maestro.vocab.srs import review
from maestro.lezione.service import (
    activity_url,
    advance_lesson,
    generate_lesson_feedback,
    get_weak_grammar_points,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_PASS_THRESHOLD = 0.7


async def _get_lesson(lesson_id: PydanticObjectId, student: Student) -> Lesson:
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        raise HTTPException(404)
    if lesson.student_id != student.id:
        raise HTTPException(403)
    return lesson


@router.get("/lezione/", response_class=HTMLResponse)
async def lezione_index(request: Request, student: Student = Depends(get_current_student)):
    active = await Lesson.find_one({"student_id": student.id, "status": "active"})
    if active:
        if active.generating and active.current_index >= len(active.activities):
            return RedirectResponse(url=f"/lezione/{active.id}/generating")
        return RedirectResponse(url=activity_url(active.id, active.current_index))
    return RedirectResponse(url="/lezione/new")


@router.get("/lezione/new", response_class=HTMLResponse)
async def lezione_new(request: Request, student: Student = Depends(get_current_student)):
    return templates.TemplateResponse(request=request, name="lezione-new.html")


@router.post("/lezione/", response_class=HTMLResponse)
async def lezione_create(
    request: Request,
    student: Student = Depends(get_current_student),
    duration: Annotated[int, Form()] = 20,
):
    from maestro.lezione.planner import prepare_lesson_immediate, generate_lesson_background
    profile = await get_profile(student.id)

    lesson = await prepare_lesson_immediate(duration, profile, student.id)
    create_background_task(
        generate_lesson_background(lesson.id, duration),
        name=f"lesson-generate-{lesson.id}",
    )

    if lesson.activities:
        return RedirectResponse(url=f"/lezione/{lesson.id}/activity/0", status_code=303)
    else:
        return RedirectResponse(url=f"/lezione/{lesson.id}/generating", status_code=303)


@router.get("/lezione/{lesson_id}", response_class=HTMLResponse)
async def lezione_overview(lesson_id: PydanticObjectId, request: Request, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if lesson.status == "active":
        return RedirectResponse(url=activity_url(lesson_id, lesson.current_index))
    if lesson.status == "completed":
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete")
    annotated_overview = await discover(lesson.overview, student_id=student.id) if lesson.overview else None
    return templates.TemplateResponse(
        request=request, name="lezione.html",
        context={"lesson": lesson, "annotated_overview": annotated_overview},
    )


@router.get("/lezione/{lesson_id}/generating", response_class=HTMLResponse)
async def lezione_generating(lesson_id: PydanticObjectId, request: Request, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if not lesson.generating:
        next_idx = lesson.current_index
        while next_idx < len(lesson.activities):
            if lesson.activities[next_idx].status == "pending":
                lesson.activities[next_idx].status = "active"
                lesson.current_index = next_idx
                await lesson.save()
                return RedirectResponse(url=activity_url(lesson_id, next_idx), status_code=303)
            next_idx += 1
        if lesson.status != "completed":
            lesson.status = "completed"
            lesson.completed_at = utcnow()
            await lesson.save()
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="lezione-generating.html",
        context={"lesson": lesson},
    )


@router.post("/lezione/{lesson_id}/start", response_class=HTMLResponse)
async def lezione_start(lesson_id: PydanticObjectId, request: Request, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if not lesson.activities:
        raise HTTPException(400, "Lesson has no activities")
    lesson.status = "active"
    lesson.started_at = utcnow()
    lesson.current_index = 0
    lesson.activities[0].status = "active"
    await lesson.save()
    return RedirectResponse(url=activity_url(lesson_id, 0), status_code=303)


@router.get("/lezione/{lesson_id}/activity/{idx}", response_class=HTMLResponse)
async def lezione_activity(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    student: Student = Depends(get_current_student),
    card_idx: int = 0,
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        if lesson.generating:
            return RedirectResponse(url=f"/lezione/{lesson_id}/generating", status_code=303)
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
        annotated = await discover(drill.prompt, student_id=student.id)
        ctx["drill"] = drill
        ctx["annotated_prompt"] = annotated
        return templates.TemplateResponse(
            request=request, name="lezione-activity-drill.html", context=ctx
        )

    if activity.type == "vocab_review":
        card_ids = activity.card_ids
        if card_idx >= len(card_ids):
            redirect_url = await advance_lesson(lesson, idx)
            return RedirectResponse(url=redirect_url, status_code=303)
        card = await UserVocabularyCard.get(card_ids[card_idx])
        if card is None:
            raise HTTPException(404)
        await card.fetch_all_links()
        profile = await get_profile(student.id)
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
        ctx["annotated_content"] = await discover(activity.content, student_id=student.id)
        ctx["annotated_questions"] = await discover_list(activity.questions or [], student_id=student.id)
        return templates.TemplateResponse(
            request=request, name="lezione-activity-reading.html", context=ctx
        )

    if activity.type == "writing":
        ctx["annotated_content"] = await discover(activity.content, student_id=student.id)
        return templates.TemplateResponse(
            request=request, name="lezione-activity-writing.html", context=ctx
        )

    if activity.type == "grammar":
        ctx["annotated_content"] = await discover_markdown(activity.content or "", student_id=student.id)
        if activity.why_important:
            ctx["annotated_why"] = await discover(activity.why_important, student_id=student.id)
        # Find the GP and its explanation for translation + chunk_ref
        gp_label = activity.title.replace("Grammatica: ", "")
        gp = await GrammarPoint.find_one({"label": gp_label})
        if not gp:
            # Try matching by content — find explanation that matches
            gp = await GrammarPoint.find_one({})  # fallback
        if gp:
            ctx["chunk_ref"] = gp.chunk_ref
            profile = await get_profile(student.id)
            level = profile.cefr_estimate if profile else "A1"
            expl = await GrammarPointExplanation.find_one(
                {"grammar_point.$id": gp.id, "student_level": level}
            )
            if not expl:
                expl = await GrammarPointExplanation.find_one({"grammar_point.$id": gp.id})
            if expl and expl.translation:
                ctx["annotated_translation"] = await discover_markdown(expl.translation, student_id=student.id)
        return templates.TemplateResponse(
            request=request, name="lezione-activity-grammar.html", context=ctx
        )

    if activity.type == "speaking":
        return templates.TemplateResponse(
            request=request, name="lezione-activity-speaking.html", context=ctx
        )

    raise HTTPException(400, f"Unknown activity type: {activity.type}")


@router.post("/lezione/{lesson_id}/activity/{idx}/skip")
async def lezione_activity_skip(lesson_id: PydanticObjectId, idx: int, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    lesson.activities[idx].status = "skipped"
    redirect_url = await advance_lesson(lesson, idx, skip=True)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post("/lezione/{lesson_id}/activity/{idx}/complete")
async def lezione_activity_complete(lesson_id: PydanticObjectId, idx: int, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    redirect_url = await advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post("/lezione/{lesson_id}/activity/{idx}/drill-submit", response_class=HTMLResponse)
async def lezione_drill_submit(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    if activity.drill_id is None:
        raise HTTPException(400)

    drill = await GeneratedDrill.get(activity.drill_id)
    if drill is None:
        raise HTTPException(404)

    form = await request.form()
    answers = list(form.getlist("answers"))

    student_input: list[str] | str = answers if drill.items else (answers[0] if answers else "")

    correct, event, feedback, rule_refs = await score_attempt(drill, student_input, student_id=student.id)

    stored_answer = json.dumps(answers) if len(answers) > 1 else (answers[0] if answers else "")
    attempt = DrillAttempt(
        student_id=student.id,
        generated_drill=drill,
        student_answer=stored_answer,
        correct=correct,
        learning_event=None,
    )
    await attempt.insert()
    drill.used = True
    await drill.save()

    lesson.activities[idx].result = {"correct": correct, "student_answer": stored_answer}

    feedback = feedback or None
    next_url = await advance_lesson(lesson, idx)

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


@router.get("/lezione/{lesson_id}/activity/{idx}/vocab-reveal", response_class=HTMLResponse)
async def lezione_vocab_reveal(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    student: Student = Depends(get_current_student),
    card_idx: int = 0,
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    card_ids = activity.card_ids
    if card_idx >= len(card_ids):
        raise HTTPException(404)
    card = await UserVocabularyCard.get(card_ids[card_idx])
    if card is None:
        raise HTTPException(404)
    await card.fetch_all_links()
    profile = await get_profile(student.id)
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


@router.post("/lezione/{lesson_id}/activity/{idx}/vocab-rate")
async def lezione_vocab_rate(
    lesson_id: PydanticObjectId,
    idx: int,
    rating: Annotated[int, Form()],
    card_idx: Annotated[int, Form()],
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
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
    redirect_url = await advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post("/lezione/{lesson_id}/activity/{idx}/writing-submit", response_class=HTMLResponse)
async def lezione_writing_submit(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    answer: Annotated[str, Form()],
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)

    activity = lesson.activities[idx]
    profile = await get_profile(student.id)
    cefr_level = profile.cefr_estimate if profile else "A1"

    feedback = await generate_writing_feedback(
        activity.content or "",
        answer,
        cefr_level,
    )

    lesson.activities[idx].result = {"student_answer": answer}
    next_url = await advance_lesson(lesson, idx)

    return templates.TemplateResponse(
        request=request,
        name="lezione-drill-result.html",
        context={
            "lesson": lesson,
            "activity": activity,
            "drill": None,
            "attempt": None,
            "correct": feedback.get("objective_correct", True) if isinstance(feedback, dict) else True,
            "feedback": feedback,
            "rule_refs": [],
            "next_url": next_url,
            "idx": idx,
            "total": len(lesson.activities),
            "is_writing": True,
        },
    )


@router.post("/lezione/{lesson_id}/activity/{idx}/reading-submit", response_class=HTMLResponse)
async def lezione_reading_submit(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)

    activity = lesson.activities[idx]
    form = await request.form()
    answers = list(form.getlist("answers"))

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
    next_url = await advance_lesson(lesson, idx)

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


@router.get("/lezione/{lesson_id}/complete", response_class=HTMLResponse)
async def lezione_complete(lesson_id: PydanticObjectId, request: Request, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    completed_count = sum(1 for a in lesson.activities if a.status == "completed")
    skipped_count = sum(1 for a in lesson.activities if a.status == "skipped")
    weak_grammar_points = await get_weak_grammar_points(lesson)
    if lesson.status == "completed" and not lesson.feedback_summary:
        from maestro.learning.lesson_analyzer import analyze_lesson
        create_background_task(
            analyze_lesson(lesson),
            name=f"lesson-analyze-{lesson_id}",
        )
    if not lesson.feedback_summary:
        try:
            lesson.feedback_summary = await generate_lesson_feedback(lesson, weak_grammar_points)
            await lesson.save()
        except Exception as exc:
            logger.warning(f"[lezione] feedback generation error: {exc}")
    annotated_feedback = await discover_markdown(lesson.feedback_summary, student_id=student.id) if lesson.feedback_summary else None
    return templates.TemplateResponse(
        request=request,
        name="lezione-complete.html",
        context={
            "lesson": lesson,
            "completed_count": completed_count,
            "skipped_count": skipped_count,
            "weak_grammar_points": weak_grammar_points,
            "annotated_feedback": annotated_feedback,
        },
    )
