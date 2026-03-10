"""
Migration 0002 — Drop the drill_templates collection.

DrillTemplate has been removed from the codebase (issue #28).
Exercise type is now selected inline via random.choice at lesson generation time.

Collections affected:
  - drill_templates   (dropped entirely)
  - generated_drills  (template field unset from all documents)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def run(db) -> None:
    await db["drill_templates"].drop()
    logger.info("0002: dropped drill_templates collection")

    result = await db["generated_drills"].update_many({}, {"$unset": {"template": ""}})
    logger.info(
        "0002: unset template field from %d generated_drills",
        result.modified_count,
    )
