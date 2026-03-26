"""
Migration 0007 — Remove stale duplicate VocabularyWord entries.

The old vocab_a0.json ingest created VocabularyWord entries for words that
already existed in the EPUB dictionary — with simplified POS tags (e.g.
"agg.num." instead of "agg.num.card.invar.e.s.m.invar.") and no entry_id.
These shadow the real dictionary entries and break the "Add to vocabulary"
button (requires entry_id).

For each duplicate:
1. Reassign any VocabularyWordDefinitions to the real (entry_id) entry
2. Reassign any UserVocabularyCards to the real entry
3. Delete the stale entry
"""

from __future__ import annotations

import logging

from bson import DBRef

logger = logging.getLogger(__name__)

WORDS_COLL = "vocabulary_words"
DEFS_COLL = "vocabulary_word_definitions"
CARDS_COLL = "user_vocabulary_cards"


async def run(db) -> None:
    words_coll = db[WORDS_COLL]
    defs_coll = db[DEFS_COLL]
    cards_coll = db[CARDS_COLL]

    # Build index: lowercase word → list of docs
    by_word: dict[str, list[dict]] = {}
    async for doc in words_coll.find():
        by_word.setdefault(doc["word"].lower(), []).append(doc)

    removed = 0
    defs_reassigned = 0
    cards_reassigned = 0

    for word, entries in by_word.items():
        with_eid = [e for e in entries if e.get("entry_id")]
        without_eid = [e for e in entries if not e.get("entry_id")]

        if not with_eid or not without_eid:
            continue

        # Pick the best real entry: prefer one with senses, then most senses
        real = sorted(with_eid, key=lambda e: len(e.get("senses", [])), reverse=True)[0]
        real_ref = DBRef(WORDS_COLL, real["_id"])

        for stale in without_eid:
            stale_ref = DBRef(WORDS_COLL, stale["_id"])

            # Reassign definitions
            result = await defs_coll.update_many(
                {"word": stale_ref},
                {"$set": {"word": real_ref}},
            )
            if result.modified_count:
                defs_reassigned += result.modified_count
                logger.info(
                    "0007: reassigned %d def(s) for '%s' (%s → %s)",
                    result.modified_count,
                    word,
                    stale["_id"],
                    real["_id"],
                )

            # Reassign cards
            result = await cards_coll.update_many(
                {"word": stale_ref},
                {"$set": {"word": real_ref}},
            )
            if result.modified_count:
                cards_reassigned += result.modified_count
                logger.info(
                    "0007: reassigned %d card(s) for '%s' (%s → %s)",
                    result.modified_count,
                    word,
                    stale["_id"],
                    real["_id"],
                )

            # Delete stale entry
            await words_coll.delete_one({"_id": stale["_id"]})
            removed += 1

    logger.info(
        "0007: removed %d stale vocab duplicates, reassigned %d defs + %d cards",
        removed,
        defs_reassigned,
        cards_reassigned,
    )
