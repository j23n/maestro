"""
Lesson plan generation.

Two-phase approach:
  1. prepare_lesson_immediate() — fast, no LLM; creates Lesson with vocab_review activity
  2. generate_lesson_background() — async; appends grammar/reading/drill/speaking/writing

_generate_lesson_content() makes a single large Sonnet call that returns all dynamic content.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import date
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import anthropic

from maestro.models import (
    Lesson,
    LessonActivity,
    LessonTopic,
    LearningProfile,
    GrammarPoint,
    GrammarPointExplanation,
    GeneratedDrill,
    DrillItem,
    DrillTemplate,
    UserVocabularyCard,
    VocabularyWord,
    CommunicativeFunction,
)
from maestro.config import settings
from maestro.llm import get_async_client
from maestro.profile import get_profile
from maestro.prompts import planner as _prompts
from maestro.utils import CEFR_ORDER, parse_llm_json, utcnow
from maestro.rag.retrieve import get_chunks_for_refs

logger = logging.getLogger(__name__)

_READING_WORD_COUNT = {"A1": 200, "A2": 300, "B1": 400, "B2": 500}
_READING_QUESTION_COUNT = 5
MIN_VOCAB = 5


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
# Grammar point selection
# ---------------------------------------------------------------------------


async def _pick_grammar_points(
    profile: Optional[LearningProfile],
    cefr_level: str,
    count: int,
) -> list[GrammarPoint]:
    """Pick grammar points to practise, prioritising weakest within level."""
    candidates = await GrammarPoint.find(
        {"cefr_level": cefr_level}
    ).to_list()
    if not candidates:
        logger.warning(f"[planner] no grammar points at level {cefr_level}, using all")
        candidates = await GrammarPoint.find_all().to_list()

    error_counts: dict = profile.grammar_error_counts if profile else {}
    correct_counts: dict = profile.grammar_correct_counts if profile else {}

    def _score(gp: GrammarPoint) -> float:
        total = correct_counts.get(gp.code, 0) + error_counts.get(gp.code, 0)
        error_rate = error_counts.get(gp.code, 0) / max(1, total)
        return -error_rate + random.uniform(0, 0.1)

    candidates.sort(key=_score)
    picked = candidates[:count]
    logger.debug(f"[planner] _pick_grammar_points: {len(candidates)} candidates → picked {[g.code for g in picked]}")
    return picked


# ---------------------------------------------------------------------------
# Communicative function selection
# ---------------------------------------------------------------------------


async def _pick_comm_functions(
    profile: Optional[LearningProfile],
    cefr_level: str,
    count: int,
    preferred_codes: list[str] = [],
) -> list[CommunicativeFunction]:
    """Pick CFs at or below the current level.

    If preferred_codes are given (from the lesson topic), matching CFs are
    returned first. Falls back to least-practised ordering.
    """
    level_idx = CEFR_ORDER.index(cefr_level) if cefr_level in CEFR_ORDER else 0
    eligible_levels = CEFR_ORDER[: level_idx + 1]
    candidates = await CommunicativeFunction.find(
        {"cefr_level": {"$in": eligible_levels}}
    ).to_list()
    if not candidates:
        logger.warning(f"[planner] no comm functions found for levels {eligible_levels}")
        return []

    fn_counts: dict = profile.functions_counts if profile else {}
    preferred_set = set(preferred_codes)

    def _score(cf: CommunicativeFunction) -> tuple:
        # Preferred CFs sort first, then least-practised
        not_preferred = cf.code not in preferred_set
        usage = fn_counts.get(cf.code, 0) + random.uniform(0, 0.5)
        return (not_preferred, usage)

    candidates.sort(key=_score)
    picked = candidates[:count]
    logger.debug(
        f"[planner] _pick_comm_functions: {len(candidates)} candidates, "
        f"preferred={preferred_codes} → picked {[c.code for c in picked]}"
    )
    return picked


# ---------------------------------------------------------------------------
# Topic generation
# ---------------------------------------------------------------------------


async def _get_past_topics(n: int = 10) -> list[LessonTopic]:
    """Return the topics of the last n completed lessons, most recent first."""
    lessons = (
        await Lesson.find(Lesson.status == "completed")
        .sort(-Lesson.created_at)
        .limit(n)
        .to_list()
    )
    topics = [l.topic for l in lessons if l.topic is not None]
    logger.debug(f"[planner] past topics ({len(topics)}): {[t.title for t in topics]}")
    return topics


async def generate_topic(
    profile: Optional[LearningProfile],
    past_topics: list[LessonTopic],
    available_cfs: list[CommunicativeFunction],
    hint: str = "",
    client: Optional["anthropic.AsyncAnthropic"] = None,
) -> LessonTopic:
    """Call Haiku to generate a personalised, CF-grounded lesson topic.

    Falls back to a simple LessonTopic built from the hint (or a default)
    if the LLM call fails or returns unparseable JSON.
    """
    cefr = profile.cefr_estimate if profile else "A1"
    interests = ", ".join(profile.student_interests) if profile and profile.student_interests else "vita quotidiana"

    # Build compact CF listing grouped by macro_category
    level_idx = CEFR_ORDER.index(cefr) if cefr in CEFR_ORDER else 0
    eligible_levels = set(CEFR_ORDER[: level_idx + 1])
    cfs_at_level = [cf for cf in available_cfs if cf.cefr_level in eligible_levels]
    by_macro: dict[str, list[CommunicativeFunction]] = {}
    for cf in cfs_at_level:
        by_macro.setdefault(cf.macro_category, []).append(cf)

    cf_lines: list[str] = []
    for macro, cfs in by_macro.items():
        cf_lines.append(f"[{macro}]")
        for cf in cfs[:8]:  # cap per category to keep prompt manageable
            cf_lines.append(f"  {cf.code}: {cf.label} — {(cf.description or cf.label)[:80]}")

    past_lines = "\n".join(
        f"  [depth {t.depth}] {t.title}" + (f" (builds on: {t.builds_on})" if t.builds_on else "")
        for t in past_topics
    ) or "  (none yet)"

    hint_line = f"\nThe student requested this topic hint: {hint}\n" if hint else ""

    prompt = _prompts.generate_topic.render(
        cefr=cefr,
        interests=interests,
        hint_line=hint_line,
        past_lines=past_lines,
        cf_lines="\n".join(cf_lines),
    )

    cef_label = profile.cefr_estimate if profile else "A1"
    logger.info(
        f"[planner] generate_topic: level={cef_label}, interests={interests!r}, "
        f"hint={hint!r}, past_topics={len(past_topics)}, available_cfs={len(available_cfs)}"
    )
    try:
        _client = client or get_async_client()
        logger.debug(f"[planner] generate_topic prompt: {prompt}")
        t0 = time.monotonic()
        response = await _client.messages.create(
            model=settings.DRILL_MODEL,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.monotonic() - t0
        raw = response.content[0].text
        logger.debug(f"[planner] generate_topic LLM in {elapsed:.2f}s: {raw}")
        data = parse_llm_json(raw)
        if data and isinstance(data.get("cf_codes"), list) and data.get("title"):
            topic = LessonTopic(
                title=data["title"],
                description=data.get("description", data["title"]),
                cf_codes=data["cf_codes"],
                depth=int(data.get("depth", 1)),
                builds_on=data.get("builds_on"),
            )
            logger.info(
                f"[planner] topic generated: {topic.title!r} (depth={topic.depth}, "
                f"cf_codes={topic.cf_codes}, builds_on={topic.builds_on!r})"
            )
            return topic
        logger.warning(f"[planner] generate_topic: unparseable or incomplete response: {raw}")
    except Exception as exc:
        logger.error(f"[planner] generate_topic failed: {exc}", exc_info=True)

    # Fallback
    fallback_title = hint or (past_topics[0].title if past_topics else "vita quotidiana")
    logger.warning(f"[planner] generate_topic using fallback title: {fallback_title!r}")
    return LessonTopic(title=fallback_title, description=fallback_title, cf_codes=[], depth=1)


# ---------------------------------------------------------------------------
# Vocab card filling (ensures minimum cards even when none are due)
# ---------------------------------------------------------------------------


async def _fill_vocab_cards(vocab_count: int, cefr_level: str) -> list[UserVocabularyCard]:
    """Return up to vocab_count cards due today; introduce new words if too few due."""
    due = await UserVocabularyCard.find(
        {"next_review": {"$lte": date.today()}}
    ).limit(vocab_count).to_list()

    if len(due) < min(MIN_VOCAB, vocab_count):
        existing_word_ids = set()
        for c in due:
            # word may be a Link; resolve the id
            ref = c.word
            if hasattr(ref, "ref"):
                existing_word_ids.add(ref.ref.id)
            elif hasattr(ref, "id"):
                existing_word_ids.add(ref.id)

        candidates = await VocabularyWord.find({"cefr_level": cefr_level}).to_list()
        new_words = [w for w in candidates if w.id not in existing_word_ids]
        random.shuffle(new_words)
        needed = min(vocab_count, MIN_VOCAB) - len(due)
        new_cards = [
            UserVocabularyCard(
                word=w,
                discovered_at=utcnow(),
                next_review=date.today(),
            )
            for w in new_words[:needed]
        ]
        if new_cards:
            await UserVocabularyCard.insert_many(new_cards)
            due.extend(new_cards)
            logger.info(f"[planner] _fill_vocab_cards: introduced {len(new_cards)} new words")

    return due[:vocab_count]


# ---------------------------------------------------------------------------
# Single-call content generation
# ---------------------------------------------------------------------------


async def _generate_lesson_content(
    cefr_level: str,
    topic: str,
    profile: Optional[LearningProfile],
    grammar_gps: list[GrammarPoint],
    drill_specs: list[dict],
    reading_count: int,
    include_writing: bool,
    client: "anthropic.AsyncAnthropic",
    speaking_cfs: list[CommunicativeFunction] = [],
) -> dict:
    """Single LLM call returning overview, grammar_motivations, drills, readings, writing, speakings."""
    reading_word_count = _READING_WORD_COUNT.get(cefr_level, 150)

    parts: list[str] = [
        _prompts.lesson_content_header.render(),
        f"Student CEFR level: {cefr_level}",
        f"Lesson topic: {topic}",
    ]
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
        f"[planner] _generate_lesson_content: level={cefr_level}, topic={topic!r}, "
        f"grammar_gps={[g.code for g in grammar_gps]}, "
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
    hint: str,
    grammar_codes: list[str],
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
        due_cards = await _fill_vocab_cards(vocab_count, cefr_level)
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
    hint: str,
    grammar_codes: list[str],
) -> None:
    """Generate topic, grammar, reading, drills, speaking, writing and append to lesson."""
    t_start = time.monotonic()
    logger.info(f"[planner] generate_lesson_background start: lesson={lesson_id}")

    profile = await get_profile()
    cefr_level = profile.cefr_estimate if profile else "A1"
    slots = _allocate_slots(duration_minutes)
    logger.info(f"[planner] slot allocation: {slots}")

    # --- Generate topic ---
    client = get_async_client()
    all_cfs = await CommunicativeFunction.find_all().to_list()
    past_topics = await _get_past_topics(10)
    lesson_topic = await generate_topic(profile, past_topics, all_cfs, hint=hint, client=client)

    # --- Resolve grammar point pool ---
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

    # --- Pick grammar points (multiple) ---
    grammar_count = slots.get("grammar", 0)
    grammar_gps: list[GrammarPoint] = []
    grammar_explanations: list[Optional[str]] = []

    if grammar_count > 0:
        if selected_gps:
            grammar_gps = selected_gps[:grammar_count]
        else:
            grammar_gps = await _pick_grammar_points(profile, cefr_level, grammar_count)

        for gp in grammar_gps:
            explanation = await GrammarPointExplanation.find_one(
                {"grammar_point.$id": gp.id, "student_level": cefr_level}
            )
            if not explanation:
                explanation = await GrammarPointExplanation.find_one(
                    {"grammar_point.$id": gp.id}
                )
            if explanation:
                grammar_explanations.append(explanation.explanation)
            else:
                from maestro.rag.retrieve import get_chunks_for_refs as _gcr
                chunks = await _gcr(gp.rag_refs)
                grammar_explanations.append(
                    "\n\n".join(c.content for c in chunks) if chunks else gp.description
                )

    # --- Pick grammar points and templates for drills ---
    drill_count = slots.get("drill", 0)
    drill_specs: list[dict] = []
    drill_templates_used: list[DrillTemplate] = []
    if drill_count > 0:
        if selected_gps:
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

    # --- Pick communicative functions for speaking ---
    speaking_count = slots.get("speaking", 0)
    speaking_cfs: list[CommunicativeFunction] = []
    if speaking_count > 0:
        speaking_cfs = await _pick_comm_functions(
            profile, cefr_level, speaking_count, preferred_codes=lesson_topic.cf_codes
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
    topic_str = f"{lesson_topic.title} — {lesson_topic.description}"
    content = await _generate_lesson_content(
        cefr_level,
        topic_str,
        profile,
        grammar_gps,
        drill_specs,
        reading_count,
        include_writing,
        client,
        speaking_cfs,
    )

    # --- Materialise activities ---

    grammar_activities: list[LessonActivity] = []
    grammar_motivations = content.get("grammar_motivations", [])
    for i, gp in enumerate(grammar_gps):
        explanation_content = grammar_explanations[i] if i < len(grammar_explanations) else gp.description
        motivation = grammar_motivations[i].get("text") if i < len(grammar_motivations) and isinstance(grammar_motivations[i], dict) else None
        grammar_activities.append(LessonActivity(
            type="grammar",
            title=f"Grammatica: {gp.label}",
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
            description=f"Leggi un testo su: {lesson_topic.title}",
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
                topic_used=topic_str,
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
                topic_used=topic_str,
                rag_refs=spec["rag_refs"],
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
            description=f"Scrivi un testo su: {lesson_topic.title}",
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
    lesson.topic = lesson_topic
    lesson.generating = False
    await lesson.save()

    elapsed_total = time.monotonic() - t_start
    logger.info(
        f"[planner] generate_lesson_background complete in {elapsed_total:.1f}s: "
        f"{len(new_activities)} new activities — {[a.type for a in new_activities]}"
    )
