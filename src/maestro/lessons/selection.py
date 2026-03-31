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

from maestro.language import DEFAULT_LANGUAGE
from maestro.models import (
    CommunicativeFunction,
    CurriculumScenario,
    GrammarPoint,
    LearningProfile,
    ScenarioProgress,
    UserVocabularyCard,
    VocabularyWord,
)
from maestro.lessons.curriculum import get_available_scenarios, get_max_available_depth
from maestro.utils import CEFR_ORDER, ensure_utc, utcnow

logger = logging.getLogger(__name__)

# Cooldown: recently visited scenarios get a penalty (seconds)
_COOLDOWN_SECONDS = 3 * 24 * 3600  # 3 days


async def _pick_a0_scenario(
    profile: Optional[LearningProfile],
    language: str | None = None,
) -> tuple[CurriculumScenario, int]:
    """Pick the next A0 scenario in sequential order.

    Returns the first scenario whose depth < 1 (i.e. not yet completed).
    Falls back to the last scenario if all are done.
    """
    lang = language or DEFAULT_LANGUAGE
    scenarios = (
        await CurriculumScenario.find({"cefr_level": "A0", "language": lang})
        .sort("sequence")
        .to_list()
    )
    if not scenarios:
        raise ValueError("No A0 curriculum scenarios found")

    progress = profile.active_progress.scenario_progress if profile else {}
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
    scenarios: list[CurriculumScenario] | None = None,
    language: str | None = None,
) -> tuple[CurriculumScenario, int]:
    """Pick the next scenario and depth level to cover.

    For A0: sequential progression through fixed lessons.
    For A1+: weighted scoring with variety.

    Args:
        scenarios: pre-fetched scenario list to avoid a redundant DB query.
        language: ISO language code (e.g. "it", "de"). Defaults to DEFAULT_LANGUAGE.

    Returns (scenario, next_depth).
    """
    lang = language or DEFAULT_LANGUAGE

    if cefr_level == "A0":
        return await _pick_a0_scenario(profile, language=lang)

    all_scenarios = (
        scenarios
        or await CurriculumScenario.find(
            {"cefr_level": cefr_level, "language": lang}
        ).to_list()
    )
    if not all_scenarios:
        all_scenarios = await CurriculumScenario.find_all().to_list()
    if not all_scenarios:
        raise ValueError("No curriculum scenarios found")

    # Filter to unlocked phases
    scenarios = get_available_scenarios(profile, all_scenarios)
    if not scenarios:
        scenarios = all_scenarios  # safety fallback

    lp = profile.active_progress if profile else None
    progress = lp.scenario_progress if lp else {}
    now = utcnow()

    # Identify weak GP codes (high error rate)
    error_counts = lp.grammar_error_counts if lp else {}
    correct_counts = lp.grammar_correct_counts if lp else {}
    weak_gps: set[str] = set()
    for code in error_counts:
        total = correct_counts.get(code, 0) + error_counts.get(code, 0)
        if total > 0 and error_counts[code] / total > 0.4:
            weak_gps.add(code)

    scored: list[tuple[float, CurriculumScenario, int]] = []
    for scenario in scenarios:
        sp = progress.get(scenario.slug, ScenarioProgress())
        max_depth = get_max_available_depth(profile, scenario, all_scenarios)
        next_depth = min(sp.depth + 1, max_depth, len(scenario.depths))

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

        # 5. Breadth bonus — encourage visiting unstarted scenarios in the
        #    current phase before going deeper in already-visited ones
        if sp.depth == 0:
            score += 3.0

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
    unlocked_codes: set[str] | None = None,
    language: str | None = None,
) -> list[GrammarPoint]:
    """Pick grammar points to practise, prioritising weakest within level.

    When candidate_codes is provided (from a scenario), filter to those codes.
    When unlocked_codes is provided, only consider GPs in the unlocked set.
    Among the top candidates, prefer GPs that share the same chunk_ref
    so lessons are coherent around a textbook section.
    """
    lang = language or DEFAULT_LANGUAGE

    if candidate_codes:
        candidates = await GrammarPoint.find(
            {"code": {"$in": candidate_codes}, "language": lang}
        ).to_list()
    else:
        candidates = await GrammarPoint.find(
            {"cefr_level": cefr_level, "language": lang}
        ).to_list()

    if unlocked_codes is not None:
        candidates = [gp for gp in candidates if gp.code in unlocked_codes]
    if not candidates:
        logger.warning("no grammar points for codes/level, using all")
        candidates = await GrammarPoint.find_all().to_list()

    lp = profile.active_progress if profile else None
    error_counts: dict = lp.grammar_error_counts if lp else {}
    correct_counts: dict = lp.grammar_correct_counts if lp else {}

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
    language: str | None = None,
) -> list[CommunicativeFunction]:
    """Pick CFs at or below the current level.

    When candidate_codes is provided (from a scenario), filter to those codes.
    Falls back to least-practised ordering.
    """
    lang = language or DEFAULT_LANGUAGE

    if candidate_codes:
        candidates = await CommunicativeFunction.find(
            {"code": {"$in": candidate_codes}, "language": lang}
        ).to_list()
    else:
        level_idx = CEFR_ORDER.index(cefr_level) if cefr_level in CEFR_ORDER else 0
        eligible_levels = CEFR_ORDER[: level_idx + 1]
        candidates = await CommunicativeFunction.find(
            {"cefr_level": {"$in": eligible_levels}, "language": lang}
        ).to_list()
    if not candidates:
        logger.warning("no comm functions found")
        return []

    fn_counts: dict = profile.active_progress.functions_counts if profile else {}

    def _score(cf: CommunicativeFunction) -> float:
        return fn_counts.get(cf.code, 0) + random.uniform(0, 0.5)

    candidates.sort(key=_score)
    picked = candidates[:count]
    logger.debug(
        f"pick_comm_functions: {len(candidates)} candidates → picked {[c.code for c in picked]}"
    )
    return picked


async def get_due_vocab_cards(
    vocab_count: int, student_id=None, language: str | None = None
) -> list[UserVocabularyCard]:
    """Return up to vocab_count cards due today (only already-discovered words)."""
    card_filter: dict = {
        "next_review": {"$lte": date.today()},
        "excluded": {"$ne": True},
    }
    if student_id is not None:
        card_filter["student_id"] = student_id
    if language is not None:
        card_filter["language"] = language
    due_all = await UserVocabularyCard.find(card_filter).to_list()

    # Batch fetch all referenced words in one query instead of N+1 fetch_all_links()
    word_ids = []
    for c in due_all:
        ref = c.word
        word_ids.append(ref.ref.id if hasattr(ref, "ref") else ref.id)
    words = await VocabularyWord.find({"_id": {"$in": word_ids}}).to_list()
    word_map = {w.id: w for w in words}

    due = []
    for c in due_all:
        ref = c.word
        wid = ref.ref.id if hasattr(ref, "ref") else ref.id
        word = word_map.get(wid)
        if word:
            c.word = word  # resolve Link so downstream code can access word fields
            due.append(c)

    return due[:vocab_count]
