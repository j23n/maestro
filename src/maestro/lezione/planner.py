"""
Lesson plan generation.

generate_lesson_plan() → tuple[list[LessonActivity], str]

Allocates activity slots based on time budget, generates all content
(drills, reading, writing, grammar motivation, overview) in a single
LLM call, and returns an ordered list ready to be stored on a Lesson
document along with the lesson overview string.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import date
from typing import Optional

import anthropic

from maestro.models import (
    LessonActivity,
    LearningProfile,
    GrammarPoint,
    GrammarPointExplanation,
    GeneratedDrill,
    DrillItem,
    DrillTemplate,
    UserVocabularyCard,
)
from maestro.settings import Settings
from maestro.utils import CEFR_ORDER, parse_llm_json
from maestro.rag.retrieve import get_chunks_for_refs

logger = logging.getLogger(__name__)
settings = Settings()

_READING_WORD_COUNT = {"A1": 200, "A2": 300, "B1": 400, "B2": 500}
_READING_QUESTION_COUNT = 5


# ---------------------------------------------------------------------------
# Slot allocation by duration
# ---------------------------------------------------------------------------


def _allocate_slots(duration_minutes: int) -> dict[str, int]:
    """Return counts of each activity type to include."""
    if duration_minutes <= 10:
        return {
            "grammar": 0,
            "drill": 2,
            "vocab_review": 10,
            "reading": 0,
            "writing": 0,
        }
    elif duration_minutes <= 20:
        return {
            "grammar": 1,
            "drill": 5,
            "vocab_review": 15,
            "reading": 1,
            "writing": 0,
        }
    else:  # 40 min
        return {
            "grammar": 1,
            "drill": 9,
            "vocab_review": 25,
            "reading": 1,
            "writing": 1,
        }


# ---------------------------------------------------------------------------
# Grammar point selection
# ---------------------------------------------------------------------------


async def _pick_grammar_points(
    profile: Optional[LearningProfile],
    cefr_level: str,
    count: int,
) -> list[GrammarPoint]:
    """Pick grammar points to practise, prioritising weakest within level."""
    cefr_idx = CEFR_ORDER.index(cefr_level) if cefr_level in CEFR_ORDER else 0
    target_levels = CEFR_ORDER[max(0, cefr_idx - 1) : cefr_idx + 1]
    candidates = await GrammarPoint.find(
        {"cefr_level": {"$in": target_levels}}
    ).to_list()
    if not candidates:
        candidates = await GrammarPoint.find_all().to_list()

    error_counts: dict = profile.grammar_error_counts if profile else {}
    correct_counts: dict = profile.grammar_correct_counts if profile else {}

    def _score(gp: GrammarPoint) -> float:
        total = correct_counts.get(gp.code, 0) + error_counts.get(gp.code, 0)
        error_rate = error_counts.get(gp.code, 0) / max(1, total)
        return -error_rate + random.uniform(0, 0.1)

    candidates.sort(key=_score)
    return candidates[:count]


# ---------------------------------------------------------------------------
# Single-call content generation
# ---------------------------------------------------------------------------


def _generate_lesson_content(
    cefr_level: str,
    topic: str,
    profile: Optional[LearningProfile],
    grammar_gp: Optional[GrammarPoint],
    drill_specs: list[dict],
    include_reading: bool,
    include_writing: bool,
    client: anthropic.Anthropic,
) -> dict:
    """Single LLM call that returns overview, grammar_motivation, drills, reading, writing."""
    reading_word_count = _READING_WORD_COUNT.get(cefr_level, 150)

    parts: list[str] = [
        "You are generating content for an Italian language lesson.",
        f"Student CEFR level: {cefr_level}",
        f"Lesson topic: {topic}",
    ]
    if profile and profile.description:
        parts.append(f"Student profile: {profile.description}")

    if grammar_gp:
        gp_errors = (
            profile.grammar_error_counts.get(grammar_gp.code, 0) if profile else 0
        )
        gp_correct = (
            profile.grammar_correct_counts.get(grammar_gp.code, 0) if profile else 0
        )
        parts.append(
            f"Grammar activity point: {grammar_gp.label} — {grammar_gp.description}\n"
            f"Student performance on this point: {gp_correct} correct, {gp_errors} errors"
        )

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

    # Build the JSON schema description
    schema: dict = {
        "overview": "2-3 sentences in Italian: what this lesson covers and what the student will gain",
    }
    if grammar_gp:
        motivation_lang = "English" if cefr_level in ("A1", "A2") else "Italian"
        schema["grammar_motivation"] = (
            f"1-2 sentences in {motivation_lang}: why {grammar_gp.label} matters in real conversation"
        )
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
    if include_reading:
        q_labels = [f"question {i + 1}" for i in range(_READING_QUESTION_COUNT)]
        a_labels = [f"answer {i + 1}" for i in range(_READING_QUESTION_COUNT)]
        schema["reading"] = {
            "text": f"Italian reading text (~{reading_word_count} words at {cefr_level} level) on the lesson topic. Must be grammatically correct and natural — verify subject-verb agreement, article-noun agreement, and prepositions.",
            "questions": q_labels,
            "answers": a_labels,
        }
    if include_writing:
        schema["writing"] = {
            "prompt": f"An Italian writing prompt appropriate for {cefr_level} level on the topic"
        }

    parts.append(
        f"\nReturn ONLY valid JSON (no markdown fences, no explanation) matching this structure:\n"
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n\n"
        "Drill rules:\n"
        "- fill_blank: items is a list of EXACTLY 10 objects {prompt, correct_answer}; each prompt is an Italian sentence with ___ as placeholder; correct_answer is the word/phrase that fills the blank\n"
        "- error_correction: items is a list of EXACTLY 10 objects {prompt, correct_answer}; each prompt is a bare erroneous Italian sentence (no intro text); correct_answer is the corrected sentence\n"
        "- free_form: no items field; use prompt (open-ended Italian writing prompt), correct_answer null, distractors []\n"
        "- All content in Italian\n"
        "- Return drills in the same order as listed in the drill specs"
    )

    prompt_text = "\n\n".join(parts)
    response = client.messages.create(
        model=settings.LESSON_MODEL,
        max_tokens=12000,
        messages=[{"role": "user", "content": prompt_text}],
    )
    raw = response.content[0].text
    result = parse_llm_json(raw)
    if not result:
        logger.warning(
            f"[planner] Failed to parse lesson content response: {raw[:300]}"
        )
        return {}
    return result


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def generate_lesson_plan(
    duration_minutes: int,
    topic: str = "",
    grammar_codes: list[str] = [],
) -> tuple[list[LessonActivity], str]:
    profile = await LearningProfile.find_one()
    cefr_level = profile.cefr_estimate if profile else "A1"

    if not topic.strip():
        topic_pool = (list(profile.student_interests) if profile else []) + (
            list(profile.themes_seen) if profile else []
        )
        topic = topic_pool[0] if topic_pool else "vita quotidiana"

    slots = _allocate_slots(duration_minutes)

    # --- Resolve grammar point pool ---
    # If the student pre-selected codes, load and sort them; otherwise fall back to algorithm.
    selected_gps: list[GrammarPoint] = []
    if grammar_codes:
        selected_gps = await GrammarPoint.find(
            {"code": {"$in": grammar_codes}}
        ).to_list()
        error_counts: dict = profile.grammar_error_counts if profile else {}
        correct_counts: dict = profile.grammar_correct_counts if profile else {}

        def _score_selected(gp: GrammarPoint) -> float:
            total = correct_counts.get(gp.code, 0) + error_counts.get(gp.code, 0)
            return -(error_counts.get(gp.code, 0) / max(1, total))

        selected_gps.sort(key=_score_selected)

    # --- Pick grammar point for grammar activity ---
    grammar_gp: Optional[GrammarPoint] = None
    grammar_explanation_content: Optional[str] = None
    if slots.get("grammar", 0) > 0:
        if selected_gps:
            grammar_gp = selected_gps[0]
        else:
            gps = await _pick_grammar_points(profile, cefr_level, 1)
            grammar_gp = gps[0] if gps else None
        if grammar_gp:
            explanation = await GrammarPointExplanation.find_one(
                {"grammar_point.$id": grammar_gp.id, "student_level": cefr_level}
            )
            if not explanation:
                explanation = await GrammarPointExplanation.find_one(
                    {"grammar_point.$id": grammar_gp.id}
                )
            if explanation:
                grammar_explanation_content = explanation.explanation
            else:
                from maestro.rag.retrieve import get_chunks_for_refs as _gcr

                chunks = await _gcr(grammar_gp.rag_refs)
                grammar_explanation_content = (
                    "\n\n".join(c.content for c in chunks)
                    if chunks
                    else grammar_gp.description
                )

    # --- Pick grammar points and templates for drills ---
    drill_count = slots.get("drill", 0)
    drill_specs: list[dict] = []
    drill_templates_used: list[DrillTemplate] = []
    if drill_count > 0:
        if selected_gps:
            # Sample from selected pool with replacement to fill all drill slots
            gps_for_drills = random.choices(selected_gps, k=drill_count)
        else:
            gps_for_drills = await _pick_grammar_points(profile, cefr_level, drill_count)
        all_templates = await DrillTemplate.find_all().to_list()
        for gp in gps_for_drills:
            matching = [t for t in all_templates if t.grammar_point_code == gp.code]
            if not matching:
                continue
            template = random.choice(matching)
            chunks = await get_chunks_for_refs(gp.rag_refs)
            rag_excerpt = chunks[0].content[:500] if chunks else ""
            rag_refs = [c.ref for c in chunks]
            drill_specs.append(
                {
                    "grammar_point_code": gp.code,
                    "gp_label": gp.label,
                    "gp_description": gp.description,
                    "exercise_type": template.exercise_type,
                    "rag_excerpt": rag_excerpt,
                    "rag_refs": rag_refs,
                }
            )
            drill_templates_used.append(template)

    # --- Load vocab cards ---
    vocab_count = slots.get("vocab_review", 0)
    due_cards = []
    if vocab_count > 0:
        due_cards = (
            await UserVocabularyCard.find({"next_review": {"$lte": date.today()}})
            .limit(vocab_count)
            .to_list()
        )

    # --- Single LLM call for all generated content ---
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    include_reading = slots.get("reading", 0) > 0
    include_writing = slots.get("writing", 0) > 0

    content = _generate_lesson_content(
        cefr_level,
        topic,
        profile,
        grammar_gp,
        drill_specs,
        include_reading,
        include_writing,
        client,
    )

    overview = content.get("overview", "")

    # --- Materialise activities into typed buckets ---

    vocab_activity: list[LessonActivity] = []
    if due_cards:
        vocab_activity.append(LessonActivity(
            type="vocab_review",
            title=f"Vocabolario ({len(due_cards)} parole)",
            description="Ripassa le parole in scadenza oggi",
            duration_minutes=max(2, len(due_cards) * 1),
            card_ids=[c.id for c in due_cards],
        ))

    reading_activity: list[LessonActivity] = []
    if include_reading and content.get("reading"):
        reading_data = content["reading"]
        reading_activity.append(LessonActivity(
            type="reading",
            title="Lettura",
            description=f"Leggi un testo su: {topic}",
            duration_minutes=5,
            content=reading_data.get("text", ""),
            questions=reading_data.get("questions", []),
            correct_answers=reading_data.get("answers", []),
        ))

    grammar_activity: list[LessonActivity] = []
    if grammar_gp and grammar_explanation_content:
        grammar_activity.append(LessonActivity(
            type="grammar",
            title=f"Grammatica: {grammar_gp.label}",
            description=f"Ripassa la regola grammaticale: {grammar_gp.label}",
            duration_minutes=3,
            content=grammar_explanation_content,
            why_important=content.get("grammar_motivation"),
        ))

    drill_activities: list[LessonActivity] = []
    llm_drills = content.get("drills", [])
    for i, (spec, template) in enumerate(zip(drill_specs, drill_templates_used)):
        drill_data = llm_drills[i] if i < len(llm_drills) else None
        if not drill_data:
            logger.warning(
                f"[planner] Missing drill data at index {i} for {spec['grammar_point_code']}"
            )
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
                topic_used=topic,
                rag_refs=spec["rag_refs"],
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
                topic_used=topic,
                rag_refs=spec["rag_refs"],
            )
        await drill.insert()
        drill_activities.append(LessonActivity(
            type="drill",
            title=f"Esercizio: {spec['gp_label']}",
            description=f"{exercise_type.replace('_', ' ').title()} · {spec['gp_label']}",
            duration_minutes=3,
            drill_id=drill.id,
        ))

    writing_activity: list[LessonActivity] = []
    if include_writing and content.get("writing"):
        writing_data = content["writing"]
        writing_activity.append(LessonActivity(
            type="writing",
            title="Scrittura",
            description=f"Scrivi un testo su: {topic}",
            duration_minutes=8,
            content=writing_data.get("prompt", ""),
        ))

    # Pedagogical order: vocab warm-up → grammar → reading → drills → writing (output)
    activities = vocab_activity + grammar_activity + reading_activity + drill_activities + writing_activity

    return activities, overview
