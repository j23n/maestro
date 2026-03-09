"""
Selection helpers for lesson planning.

Picks scenarios, grammar points, communicative functions, and vocabulary cards
based on the student's profile and CEFR level.
"""

from __future__ import annotations

import logging
import random
from datetime import date
from typing import Optional

from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    LearningProfile,
    ScenarioProgress,
    UserVocabularyCard,
    VocabularyWord,
)
from maestro.utils import CEFR_ORDER, cefr_levels_up_to, ensure_utc, utcnow

logger = logging.getLogger(__name__)

MIN_VOCAB = 5

# Cooldown: recently visited scenarios get a penalty (seconds)
_COOLDOWN_SECONDS = 3 * 24 * 3600  # 3 days

# A1 early/late scenario weighting
_EARLY_A1_SLUGS = {
    "presentarsi",
    "al-bar",
    "al-ristorante",
    "fare-la-spesa",
    "la-famiglia",
    "la-giornata",
}
_LATE_A1_SLUGS = {
    "capire-e-farsi-capire",
    "opinioni-e-accordo",
    "permessi-e-regole",
    "scrivere-un-messaggio",
}
_EARLY_A1_LESSON_THRESHOLD = 5


async def _pick_a0_scenario(
    profile: Optional[LearningProfile],
) -> tuple[CurriculumScenario, int]:
    """Pick the next A0 scenario in sequential order.

    Returns the first scenario whose depth < 1 (i.e. not yet completed).
    Falls back to the last scenario if all are done.
    """
    scenarios = (
        await CurriculumScenario.find({"cefr_level": "A0"}).sort("sequence").to_list()
    )
    if not scenarios:
        raise ValueError("No A0 curriculum scenarios found")

    progress = profile.scenario_progress if profile else {}
    for scenario in scenarios:
        sp = progress.get(scenario.slug, ScenarioProgress())
        if sp.depth < 1:
            logger.info(
                f"_pick_a0_scenario: {scenario.slug} (sequence {scenario.sequence})"
            )
            return scenario, 1
    # All done — return last scenario
    last = scenarios[-1]
    logger.info(
        "all A0 scenarios exhausted, returning last", extra={"scenario": last.slug}
    )
    return last, 1


async def pick_scenario(
    profile: Optional[LearningProfile],
    cefr_level: str,
) -> tuple[CurriculumScenario, int]:
    """Pick the next scenario and depth level to cover.

    For A0: sequential progression through fixed lessons.
    For A1+: weighted scoring with variety.

    Returns (scenario, next_depth).
    """
    if cefr_level == "A0":
        return await _pick_a0_scenario(profile)

    scenarios = await CurriculumScenario.find({"cefr_level": cefr_level}).to_list()
    if not scenarios:
        scenarios = await CurriculumScenario.find_all().to_list()
    if not scenarios:
        raise ValueError("No curriculum scenarios found")

    progress = profile.scenario_progress if profile else {}
    now = utcnow()

    # Identify weak GP codes (high error rate)
    error_counts = profile.grammar_error_counts if profile else {}
    correct_counts = profile.grammar_correct_counts if profile else {}
    weak_gps: set[str] = set()
    for code in error_counts:
        total = correct_counts.get(code, 0) + error_counts.get(code, 0)
        if total > 0 and error_counts[code] / total > 0.4:
            weak_gps.add(code)

    # Count total A1 lessons for early weighting (exclude A0 lessons)
    a1_slugs = {s.slug for s in scenarios}
    a1_lesson_total = (
        sum(sp.lesson_count for slug, sp in progress.items() if slug in a1_slugs)
        if progress
        else 0
    )

    scored: list[tuple[float, CurriculumScenario, int]] = []
    for scenario in scenarios:
        sp = progress.get(scenario.slug, ScenarioProgress())
        next_depth = min(sp.depth + 1, len(scenario.depths))

        score = 0.0

        # 1. Unvisited bonus
        if sp.depth == 0:
            score += 10.0

        # 2. Prefer lower next-depth (introduction first)
        score -= next_depth * 0.5

        # 3. Weak GP overlap bonus
        overlap = len(weak_gps & set(scenario.gp_codes))
        score += overlap * 1.5

        # 4. Cooldown penalty
        if sp.last_visited:
            elapsed = (now - ensure_utc(sp.last_visited)).total_seconds()
            if elapsed < _COOLDOWN_SECONDS:
                score -= 5.0 * (1 - elapsed / _COOLDOWN_SECONDS)

        # 5. Early A1 weighting — steer beginners to easier scenarios first
        if cefr_level == "A1" and a1_lesson_total < _EARLY_A1_LESSON_THRESHOLD:
            if scenario.slug in _EARLY_A1_SLUGS:
                score += 3.0
            elif scenario.slug in _LATE_A1_SLUGS:
                score -= 3.0

        # 6. Jitter
        score += random.uniform(0, 1.0)

        scored.append((score, scenario, next_depth))

    scored.sort(key=lambda x: -x[0])
    _, best_scenario, best_depth = scored[0]
    logger.info(
        f"pick_scenario: {best_scenario.slug} depth={best_depth} "
        f"(from {len(scenarios)} candidates)"
    )
    return best_scenario, best_depth


async def pick_grammar_points(
    profile: Optional[LearningProfile],
    cefr_level: str,
    count: int,
    candidate_codes: list[str] | None = None,
) -> list[GrammarPoint]:
    """Pick grammar points to practise, prioritising weakest within level.

    When candidate_codes is provided (from a scenario), filter to those codes.
    Among the top candidates, prefer GPs that share the same chunk_ref
    so lessons are coherent around a textbook section.
    """
    if candidate_codes:
        candidates = await GrammarPoint.find(
            {"code": {"$in": candidate_codes}}
        ).to_list()
    else:
        candidates = await GrammarPoint.find({"cefr_level": cefr_level}).to_list()
    if not candidates:
        logger.warning("no grammar points for codes/level, using all")
        candidates = await GrammarPoint.find_all().to_list()

    error_counts: dict = profile.grammar_error_counts if profile else {}
    correct_counts: dict = profile.grammar_correct_counts if profile else {}

    def _score(gp: GrammarPoint) -> float:
        total = correct_counts.get(gp.code, 0) + error_counts.get(gp.code, 0)
        error_rate = error_counts.get(gp.code, 0) / max(1, total)
        return -error_rate + random.uniform(0, 0.1)

    candidates.sort(key=_score)

    # Take a wider pool (3× count) and group by chunk_ref
    pool = candidates[: count * 3]
    if len(pool) > count:
        by_chunk: dict[Optional[str], list[GrammarPoint]] = {}
        for gp in pool:
            by_chunk.setdefault(gp.chunk_ref, []).append(gp)
        # Pick the chunk_ref group with the most candidates
        best_chunk = max(by_chunk, key=lambda k: len(by_chunk[k]) if k else 0)
        if best_chunk and len(by_chunk[best_chunk]) >= count:
            picked = by_chunk[best_chunk][:count]
        else:
            # Not enough from one chunk — fall back to weakness order
            picked = pool[:count]
    else:
        picked = pool[:count]

    logger.debug(
        f"pick_grammar_points: {len(candidates)} candidates → picked {[g.code for g in picked]}"
    )
    return picked


async def pick_comm_functions(
    profile: Optional[LearningProfile],
    cefr_level: str,
    count: int,
    candidate_codes: list[str] | None = None,
) -> list[CommunicativeFunction]:
    """Pick CFs at or below the current level.

    When candidate_codes is provided (from a scenario), filter to those codes.
    Falls back to least-practised ordering.
    """
    if candidate_codes:
        candidates = await CommunicativeFunction.find(
            {"code": {"$in": candidate_codes}}
        ).to_list()
    else:
        level_idx = CEFR_ORDER.index(cefr_level) if cefr_level in CEFR_ORDER else 0
        eligible_levels = CEFR_ORDER[: level_idx + 1]
        candidates = await CommunicativeFunction.find(
            {"cefr_level": {"$in": eligible_levels}}
        ).to_list()
    if not candidates:
        logger.warning("no comm functions found")
        return []

    fn_counts: dict = profile.functions_counts if profile else {}

    def _score(cf: CommunicativeFunction) -> float:
        return fn_counts.get(cf.code, 0) + random.uniform(0, 0.5)

    candidates.sort(key=_score)
    picked = candidates[:count]
    logger.debug(
        f"pick_comm_functions: {len(candidates)} candidates → picked {[c.code for c in picked]}"
    )
    return picked


async def fill_vocab_cards(
    vocab_count: int, cefr_level: str, student_id=None
) -> list[UserVocabularyCard]:
    """Return up to vocab_count cards due today; introduce new words if too few due.

    Only considers words at the student's CEFR level +1 (e.g. A1 student sees A1+A2 words).
    """
    visible_levels = cefr_levels_up_to(cefr_level)

    card_filter: dict = {"next_review": {"$lte": date.today()}}
    if student_id is not None:
        card_filter["student_id"] = student_id
    due_all = await UserVocabularyCard.find(card_filter).to_list()

    # Batch fetch all referenced words in one query instead of N+1 fetch_all_links()
    word_ids = []
    for c in due_all:
        ref = c.word
        word_ids.append(ref.ref.id if hasattr(ref, "ref") else ref.id)
    words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
    word_map = {w.id: w for w in words}

    # Filter to words within the student's level range
    due = []
    existing_word_ids = set()
    for c in due_all:
        ref = c.word
        wid = ref.ref.id if hasattr(ref, "ref") else ref.id
        word = word_map.get(wid)
        if word and word.cefr_level in visible_levels:
            c.word = word  # resolve Link so downstream code can access word fields
            due.append(c)
        existing_word_ids.add(wid)

    if len(due) < min(MIN_VOCAB, vocab_count):
        candidates = await VocabularyWord.find(
            {"cefr_level": {"$in": visible_levels}}
        ).to_list()
        new_words = [w for w in candidates if w.id not in existing_word_ids]
        random.shuffle(new_words)
        needed = min(vocab_count, MIN_VOCAB) - len(due)
        new_cards = [
            UserVocabularyCard(
                student_id=student_id,
                word=w,
                discovered_at=utcnow(),
                next_review=date.today(),
            )
            for w in new_words[:needed]
        ]
        if new_cards:
            await UserVocabularyCard.insert_many(new_cards)
            due.extend(new_cards)
            logger.info(f"fill_vocab_cards: introduced {len(new_cards)} new words")

    return due[:vocab_count]
