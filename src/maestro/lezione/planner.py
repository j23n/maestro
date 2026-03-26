"""
Lesson plan generation.

Two-phase approach:
  1. prepare_lesson_immediate() — fast, no LLM; creates Lesson with vocab_review activity
  2. generate_lesson_background() — async; appends grammar/reading/drill/speaking/writing

_generate_lesson_content() makes a single large Sonnet call that returns all dynamic content.
Scenario selection replaces old LLM-based topic generation.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

from maestro.models import (
    Lesson,
    LessonActivity,
    LearningProfile,
    GrammarPoint,
    ExerciseType,
    CommunicativeFunction,
    GrammarChunk,
    CurriculumScenario,
    ScenarioProgress,
    ActivityType,
    ActivityStatus,
    LessonStatus,
)
from maestro.config import settings
from maestro.llm import llm_messages_create
from maestro.models import CallType
from maestro.profile import get_profile
from maestro.utils import (
    explanation_lang_for_level,
    parse_llm_json,
    strip_lang_spans,
    utcnow,
)
from maestro.lezione.slots import _allocate_slots
from maestro.lezione.prompts import (
    build_lesson_content_prompt,
    build_lesson_content_system,
)
from maestro.lezione.materialize import materialize_activities
from maestro.lezione.a0 import _generate_a0_lesson_background
from maestro.lezione.schemas import LessonContentResponse
from maestro.lezione.curriculum import (
    get_unlocked_gps,
    pick_archetype,
)
from maestro.lezione.selection import (
    pick_scenario,
    pick_grammar_points,
    pick_comm_functions,
    get_due_vocab_cards,
)
from maestro.strings import t

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-call content generation
# ---------------------------------------------------------------------------


async def _generate_lesson_content(
    cefr_level: str,
    scenario: CurriculumScenario,
    depth: int,
    profile: Optional[LearningProfile],
    grammar_gps: list[GrammarPoint],
    drill_specs: list[dict],
    reading_count: int,
    include_writing: bool,
    speaking_cfs: list[CommunicativeFunction] | None = None,
    lesson_context: str = "",
    student_id=None,
    lesson_id=None,
    archetype: str = "",
) -> LessonContentResponse:
    """Single LLM call returning validated lesson content."""
    if speaking_cfs is None:
        speaking_cfs = []
    prompt_text = build_lesson_content_prompt(
        cefr_level=cefr_level,
        scenario=scenario,
        depth=depth,
        profile=profile,
        grammar_gps=grammar_gps,
        drill_specs=drill_specs,
        reading_count=reading_count,
        include_writing=include_writing,
        speaking_cfs=speaking_cfs,
        lesson_context=lesson_context,
        archetype=archetype,
    )

    logger.debug(f"lesson content prompt: {prompt_text}")
    logger.info(
        "generating lesson content",
        extra={
            "cefr_level": cefr_level,
            "scenario": scenario.slug,
            "depth": depth,
            "grammar_gps": [g.code for g in grammar_gps],
            "n_drills": len(drill_specs),
            "reading_count": reading_count,
            "include_writing": include_writing,
            "speaking_cfs": [c.code for c in speaking_cfs],
        },
    )
    response = await llm_messages_create(
        model=settings.LESSON_MODEL,
        max_tokens=16000,
        system=build_lesson_content_system(),
        messages=[{"role": "user", "content": prompt_text}],
        entity_id=lesson_id,
        call_type=CallType.LESSON_PLAN,
        student_id=student_id,
    )
    raw = response.content[0].text
    logger.info(
        "lesson content LLM response received", extra={"response_length": len(raw)}
    )
    logger.debug(f"lesson content raw: {raw}")
    result = parse_llm_json(raw)
    if not result or not isinstance(result, dict):
        logger.error("failed to parse lesson content LLM response", extra={"raw": raw})
        return LessonContentResponse()
    try:
        content = LessonContentResponse.model_validate(result)
    except Exception:
        logger.warning("lesson content validation partial", exc_info=True)
        content = LessonContentResponse()
    logger.debug(f"lesson content fields: {list(content.model_fields_set)}")
    return content


# ---------------------------------------------------------------------------
# Phase 1: fast path — creates lesson with vocab activity immediately
# ---------------------------------------------------------------------------


async def prepare_lesson_immediate(
    duration_minutes: int,
    profile: Optional[LearningProfile],
    student_id=None,
    lesson_context: str = "",
    focus_weak: bool = False,
    scenario_slug: str | None = None,
) -> Lesson:
    """Create and save a Lesson with only the vocab_review activity (no LLM calls).

    Sets status=active, generating=True. Returns the inserted Lesson.
    """
    cefr_level = profile.cefr_estimate if profile else "A0"

    activities: list[LessonActivity] = []

    # A0 lessons are fully static — no vocab review needed at creation
    if cefr_level == "A0":
        lesson = Lesson(
            student_id=student_id,
            duration_minutes=duration_minutes,
            cefr_at_start=cefr_level,
            lesson_context=lesson_context or None,
            focus_weak=focus_weak,
            scenario_slug=scenario_slug,
            status=LessonStatus.ACTIVE,
            started_at=utcnow(),
            generating=True,
            generation_started_at=utcnow(),
            activities=activities,
            current_index=0,
        )
        await lesson.insert()
        logger.info("lesson created (A0)", extra={"lesson_id": str(lesson.id)})
        return lesson

    slots = _allocate_slots(duration_minutes)
    vocab_count = slots.get(ActivityType.VOCAB_REVIEW, 0)

    if vocab_count > 0:
        due_cards = await get_due_vocab_cards(vocab_count, student_id=student_id)
        if due_cards:
            activities.append(
                LessonActivity(
                    type=ActivityType.VOCAB_REVIEW,
                    title=t("vocab_title", count=len(due_cards)),
                    description=t("vocab_desc"),
                    duration_minutes=max(2, len(due_cards) * 1),
                    card_ids=[c.id for c in due_cards],
                    status=ActivityStatus.ACTIVE,
                )
            )

    lesson = Lesson(
        student_id=student_id,
        duration_minutes=duration_minutes,
        cefr_at_start=cefr_level,
        lesson_context=lesson_context or None,
        focus_weak=focus_weak,
        scenario_slug=scenario_slug,
        status=LessonStatus.ACTIVE,
        started_at=utcnow(),
        generating=True,
        generation_started_at=utcnow(),
        activities=activities,
        current_index=0,
    )
    await lesson.insert()
    logger.info(
        "lesson created",
        extra={
            "lesson_id": str(lesson.id),
            "n_vocab_cards": len(activities[0].card_ids) if activities else 0,
        },
    )
    return lesson


# ---------------------------------------------------------------------------
# Phase 2: background — appends all LLM-generated activities to the lesson
# ---------------------------------------------------------------------------


async def generate_lesson_background(
    lesson_id,
    duration_minutes: int,
    scenario_slug: str | None = None,
    focus_weak: bool = False,
) -> None:
    """Pick scenario, generate content, and append activities to lesson."""
    try:
        await _generate_lesson_background(
            lesson_id, duration_minutes, scenario_slug, focus_weak
        )
    except Exception:
        logger.exception(
            "lesson generation failed",
            extra={"lesson_id": str(lesson_id)},
        )
        try:
            await Lesson.find_one(
                Lesson.id == lesson_id,
                Lesson.generating == True,  # noqa: E712
            ).update(
                {
                    "$set": {
                        "generating": False,
                        "generation_error": "Content generation failed. Please try again.",
                        "status": LessonStatus.ABANDONED.value,
                    }
                }
            )
        except Exception:
            logger.exception(
                "failed to clear generating flag",
                extra={"lesson_id": str(lesson_id)},
            )
        raise


async def _generate_lesson_background(
    lesson_id,
    duration_minutes: int,
    scenario_slug: str | None = None,
    focus_weak: bool = False,
) -> None:
    t_start = time.monotonic()
    logger.info(
        "lesson background generation started", extra={"lesson_id": str(lesson_id)}
    )

    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        logger.error("lesson not found", extra={"lesson_id": str(lesson_id)})
        return
    profile = await get_profile(lesson.student_id) if lesson.student_id else None
    cefr_level = profile.cefr_estimate if profile else "A0"

    if cefr_level == "A0":
        return await _generate_a0_lesson_background(lesson_id, duration_minutes)

    # Merge explicit params with stored lesson fields (supports retry)
    scenario_slug = scenario_slug or lesson.scenario_slug
    focus_weak = focus_weak or lesson.focus_weak

    slots = _allocate_slots(duration_minutes)
    logger.info("slot allocation", extra={"slots": slots})

    # --- Pick scenario ---
    # Fetch all scenarios once — reused by pick_scenario and the curriculum engine below
    all_scenarios = await CurriculumScenario.find({"cefr_level": cefr_level}).to_list()

    if scenario_slug:
        scenario_doc = await CurriculumScenario.find_one({"slug": scenario_slug})
        if scenario_doc:
            progress = profile.scenario_progress if profile else {}
            sp = progress.get(scenario_slug, ScenarioProgress())
            # Intentional: explicit slug selection bypasses depth gating —
            # this is a manual override, so students can revisit any scenario.
            depth = min(sp.depth + 1, len(scenario_doc.depths))
            scenario = scenario_doc
        else:
            logger.warning(
                "scenario not found, falling back to auto-pick",
                extra={"scenario_slug": scenario_slug},
            )
            scenario, depth = await pick_scenario(
                profile, cefr_level, scenarios=all_scenarios
            )
    else:
        scenario, depth = await pick_scenario(
            profile, cefr_level, scenarios=all_scenarios
        )
    logger.info("scenario selected", extra={"scenario": scenario.slug, "depth": depth})

    # --- Curriculum engine: unlock GPs and pick archetype ---
    all_gp_codes = {code for s in all_scenarios for code in s.gp_codes}
    all_gps = await GrammarPoint.find({"code": {"$in": list(all_gp_codes)}}).to_list()
    prereqs_map = {gp.code: gp.prerequisites for gp in all_gps if gp.prerequisites}
    unlocked = get_unlocked_gps(profile, all_gp_codes, prereqs_map)
    archetype = pick_archetype(profile, unlocked, scenario.gp_codes, focus_weak)
    logger.info(
        "curriculum engine",
        extra={
            "unlocked_gps": len(unlocked),
            "total_gps": len(all_gp_codes),
            "archetype": archetype.value,
        },
    )

    # --- Pick grammar points (multiple) ---
    grammar_count = slots.get(ActivityType.GRAMMAR, 0)
    grammar_gps: list[GrammarPoint] = []

    # When focus_weak is on, ignore scenario's gp_codes constraint
    gp_candidate_codes = None if focus_weak else scenario.gp_codes

    if grammar_count > 0:
        grammar_gps = await pick_grammar_points(
            profile,
            cefr_level,
            grammar_count,
            candidate_codes=gp_candidate_codes,
            unlocked_codes=unlocked,
        )

    expl_lang = explanation_lang_for_level(cefr_level)
    fallback_lang = "it" if expl_lang == "en" else "en"
    grammar_explanations = [
        gp.explanations.get(expl_lang) or gp.explanations.get(fallback_lang)
        for gp in grammar_gps
    ]

    # --- Build drill specs tied to the lesson's grammar points ---
    # Distribute drills evenly across grammar_gps so each GP gets its own drills.
    # This ensures drills are always tied to covered grammar (goals 4 & 5).
    drill_count = slots.get(ActivityType.DRILL, 0)
    drill_specs: list[dict] = []
    chunk_cache: dict[str, str] = {}
    if drill_count > 0 and grammar_gps:
        drills_per_gp = drill_count // len(grammar_gps)
        remainder = drill_count % len(grammar_gps)
        for i, gp in enumerate(grammar_gps):
            count = drills_per_gp + (1 if i < remainder else 0)
            if gp.chunk_ref and gp.chunk_ref not in chunk_cache:
                chunk = await GrammarChunk.find_one({"ref": gp.chunk_ref})
                chunk_cache[gp.chunk_ref] = chunk.content[:500] if chunk else ""
            chunk_excerpt = chunk_cache.get(gp.chunk_ref or "", "")
            for _ in range(count):
                exercise_type = random.choice(
                    [ExerciseType.FILL_BLANK, ExerciseType.ERROR_CORRECTION]
                )
                drill_specs.append(
                    {
                        "grammar_point_code": gp.code,
                        "gp_label": gp.label,
                        "exercise_type": exercise_type,
                        "rag_excerpt": chunk_excerpt,
                        "chunk_ref": gp.chunk_ref,
                    }
                )
    elif drill_count > 0:
        # Fallback: no grammar_gps selected, pick independently
        gps_for_drills = await pick_grammar_points(
            profile,
            cefr_level,
            drill_count,
            candidate_codes=gp_candidate_codes,
            unlocked_codes=unlocked,
        )
        for gp in gps_for_drills:
            exercise_type = random.choice(
                [ExerciseType.FILL_BLANK, ExerciseType.ERROR_CORRECTION]
            )
            chunk_excerpt = ""
            if gp.chunk_ref:
                chunk = await GrammarChunk.find_one({"ref": gp.chunk_ref})
                if chunk:
                    chunk_excerpt = chunk.content[:500]
            drill_specs.append(
                {
                    "grammar_point_code": gp.code,
                    "gp_label": gp.label,
                    "exercise_type": exercise_type,
                    "rag_excerpt": chunk_excerpt,
                    "chunk_ref": gp.chunk_ref,
                }
            )

    # --- Inject one review drill for the weakest past GP (A1+) ---
    if profile and drill_specs:
        lesson_gp_codes = {s["grammar_point_code"] for s in drill_specs}
        weak_candidates: list[tuple[str, float]] = []
        for gp_code, outcomes in profile.grammar_recent_outcomes.items():
            if gp_code in lesson_gp_codes:
                continue
            ok_count = sum(
                1 for o in outcomes if (o.get("ok") if isinstance(o, dict) else o)
            )
            total = len(outcomes)
            if total >= 2 and (total - ok_count) / total > 0.3:
                weak_candidates.append((gp_code, (total - ok_count) / total))
        if weak_candidates:
            weak_candidates.sort(key=lambda x: x[1], reverse=True)
            review_code = weak_candidates[0][0]
            review_gp = await GrammarPoint.find_one(GrammarPoint.code == review_code)
            if review_gp:
                chunk_excerpt = ""
                if review_gp.chunk_ref:
                    if review_gp.chunk_ref not in chunk_cache:
                        chunk = await GrammarChunk.find_one(
                            {"ref": review_gp.chunk_ref}
                        )
                        chunk_cache[review_gp.chunk_ref] = (
                            chunk.content[:500] if chunk else ""
                        )
                    chunk_excerpt = chunk_cache.get(review_gp.chunk_ref, "")
                drill_specs.append(
                    {
                        "grammar_point_code": review_gp.code,
                        "gp_label": review_gp.label,
                        "exercise_type": random.choice(
                            [ExerciseType.FILL_BLANK, ExerciseType.ERROR_CORRECTION]
                        ),
                        "rag_excerpt": chunk_excerpt,
                        "chunk_ref": review_gp.chunk_ref,
                    }
                )
                logger.info("review drill injected", extra={"gp_code": review_code})

    # --- Pick communicative functions for speaking ---
    speaking_count = slots.get(ActivityType.SPEAKING, 0)
    speaking_cfs: list[CommunicativeFunction] = []
    if speaking_count > 0:
        speaking_cfs = await pick_comm_functions(
            profile, cefr_level, speaking_count, candidate_codes=scenario.cf_codes
        )
    logger.info(
        "speaking CFs selected", extra={"speaking_cfs": [c.code for c in speaking_cfs]}
    )

    reading_count = slots.get(ActivityType.READING, 0)
    listening_count = slots.get(ActivityType.LISTENING, 0)
    include_writing = slots.get(ActivityType.WRITING, 0) > 0

    logger.info(
        "activity plan",
        extra={
            "grammar_gps": [g.code for g in grammar_gps],
            "n_drills": len(drill_specs),
            "reading_count": reading_count,
            "listening_count": listening_count,
            "include_writing": include_writing,
            "speaking_cfs": [c.code for c in speaking_cfs],
        },
    )

    # --- Record newly introduced GPs (atomic to avoid race with concurrent lessons) ---
    if profile and grammar_gps:
        introduced_set = set(profile.grammar_introduced)
        new_intros = [gp.code for gp in grammar_gps if gp.code not in introduced_set]
        if new_intros:
            await LearningProfile.get_pymongo_collection().update_one(
                {"_id": profile.id},
                {"$addToSet": {"grammar_introduced": {"$each": new_intros}}},
            )
            logger.info("grammar introduced", extra={"new_gps": new_intros})

    # --- Single LLM call ---
    # The LLM generates reading texts for both LISTENING and READING activities;
    # pass the combined total so it produces enough passages.
    content = await _generate_lesson_content(
        cefr_level,
        scenario,
        depth,
        profile,
        grammar_gps,
        drill_specs,
        reading_count + listening_count,
        include_writing,
        speaking_cfs,
        lesson_context=lesson.lesson_context or "",
        student_id=lesson.student_id,
        lesson_id=lesson.id,
        archetype=archetype.value,
    )

    topic_title = strip_lang_spans(content.topic_title or scenario.label)
    topic_description = strip_lang_spans(
        content.topic_description or scenario.description
    )

    # --- Materialise activities ---
    new_activities = await materialize_activities(
        content=content,
        grammar_gps=grammar_gps,
        grammar_explanations=grammar_explanations,
        drill_specs=drill_specs,
        speaking_cfs=speaking_cfs,
        include_writing=include_writing,
        reading_count=reading_count,
        listening_count=listening_count,
        topic_title=topic_title,
        scenario_slug=scenario.slug,
        cefr_level=cefr_level,
        student_id=lesson.student_id,
    )

    # --- Generate audio for LISTENING activities ---
    from maestro.tts import generate_lesson_audio

    for i, act in enumerate(new_activities):
        if act.type == ActivityType.LISTENING and act.content:
            act.audio_path = await generate_lesson_audio(act.content, str(lesson_id), i)

    # --- Atomically update lesson ---
    activities_dicts = [a.model_dump() for a in new_activities]
    initial_count = len(lesson.activities)
    await Lesson.find_one(Lesson.id == lesson_id).update(
        {
            "$push": {"activities": {"$each": activities_dicts}},
            "$set": {
                "overview": content.overview,
                "scenario_slug": scenario.slug,
                "scenario_depth": depth,
                "topic_title": topic_title,
                "topic_description": topic_description,
                "archetype": archetype.value,
                "generating": False,
            },
        }
    )
    # If the lesson had no initial activities, activate the first appended one
    # (must be a separate update — $push and $set on the same array in one op
    # has undefined field-ordering behaviour in MongoDB)
    if initial_count == 0 and new_activities:
        await Lesson.find_one(Lesson.id == lesson_id).update(
            {
                "$set": {
                    f"activities.{initial_count}.status": ActivityStatus.ACTIVE.value
                }
            }
        )

    elapsed_total = time.monotonic() - t_start
    logger.info(
        "lesson background generation complete",
        extra={
            "elapsed_s": round(elapsed_total, 1),
            "n_activities": len(new_activities),
            "activity_types": [a.type for a in new_activities],
        },
    )
