"""
Migration 0011 — Move flat progress fields into per-language namespace.

Restructures LearningProfile: moves 12 language-scoped fields into
``progress.<target_language>`` and $unsets the flat originals.

Also backfills ``language="it"`` on UserVocabularyCards missing the field.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_FIELDS_TO_MOVE = [
    "grammar_correct_counts",
    "grammar_error_counts",
    "grammar_recent_outcomes",
    "grammar_mastery_scores",
    "grammar_introduced",
    "functions_counts",
    "scenario_progress",
    "cefr_estimate",
    "onboarding_completed",
    "onboarding_skipped",
    "themes_seen",
    "description",
]

_DEFAULTS = {
    "grammar_correct_counts": {},
    "grammar_error_counts": {},
    "grammar_recent_outcomes": {},
    "grammar_mastery_scores": {},
    "grammar_introduced": [],
    "functions_counts": {},
    "scenario_progress": {},
    "cefr_estimate": "A0",
    "onboarding_completed": False,
    "onboarding_skipped": False,
    "themes_seen": [],
    "description": "",
}


async def run(db) -> None:
    # --- Learning profiles: nest flat fields under progress.<lang> ---
    profile_coll = db["learning_profile"]
    count = 0
    async for doc in profile_coll.find({"progress": {"$exists": False}}):
        lang = doc.get("target_language", "it")
        lang_progress = {}
        for field in _FIELDS_TO_MOVE:
            lang_progress[field] = doc.get(field, _DEFAULTS[field])

        unset_fields = {f: 1 for f in _FIELDS_TO_MOVE if f in doc}

        update: dict = {"$set": {f"progress.{lang}": lang_progress}}
        if unset_fields:
            update["$unset"] = unset_fields

        await profile_coll.update_one({"_id": doc["_id"]}, update)
        count += 1

    logger.info("0011: migrated %d profiles to multi-language progress", count)

    # --- Vocab cards: backfill language ---
    card_coll = db["user_vocabulary_cards"]
    result = await card_coll.update_many(
        {"language": {"$exists": False}},
        {"$set": {"language": "it"}},
    )
    if result.modified_count:
        logger.info(
            "0011: backfilled language='it' on %d vocab cards",
            result.modified_count,
        )
