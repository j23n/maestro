"""
Lesson plan generation.

Two-phase approach:
  1. prepare_lesson_immediate() — fast, no LLM; creates Lesson with vocab_review activity
  2. generate_lesson_background() — async; appends grammar/reading/drill/speaking/writing

_generate_lesson_content() makes a single large Sonnet call that returns all dynamic content.
Scenario selection replaces old LLM-based topic generation.
"""

from __future__ import annotations

import json
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
    GeneratedDrill,
    DrillItem,
    DrillTemplate,
    CommunicativeFunction,
    ItalianChunk,
    CurriculumScenario,
)
from maestro.config import settings
from maestro.llm import get_async_client
from maestro.profile import get_profile
from maestro.prompts import planner as _prompts
from maestro.utils import parse_llm_json, utcnow
from maestro.lezione.selection import (
    pick_scenario,
    pick_grammar_points,
    pick_comm_functions,
    fill_vocab_cards,
)

logger = logging.getLogger(__name__)

_READING_WORD_COUNT = {"A1": 200, "A2": 300, "B1": 400, "B2": 500}
_READING_QUESTION_COUNT = 5


# ---------------------------------------------------------------------------
# Slot allocation by duration
# ---------------------------------------------------------------------------


def _allocate_slots(duration_minutes: int) -> dict[str, int]:
    """Return counts of each activity type to include."""
    if duration_minutes <= 10:
        return {
            "grammar": 1,
            "drill": 3,
            "vocab_review": 10,
            "reading": 1,
            "writing": 1,
            "speaking": 1,
        }
    elif duration_minutes <= 20:
        return {
            "grammar": 2,
            "drill": 6,
            "vocab_review": 15,
            "reading": 2,
            "writing": 1,
            "speaking": 1,
        }
    else:  # 40 min
        return {
            "grammar": 3,
            "drill": 12,
            "vocab_review": 25,
            "reading": 3,
            "writing": 2,
            "speaking": 2,
        }


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
    speaking_cfs: list[CommunicativeFunction] = [],
) -> dict:
    """Single LLM call returning topic_title, topic_description, overview, grammar_motivations, drills, readings, writing, speakings."""
    reading_word_count = _READING_WORD_COUNT.get(cefr_level, 150)
    depth_description = scenario.depths[depth - 1] if depth <= len(scenario.depths) else scenario.depths[-1]

    parts: list[str] = [
        _prompts.lesson_content_header.render(),
        f"Student CEFR level: {cefr_level}",
        f'Curriculum scenario: "{scenario.label}" (depth {depth})',
        f"Depth focus: {depth_description}",
    ]

    # Persona
    if profile and profile.persona:
        persona_parts = []
        if profile.persona.tags:
            persona_parts.append(", ".join(profile.persona.tags))
        if profile.persona.freetext:
            persona_parts.append(profile.persona.freetext)
        if persona_parts:
            parts.append(f"Student persona: {'; '.join(persona_parts)}")

    if profile and profile.description:
        parts.append(f"Student profile: {profile.description}")

    if grammar_gps:
        gp_lines = []
        for gp in grammar_gps:
            gp_errors = profile.grammar_error_counts.get(gp.code, 0) if profile else 0
            gp_correct = profile.grammar_correct_counts.get(gp.code, 0) if profile else 0
            gp_lines.append(
                f"  - {gp.label} ({gp.code}) — {gp.description}\n"
                f"    Performance: {gp_correct} correct, {gp_errors} errors"
            )
        parts.append("Grammar activity points:\n" + "\n".join(gp_lines))

    if drill_specs:
        drill_lines = []
        for spec in drill_specs:
            rag_part = (
                f"\n  RAG excerpt: {spec['rag_excerpt'][:500]}"
                if spec.get("rag_excerpt")
                else ""
            )
            drill_lines.append(
                f"- grammar_point_code: {spec['grammar_point_code']}, "
                f"exercise_type: {spec['exercise_type']}, "
                f"label: {spec['gp_label']}, "
                f"description: {spec['gp_description']}"
                f"{rag_part}"
            )
        parts.append("Drills to generate:\n" + "\n".join(drill_lines))

    if speaking_cfs:
        cf_lines_all = []
        for cf in speaking_cfs:
            cf_examples = cf.examples[:3]
            cf_patterns = cf.patterns[:3]
            cf_block = [
                f"Speaking activity — Communicative function: {cf.label} ({cf.code})",
                f"Category: {cf.macro_category}",
            ]
            if cf_examples:
                cf_block.append("Examples: " + "; ".join(cf_examples))
            if cf_patterns:
                cf_block.append("Patterns: " + "; ".join(cf_patterns))
            cf_lines_all.append("\n".join(cf_block))
        parts.append("\n\n".join(cf_lines_all))

    # Build the JSON schema description
    motivation_lang = "English" if cefr_level in ("A1", "A2") else "Italian"
    schema: dict = {
        "topic_title": "A creative Italian title for this lesson (3-8 words)",
        "topic_description": "1-2 sentences describing the specific situation covered",
        "overview": "2-3 sentences in Italian: what this lesson covers and what the student will gain",
    }
    if grammar_gps:
        schema["grammar_motivations"] = [
            {
                "code": gp.code,
                "text": f"1-2 sentences in {motivation_lang}: why {gp.label} matters in real conversation",
            }
            for gp in grammar_gps
        ]
    if drill_specs:
        example_drills = []
        for spec in drill_specs:
            if spec["exercise_type"] in ("fill_blank", "error_correction"):
                example_drills.append({
                    "grammar_point_code": spec["grammar_point_code"],
                    "items": [{"prompt": "...", "correct_answer": "..."}, "... 10 items total"],
                })
            else:
                example_drills.append({
                    "grammar_point_code": spec["grammar_point_code"],
                    "prompt": "...",
                    "correct_answer": None,
                    "distractors": [],
                })
        schema["drills"] = example_drills
    if reading_count > 0:
        q_labels = [f"question {i + 1}" for i in range(_READING_QUESTION_COUNT)]
        a_labels = [f"answer {i + 1}" for i in range(_READING_QUESTION_COUNT)]
        schema["readings"] = [
            {
                "text": f"Italian reading text (~{reading_word_count} words at {cefr_level} level) on the lesson topic. Must be grammatically correct and natural.",
                "questions": q_labels,
                "answers": a_labels,
            }
            for _ in range(reading_count)
        ]
    if include_writing:
        schema["writing"] = {
            "prompt": f"An Italian writing prompt appropriate for {cefr_level} level on the topic"
        }
    if speaking_cfs:
        schema["speakings"] = [
            {
                "prompt": f"2-3 sentence Italian speaking prompt asking the student to practise {cf.label}"
            }
            for cf in speaking_cfs
        ]

    parts.append(
        _prompts.lesson_content_footer.render(
            schema_json=json.dumps(schema, indent=2, ensure_ascii=False),
            reading_count=reading_count,
            speaking_count=len(speaking_cfs),
            grammar_count=len(grammar_gps),
        )
    )

    prompt_text = "\n\n".join(parts)
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
    elapsed = time.monotonic() - t0
    raw = response.content[0].text
    logger.info(f"[planner] lesson content LLM in {elapsed:.2f}s, response length={len(raw)} chars")
    logger.debug(f"[planner] lesson content raw: {raw}")
    result = parse_llm_json(raw)
    if not result:
        logger.error(f"[planner] failed to parse lesson content response: {raw}")
        return {}
    logger.debug(f"[planner] lesson content keys: {list(result.keys())}")
    return result


# ---------------------------------------------------------------------------
# Phase 1: fast path — creates lesson with vocab activity immediately
# ---------------------------------------------------------------------------


async def prepare_lesson_immediate(
    duration_minutes: int,
    profile: Optional[LearningProfile],
) -> Lesson:
    """Create and save a Lesson with only the vocab_review activity (no LLM calls).

    Sets status=active, generating=True. Returns the inserted Lesson.
    """
    cefr_level = profile.cefr_estimate if profile else "A1"
    slots = _allocate_slots(duration_minutes)
    vocab_count = slots.get("vocab_review", 0)

    activities: list[LessonActivity] = []
    if vocab_count > 0:
        due_cards = await fill_vocab_cards(vocab_count, cefr_level)
        if due_cards:
            activities.append(LessonActivity(
                type="vocab_review",
                title=f"Vocabolario ({len(due_cards)} parole)",
                description="Ripassa le parole in scadenza oggi",
                duration_minutes=max(2, len(due_cards) * 1),
                card_ids=[c.id for c in due_cards],
                status="active",
            ))

    lesson = Lesson(
        duration_minutes=duration_minutes,
        cefr_at_start=cefr_level,
        status="active",
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
) -> None:
    """Pick scenario, generate content, and append activities to lesson."""
    try:
        await _generate_lesson_background(lesson_id, duration_minutes)
    except Exception:
        logger.exception(f"[planner] generate_lesson_background failed for lesson {lesson_id}")
        try:
            lesson = await Lesson.get(lesson_id)
            if lesson and lesson.generating:
                lesson.generating = False
                await lesson.save()
        except Exception:
            logger.exception(f"[planner] failed to clear generating flag for lesson {lesson_id}")
        raise


async def _generate_lesson_background(
    lesson_id,
    duration_minutes: int,
) -> None:
    t_start = time.monotonic()
    logger.info(f"[planner] generate_lesson_background start: lesson={lesson_id}")

    profile = await get_profile()
    cefr_level = profile.cefr_estimate if profile else "A1"
    slots = _allocate_slots(duration_minutes)
    logger.info(f"[planner] slot allocation: {slots}")

    # --- Pick scenario ---
    client = get_async_client()
    scenario, depth = await pick_scenario(profile, cefr_level)
    logger.info(f"[planner] scenario: {scenario.slug} depth={depth}")

    # --- Pick grammar points (multiple) ---
    grammar_count = slots.get("grammar", 0)
    grammar_gps: list[GrammarPoint] = []
    grammar_explanations: list[Optional[GrammarPointExplanation]] = []

    if grammar_count > 0:
        grammar_gps = await pick_grammar_points(
            profile, cefr_level, grammar_count, candidate_codes=scenario.gp_codes
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
    drill_count = slots.get("drill", 0)
    drill_specs: list[dict] = []
    drill_templates_used: list[DrillTemplate] = []
    if drill_count > 0:
        gps_for_drills = await pick_grammar_points(
            profile, cefr_level, drill_count, candidate_codes=scenario.gp_codes
        )
        all_templates = await DrillTemplate.find_all().to_list()
        for gp in gps_for_drills:
            matching = [t for t in all_templates if t.grammar_point_code == gp.code]
            if not matching:
                continue
            template = random.choice(matching)
            chunk_excerpt = ""
            if gp.chunk_ref:
                chunk = await ItalianChunk.find_one({"ref": gp.chunk_ref})
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
    speaking_count = slots.get("speaking", 0)
    speaking_cfs: list[CommunicativeFunction] = []
    if speaking_count > 0:
        speaking_cfs = await pick_comm_functions(
            profile, cefr_level, speaking_count, candidate_codes=scenario.cf_codes
        )
    logger.info(f"[planner] speaking_cfs: {[c.code for c in speaking_cfs]}")

    reading_count = slots.get("reading", 0)
    include_writing = slots.get("writing", 0) > 0

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
    )

    topic_title = content.get("topic_title", scenario.label)
    topic_description = content.get("topic_description", scenario.description)

    # --- Materialise activities ---

    grammar_activities: list[LessonActivity] = []
    grammar_motivations = content.get("grammar_motivations", [])
    for i, gp in enumerate(grammar_gps):
        exp = grammar_explanations[i] if i < len(grammar_explanations) else None
        if exp:
            explanation_content = exp.explanation
            grammar_title = exp.title or gp.label
        else:
            # Fallback: load chunk content directly
            if gp.chunk_ref:
                chunk = await ItalianChunk.find_one({"ref": gp.chunk_ref})
                explanation_content = chunk.content if chunk else gp.description
            else:
                explanation_content = gp.description
            grammar_title = gp.label
        motivation = grammar_motivations[i].get("text") if i < len(grammar_motivations) and isinstance(grammar_motivations[i], dict) else None
        grammar_activities.append(LessonActivity(
            type="grammar",
            title=f"Grammatica: {grammar_title}",
            description=f"Ripassa la regola grammaticale: {gp.label}",
            duration_minutes=3,
            content=explanation_content,
            why_important=motivation,
        ))

    reading_activities: list[LessonActivity] = []
    llm_readings = content.get("readings", [])
    for i, reading_data in enumerate(llm_readings[:reading_count]):
        if not isinstance(reading_data, dict):
            continue
        reading_activities.append(LessonActivity(
            type="reading",
            title=f"Lettura {i + 1}" if reading_count > 1 else "Lettura",
            description=f"Leggi un testo su: {topic_title}",
            duration_minutes=5,
            content=reading_data.get("text", ""),
            questions=reading_data.get("questions", []),
            correct_answers=reading_data.get("answers", []),
        ))

    drill_activities: list[LessonActivity] = []
    llm_drills = content.get("drills", [])
    logger.info(f"[planner] materialising {len(drill_specs)} drills ({len(llm_drills)} returned by LLM)")
    for i, (spec, template) in enumerate(zip(drill_specs, drill_templates_used)):
        drill_data = llm_drills[i] if i < len(llm_drills) else None
        if not drill_data:
            logger.warning(f"[planner] missing drill data at index {i} for {spec['grammar_point_code']}")
            continue
        exercise_type = spec["exercise_type"]
        if exercise_type in ("fill_blank", "error_correction"):
            raw_items = drill_data.get("items") or []
            items = [
                DrillItem(prompt=it["prompt"], correct_answer=it.get("correct_answer"))
                for it in raw_items
                if isinstance(it, dict) and it.get("prompt")
            ]
            drill = GeneratedDrill(
                template=template,
                grammar_point_code=spec["grammar_point_code"],
                cefr_level=cefr_level,
                exercise_type=exercise_type,
                prompt="",
                correct_answer=None,
                distractors=[],
                items=items,
                scenario_slug=scenario.slug,
                chunk_ref=spec.get("chunk_ref"),
            )
        else:  # free_form
            drill = GeneratedDrill(
                template=template,
                grammar_point_code=spec["grammar_point_code"],
                cefr_level=cefr_level,
                exercise_type=exercise_type,
                prompt=drill_data.get("prompt", ""),
                correct_answer=None,
                distractors=[],
                scenario_slug=scenario.slug,
                chunk_ref=spec.get("chunk_ref"),
            )
        await drill.insert()
        logger.debug(f"[planner] drill inserted: {drill.id} ({exercise_type}, {spec['grammar_point_code']})")
        drill_activities.append(LessonActivity(
            type="drill",
            title=f"Esercizio: {spec['gp_label']}",
            description=f"{exercise_type.replace('_', ' ').title()} · {spec['gp_label']}",
            duration_minutes=3,
            drill_id=drill.id,
        ))

    speaking_activities: list[LessonActivity] = []
    llm_speakings = content.get("speakings", [])
    for i, cf in enumerate(speaking_cfs):
        speaking_data = llm_speakings[i] if i < len(llm_speakings) else None
        prompt_text = speaking_data.get("prompt", "") if isinstance(speaking_data, dict) else ""
        speaking_activities.append(LessonActivity(
            type="speaking",
            title=f"Parlare: {cf.label}",
            description=f"Pratica: {cf.label}",
            duration_minutes=3,
            content=prompt_text,
        ))

    writing_activities: list[LessonActivity] = []
    if include_writing and content.get("writing"):
        writing_data = content["writing"]
        writing_activities.append(LessonActivity(
            type="writing",
            title="Scrittura",
            description=f"Scrivi un testo su: {topic_title}",
            duration_minutes=8,
            content=writing_data.get("prompt", ""),
        ))

    # Pedagogical order: grammar × N → readings × N → drills × N → speakings × N → writing × N
    new_activities = grammar_activities + reading_activities + drill_activities + speaking_activities + writing_activities

    # --- Atomically update lesson ---
    lesson = await Lesson.get(lesson_id)
    if lesson is None:
        logger.error(f"[planner] generate_lesson_background: lesson {lesson_id} not found")
        return

    lesson.activities.extend(new_activities)
    lesson.overview = content.get("overview", "")
    lesson.scenario_slug = scenario.slug
    lesson.scenario_depth = depth
    lesson.topic_title = topic_title
    lesson.topic_description = topic_description
    lesson.generating = False
    await lesson.save()

    elapsed_total = time.monotonic() - t_start
    logger.info(
        f"[planner] generate_lesson_background complete in {elapsed_total:.1f}s: "
        f"{len(new_activities)} new activities — {[a.type for a in new_activities]}"
    )
