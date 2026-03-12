"""
Migration 0004 — Change VocabularyWord unique index from (word) to (word, part_of_speech).

The old Field(unique=True) on word created a single-field unique index named "word_1".
Beanie's init_beanie() creates the new compound index from Settings.indexes but does NOT
drop old indexes, so we must explicitly drop it here.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run(db) -> None:
    coll = db["vocabulary_words"]

    # Drop old single-field unique index on "word"
    try:
        await coll.drop_index("word_1")
        logger.info("0004: dropped old word_1 unique index")
    except Exception:
        logger.info("0004: word_1 index not found (already dropped)")

    # Create compound unique index (idempotent — no-op if Beanie already created it)
    await coll.create_index(
        [("word", 1), ("part_of_speech", 1)],
        unique=True,
        name="word_1_part_of_speech_1",
    )
    logger.info("0004: created compound unique index on (word, part_of_speech)")
