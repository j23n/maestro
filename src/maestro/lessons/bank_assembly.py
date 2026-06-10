"""Assemble lesson content from the static bank instead of LLM generation.

try_assemble_from_bank() returns a LessonContentResponse built purely from
pre-authored bank material — drill items with verified answer keys,
level-validated texts, CF prompts — or None when the bank can't cover the
requested lesson (the planner then falls back to full LLM generation).

Personalization stays in *selection* (which scenario/GPs/CFs/depth) and in
the small adaptation pass (lessons.adapt) that writes framing around this
content; the target-language exercise material itself is immutable.
"""

from __future__ import annotations

import logging
import random

from maestro.lessons import bank
from maestro.lessons.schemas import (
    DrillItemResponse,
    DrillResponse,
    LessonContentResponse,
    ReadingQuestionResponse,
    ReadingResponse,
    SpeakingResponse,
    WritingResponse,
)
from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    ExerciseType,
    LearningProfile,
    ScenarioProgress,
)

logger = logging.getLogger(__name__)

# Items per drill activity (the LLM path asks for ~10; bank pools are sampled)
_ITEMS_PER_DRILL = 6
_MIN_ITEMS_PER_DRILL = 3


def _bank_text_to_reading(text: bank.BankText) -> ReadingResponse:
    return ReadingResponse(
        text=text.text,
        questions=[
            ReadingQuestionResponse(
                text=q.text,
                correct_answer=q.correct_answer,
                grammar_point_codes=q.grammar_point_codes,
            )
            for q in text.questions
        ],
        vocab_annotations=text.vocab_annotations,
    )


def _rotate(variants: list, offset: int, count: int) -> list:
    """Pick up to `count` distinct variants, rotating by `offset` so repeat
    visits to a scenario see different material."""
    if not variants:
        return []
    count = min(count, len(variants))
    return [variants[(offset + i) % len(variants)] for i in range(count)]


def _sample_drill_items(
    pool: list[bank.BankDrillItem],
    used: set[int],
    preferred_type: ExerciseType,
) -> tuple[list[bank.BankDrillItem], ExerciseType] | None:
    """Sample one drill activity's items from a GP's pool.

    Prefers unused items of the preferred exercise type; falls back to the
    other type when the preferred pool is too small. A GeneratedDrill has a
    single exercise_type, so each sample is type-homogeneous. Returns None
    when no type has enough unused items (caller may reuse used items).
    """
    by_type: dict[ExerciseType, list[tuple[int, bank.BankDrillItem]]] = {}
    for idx, item in enumerate(pool):
        if idx in used:
            continue
        by_type.setdefault(item.exercise_type, []).append((idx, item))

    candidates = by_type.get(preferred_type, [])
    chosen_type = preferred_type
    if len(candidates) < _MIN_ITEMS_PER_DRILL:
        # Not enough of the preferred type — take whichever type has most left
        best = max(by_type.items(), key=lambda kv: len(kv[1]), default=None)
        if best is None or len(best[1]) < _MIN_ITEMS_PER_DRILL:
            return None
        chosen_type, candidates = best

    picked = random.sample(candidates, min(_ITEMS_PER_DRILL, len(candidates)))
    used.update(idx for idx, _ in picked)
    return [item for _, item in picked], chosen_type


def try_assemble_from_bank(
    *,
    language: str,
    cefr_level: str,
    scenario: CurriculumScenario,
    depth: int,
    profile: LearningProfile | None,
    drill_specs: list[dict],
    listening_count: int,
    reading_count: int,
    include_writing: bool,
    speaking_cfs: list[CommunicativeFunction],
) -> LessonContentResponse | None:
    """Build LessonContentResponse from the bank, or None if coverage is missing.

    Mutates drill_specs in place: optional specs (the injected weak-GP review
    drill) without bank coverage are dropped; each kept spec's exercise_type
    is rewritten to match the sampled items so materialization stays aligned.
    """
    scenario_file = bank.get_scenario_texts(language, cefr_level, scenario.slug)
    if scenario_file is None:
        logger.info(
            "bank: no text bank for scenario", extra={"scenario": scenario.slug}
        )
        return None
    depth_content = scenario_file.depths.get(depth)
    if depth_content is None:
        logger.info(
            "bank: no depth content",
            extra={"scenario": scenario.slug, "depth": depth},
        )
        return None

    sp = ScenarioProgress()
    if profile is not None:
        sp = profile.active_progress.scenario_progress.get(
            scenario.slug, ScenarioProgress()
        )
    offset = sp.lesson_count

    # --- Texts ---
    if listening_count > 0 and not depth_content.listenings:
        logger.info("bank: no listening variants", extra={"scenario": scenario.slug})
        return None
    if reading_count > 0 and not depth_content.readings:
        logger.info("bank: no reading variants", extra={"scenario": scenario.slug})
        return None
    listenings = [
        _bank_text_to_reading(t)
        for t in _rotate(depth_content.listenings, offset, listening_count)
    ]
    readings = [
        _bank_text_to_reading(t)
        for t in _rotate(depth_content.readings, offset, reading_count)
    ]

    # --- Writing ---
    writing = None
    if include_writing:
        if not depth_content.writings:
            logger.info("bank: no writing prompt", extra={"scenario": scenario.slug})
            return None
        picked = _rotate(depth_content.writings, offset, 1)[0]
        writing = WritingResponse(
            prompt=picked.prompt, vocab_annotations=picked.vocab_annotations
        )

    # --- Speaking (CF prompts, scenario-scoped) ---
    speakings: list[SpeakingResponse] = []
    by_cf: dict[str, list[bank.BankSpeaking]] = {}
    for s in scenario_file.speakings:
        by_cf.setdefault(s.cf_code, []).append(s)
    for cf in speaking_cfs:
        variants = by_cf.get(cf.code)
        if not variants:
            logger.info(
                "bank: no speaking prompt for CF",
                extra={"scenario": scenario.slug, "cf_code": cf.code},
            )
            return None
        picked = _rotate(variants, offset, 1)[0]
        speakings.append(
            SpeakingResponse(
                prompt=picked.prompt, vocab_annotations=picked.vocab_annotations
            )
        )

    # --- Drills ---
    # Sample per-GP pools without replacement within the lesson. Required
    # specs (the lesson's grammar points) fail assembly when uncovered;
    # optional specs (injected review drill) are silently dropped.
    drills: list[DrillResponse] = []
    kept_specs: list[dict] = []
    used_by_gp: dict[str, set[int]] = {}
    for spec in drill_specs:
        gp_code = spec["grammar_point_code"]
        pool = bank.get_drill_items(language, cefr_level, gp_code)
        sampled = None
        if pool:
            used = used_by_gp.setdefault(gp_code, set())
            sampled = _sample_drill_items(pool, used, spec["exercise_type"])
            if sampled is None and len(used) > 0:
                # Pool exhausted within this lesson — allow reuse
                used.clear()
                sampled = _sample_drill_items(pool, used, spec["exercise_type"])
        if sampled is None:
            if spec.get("optional"):
                logger.info(
                    "bank: dropping optional drill spec", extra={"gp_code": gp_code}
                )
                continue
            logger.info("bank: no drill items for GP", extra={"gp_code": gp_code})
            return None
        items, exercise_type = sampled
        spec["exercise_type"] = exercise_type
        kept_specs.append(spec)
        annotations = [a for item in items for a in item.vocab_annotations]
        drills.append(
            DrillResponse(
                grammar_point_code=gp_code,
                items=[
                    DrillItemResponse(
                        prompt=item.prompt,
                        correct_answer=item.correct_answer,
                        hint=item.hint,
                    )
                    for item in items
                ],
                vocab_annotations=annotations,
            )
        )
    drill_specs[:] = kept_specs

    logger.info(
        "bank assembly succeeded",
        extra={
            "scenario": scenario.slug,
            "depth": depth,
            "n_drills": len(drills),
            "n_listenings": len(listenings),
            "n_readings": len(readings),
            "n_speakings": len(speakings),
            "include_writing": writing is not None,
        },
    )
    return LessonContentResponse(
        drills=drills,
        listenings=listenings,
        readings=readings,
        writing=writing,
        speakings=speakings,
    )
