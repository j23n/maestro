"""
Migration 0005 — Backfill grammar_introduced from grammar_recent_outcomes.

Any GP code that appears in grammar_recent_outcomes has been exercised,
so it was effectively introduced in a lesson. This backfills the new
grammar_introduced field for existing students.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run(db) -> None:
    coll = db["learning_profile"]
    count = 0
    async for doc in coll.find({"grammar_introduced": {"$exists": False}}):
        outcomes = doc.get("grammar_recent_outcomes") or {}
        introduced = list(outcomes.keys())
        await coll.update_one(
            {"_id": doc["_id"]},
            {"$set": {"grammar_introduced": introduced}},
        )
        count += 1
    if count:
        logger.info("0005: backfilled grammar_introduced for %d profiles", count)
    else:
        logger.info("0005: no profiles needed backfill")
