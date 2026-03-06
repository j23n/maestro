"""
Selection helpers for lesson planning.

Picks grammar points, communicative functions, and vocabulary cards
based on the student's profile and CEFR level.
"""
from __future__ import annotations

import logging
import random
from datetime import date
from typing import Optional

from maestro.models import (
    CommunicativeFunction,
    GrammarPoint,
    Lesson,
    LessonTopic,
    LearningProfile,
    UserVocabularyCard,
    VocabularyWord,
)
from maestro.utils import CEFR_ORDER, utcnow

logger = logging.getLogger(__name__)

MIN_VOCAB = 5


async def pick_grammar_points(
    profile: Optional[LearningProfile],
    cefr_level: str,
    count: int,
) -> list[GrammarPoint]:
    """Pick grammar points to practise, prioritising weakest within level.

    Among the top candidates, prefer GPs that share the same chunk_ref
    so lessons are coherent around a textbook section.
    """
    candidates = await GrammarPoint.find(
        {"cefr_level": cefr_level}
    ).to_list()
    if not candidates:
        logger.warning(f"[selection] no grammar points at level {cefr_level}, using all")
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

    logger.debug(f"[selection] pick_grammar_points: {len(candidates)} candidates → picked {[g.code for g in picked]}")
    return picked


async def pick_comm_functions(
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
        logger.warning(f"[selection] no comm functions found for levels {eligible_levels}")
        return []

    fn_counts: dict = profile.functions_counts if profile else {}
    preferred_set = set(preferred_codes)

    def _score(cf: CommunicativeFunction) -> tuple:
        not_preferred = cf.code not in preferred_set
        usage = fn_counts.get(cf.code, 0) + random.uniform(0, 0.5)
        return (not_preferred, usage)

    candidates.sort(key=_score)
    picked = candidates[:count]
    logger.debug(
        f"[selection] pick_comm_functions: {len(candidates)} candidates, "
        f"preferred={preferred_codes} → picked {[c.code for c in picked]}"
    )
    return picked


async def get_past_topics(n: int = 10) -> list[LessonTopic]:
    """Return the topics of the last n completed lessons, most recent first."""
    lessons = (
        await Lesson.find(Lesson.status == "completed")
        .sort(-Lesson.created_at)
        .limit(n)
        .to_list()
    )
    topics = [l.topic for l in lessons if l.topic is not None]
    logger.debug(f"[selection] past topics ({len(topics)}): {[t.title for t in topics]}")
    return topics


async def fill_vocab_cards(vocab_count: int, cefr_level: str) -> list[UserVocabularyCard]:
    """Return up to vocab_count cards due today; introduce new words if too few due."""
    due = await UserVocabularyCard.find(
        {"next_review": {"$lte": date.today()}}
    ).limit(vocab_count).to_list()

    if len(due) < min(MIN_VOCAB, vocab_count):
        existing_word_ids = set()
        for c in due:
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
            logger.info(f"[selection] fill_vocab_cards: introduced {len(new_cards)} new words")

    return due[:vocab_count]
