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
    LearningEvent,
    Lesson,
    ActivityType,
    ActivityStatus,
    LessonStatus,
    CurriculumScenario,
    ScenarioProgress,
)
from maestro.profile import get_profile, save_onboarding_field
from maestro.learning.weakness import (
    build_gp_titles,
    build_grammar_by_level,
    top_weaknesses,
)
from maestro.vocab.query import get_word_definition
from maestro.drills.scoring import score_attempt
from maestro.learning.scorer import generate_writing_feedback
from maestro import taxonomy
from maestro.templates import templates
from maestro.utils import create_background_task, utcnow
from maestro.config import settings as _settings
from maestro.vocab.discover import (
    discover,
    discover_markdown,
    discover_list,
    lang_wrap,
    hide_translations,
)
from maestro.vocab.srs import review
from maestro.lezione.planner import prepare_lesson_immediate, generate_lesson_background
from markupsafe import escape
from maestro.lezione.service import (
    activity_url,
    advance_lesson,
    count_paid_lessons,
    ensure_lesson_feedback,
    get_lesson_events,
    get_weak_grammar_points,
    score_reading_activity,
    update_scenario_progress,
    _sweep_leftover_activities,
    _credit_a0_mastery,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_lesson(lesson_id: PydanticObjectId, student: Student) -> Lesson:
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        logger.warning("lesson not found: %s for student=%s", lesson_id, student.id)
        raise HTTPException(404)
    if lesson.student_id != student.id:
        logger.warning(
            "lesson access denied: lesson=%s student=%s", lesson_id, student.id
        )
        raise HTTPException(403)
    return lesson


@router.get("/lezione/", response_class=HTMLResponse)
async def lezione_index(
    request: Request, student: Student = Depends(get_current_student)
):
    active = await Lesson.find_one(
        {"student_id": student.id, "status": LessonStatus.ACTIVE}
    )
    if active:
        if active.generating and active.current_index >= len(active.activities):
            return RedirectResponse(url=f"/lezione/{active.id}/generating")
        return RedirectResponse(url=activity_url(active.id, active.current_index))

    profile = await get_profile(student.id)
    cefr = profile.cefr_estimate if profile else "A0"

    if cefr == "A0":
        return templates.TemplateResponse(
            request=request,
            name="lezione-index.html",
            context={"cefr": cefr},
        )

    # A1+: build config screen data
    from maestro.lezione.selection import pick_scenario as _pick_scenario

    # All scenarios at level with progress
    scenarios = await CurriculumScenario.find({"cefr_level": cefr}).to_list()
    if not scenarios:
        # No scenarios seeded for this level — fall back to simple start
        return templates.TemplateResponse(
            request=request,
            name="lezione-index.html",
            context={"cefr": "A0"},  # render A0 simple form
        )

    auto_scenario, auto_depth = await _pick_scenario(profile, cefr)

    scenarios.sort(key=lambda s: s.label)
    progress = profile.scenario_progress if profile else {}
    _no_progress = ScenarioProgress()
    scenario_options = [
        {
            "scenario": s,
            "depth_completed": progress.get(s.slug, _no_progress).depth,
            "max_depth": len(s.depths),
        }
        for s in scenarios
    ]

    # Compute weak GPs
    grammar_points = await GrammarPoint.find({"cefr_level": cefr}).to_list()
    gp_titles = build_gp_titles(grammar_points, cefr)
    grammar_by_level = build_grammar_by_level(grammar_points, profile, gp_titles)
    weaknesses = top_weaknesses(grammar_by_level, cefr)

    return templates.TemplateResponse(
        request=request,
        name="lezione-index.html",
        context={
            "cefr": cefr,
            "scenario_options": scenario_options,
            "auto_scenario_slug": auto_scenario.slug,
            "weaknesses": weaknesses,
            "persona": profile.persona if profile else None,
        },
    )


@router.post("/lezione/", response_class=HTMLResponse)
async def lezione_create(
    request: Request,
    student: Student = Depends(get_current_student),
    duration: Annotated[int, Form()] = 20,
    scenario_slug: Annotated[str, Form()] = "",
    focus_weak: Annotated[bool, Form()] = False,
    lesson_context: Annotated[str, Form(max_length=200)] = "",
):
    account = request.state.account
    if account.subscription_tier == "free":
        used = await count_paid_lessons(student.id)
        limit = _settings.FREE_TIER_LESSON_LIMIT_EX_A0
        if used >= limit:
            logger.info(
                "tier limit reached",
                extra={"student_id": str(student.id), "used": used, "limit": limit},
            )
            return templates.TemplateResponse(
                request=request,
                name="lezione-limit.html",
                context={"limit": limit},
                status_code=402,
            )

    # Abandon any existing active lessons before creating a new one
    await Lesson.find(
        {"student_id": student.id, "status": LessonStatus.ACTIVE}
    ).update_many({"$set": {"status": LessonStatus.ABANDONED.value}})

    profile = await get_profile(student.id)
    lesson = await prepare_lesson_immediate(
        duration,
        profile,
        student.id,
        lesson_context=lesson_context.strip(),
        focus_weak=focus_weak,
        scenario_slug=scenario_slug or None,
    )
    logger.info(
        "lesson created",
        extra={
            "student_id": str(student.id),
            "lesson_id": str(lesson.id),
            "scenario": scenario_slug or "auto",
        },
    )
    create_background_task(
        generate_lesson_background(
            lesson.id,
            duration,
            scenario_slug=scenario_slug or None,
            focus_weak=focus_weak,
        ),
        name=f"lesson-generate-{lesson.id}",
    )

    if lesson.activities:
        return RedirectResponse(url=f"/lezione/{lesson.id}/activity/0", status_code=303)
    else:
        return RedirectResponse(url=f"/lezione/{lesson.id}/generating", status_code=303)


@router.get("/lezione/{lesson_id}", response_class=HTMLResponse)
async def lezione_overview(
    lesson_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if lesson.status == LessonStatus.ACTIVE:
        return RedirectResponse(url=activity_url(lesson_id, lesson.current_index))
    if lesson.status == LessonStatus.COMPLETED:
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete")
    overview_lang = "en" if lesson.cefr_at_start == "A0" else _settings.TARGET_LANGUAGE
    annotated_overview = (
        await discover(lang_wrap(lesson.overview, overview_lang), student_id=student.id)
        if lesson.overview
        else None
    )
    return templates.TemplateResponse(
        request=request,
        name="lezione.html",
        context={"lesson": lesson, "annotated_overview": annotated_overview},
    )


@router.get("/lezione/{lesson_id}/generating", response_class=HTMLResponse)
async def lezione_generating(
    lesson_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
):
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
                await lesson.update(
                    {
                        "$set": {
                            f"activities.{next_idx}.status": ActivityStatus.ACTIVE.value,
                            "current_index": next_idx,
                        }
                    }
                )
                return RedirectResponse(
                    url=activity_url(lesson_id, next_idx), status_code=303
                )
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
            if lesson.cefr_at_start == "A0":
                await _credit_a0_mastery(lesson)
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete", status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="lezione-generating.html",
        context={"lesson": lesson},
    )


@router.post("/lezione/{lesson_id}/retry")
async def lezione_retry(
    lesson_id: PydanticObjectId, student: Student = Depends(get_current_student)
):
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
async def lezione_start(
    lesson_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if not lesson.activities:
        raise HTTPException(400, "Lesson has no activities")
    now = utcnow()
    await lesson.update(
        {
            "$set": {
                "status": LessonStatus.ACTIVE.value,
                "started_at": now,
                "current_index": 0,
                "activities.0.status": ActivityStatus.ACTIVE.value,
            }
        }
    )
    logger.info("lesson started: lesson=%s", lesson_id)
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
            return RedirectResponse(
                url=f"/lezione/{lesson_id}/generating", status_code=303
            )
        return RedirectResponse(url=f"/lezione/{lesson_id}/complete", status_code=303)
    activity = lesson.activities[idx]

    if activity.status == ActivityStatus.PENDING:
        return RedirectResponse(
            url=activity_url(lesson_id, lesson.current_index), status_code=303
        )

    is_review = activity.status in (ActivityStatus.COMPLETED, ActivityStatus.SKIPPED)

    # Only grammar activities can be revisited; redirect all others to current activity
    if is_review and activity.type != ActivityType.GRAMMAR:
        return RedirectResponse(
            url=activity_url(lesson_id, lesson.current_index), status_code=303
        )

    total = len(lesson.activities)

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
        ctx["annotated_content"] = hide_translations(
            await discover(lang_wrap(activity.content, lang), student_id=student.id)
        )
        ctx["annotated_questions"] = await discover_list(
            [lang_wrap(q, lang) for q in (activity.questions or [])],
            student_id=student.id,
        )
        return templates.TemplateResponse(
            request=request, name="lezione-activity-reading.html", context=ctx
        )

    if activity.type == ActivityType.LISTENING:
        lang = _settings.TARGET_LANGUAGE
        ctx["annotated_content"] = hide_translations(
            await discover(lang_wrap(activity.content, lang), student_id=student.id)
        )
        ctx["annotated_questions"] = await discover_list(
            [lang_wrap(q, lang) for q in (activity.questions or [])],
            student_id=student.id,
        )
        ctx["audio_url"] = activity.audio_path
        return templates.TemplateResponse(
            request=request, name="lezione-activity-listening.html", context=ctx
        )

    if activity.type == ActivityType.WRITING:
        lang = _settings.TARGET_LANGUAGE
        ctx["annotated_content"] = await discover_markdown(
            activity.content or "", student_id=student.id, lang=lang
        )
        return templates.TemplateResponse(
            request=request, name="lezione-activity-writing.html", context=ctx
        )

    if activity.type == ActivityType.GRAMMAR:
        ctx["annotated_content"] = hide_translations(
            await discover_markdown(activity.content or "", student_id=student.id)
        )
        profile = await get_profile(student.id)
        level = profile.cefr_estimate if profile else "A0"
        if activity.why_important:
            why_lang = (
                "en" if level in ("A0", "A1", "A2") else _settings.TARGET_LANGUAGE
            )
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
async def lezione_activity_skip(
    lesson_id: PydanticObjectId,
    idx: int,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    if activity.status in (ActivityStatus.COMPLETED, ActivityStatus.SKIPPED):
        if lesson.status == LessonStatus.COMPLETED:
            url = f"/lezione/{lesson.id}/complete"
        else:
            url = activity_url(lesson.id, lesson.current_index)
        return Response(status_code=204, headers={"HX-Redirect": url})
    redirect_url = await advance_lesson(lesson, idx, skip=True)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post("/lezione/{lesson_id}/activity/{idx}/complete")
async def lezione_activity_complete(
    lesson_id: PydanticObjectId,
    idx: int,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    if activity.status in (ActivityStatus.COMPLETED, ActivityStatus.SKIPPED):
        if lesson.status == LessonStatus.COMPLETED:
            url = f"/lezione/{lesson.id}/complete"
        else:
            url = activity_url(lesson.id, lesson.current_index)
        return Response(status_code=204, headers={"HX-Redirect": url})
    redirect_url = await advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post(
    "/lezione/{lesson_id}/activity/{idx}/onboarding-submit", response_class=HTMLResponse
)
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
    await lesson.update(
        {"$set": {f"activities.{idx}.result": {"answer": answer.strip()}}}
    )

    return templates.TemplateResponse(
        request=request,
        name="lezione-onboarding-response.html",
        context={"lesson": lesson, "idx": idx, "response_text": response_text},
    )


@router.post(
    "/lezione/{lesson_id}/activity/{idx}/drill-submit", response_class=HTMLResponse
)
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

    student_input: list[str] | str = (
        answers if drill.items else (answers[0] if answers else "")
    )

    correct, event, feedback, rule_refs = await score_attempt(
        drill, student_input, student_id=student.id, lesson_id=lesson.id
    )

    stored_answer = (
        json.dumps(answers) if len(answers) > 1 else (answers[0] if answers else "")
    )
    attempt = DrillAttempt(
        student_id=student.id,
        generated_drill=drill,
        student_answer=stored_answer,
        correct=correct,
    )
    await attempt.insert()
    drill.used = True
    await drill.save()

    if event:
        event.lesson_id = lesson.id
        event.activity_type = ActivityType.DRILL.value
        event.activity_index = idx
        event.student_text = stored_answer
        await event.insert()

    drill_result: dict = {"correct": correct, "student_answer": stored_answer}

    # Capture per-item scoring detail for later inspection / flagging
    if drill.items and isinstance(feedback, dict) and "items" in feedback:
        # Multi-item drill: store per-item scores
        drill_result["item_scores"] = [
            {
                "objective_correct": item.get("objective_correct", False),
                "tips": item.get("tips", []),
                "objective_note": item.get("objective_note", ""),
                "grammar_errors": item.get("grammar_errors", []),
            }
            for item in feedback.get("items", [])
        ]
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


@router.get(
    "/lezione/{lesson_id}/activity/{idx}/vocab-reveal", response_class=HTMLResponse
)
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
            headers={
                "HX-Redirect": f"/lezione/{lesson_id}/activity/{idx}?card_idx={next_card_idx}"
            },
        )
    redirect_url = await advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post(
    "/lezione/{lesson_id}/activity/{idx}/writing-submit", response_class=HTMLResponse
)
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
        student_id=student.id,
        lesson_id=lesson.id,
    )

    await taxonomy.ensure_loaded()
    valid_codes = {g.code for g in taxonomy.grammar_points()}
    event = LearningEvent(
        student_id=student.id,
        lesson_id=lesson.id,
        activity_type=ActivityType.WRITING.value,
        activity_index=idx,
        student_text=answer,
        grammar_correct=[
            c for c in feedback.get("grammar_correct_codes", []) if c in valid_codes
        ],
        grammar_errors=[
            c for c in feedback.get("grammar_error_codes", []) if c in valid_codes
        ],
    )
    await event.insert()

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
            "correct": feedback.get("objective_correct", True)
            if isinstance(feedback, dict)
            else True,
            "feedback": feedback,
            "rule_refs": [],
            "next_url": next_url,
            "idx": idx,
            "total": len(lesson.activities),
            "is_writing": True,
        },
    )


@router.post(
    "/lezione/{lesson_id}/activity/{idx}/reading-submit", response_class=HTMLResponse
)
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
    overall_correct, feedback, gp_correct, gp_errors = await score_reading_activity(
        questions,
        correct_answers,
        answers,
        cefr_level=lesson.cefr_at_start,
        student_id=student.id,
        lesson_id=lesson.id,
    )

    joined_answers = " | ".join(a for a in answers if a)
    event = LearningEvent(
        student_id=student.id,
        lesson_id=lesson.id,
        activity_type=activity.type.value,
        activity_index=idx,
        student_text=joined_answers,
        grammar_correct=gp_correct,
        grammar_errors=gp_errors,
    )
    await event.insert()

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
async def lezione_abandon(
    lesson_id: PydanticObjectId, student: Student = Depends(get_current_student)
):
    lesson = await _get_lesson(lesson_id, student)
    if lesson.status == LessonStatus.ACTIVE:
        await lesson.update({"$set": {"status": LessonStatus.ABANDONED.value}})
        logger.info("lesson abandoned: lesson=%s", lesson_id)
    return Response(status_code=204, headers={"HX-Redirect": "/lezione/"})


@router.get("/lezione/{lesson_id}/complete", response_class=HTMLResponse)
async def lezione_complete(
    lesson_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    completed_count = sum(
        1 for a in lesson.activities if a.status == ActivityStatus.COMPLETED
    )
    skipped_count = sum(
        1 for a in lesson.activities if a.status == ActivityStatus.SKIPPED
    )
    events = await get_lesson_events(lesson)
    weak_grammar_points = await get_weak_grammar_points(lesson, events)
    await ensure_lesson_feedback(lesson, weak_grammar_points, events)
    annotated_feedback = (
        await discover_markdown(
            lesson.feedback_summary, student_id=student.id, lang="en"
        )
        if lesson.feedback_summary
        else None
    )

    # Detect CEFR graduation
    graduated_to = None
    profile = await get_profile(student.id)
    if (
        profile
        and lesson.cefr_at_start
        and profile.cefr_estimate != lesson.cefr_at_start
    ):
        graduated_to = profile.cefr_estimate

    # Collect grammar points covered in this lesson (preserving block order)
    covered_gp_codes = [
        a.grammar_point_code
        for a in lesson.activities
        if a.type == ActivityType.GRAMMAR and a.grammar_point_code
    ]
    if covered_gp_codes:
        gp_by_code = {
            gp.code: gp
            for gp in await GrammarPoint.find(
                {"code": {"$in": covered_gp_codes}}
            ).to_list()
        }
        covered_grammar_points = [
            gp_by_code[c] for c in covered_gp_codes if c in gp_by_code
        ]
    else:
        covered_grammar_points = []

    return templates.TemplateResponse(
        request=request,
        name="lezione-complete.html",
        context={
            "lesson": lesson,
            "completed_count": completed_count,
            "skipped_count": skipped_count,
            "weak_grammar_points": weak_grammar_points,
            "covered_grammar_points": covered_grammar_points,
            "annotated_feedback": annotated_feedback,
            "graduated_to": graduated_to,
        },
    )
