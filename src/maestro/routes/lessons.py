import asyncio
import json
import logging
import random
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
    CommunicativeFunction,
    ScenarioProgress,
)
from maestro.learning.profile import get_profile, save_onboarding_field
from maestro.learning.weakness import (
    build_grammar_by_level,
    build_titles,
    build_tooltip_data,
    top_weaknesses,
)
from maestro.vocab.query import get_word_definition
from maestro.lessons.drill_scoring import score_attempt
from maestro.learning.scorer import (
    generate_writing_feedback,
    generate_speaking_feedback,
)
from maestro.i18n import t
from maestro.rate_limit import limiter
from maestro.learning import grammar_cache
from maestro.templates import render_with_discover
from maestro.utils import create_background_task, ensure_utc, utcnow
from maestro.config import settings as _settings
from maestro.vocab.srs import review
from maestro.lessons.planner import prepare_lesson_immediate, generate_lesson_background
from maestro.i18n import strings_t as st
from maestro.learning.onboarding import skip_onboarding as _skip_onboarding
from markupsafe import escape
from maestro.lessons.lifecycle import (
    activity_url,
    advance_lesson,
    count_paid_lessons,
    ensure_lesson_feedback,
    get_lesson_discovered_words,
    get_lesson_events,
    get_weak_grammar_points,
    score_reading_activity,
    update_scenario_progress,
    _sweep_leftover_activities,
    _credit_a0_mastery,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_GENERATION_TIMEOUT_SECONDS = 180  # 3 minutes


def _review_redirect(lesson_id, idx) -> Response:
    """Redirect to the activity review page after submission.

    Returns HX-Redirect for HTMX requests and a <script> redirect
    for fetch-based handlers (speaking).
    """
    url = f"/lessons/{lesson_id}/activity/{idx}"
    html = f'<script>window.location.href="{url}"</script>'
    return Response(
        content=html,
        media_type="text/html",
        headers={"HX-Redirect": url},
    )


_LEARNING_TYPES = {
    ActivityType.GRAMMAR,
    ActivityType.DRILL,
    ActivityType.READING,
    ActivityType.LISTENING,
    ActivityType.WRITING,
    ActivityType.SPEAKING,
    ActivityType.VOCAB_REVIEW,
}


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


@router.get("/onboarding/skip")
async def skip_onboarding(
    request: Request, student: Student = Depends(get_current_student)
):
    await _skip_onboarding(student.id)
    return RedirectResponse(url="/lessons/", status_code=303)


@router.get("/lessons/", response_class=HTMLResponse)
async def lesson_index(
    request: Request, student: Student = Depends(get_current_student)
):
    active = await Lesson.find_one(
        {"student_id": student.id, "status": LessonStatus.ACTIVE}
    )
    if active:
        if active.generating and active.current_index >= len(active.activities):
            return RedirectResponse(url=f"/lessons/{active.id}/generating")
        return RedirectResponse(url=activity_url(active.id, active.current_index))

    profile = await get_profile(student.id)
    cefr = profile.active_progress.cefr_estimate if profile else "A0"

    if cefr == "A0":
        from maestro.lessons.selection import pick_scenario as _pick_a0_scenario

        a0_scenarios = await CurriculumScenario.find({"cefr_level": "A0"}).to_list()
        progress = profile.active_progress.scenario_progress if profile else {}
        a0_completed = sum(
            1
            for s in a0_scenarios
            if progress.get(s.slug, ScenarioProgress()).depth >= 1
        )
        a0_total = len(a0_scenarios)
        a0_lesson_number = a0_completed + 1
        show_welcome = a0_lesson_number == 1

        # Next scenario preview (always) + lesson history (returning students only)
        next_scenario = None
        if a0_scenarios:
            next_scenario_doc, _ = await _pick_a0_scenario(
                profile, "A0", scenarios=a0_scenarios, language=profile.target_language
            )
            next_scenario = next_scenario_doc
        lesson_history: list[dict] = []
        if not show_welcome:
            recent_lessons = (
                await Lesson.find(
                    {"student_id": student.id, "status": LessonStatus.COMPLETED}
                )
                .sort(-Lesson.completed_at)
                .limit(5)
                .to_list()
            )
            scenario_labels = {s.slug: s.label for s in a0_scenarios}
            lesson_history = [
                {
                    "lesson": lesson,
                    "scenario_label": scenario_labels.get(lesson.scenario_slug, ""),
                }
                for lesson in recent_lessons
            ]

        return await render_with_discover(
            request,
            "lesson-index.html",
            {
                "cefr": cefr,
                "show_welcome": show_welcome,
                "a0_lesson_number": a0_lesson_number,
                "a0_total": a0_total,
                "next_scenario": next_scenario,
                "lesson_history": lesson_history,
            },
            student_id=student.id,
        )

    # A1+: build config screen data
    from maestro.lessons.selection import pick_scenario as _pick_scenario

    # All scenarios at level with progress
    lang = request.state.lang_ctx.code
    scenarios = await CurriculumScenario.find(
        {"cefr_level": cefr, "language": lang}
    ).to_list()
    if not scenarios:
        # No scenarios seeded for this level — fall back to simple start
        return await render_with_discover(
            request, "lesson-index.html", {"cefr": "A0"}, student_id=student.id
        )

    auto_scenario, auto_depth = await _pick_scenario(profile, cefr, language=lang)

    scenarios.sort(key=lambda s: s.label)
    progress = profile.active_progress.scenario_progress if profile else {}
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
    gp_titles = build_titles(grammar_points, cefr, lang)
    grammar_by_level = build_grammar_by_level(grammar_points, profile, gp_titles)
    weaknesses = top_weaknesses(grammar_by_level, cefr)

    return await render_with_discover(
        request,
        "lesson-index.html",
        {
            "cefr": cefr,
            "scenario_options": scenario_options,
            "auto_scenario_slug": auto_scenario.slug,
            "weaknesses": weaknesses,
            "persona": profile.persona if profile else None,
        },
        student_id=student.id,
    )


@router.post("/lessons/", response_class=HTMLResponse)
async def lesson_create(
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
            return await render_with_discover(
                request,
                "lesson-limit.html",
                {"limit": limit},
                student_id=student.id,
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
        return RedirectResponse(url=f"/lessons/{lesson.id}/activity/0", status_code=303)
    else:
        return RedirectResponse(url=f"/lessons/{lesson.id}/generating", status_code=303)


@router.get("/lessons/{lesson_id}", response_class=HTMLResponse)
async def lesson_overview(
    lesson_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    if lesson.status == LessonStatus.ACTIVE:
        return RedirectResponse(url=activity_url(lesson_id, lesson.current_index))
    if lesson.status == LessonStatus.COMPLETED:
        return RedirectResponse(url=f"/lessons/{lesson_id}/complete")
    overview_lang = "en" if lesson.cefr_at_start == "A0" else lesson.language
    return await render_with_discover(
        request,
        "lesson.html",
        {"lesson": lesson, "overview_lang": overview_lang},
        student_id=student.id,
        create_cards=True,
    )


@router.get("/lessons/{lesson_id}/generating", response_class=HTMLResponse)
async def lesson_generating(
    lesson_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    is_htmx = request.headers.get("HX-Request") == "true"

    # Detect generation timeout
    if (
        lesson.generating
        and lesson.generation_started_at is not None
        and (utcnow() - ensure_utc(lesson.generation_started_at)).total_seconds()
        > _GENERATION_TIMEOUT_SECONDS
    ):
        elapsed = (utcnow() - ensure_utc(lesson.generation_started_at)).total_seconds()
        logger.warning(
            "lesson generation timed out",
            extra={
                "lesson_id": str(lesson_id),
                "started_at": lesson.generation_started_at.isoformat(),
                "elapsed_s": round(elapsed, 1),
            },
        )
        await Lesson.find_one(
            Lesson.id == lesson_id,
            Lesson.generating == True,  # noqa: E712
        ).update(
            {
                "$set": {
                    "generating": False,
                    "generation_error": "Lesson generation took too long. Please try again.",
                    "status": LessonStatus.ABANDONED.value,
                }
            }
        )
        # Re-fetch to get authoritative state (handles race with background task)
        lesson = await _get_lesson(lesson_id, student)

    if not lesson.generating:
        if lesson.generation_error:
            # Show error state with retry button
            return await render_with_discover(
                request,
                "lesson-generating.html",
                {"lesson": lesson},
                student_id=student.id,
            )
        dest = None
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
                dest = activity_url(lesson_id, next_idx)
                break
            next_idx += 1
        if dest is None:
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
            dest = f"/lessons/{lesson_id}/complete"
        # HX-Redirect forces a full page navigation so scripts reinitialize
        if is_htmx:
            return Response(status_code=200, headers={"HX-Redirect": dest})
        return RedirectResponse(url=dest, status_code=303)
    return await render_with_discover(
        request,
        "lesson-generating.html",
        {"lesson": lesson},
        student_id=student.id,
    )


@router.post("/lessons/{lesson_id}/retry")
async def lesson_retry(
    lesson_id: PydanticObjectId, student: Student = Depends(get_current_student)
):
    lesson = await _get_lesson(lesson_id, student)
    if lesson.status == LessonStatus.COMPLETED:
        return RedirectResponse(url=f"/lessons/{lesson_id}/complete", status_code=303)

    await lesson.update(
        {
            "$set": {
                "generating": True,
                "generation_error": None,
                "generation_started_at": utcnow(),
            }
        }
    )

    create_background_task(
        generate_lesson_background(lesson.id, lesson.duration_minutes),
        name=f"lesson-retry-{lesson.id}",
    )

    return RedirectResponse(url=f"/lessons/{lesson_id}/generating", status_code=303)


@router.post("/lessons/{lesson_id}/start", response_class=HTMLResponse)
async def lesson_start(
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


@router.get("/lessons/{lesson_id}/activity/{idx}", response_class=HTMLResponse)
async def lesson_activity(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    student: Student = Depends(get_current_student),
    card_idx: int = 0,
    mode: str = "random",
    correct: int = 0,
    incorrect: int = 0,
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        if lesson.generating:
            return RedirectResponse(
                url=f"/lessons/{lesson_id}/generating", status_code=303
            )
        return RedirectResponse(url=f"/lessons/{lesson_id}/complete", status_code=303)
    activity = lesson.activities[idx]

    if activity.status == ActivityStatus.PENDING:
        return RedirectResponse(
            url=activity_url(lesson_id, lesson.current_index), status_code=303
        )

    is_review = activity.status in (ActivityStatus.COMPLETED, ActivityStatus.SKIPPED)

    # Completed scored activities — show review template with original context + corrections
    if is_review and activity.result:
        result = activity.result
        total = len(lesson.activities)
        review_ctx = {
            "lesson": lesson,
            "activity": activity,
            "idx": idx,
            "total": total,
            "is_review": True,
            "correct": result.get("correct"),
            "feedback": result.get("feedback"),
        }

        if activity.type == ActivityType.SPEAKING:
            review_ctx.update(
                recognized_text=result.get("recognized_text"),
                pronunciation_score=result.get("pronunciation_score"),
                accuracy_score=result.get("accuracy_score"),
                fluency_score=result.get("fluency_score"),
                words=result.get("word_assessments", []),
            )
            return await render_with_discover(
                request,
                "review-activity-speaking.html",
                review_ctx,
                student_id=student.id,
            )

        if activity.type == ActivityType.DRILL and activity.drill_id:
            drill = await GeneratedDrill.get(activity.drill_id)
            review_ctx.update(drill=drill, rule_refs=[])
            return await render_with_discover(
                request,
                "review-activity-drill.html",
                review_ctx,
                student_id=student.id,
            )

        if activity.type == ActivityType.WRITING:
            review_ctx.update(
                content=activity.content or "",
                student_answer=result.get("student_answer", ""),
            )
            return await render_with_discover(
                request,
                "review-activity-writing.html",
                review_ctx,
                student_id=student.id,
            )

        if activity.type in (ActivityType.READING, ActivityType.LISTENING):
            review_ctx.update(
                student_answers=result.get("student_answers", []),
                question_lang="en" if lesson.cefr_at_start == "A0" else lesson.language,
            )
            if activity.type == ActivityType.LISTENING:
                review_ctx["audio_url"] = activity.audio_path
                template = "review-activity-listening.html"
            else:
                template = "review-activity-reading.html"
            return await render_with_discover(
                request,
                template,
                review_ctx,
                student_id=student.id,
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
        ctx["drill"] = drill
        return await render_with_discover(
            request,
            "lesson-activity-drill.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    if activity.type == ActivityType.VOCAB_REVIEW:
        card_ids = activity.card_ids
        total_cards = len(card_ids)
        if mode not in ("word", "translation", "random"):
            mode = "random"
        correct = max(0, min(correct, total_cards))
        incorrect = max(0, min(incorrect, total_cards))
        selected_mode = mode
        resolved_mode = (
            random.choice(("word", "translation")) if mode == "random" else mode
        )

        def _vocab_complete_ctx(c: int, ic: int, cont_url: str) -> dict:
            return dict(
                is_complete=True,
                correct=c,
                incorrect=ic,
                continue_url=cont_url,
                card=None,
                mode=resolved_mode,
                selected_mode=selected_mode,
                mode_url_prefix=f"/lessons/{lesson_id}/activity/{idx}?card_idx=0&correct=0&incorrect=0&mode=",
                total_cards=total_cards,
            )

        if is_review:
            result = activity.result or {}
            continue_url = (
                f"/lessons/{lesson_id}/complete"
                if lesson.status == LessonStatus.COMPLETED
                else activity_url(lesson_id, lesson.current_index)
            )
            ctx.update(
                _vocab_complete_ctx(
                    result.get("correct", 0),
                    result.get("incorrect", 0),
                    continue_url,
                )
            )
            return await render_with_discover(
                request,
                "lesson-activity-vocab.html",
                ctx,
                student_id=student.id,
                create_cards=True,
            )
        # Discovered-scope: populate card_ids dynamically on first visit
        if activity.review_scope == "discovered" and not activity.card_ids:
            discovered = await get_lesson_discovered_words(lesson)
            # Exclude cards already assigned to earlier discovered reviews
            already_reviewed: set = set()
            for prev in lesson.activities[:idx]:
                if prev.review_scope == "discovered" and prev.card_ids:
                    already_reviewed.update(prev.card_ids)
            discovered = [w for w in discovered if w.id not in already_reviewed]
            if not discovered:
                # No new words discovered — auto-skip
                redirect_url = await advance_lesson(lesson, idx, skip=True)
                return RedirectResponse(url=redirect_url, status_code=303)
            card_ids_new = [w.id for w in discovered]
            title = st("vocab_discovered_title", count=len(card_ids_new))
            await lesson.update(
                {
                    "$set": {
                        f"activities.{idx}.card_ids": card_ids_new,
                        f"activities.{idx}.title": title,
                    }
                }
            )
            activity.card_ids = card_ids_new
            activity.title = title
        card_ids = activity.card_ids
        total_cards = len(card_ids)
        if not card_ids:
            # No vocab cards — auto-skip this activity
            redirect_url = await advance_lesson(lesson, idx)
            return RedirectResponse(url=redirect_url, status_code=303)

        if card_idx >= total_cards:
            # All cards reviewed — advance and show results
            await advance_lesson(
                lesson, idx, result={"correct": correct, "incorrect": incorrect}
            )
            continue_url = (
                f"/lessons/{lesson_id}/complete"
                if lesson.status == LessonStatus.COMPLETED
                else activity_url(lesson_id, lesson.current_index)
            )
            ctx.update(_vocab_complete_ctx(correct, incorrect, continue_url))
            return await render_with_discover(
                request,
                "lesson-activity-vocab.html",
                ctx,
                student_id=student.id,
                create_cards=True,
            )

        card = await UserVocabularyCard.get(card_ids[card_idx])
        if card is None:
            raise HTTPException(404)
        await card.fetch_all_links()
        profile = await get_profile(student.id)
        level = profile.active_progress.cefr_estimate if profile else "A0"
        word_def = await get_word_definition(card.word, level)
        ctx.update(
            card=card,
            word_def=word_def,
            mode=resolved_mode,
            selected_mode=selected_mode,
            correct=correct,
            incorrect=incorrect,
            total_cards=total_cards,
            reveal_url=(
                f"/lessons/{lesson_id}/activity/{idx}/vocab-reveal"
                f"?card_idx={card_idx}&mode={resolved_mode}"
                f"&correct={correct}&incorrect={incorrect}"
            ),
            mode_url_prefix=(
                f"/lessons/{lesson_id}/activity/{idx}"
                f"?card_idx={card_idx}&correct={correct}&incorrect={incorrect}&mode="
            ),
        )
        return await render_with_discover(
            request,
            "lesson-activity-vocab.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    if activity.type == ActivityType.READING:
        ctx["question_lang"] = "en" if lesson.cefr_at_start == "A0" else lesson.language
        return await render_with_discover(
            request,
            "lesson-activity-reading.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    if activity.type == ActivityType.LISTENING:
        ctx["audio_url"] = activity.audio_path
        ctx["question_lang"] = "en" if lesson.cefr_at_start == "A0" else lesson.language
        return await render_with_discover(
            request,
            "lesson-activity-listening.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    if activity.type == ActivityType.WRITING:
        ctx["content"] = activity.content or ""
        return await render_with_discover(
            request,
            "lesson-activity-writing.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    if activity.type == ActivityType.GRAMMAR:
        ctx["content"] = activity.content or ""
        profile = await get_profile(student.id)
        level = profile.active_progress.cefr_estimate if profile else "A0"
        if activity.why_important:
            why_lang = "en" if level in ("A0", "A1", "A2") else lesson.language
            ctx["why_lang"] = why_lang
        # Find the GP and its explanation for translation + chunk_ref
        if activity.grammar_point_code:
            gp = await GrammarPoint.find_one({"code": activity.grammar_point_code})
        else:
            # Fallback for old lessons without the field
            gp_label = activity.title.replace("Grammatica: ", "")
            gp = await GrammarPoint.find_one({"label": gp_label})
        if gp:
            ctx["chunk_ref"] = gp.chunk_ref
            if not activity.why_important:
                expl_lang = "it" if level in ("B1", "B2") else "en"
                expl = gp.explanations.get(expl_lang) or next(
                    (gp.explanations[k] for k in ("en", "it") if k in gp.explanations),
                    None,
                )
                if expl and expl.why_this_matters:
                    ctx["why_this_matters"] = expl.why_this_matters
        return await render_with_discover(
            request,
            "lesson-activity-grammar.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    if activity.type == ActivityType.INTRO:
        gp_codes = activity.grammar_point_codes
        cf_codes = activity.cf_codes
        grammar_points = (
            await GrammarPoint.find({"code": {"$in": gp_codes}}).to_list()
            if gp_codes
            else []
        )
        comm_functions = (
            await CommunicativeFunction.find({"code": {"$in": cf_codes}}).to_list()
            if cf_codes
            else []
        )
        cefr = lesson.cefr_at_start or "A1"
        lang = lesson.language
        ctx["grammar_points"] = grammar_points
        ctx["gp_titles"] = build_titles(grammar_points, cefr, lang)
        ctx["gp_tooltip_data"] = build_tooltip_data(grammar_points, cefr, lang)
        ctx["comm_functions"] = comm_functions
        ctx["cf_titles"] = build_titles(comm_functions, cefr, lang)
        ctx["cf_tooltip_data"] = build_tooltip_data(comm_functions, cefr, lang)
        if lesson.scenario_slug:
            scenario = await CurriculumScenario.find_one({"slug": lesson.scenario_slug})
            if scenario and scenario.image:
                ctx["scenario_image_url"] = f"/static/{scenario.image}"
        return await render_with_discover(
            request,
            "lesson-activity-intro.html",
            ctx,
            student_id=student.id,
            create_cards=False,
        )

    if activity.type == ActivityType.INFO:
        ctx["content"] = activity.content or ""
        return await render_with_discover(
            request,
            "lesson-activity-info.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    if activity.type == ActivityType.SPEAKING:
        return await render_with_discover(
            request,
            "lesson-activity-speaking.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    if activity.type == ActivityType.ONBOARDING:
        return await render_with_discover(
            request,
            "lesson-activity-onboarding.html",
            ctx,
            student_id=student.id,
            create_cards=True,
        )

    raise HTTPException(400, f"Unknown activity type: {activity.type}")


@router.post("/lessons/{lesson_id}/activity/{idx}/skip")
async def lesson_activity_skip(
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
            url = f"/lessons/{lesson.id}/complete"
        else:
            url = activity_url(lesson.id, lesson.current_index)
        return Response(status_code=204, headers={"HX-Redirect": url})
    redirect_url = await advance_lesson(lesson, idx, skip=True)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post("/lessons/{lesson_id}/activity/{idx}/complete")
async def lesson_activity_complete(
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
            url = f"/lessons/{lesson.id}/complete"
        else:
            url = activity_url(lesson.id, lesson.current_index)
        return Response(status_code=204, headers={"HX-Redirect": url})
    redirect_url = await advance_lesson(lesson, idx)
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post(
    "/lessons/{lesson_id}/activity/{idx}/onboarding-submit", response_class=HTMLResponse
)
async def lesson_onboarding_submit(
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

    if activity.profile_field == "combined":
        # Combined form: save all fields at once
        result = {}
        for field in ("name", "background", "interests", "goal"):
            value = form.get(field, "")
            if value and value.strip():
                await save_onboarding_field(student, field, value.strip())
                result[field] = value.strip()

        await lesson.update({"$set": {f"activities.{idx}.result": result}})

        response_text = t("onboarding_combined_response")
    else:
        answer = form.get("answer", "")
        await save_onboarding_field(student, activity.profile_field, answer)

        response_text = activity.response_template or "Got it!"
        response_text = response_text.replace("{answer}", str(escape(answer.strip())))

        await lesson.update(
            {"$set": {f"activities.{idx}.result": {"answer": answer.strip()}}}
        )

    return await render_with_discover(
        request,
        "lesson-onboarding-response.html",
        {"lesson": lesson, "idx": idx, "response_text": response_text},
        student_id=student.id,
    )


@router.post(
    "/lessons/{lesson_id}/activity/{idx}/drill-submit", response_class=HTMLResponse
)
async def lesson_drill_submit(
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

    try:
        correct, event, feedback, rule_refs = await score_attempt(
            drill,
            student_input,
            student_id=student.id,
            lesson_id=lesson.id,
            language=lesson.language,
        )
    except Exception:
        logger.exception(
            "scoring failed for drill", extra={"lesson_id": str(lesson.id), "idx": idx}
        )
        _err_feedback = {"scoring_unavailable": t("scoring_unavailable")}
        await advance_lesson(
            lesson,
            idx,
            result={"correct": None, "student_answer": "", "feedback": _err_feedback},
        )
        return _review_redirect(lesson_id, idx)

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
        logger.debug(
            "drill event stored",
            extra={
                "lesson_id": str(lesson.id),
                "grammar_errors": event.grammar_errors,
                "grammar_correct": event.grammar_correct,
            },
        )

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
    drill_result["feedback"] = feedback
    await advance_lesson(lesson, idx, result=drill_result)

    return _review_redirect(lesson_id, idx)


@router.get(
    "/lessons/{lesson_id}/activity/{idx}/vocab-reveal", response_class=HTMLResponse
)
async def lesson_vocab_reveal(
    lesson_id: PydanticObjectId,
    idx: int,
    request: Request,
    student: Student = Depends(get_current_student),
    card_idx: int = 0,
    mode: str = "word",
    correct: int = 0,
    incorrect: int = 0,
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
    level = profile.active_progress.cefr_estimate if profile else "A0"
    word_def = await get_word_definition(card.word, level)
    return await render_with_discover(
        request,
        "vocab-card-back.html",
        {
            "card": card,
            "word_def": word_def,
            "mode": mode,
            "card_idx": card_idx,
            "total_cards": len(card_ids),
            "review_url": f"/lessons/{lesson_id}/activity/{idx}/vocab-rate",
            "review_extra_name": "card_idx",
            "review_extra_value": card_idx,
            "correct": correct,
            "incorrect": incorrect,
        },
    )


@router.post("/lessons/{lesson_id}/activity/{idx}/vocab-rate")
async def lesson_vocab_rate(
    lesson_id: PydanticObjectId,
    idx: int,
    rating: Annotated[int, Form()],
    card_idx: Annotated[int, Form()],
    student: Student = Depends(get_current_student),
    mode: Annotated[str, Form()] = "random",
    correct: Annotated[int, Form()] = 0,
    incorrect: Annotated[int, Form()] = 0,
):
    lesson = await _get_lesson(lesson_id, student)
    if idx >= len(lesson.activities):
        raise HTTPException(404)
    activity = lesson.activities[idx]
    card_ids = activity.card_ids
    if card_idx >= len(card_ids):
        raise HTTPException(404)
    if mode not in ("word", "translation", "random"):
        mode = "random"
    correct = max(0, min(correct, len(card_ids)))
    incorrect = max(0, min(incorrect, len(card_ids)))

    card = await UserVocabularyCard.get(card_ids[card_idx])
    if card is None:
        raise HTTPException(404)
    if card.student_id != student.id:
        raise HTTPException(403)
    card = review(card, rating)
    await card.save()

    new_correct = correct + (1 if rating >= 3 else 0)
    new_incorrect = incorrect + (1 if rating < 3 else 0)

    next_card_idx = card_idx + 1
    redirect_url = (
        f"/lessons/{lesson_id}/activity/{idx}"
        f"?card_idx={next_card_idx}&mode={mode}"
        f"&correct={new_correct}&incorrect={new_incorrect}"
    )
    return Response(status_code=204, headers={"HX-Redirect": redirect_url})


@router.post(
    "/lessons/{lesson_id}/activity/{idx}/writing-submit", response_class=HTMLResponse
)
async def lesson_writing_submit(
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
    cefr_level = profile.active_progress.cefr_estimate if profile else "A0"

    try:
        feedback = await generate_writing_feedback(
            activity.content or "",
            answer,
            cefr_level,
            student_id=student.id,
            lesson_id=lesson.id,
            language=lesson.language,
        )
    except Exception:
        logger.exception(
            "scoring failed for writing",
            extra={"lesson_id": str(lesson.id), "idx": idx},
        )
        _err_feedback = {"scoring_unavailable": t("scoring_unavailable")}
        await advance_lesson(
            lesson, idx, result={"student_answer": answer, "feedback": _err_feedback}
        )
        return _review_redirect(lesson_id, idx)

    await grammar_cache.ensure_loaded(lesson.language)
    valid_codes = {g.code for g in grammar_cache.grammar_points(lesson.language)}
    event = LearningEvent(
        student_id=student.id,
        lesson_id=lesson.id,
        activity_type=ActivityType.WRITING.value,
        activity_index=idx,
        evidence_type="productive",
        student_text=answer,
        grammar_correct=[
            c for c in feedback.get("grammar_correct_codes", []) if c in valid_codes
        ],
        grammar_errors=[
            c for c in feedback.get("grammar_error_codes", []) if c in valid_codes
        ],
        themes=feedback.get("themes", []),
    )
    await event.insert()
    logger.debug(
        "writing event stored",
        extra={
            "lesson_id": str(lesson.id),
            "grammar_errors": event.grammar_errors,
            "grammar_correct": event.grammar_correct,
        },
    )

    writing_result = {"student_answer": answer, "feedback": feedback}
    await advance_lesson(lesson, idx, result=writing_result)

    return _review_redirect(lesson_id, idx)


@router.post(
    "/lessons/{lesson_id}/activity/{idx}/speaking-submit", response_class=HTMLResponse
)
async def lesson_speaking_submit(
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
    audio_file = form.get("audio")
    if audio_file is None or not hasattr(audio_file, "read"):
        raise HTTPException(400, "No audio file provided")

    max_audio_bytes = 2 * 1024 * 1024  # 2 MB
    audio_bytes = await audio_file.read(max_audio_bytes + 1)
    if len(audio_bytes) > max_audio_bytes:
        raise HTTPException(413, "Audio file too large")

    if audio_bytes[:4] != b"RIFF":
        raise HTTPException(400, "Invalid audio format — expected WAV")

    # --- Stage 1: Transcribe ---
    from maestro.stt import transcribe, assess_pronunciation

    recognized_text = None
    try:
        transcription = await transcribe(audio_bytes, language=lesson.language)
        recognized_text = transcription.recognized_text
    except Exception:
        logger.exception(
            "transcription failed for speaking",
            extra={"lesson_id": str(lesson.id), "idx": idx},
        )
        await advance_lesson(
            lesson, idx, result={"student_answer": "", "correct": None}
        )
        return _review_redirect(lesson_id, idx)

    # --- Empty check ---
    if not recognized_text or not recognized_text.strip():
        await advance_lesson(
            lesson, idx, result={"student_answer": "", "correct": None}
        )
        return _review_redirect(lesson_id, idx)

    # --- Stage 2 + 3: LLM feedback + Pronunciation (parallel) ---
    profile = await get_profile(student.id)
    cefr_level = profile.active_progress.cefr_estimate if profile else "A0"
    prompt_text = activity.content or ""

    feedback_coro = generate_speaking_feedback(
        prompt_text,
        recognized_text,
        cefr_level,
        student_id=student.id,
        lesson_id=lesson.id,
        language=lesson.language,
    )
    pronunciation_coro = assess_pronunciation(
        audio_bytes, recognized_text, language=lesson.language
    )

    results = await asyncio.gather(
        feedback_coro, pronunciation_coro, return_exceptions=True
    )
    feedback_result = results[0]
    pronunciation_result = results[1]

    # Handle partial failures
    feedback = None
    if isinstance(feedback_result, Exception):
        logger.error(
            "LLM feedback failed for speaking",
            extra={"lesson_id": str(lesson.id), "idx": idx},
            exc_info=feedback_result,
        )
    else:
        feedback = feedback_result

    pronunciation = None
    if isinstance(pronunciation_result, Exception):
        logger.error(
            "pronunciation scoring failed for speaking",
            extra={"lesson_id": str(lesson.id), "idx": idx},
            exc_info=pronunciation_result,
        )
    else:
        pronunciation = pronunciation_result

    # Both failed → scoring_unavailable
    if feedback is None and pronunciation is None:
        await advance_lesson(
            lesson,
            idx,
            result={
                "student_answer": recognized_text,
                "recognized_text": recognized_text,
                "correct": None,
            },
        )
        return _review_redirect(lesson_id, idx)

    # --- Build result and LearningEvent ---
    speaking_result = {"student_answer": recognized_text}
    if pronunciation:
        speaking_result.update(
            {
                "pronunciation_score": pronunciation.pronunciation_score,
                "accuracy_score": pronunciation.accuracy_score,
                "fluency_score": pronunciation.fluency_score,
                "completeness_score": pronunciation.completeness_score,
                "recognized_text": recognized_text,
            }
        )
        speaking_result["word_assessments"] = [
            {
                "word": w.word,
                "accuracy_score": w.accuracy_score,
                "error_type": w.error_type,
                "offset_seconds": w.offset_seconds,
                "duration_seconds": w.duration_seconds,
            }
            for w in pronunciation.words
        ]
    else:
        speaking_result["recognized_text"] = recognized_text

    if feedback:
        speaking_result["feedback"] = feedback

    grammar_correct = []
    grammar_errors = []
    if feedback:
        await grammar_cache.ensure_loaded(lesson.language)
        valid_codes = {g.code for g in grammar_cache.grammar_points(lesson.language)}
        grammar_correct = [
            c for c in feedback.get("grammar_correct_codes", []) if c in valid_codes
        ]
        grammar_errors = [
            c for c in feedback.get("grammar_error_codes", []) if c in valid_codes
        ]

    await advance_lesson(lesson, idx, result=speaking_result)

    event = LearningEvent(
        student_id=student.id,
        lesson_id=lesson.id,
        activity_type=ActivityType.SPEAKING.value,
        activity_index=idx,
        evidence_type="productive",
        student_text=recognized_text,
        grammar_correct=grammar_correct,
        grammar_errors=grammar_errors,
        themes=feedback.get("themes", []) if feedback else [],
    )
    await event.insert()
    logger.debug(
        "speaking event stored",
        extra={
            "lesson_id": str(lesson.id),
            "pronunciation_score": pronunciation.pronunciation_score
            if pronunciation
            else None,
            "grammar_errors": grammar_errors,
            "grammar_correct": grammar_correct,
        },
    )

    return _review_redirect(lesson_id, idx)


@router.get("/speaking/word-audio/{word:path}")
@limiter.limit("30/minute")
async def speaking_word_audio(
    request: Request,
    word: str,
    student: Student = Depends(get_current_student),
):
    """Generate TTS for a word and return its static URL (JSON)."""
    from maestro.tts import generate_word_audio

    url = await generate_word_audio(word, language=request.state.lang_ctx.code)
    if url is None:
        raise HTTPException(503, "TTS unavailable")
    return {"url": url}


@router.post(
    "/lessons/{lesson_id}/activity/{idx}/reading-submit", response_class=HTMLResponse
)
async def lesson_reading_submit(
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

    q_items = activity.questions or []
    questions = [q.text for q in q_items]
    correct_answers = [q.correct_answer for q in q_items]

    try:
        overall_correct, feedback, gp_correct, gp_errors = await score_reading_activity(
            questions,
            correct_answers,
            answers,
            cefr_level=lesson.cefr_at_start,
            student_id=student.id,
            lesson_id=lesson.id,
            language=lesson.language,
        )
    except Exception:
        logger.exception(
            "scoring failed for reading",
            extra={"lesson_id": str(lesson.id), "idx": idx},
        )
        _err_feedback = {"scoring_unavailable": t("scoring_unavailable")}
        await advance_lesson(
            lesson,
            idx,
            result={
                "student_answers": answers,
                "correct": None,
                "feedback": _err_feedback,
            },
        )
        return _review_redirect(lesson_id, idx)

    joined_answers = " | ".join(a for a in answers if a)
    event = LearningEvent(
        student_id=student.id,
        lesson_id=lesson.id,
        activity_type=activity.type.value,
        activity_index=idx,
        evidence_type="receptive",
        student_text=joined_answers,
        grammar_correct=gp_correct,
        grammar_errors=gp_errors,
    )
    await event.insert()

    reading_result = {
        "student_answers": answers,
        "correct": overall_correct,
        "feedback": feedback,
    }
    await advance_lesson(lesson, idx, result=reading_result)

    return _review_redirect(lesson_id, idx)


@router.post("/lessons/{lesson_id}/abandon")
async def lesson_abandon(
    lesson_id: PydanticObjectId, student: Student = Depends(get_current_student)
):
    lesson = await _get_lesson(lesson_id, student)
    if lesson.status == LessonStatus.ACTIVE:
        await lesson.update({"$set": {"status": LessonStatus.ABANDONED.value}})
        logger.info("lesson abandoned: lesson=%s", lesson_id)
    return Response(status_code=204, headers={"HX-Redirect": "/lessons/"})


@router.get("/lessons/{lesson_id}/complete", response_class=HTMLResponse)
async def lesson_complete(
    lesson_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await _get_lesson(lesson_id, student)
    learning = [a for a in lesson.activities if a.type in _LEARNING_TYPES]
    completed_count = sum(1 for a in learning if a.status == ActivityStatus.COMPLETED)
    skipped_count = sum(1 for a in learning if a.status == ActivityStatus.SKIPPED)
    events = await get_lesson_events(lesson)
    weak_grammar_points = await get_weak_grammar_points(lesson, events)
    await ensure_lesson_feedback(lesson, weak_grammar_points, events)

    # Detect CEFR graduation
    graduated_to = None
    profile = await get_profile(student.id)
    if (
        profile
        and lesson.cefr_at_start
        and profile.active_progress.cefr_estimate != lesson.cefr_at_start
    ):
        graduated_to = profile.active_progress.cefr_estimate

    # Collect grammar points covered in this lesson (preserving block order)
    covered_gp_codes = [
        a.grammar_point_code
        for a in lesson.activities
        if a.type == ActivityType.GRAMMAR and a.grammar_point_code
    ]
    if covered_gp_codes:
        covered_gps = await GrammarPoint.find(
            {"code": {"$in": covered_gp_codes}}
        ).to_list()
        gp_by_code = {gp.code: gp for gp in covered_gps}
        covered_grammar_points = [
            gp_by_code[c] for c in covered_gp_codes if c in gp_by_code
        ]
        all_gps = list(covered_gps)
    else:
        covered_grammar_points = []
        all_gps = []
    all_gps.extend(weak_grammar_points)
    gp_titles = (
        build_titles(all_gps, lesson.cefr_at_start, lesson.language) if all_gps else {}
    )

    # Build GP recent outcomes for pip display
    gp_outcomes: dict[str, list] = {}
    if profile:
        all_gp_codes = {gp.code for gp in all_gps}
        for code in all_gp_codes:
            gp_outcomes[code] = profile.active_progress.grammar_recent_outcomes.get(
                code, []
            )

    # Collect communicative functions covered in this lesson
    cf_codes = list(dict.fromkeys(c for ev in events for c in ev.functions_performed))
    if cf_codes:
        covered_comm_functions = await CommunicativeFunction.find(
            {"code": {"$in": cf_codes}}
        ).to_list()
        cf_by_code = {cf.code: cf for cf in covered_comm_functions}
        covered_comm_functions = [cf_by_code[c] for c in cf_codes if c in cf_by_code]
    else:
        covered_comm_functions = []

    discovered_words = await get_lesson_discovered_words(lesson)

    # Look up scenario outro for narrative recap
    scenario_outro = ""
    if lesson.scenario_slug:
        scenario = await CurriculumScenario.find_one({"slug": lesson.scenario_slug})
        if scenario and scenario.outro:
            scenario_outro = scenario.outro

    return await render_with_discover(
        request,
        "lesson-complete.html",
        {
            "lesson": lesson,
            "completed_count": completed_count,
            "skipped_count": skipped_count,
            "weak_grammar_points": weak_grammar_points,
            "covered_grammar_points": covered_grammar_points,
            "covered_comm_functions": covered_comm_functions,
            "cf_titles": build_titles(
                covered_comm_functions,
                lesson.cefr_at_start or "A1",
                lesson.language,
            ),
            "discovered_words": discovered_words,
            "gp_titles": gp_titles,
            "gp_outcomes": gp_outcomes,
            "graduated_to": graduated_to,
            "is_a0": lesson.cefr_at_start == "A0",
            "scenario_outro": scenario_outro,
        },
        student_id=student.id,
    )
