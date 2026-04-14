import logging
from typing import Annotated

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from maestro.auth import get_current_student
from maestro.models import (
    Student,
    GrammarPoint,
    Lesson,
    ActivityType,
    ActivityStatus,
    LessonStatus,
    CurriculumScenario,
    CommunicativeFunction,
    ScenarioProgress,
)
from maestro.learning.profile import get_profile
from maestro.learning.weakness import (
    build_grammar_by_level,
    build_titles,
    top_weaknesses,
)
from maestro.templates import render_with_discover
from maestro.utils import create_background_task, ensure_utc, utcnow
from maestro.config import settings as _settings
from maestro.lessons.planner import prepare_lesson_immediate, generate_lesson_background
from maestro.learning.onboarding import skip_onboarding as _skip_onboarding
from maestro.lessons.lifecycle import (
    activity_url,
    count_paid_lessons,
    ensure_lesson_feedback,
    get_lesson_discovered_words,
    get_lesson_events,
    get_weak_grammar_points,
    update_scenario_progress,
    _sweep_leftover_activities,
    _credit_a0_mastery,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_GENERATION_TIMEOUT_SECONDS = 180  # 3 minutes


def review_redirect(lesson_id, idx) -> Response:
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


async def get_lesson(lesson_id: PydanticObjectId, student: Student) -> Lesson:
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

        a0_scenarios = await CurriculumScenario.find(
            {"cefr_level": "A0", "language": profile.target_language}
        ).to_list()
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
                    {
                        "student_id": student.id,
                        "status": LessonStatus.COMPLETED,
                        "language": profile.target_language,
                    }
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
    lesson = await get_lesson(lesson_id, student)
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
    )


@router.get("/lessons/{lesson_id}/generating", response_class=HTMLResponse)
async def lesson_generating(
    lesson_id: PydanticObjectId,
    request: Request,
    student: Student = Depends(get_current_student),
):
    lesson = await get_lesson(lesson_id, student)
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
        lesson = await get_lesson(lesson_id, student)

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
    lesson = await get_lesson(lesson_id, student)
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
    lesson = await get_lesson(lesson_id, student)
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


@router.post("/lessons/{lesson_id}/abandon")
async def lesson_abandon(
    lesson_id: PydanticObjectId, student: Student = Depends(get_current_student)
):
    lesson = await get_lesson(lesson_id, student)
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
    lesson = await get_lesson(lesson_id, student)
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
