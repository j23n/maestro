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
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import anthropic

from maestro.models import (
    Lesson,
    LessonActivity,
    LearningProfile,
    GrammarPoint,
    GrammarPointExplanation,
    DrillTemplate,
    CommunicativeFunction,
    GrammarChunk,
    CurriculumScenario,
    ScenarioProgress,
    ActivityType,
    ActivityStatus,
    LessonStatus,
)
from maestro.config import settings
from maestro.llm import get_async_client, log_llm_usage
from maestro.profile import get_profile
from maestro.utils import parse_llm_json, strip_lang_spans, utcnow
from maestro.lezione.slots import _allocate_slots
from maestro.lezione.prompts import build_lesson_content_prompt
from maestro.lezione.materialize import materialize_activities
from maestro.lezione.a0 import _generate_a0_lesson_background
from maestro.lezione.schemas import LessonContentResponse
from maestro.lezione.selection import (
    pick_scenario,
    pick_grammar_points,
    pick_comm_functions,
    fill_vocab_cards,
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
    client: "anthropic.AsyncAnthropic",
    speaking_cfs: list[CommunicativeFunction] | None = None,
    lesson_context: str = "",
    student_id=None,
    lesson_id=None,
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
    )

    logger.debug(f"[planner] _generate_lesson_content prompt: {prompt_text}")
    logger.info(
        f"[planner] _generate_lesson_content: level={cefr_level}, scenario={scenario.slug}, "
        f"depth={depth}, grammar_gps={[g.code for g in grammar_gps]}, "
        f"n_drills={len(drill_specs)}, reading_count={reading_count}, "
        f"writing={include_writing}, speaking_cfs={[c.code for c in speaking_cfs]}"
    )
    t0 = time.monotonic()
    response = await client.messages.create(
        model=settings.LESSON_MODEL,
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt_text}],
    )
    log_llm_usage(response, "plan", student_id=student_id, lesson_id=lesson_id)
    elapsed = time.monotonic() - t0
    raw = response.content[0].text
    logger.info(
        f"[planner] lesson content LLM in {elapsed:.2f}s, response length={len(raw)} chars"
    )
    logger.debug(f"[planner] lesson content raw: {raw}")
    result = parse_llm_json(raw)
    if not result or not isinstance(result, dict):
        logger.error(f"[planner] failed to parse lesson content response: {raw}")
        return LessonContentResponse()
    try:
        content = LessonContentResponse.model_validate(result)
    except Exception as e:
        logger.warning(f"[planner] lesson content validation partial: {e}")
        content = LessonContentResponse()
    logger.debug(f"[planner] lesson content fields: {list(content.model_fields_set)}")
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

    # A0 lessons are fully static — no vocab review activity, but seed cards
    # so they appear in /vocab
    if cefr_level == "A0":
        await fill_vocab_cards(25, cefr_level, student_id=student_id)
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
            activities=activities,
            current_index=0,
        )
        await lesson.insert()
        logger.info(f"[planner] prepare_lesson_immediate (A0): lesson={lesson.id}")
        return lesson

    slots = _allocate_slots(duration_minutes)
    vocab_count = slots.get(ActivityType.VOCAB_REVIEW, 0)

    if vocab_count > 0:
        due_cards = await fill_vocab_cards(
            vocab_count, cefr_level, student_id=student_id
        )
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
        activities=activities,
        current_index=0,
    )
    await lesson.insert()
    logger.info(
        f"[planner] prepare_lesson_immediate: lesson={lesson.id}, "
        f"vocab_cards={len(activities[0].card_ids) if activities else 0}"
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
            f"[planner] generate_lesson_background failed for lesson {lesson_id}"
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
                f"[planner] failed to clear generating flag for lesson {lesson_id}"
            )
        raise


async def _generate_lesson_background(
    lesson_id,
    duration_minutes: int,
    scenario_slug: str | None = None,
    focus_weak: bool = False,
) -> None:
    t_start = time.monotonic()
    logger.info(f"[planner] generate_lesson_background start: lesson={lesson_id}")

    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        logger.error(
            f"[planner] generate_lesson_background: lesson {lesson_id} not found"
        )
        return
    profile = await get_profile(lesson.student_id) if lesson.student_id else None
    cefr_level = profile.cefr_estimate if profile else "A0"

    if cefr_level == "A0":
        return await _generate_a0_lesson_background(lesson_id, duration_minutes)

    # Merge explicit params with stored lesson fields (supports retry)
    scenario_slug = scenario_slug or lesson.scenario_slug
    focus_weak = focus_weak or lesson.focus_weak

    slots = _allocate_slots(duration_minutes)
    logger.info(f"[planner] slot allocation: {slots}")

    # --- Pick scenario ---
    client = get_async_client()
    if scenario_slug:
        scenario_doc = await CurriculumScenario.find_one({"slug": scenario_slug})
        if scenario_doc:
            progress = profile.scenario_progress if profile else {}
            sp = progress.get(scenario_slug, ScenarioProgress())
            depth = min(sp.depth + 1, len(scenario_doc.depths))
            scenario = scenario_doc
        else:
            logger.warning(
                f"[planner] scenario_slug={scenario_slug} not found, falling back to auto-pick"
            )
            scenario, depth = await pick_scenario(profile, cefr_level)
    else:
        scenario, depth = await pick_scenario(profile, cefr_level)
    logger.info(f"[planner] scenario: {scenario.slug} depth={depth}")

    # --- Pick grammar points (multiple) ---
    grammar_count = slots.get(ActivityType.GRAMMAR, 0)
    grammar_gps: list[GrammarPoint] = []
    grammar_explanations: list[Optional[GrammarPointExplanation]] = []

    # When focus_weak is on, ignore scenario's gp_codes constraint
    gp_candidate_codes = None if focus_weak else scenario.gp_codes

    if grammar_count > 0:
        grammar_gps = await pick_grammar_points(
            profile, cefr_level, grammar_count, candidate_codes=gp_candidate_codes
        )

        for gp in grammar_gps:
            explanation = await GrammarPointExplanation.find_one(
                {"grammar_point.$id": gp.id, "student_level": cefr_level}
            )
            if not explanation:
                explanation = await GrammarPointExplanation.find_one(
                    {"grammar_point.$id": gp.id}
                )
            grammar_explanations.append(explanation)

    # --- Pick grammar points and templates for drills ---
    drill_count = slots.get(ActivityType.DRILL, 0)
    drill_specs: list[dict] = []
    drill_templates_used: list[DrillTemplate] = []
    if drill_count > 0:
        gps_for_drills = await pick_grammar_points(
            profile, cefr_level, drill_count, candidate_codes=gp_candidate_codes
        )
        all_templates = await DrillTemplate.find_all().to_list()
        for gp in gps_for_drills:
            matching = [t for t in all_templates if t.grammar_point_code == gp.code]
            if not matching:
                continue
            template = random.choice(matching)
            chunk_excerpt = ""
            if gp.chunk_ref:
                chunk = await GrammarChunk.find_one({"ref": gp.chunk_ref})
                if chunk:
                    chunk_excerpt = chunk.content[:500]
            drill_specs.append(
                {
                    "grammar_point_code": gp.code,
                    "gp_label": gp.label,
                    "gp_description": gp.description,
                    "exercise_type": template.exercise_type,
                    "rag_excerpt": chunk_excerpt,
                    "chunk_ref": gp.chunk_ref,
                }
            )
            drill_templates_used.append(template)

    # --- Pick communicative functions for speaking ---
    speaking_count = slots.get(ActivityType.SPEAKING, 0)
    speaking_cfs: list[CommunicativeFunction] = []
    if speaking_count > 0:
        speaking_cfs = await pick_comm_functions(
            profile, cefr_level, speaking_count, candidate_codes=scenario.cf_codes
        )
    logger.info(f"[planner] speaking_cfs: {[c.code for c in speaking_cfs]}")

    reading_count = slots.get(ActivityType.READING, 0)
    include_writing = slots.get(ActivityType.WRITING, 0) > 0

    logger.info(
        f"[planner] grammar: {[g.code for g in grammar_gps]}, "
        f"drills: {len(drill_specs)}, reading: {reading_count}, "
        f"writing: {include_writing}, speaking: {[c.code for c in speaking_cfs]}"
    )

    # --- Single LLM call ---
    content = await _generate_lesson_content(
        cefr_level,
        scenario,
        depth,
        profile,
        grammar_gps,
        drill_specs,
        reading_count,
        include_writing,
        client,
        speaking_cfs,
        lesson_context=lesson.lesson_context or "",
        student_id=lesson.student_id,
        lesson_id=lesson_id,
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
        drill_templates_used=drill_templates_used,
        speaking_cfs=speaking_cfs,
        include_writing=include_writing,
        reading_count=reading_count,
        topic_title=topic_title,
        scenario_slug=scenario.slug,
        cefr_level=cefr_level,
        student_id=lesson.student_id,
    )

    # --- Atomically update lesson ---
    activities_dicts = [a.model_dump() for a in new_activities]
    await Lesson.find_one(Lesson.id == lesson_id).update(
        {
            "$push": {"activities": {"$each": activities_dicts}},
            "$set": {
                "overview": content.overview,
                "scenario_slug": scenario.slug,
                "scenario_depth": depth,
                "topic_title": topic_title,
                "topic_description": topic_description,
                "generating": False,
            },
        }
    )

    elapsed_total = time.monotonic() - t_start
    logger.info(
        f"[planner] generate_lesson_background complete in {elapsed_total:.1f}s: "
        f"{len(new_activities)} new activities — {[a.type for a in new_activities]}"
    )
