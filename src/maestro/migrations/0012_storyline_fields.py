"""
Migration 0012 — Add storyline fields to LanguageProgress.

Adds three new fields under ``progress.<lang>`` on every learning_profile doc:

    storyline: ""                          (empty string)
    storyline_lessons_since_evolve: 0      (counter for auto-evolve trigger)
    storyline_updated_at: None             (timestamp of last storyline change)

Idempotent: only $sets fields that are missing for a given language key.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "storyline": "",
    "storyline_lessons_since_evolve": 0,
    "storyline_updated_at": None,
}


async def run(db) -> None:
    profile_coll = db["learning_profile"]
    touched = 0

    async for doc in profile_coll.find({"progress": {"$exists": True}}):
        progress = doc.get("progress") or {}
        if not isinstance(progress, dict):
            continue

        set_ops: dict = {}
        for lang, lang_progress in progress.items():
            if not isinstance(lang_progress, dict):
                continue
            for field, default in _DEFAULTS.items():
                if field not in lang_progress:
                    set_ops[f"progress.{lang}.{field}"] = default

        if set_ops:
            await profile_coll.update_one({"_id": doc["_id"]}, {"$set": set_ops})
            touched += 1

    logger.info("0012: added storyline fields to %d profiles", touched)
