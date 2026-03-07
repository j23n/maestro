import json
import logging
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from maestro.auth import get_current_student
from maestro.models import (
    Student,
    UserVocabularyCard,
    GeneratedDrill,
    DrillAttempt,
    GrammarPoint,
    GrammarPointExplanation,
    Lesson,
    ActivityType,
    ActivityStatus,
    LessonStatus,
    CurriculumScenario,
)
from maestro.profile import get_profile, save_onboarding_field
from maestro.vocab.query import get_word_definition
from maestro.drills.scoring import score_attempt
from maestro.learning.scorer import generate_writing_feedback
from maestro.templates import templates
from maestro.utils import utcnow, create_background_task
from maestro.config import settings as _settings
from maestro.vocab.discover import discover, discover_markdown, discover_list, lang_wrap
from maestro.vocab.srs import review
from maestro.lezione.planner import prepare_lesson_immediate, generate_lesson_background
from markupsafe import escape
from maestro.lezione.service import (
    activity_url,
    advance_lesson,
    ensure_lesson_feedback,
    get_weak_grammar_points,
    score_reading_activity,
    update_scenario_progress,
    _sweep_leftover_activities,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_lesson(lesson_id: PydanticObjectId, student: Student) -> Lesson:
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        raise HTTPException(404)
    if lesson.student_id != student.id:
        raise HTTPException(403)
    return lesson


@router.get("/lezione/", response_class=HTMLResponse)
async def lezione_index(request: Request, student: Student = Depends(get_current_student)):
    active = await Lesson.find_one({"student_id": student.id, "status": LessonStatus.ACTIVE})
    if active:
        if active.generating and active.current_index >= len(active.activities):
            return RedirectResponse(url=f"/lezione/{active.id}/generating")
        return RedirectResponse(url=activity_url(active.id, active.current_index))

    # No active lesson — show history + start button
    recent_lessons = await Lesson.find(
        {"student_id": student.id, "status": LessonStatus.COMPLETED}
    ).sort(-Lesson.completed_at).limit(20).to_list()

    scenario_slugs = {l.scenario_slug for l in recent_lessons if l.scenario_slug}
    scenarios_list = await CurriculumScenario.find(
        {"slug": {"$in": list(scenario_slugs)}}
    ).to_list() if scenario_slugs else []
    scenario_labels = {s.slug: s.label for s in scenarios_list}

    lesson_history = [
        {"lesson": l, "scenario_label": scenario_labels.get(l.scenario_slug, "")}
        for l in recent_lessons
    ]

    profile = await get_profile(student.id)
    cefr = profile.cefr_estimate if profile else "A0"

    return templates.TemplateResponse(
        request=request,
        name="lezione-index.html",
        context={"lesson_history": lesson_history, "cefr": cefr},
    )


@router.get("/lezione/new", response_class=HTMLResponse)
async def lezione_new(request: Request, student: Student = Depends(get_current_student)):
    profile = await get_profile(student.id)
    cefr = profile.cefr_estimate if profile else "A0"
    return templates.TemplateResponse(request=request, name="lezione-new.html", context={"cefr": cefr})


@router.post("/lezione/", response_class=HTMLResponse)
async def lezione_create(
    request: Request,
    student: Student = Depends(get_current_student),
    duration: Annotated[int, Form()] = 20,
):
    # Abandon any existing active lessons before creating a new one
    await Lesson.find(
        {"student_id": student.id, "status": LessonStatus.ACTIVE}
    ).update_many({"$set": {"status": LessonStatus.ABANDONED.value}})

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
    if lesson.status == LessonStatus.ACTIVE:
        return RedirectResponse(url=activity_url(lesson_id, lesson.current_index))
    if lesson.status == LessonStatus.COMPLETED:
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete")
    overview_lang = "en" if lesson.cefr_at_start == "A0" else _settings.TARGET_LANGUAGE
    annotated_overview = await discover(lang_wrap(lesson.overview, overview_lang), student_id=student.id) if lesson.overview else None
    return templates.TemplateResponse(
        request=request, name="lezione.html",
        context={"lesson": lesson, "annotated_overview": annotated_overview},
    )


@router.get("/lezione/{lesson_id}/generating", response_class=HTMLResponse)
async def lezione_generating(lesson_id: PydanticObjectId, request: Request, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if not lesson.generating:
        if lesson.generation_error:
            # Show error state with retry button
            return templates.TemplateResponse(
                request=request,
                name="lezione-generating.html",
                context={"lesson": lesson},
            )
        next_idx = lesson.current_index
        while next_idx < len(lesson.activities):
            if lesson.activities[next_idx].status == ActivityStatus.PENDING:
                lesson.activities[next_idx].status = ActivityStatus.ACTIVE
                lesson.current_index = next_idx
                await lesson.update({"$set": {
                    f"activities.{next_idx}.status": ActivityStatus.ACTIVE.value,
                    "current_index": next_idx,
                }})
                return RedirectResponse(url=activity_url(lesson_id, next_idx), status_code=303)
            next_idx += 1
        if lesson.status != LessonStatus.COMPLETED:
            now = utcnow()
            lesson.status = LessonStatus.COMPLETED
            lesson.completed_at = now
            set_fields = {
                "status": LessonStatus.COMPLETED.value,
                "completed_at": now,
            }
            _sweep_leftover_activities(lesson, set_fields)
            await lesson.update({"$set": set_fields})
            await update_scenario_progress(lesson)
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="lezione-generating.html",
        context={"lesson": lesson},
    )


@router.post("/lezione/{lesson_id}/retry")
async def lezione_retry(lesson_id: PydanticObjectId, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if lesson.status == LessonStatus.COMPLETED:
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete", status_code=303)

    await lesson.update({"$set": {"generating": True, "generation_error": None}})

    create_background_task(
        generate_lesson_background(lesson.id, lesson.duration_minutes),
        name=f"lesson-retry-{lesson.id}",
    )

    return RedirectResponse(url=f"/lezione/{lesson_id}/generating", status_code=303)


@router.post("/lezione/{lesson_id}/start", response_class=HTMLResponse)
async def lezione_start(lesson_id: PydanticObjectId, request: Request, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if not lesson.activities:
        raise HTTPException(400, "Lesson has no activities")
    now = utcnow()
    await lesson.update({"$set": {
        "status": LessonStatus.ACTIVE.value,
        "started_at": now,
        "current_index": 0,
        "activities.0.status": ActivityStatus.ACTIVE.value,
    }})
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

    if activity.status == ActivityStatus.PENDING:
        return RedirectResponse(url=activity_url(lesson_id, lesson.current_index), status_code=303)

    total = len(lesson.activities)

    is_review = activity.status in (ActivityStatus.COMPLETED, ActivityStatus.SKIPPED)

    ctx = {
        "lesson": lesson,
        "activity": activity,
        "idx": idx,
        "total": total,
        "card_idx": card_idx,
        "is_review": is_review,
    }

    if activity.type == ActivityType.DRILL:
        if activity.drill_id is None:
            raise HTTPException(400, "No drill attached to this activity")
        drill = await GeneratedDrill.get(activity.drill_id)
        if drill is None:
            raise HTTPException(404)
        lang = _settings.TARGET_LANGUAGE
        annotated = await discover(lang_wrap(drill.prompt, lang), student_id=student.id)
        ctx["drill"] = drill
        ctx["annotated_prompt"] = annotated
        return templates.TemplateResponse(
            request=request, name="lezione-activity-drill.html", context=ctx
        )

    if activity.type == ActivityType.VOCAB_REVIEW:
        card_ids = activity.card_ids
        if card_idx >= len(card_ids):
            redirect_url = await advance_lesson(lesson, idx)
            return RedirectResponse(url=redirect_url, status_code=303)
        card = await UserVocabularyCard.get(card_ids[card_idx])
        if card is None:
            raise HTTPException(404)
        await card.fetch_all_links()
        profile = await get_profile(student.id)
        level = profile.cefr_estimate if profile else "A0"
        word_def = await get_word_definition(card.word, level)
        ctx["card"] = card
        ctx["word_def"] = word_def
        ctx["mode"] = "word"
        return templates.TemplateResponse(
            request=request, name="lezione-activity-vocab.html", context=ctx
        )

    if activity.type == ActivityType.READING:
        lang = _settings.TARGET_LANGUAGE
        ctx["annotated_content"] = await discover(lang_wrap(activity.content, lang), student_id=student.id)
        ctx["annotated_questions"] = await discover_list(
            [lang_wrap(q, lang) for q in (activity.questions or [])], student_id=student.id
        )
        return templates.TemplateResponse(
            request=request, name="lezione-activity-reading.html", context=ctx
        )

    if activity.type == ActivityType.WRITING:
        lang = _settings.TARGET_LANGUAGE
        ctx["annotated_content"] = await discover(lang_wrap(activity.content, lang), student_id=student.id)
        return templates.TemplateResponse(
            request=request, name="lezione-activity-writing.html", context=ctx
        )

    if activity.type == ActivityType.GRAMMAR:
        ctx["annotated_content"] = await discover_markdown(activity.content or "", student_id=student.id)
        profile = await get_profile(student.id)
        level = profile.cefr_estimate if profile else "A0"
        if activity.why_important:
            why_lang = "en" if level in ("A0", "A1", "A2") else _settings.TARGET_LANGUAGE
            ctx["annotated_why"] = await discover(
                lang_wrap(activity.why_important, why_lang), student_id=student.id
            )
        # Find the GP and its explanation for translation + chunk_ref
        if activity.grammar_point_code:
            gp = await GrammarPoint.find_one({"code": activity.grammar_point_code})
        else:
            # Fallback for old lessons without the field
            gp_label = activity.title.replace("Grammatica: ", "")
            gp = await GrammarPoint.find_one({"label": gp_label})
        if gp:
            ctx["chunk_ref"] = gp.chunk_ref
            expl = await GrammarPointExplanation.find_one(
                {"grammar_point.$id": gp.id, "student_level": level}
            )
            if not expl:
                expl = await GrammarPointExplanation.find_one({"grammar_point.$id": gp.id})
            if expl and expl.translation:
                ctx["annotated_translation"] = await discover_markdown(
                    expl.translation, student_id=student.id, lang="en"
                )
        return templates.TemplateResponse(
            request=request, name="lezione-activity-grammar.html", context=ctx
        )

    if activity.type == ActivityType.SPEAKING:
        return templates.TemplateResponse(
            request=request, name="lezione-activity-speaking.html", context=ctx
        )

    if activity.type == ActivityType.ONBOARDING:
        return templates.TemplateResponse(
            request=request, name="lezione-activity-onboarding.html", context=ctx
        )

    raise HTTPException(400, f"Unknown activity type: {activity.type}")


@router.post("/lezione/{lesson_id}/activity/{idx}/skip")
async def lezione_activity_skip(lesson_id: PydanticObjectId, idx: int, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    redirect_url = await advance_lesson(lesson, idx, skip=True)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post("/lezione/{lesson_id}/activity/{idx}/complete")
async def lezione_activity_complete(lesson_id: PydanticObjectId, idx: int, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    redirect_url = await advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post("/lezione/{lesson_id}/activity/{idx}/onboarding-submit", response_class=HTMLResponse)
async def lezione_onboarding_submit(
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

    # Save to student profile based on profile_field
    await save_onboarding_field(student, activity.profile_field, answer)

    # Build response text from template
    response_text = activity.response_template or "Got it!"
    response_text = response_text.replace("{answer}", str(escape(answer.strip())))

    # Mark as answered in result
    await lesson.update({"$set": {f"activities.{idx}.result": {"answer": answer.strip()}}})

    return templates.TemplateResponse(
        request=request,
        name="lezione-onboarding-response.html",
        context={"lesson": lesson, "idx": idx, "response_text": response_text},
    )


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

    drill_result = {"correct": correct, "student_answer": stored_answer}

    feedback = feedback or None
    next_url = await advance_lesson(lesson, idx, result=drill_result)

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
    level = profile.cefr_estimate if profile else "A0"
    word_def = await get_word_definition(card.word, level)
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
    if card.student_id != student.id:
        raise HTTPException(403)
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
    cefr_level = profile.cefr_estimate if profile else "A0"

    feedback = await generate_writing_feedback(
        activity.content or "",
        answer,
        cefr_level,
    )

    writing_result = {"student_answer": answer}
    next_url = await advance_lesson(lesson, idx, result=writing_result)

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
    overall_correct, feedback = await score_reading_activity(questions, correct_answers, answers)

    reading_result = {"student_answers": answers, "correct": overall_correct}
    next_url = await advance_lesson(lesson, idx, result=reading_result)

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


@router.post("/lezione/{lesson_id}/abandon")
async def lezione_abandon(lesson_id: PydanticObjectId, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    if lesson.status == LessonStatus.ACTIVE:
        await lesson.update({"$set": {"status": LessonStatus.ABANDONED.value}})
    return RedirectResponse(url="/lezione/", status_code=303)


@router.get("/lezione/{lesson_id}/complete", response_class=HTMLResponse)
async def lezione_complete(lesson_id: PydanticObjectId, request: Request, student: Student = Depends(get_current_student)):
    lesson = await _get_lesson(lesson_id, student)
    completed_count = sum(1 for a in lesson.activities if a.status == ActivityStatus.COMPLETED)
    skipped_count = sum(1 for a in lesson.activities if a.status == ActivityStatus.SKIPPED)
    weak_grammar_points = await get_weak_grammar_points(lesson)
    await ensure_lesson_feedback(lesson, weak_grammar_points)
    annotated_feedback = await discover_markdown(lesson.feedback_summary, student_id=student.id, lang="en") if lesson.feedback_summary else None
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
