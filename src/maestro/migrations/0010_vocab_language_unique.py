"""
Migration 0010 — Add language to VocabularyWord unique index.

Changes unique index from (word, part_of_speech) to (word, part_of_speech, language)
to support multiple languages sharing the same database.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run(db) -> None:
    coll = db["vocabulary_words"]

    # Backfill language="it" on any docs missing the field
    result = await coll.update_many(
        {"language": {"$exists": False}},
        {"$set": {"language": "it"}},
    )
    if result.modified_count:
        logger.info("0010: backfilled language='it' on %d docs", result.modified_count)

    # Drop old compound unique index on (word, part_of_speech)
    try:
        await coll.drop_index("word_1_part_of_speech_1")
        logger.info("0010: dropped old (word, part_of_speech) unique index")
    except Exception:
        logger.info("0010: old index not found (already dropped)")

    # Create new compound unique index including language
    await coll.create_index(
        [("word", 1), ("part_of_speech", 1), ("language", 1)],
        unique=True,
        name="word_1_part_of_speech_1_language_1",
    )
    logger.info("0010: created unique index on (word, part_of_speech, language)")
